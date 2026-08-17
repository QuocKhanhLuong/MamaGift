"""Job lifecycle tests: idempotency, leases, retries, reprocess and versioning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ingestion
from app.models import Document, Job, ParseRun
from app.settings import Settings
from app.state_machine import DocumentStatus, JobStatus
from app.storage import LocalObjectStorage
from app.worker import process_next_job
from mamagift_docpipe import ParserError, ParserErrorCode


def _upload_document(
    session: Session, storage: LocalObjectStorage, settings: Settings, data: bytes
) -> Document:
    result = ingestion.create_document(
        session, storage, settings, "cong-van.pdf", "application/pdf", data
    )
    return result.document


def test_enqueue_is_idempotent_for_the_same_target_version(
    session: Session, storage: LocalObjectStorage, settings: Settings, pdf_bytes: bytes
) -> None:
    document = _upload_document(session, storage, settings, pdf_bytes)

    first = ingestion.enqueue_parse_job(session, document, reason="upload")
    second = ingestion.enqueue_parse_job(session, document, reason="upload-again")
    session.commit()

    assert first.id == second.id
    assert len(session.scalars(select(Job)).all()) == 1


def test_worker_unavailable_leaves_the_job_retryable(
    session: Session, storage: LocalObjectStorage, settings: Settings, pdf_bytes: bytes
) -> None:
    """Nothing leases the job, so it must stay queued and the document unchanged."""
    document = _upload_document(session, storage, settings, pdf_bytes)

    job = ingestion.latest_job(session, document.id)
    assert job is not None
    assert job.status == JobStatus.QUEUED.value
    assert document.status == DocumentStatus.QUEUED_FOR_PARSE.value
    assert document.status != "WORKER_UNAVAILABLE"


def test_expired_lease_is_requeued(
    session: Session, storage: LocalObjectStorage, settings: Settings, pdf_bytes: bytes
) -> None:
    _upload_document(session, storage, settings, pdf_bytes)

    leased = ingestion.lease_next_job(session, "worker-a", settings)
    assert leased is not None
    assert leased.status == JobStatus.LEASED.value
    assert ingestion.lease_next_job(session, "worker-b", settings) is None

    # The worker died: force the lease into the past.
    leased.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()

    requeued = ingestion.lease_next_job(session, "worker-b", settings)
    assert requeued is not None
    assert requeued.id == leased.id
    assert requeued.leased_by == "worker-b"


def test_parser_error_is_recorded_as_a_terminal_failure(
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _upload_document(session, storage, settings, pdf_bytes)

    def explode(*args: object, **kwargs: object) -> None:
        raise ParserError(
            ParserErrorCode.NORMALIZATION_FAILURE,
            "provider produced an unusable artifact",
            parser_name="test",
        )

    monkeypatch.setattr(ingestion, "run_ingestion", explode)
    assert process_next_job(session, storage, settings, "worker-a") is None

    session.refresh(document)
    job = ingestion.latest_job(session, document.id)
    assert job is not None
    assert job.status == JobStatus.FAILED_TERMINAL.value
    assert job.error is not None
    assert job.error["code"] == "normalization_failure"
    assert document.status == DocumentStatus.PARSE_FAILED.value
    assert document.error_code == "normalization_failure"


def test_retryable_failure_requeues_until_max_attempts(
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _upload_document(session, storage, settings, pdf_bytes)

    def flaky(*args: object, **kwargs: object) -> None:
        raise ParserError(ParserErrorCode.PROVIDER_FAILURE, "provider crashed", parser_name="test")

    monkeypatch.setattr(ingestion, "run_ingestion", flaky)

    for attempt in range(1, settings.job_max_attempts + 1):
        assert process_next_job(session, storage, settings, "worker-a") is None
        job = ingestion.latest_job(session, document.id)
        assert job is not None
        assert job.attempt == attempt
        expected = (
            JobStatus.QUEUED.value
            if attempt < settings.job_max_attempts
            else JobStatus.FAILED_TERMINAL.value
        )
        assert job.status == expected

    session.refresh(document)
    assert document.status == DocumentStatus.PARSE_FAILED.value
    assert session.scalars(select(ParseRun)).all() == []


def test_retry_after_failure_does_not_create_a_duplicate_current_version(
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _upload_document(session, storage, settings, pdf_bytes)

    calls = {"count": 0}
    real_run_ingestion = ingestion.run_ingestion

    def fail_once(*args: object, **kwargs: object):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ParserError(ParserErrorCode.PROVIDER_FAILURE, "transient", parser_name="test")
        return real_run_ingestion(*args, **kwargs)

    monkeypatch.setattr(ingestion, "run_ingestion", fail_once)

    assert process_next_job(session, storage, settings, "worker-a") is None
    run = process_next_job(session, storage, settings, "worker-a")
    assert run is not None

    runs = session.scalars(select(ParseRun).where(ParseRun.document_id == document.id)).all()
    assert len(runs) == 1
    assert [item.version for item in runs] == [1]
    assert sum(1 for item in runs if item.is_current) == 1


def test_reprocess_creates_a_new_parse_run_and_keeps_the_old_one(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
) -> None:
    document_id = upload(client, pdf_bytes).json()["document"]["id"]
    assert process_next_job(session, storage, settings, "worker-a") is not None

    first_run = session.scalar(
        select(ParseRun).where(ParseRun.document_id == document_id, ParseRun.version == 1)
    )
    assert first_run is not None
    first_canonical = dict(first_run.canonical)

    response = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert response.status_code == 202
    assert response.json()["job"]["status"] == JobStatus.QUEUED.value

    assert process_next_job(session, storage, settings, "worker-a") is not None

    runs = session.scalars(
        select(ParseRun).where(ParseRun.document_id == document_id).order_by(ParseRun.version)
    ).all()
    assert [run.version for run in runs] == [1, 2]
    assert [run.is_current for run in runs] == [False, True]

    # The superseded run is untouched: reprocessing never rewrites earlier output.
    session.refresh(first_run)
    assert first_run.canonical == first_canonical

    document = session.get(Document, document_id)
    assert document is not None
    assert document.current_parse_run_id == runs[1].id


def test_reprocess_is_rejected_while_the_document_is_processing(
    client: TestClient, upload, pdf_bytes: bytes
) -> None:
    document_id = upload(client, pdf_bytes).json()["document"]["id"]

    response = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
