"""Correction feedback: submit -> overlay on canonical, raw prediction preserved.

`docs/08_API_AND_DATA_CONTRACTS.md` section 13; `docs/09_CODEX_EXECUTION.md` section 8.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, FeedbackEvent, ParseRun
from app.settings import Settings
from app.storage import LocalObjectStorage
from app.worker import process_next_job


def _process_one_document(client: TestClient, upload, session, storage, settings, pdf_bytes):
    document_id = upload(client, pdf_bytes).json()["document"]["id"]
    assert process_next_job(session, storage, settings, "worker-a") is not None
    return document_id


def _process_document_with_deadline(
    client: TestClient, upload, session, storage, settings, fixture_paths
):
    document_id = _process_one_document(
        client, upload, session, storage, settings, fixture_paths["quyet_dinh"].read_bytes()
    )
    canonical = client.get(f"/api/v1/documents/{document_id}/canonical").json()["canonical"]
    field = next(field for field in canonical["extracted_fields"] if field["name"] == "deadline")
    return document_id, field


def _feedback_count(session: Session, document_id: str) -> int:
    return len(
        session.scalars(select(FeedbackEvent).where(FeedbackEvent.document_id == document_id)).all()
    )


def _assert_feedback_field_required(response, request_id: str, missing_fields: list[str]) -> None:
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "feedback_field_required"
    assert error["retryable"] is False
    assert error["request_id"] == request_id
    assert error["details"] == {"missing_fields": missing_fields}


def _assert_feedback_field_invalid(
    response, request_id: str, document_id: str, field_id: str
) -> None:
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "feedback_field_invalid"
    assert error["retryable"] is False
    assert error["request_id"] == request_id
    assert error["details"] == {
        "document_id": document_id,
        "field_id": field_id,
        "reason": "not_in_current_canonical",
    }


def test_correction_is_persisted_and_visible_on_reload(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    document_id = _process_one_document(
        client, upload, session, storage, settings, fixture_paths["quyet_dinh"].read_bytes()
    )

    before = client.get(f"/api/v1/documents/{document_id}/canonical").json()["canonical"]
    field = next(f for f in before["extracted_fields"] if f["name"] == "deadline")
    assert field["review_status"] == "unreviewed"
    raw_value = field["raw_value"]

    document = session.get(Document, document_id)
    assert document is not None
    assert document.current_parse_run_id is not None
    current_run = session.get(ParseRun, document.current_parse_run_id)
    assert current_run is not None
    raw_canonical = deepcopy(current_run.canonical)

    feedback_response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        json={
            "feedback_type": "critical_field_correction",
            "field_id": field["id"],
            "corrected_value": "2026-08-25",
        },
    )
    assert feedback_response.status_code == 201
    body = feedback_response.json()
    assert body["id"]
    assert body["document_id"] == document_id
    assert body["corrected_value"] == "2026-08-25"

    # A fresh GET (simulating a reload) must show the correction, not the stale prediction.
    after = client.get(f"/api/v1/documents/{document_id}/canonical").json()["canonical"]
    corrected_field = next(f for f in after["extracted_fields"] if f["id"] == field["id"])
    assert corrected_field["review_status"] == "corrected"
    assert corrected_field["corrected_value"] == "2026-08-25"

    # The raw prediction is preserved, never rewritten by the correction.
    assert corrected_field["raw_value"] == raw_value
    session.refresh(current_run)
    assert current_run.canonical == raw_canonical


def test_only_the_latest_correction_for_a_field_is_shown(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    document_id = _process_one_document(
        client, upload, session, storage, settings, fixture_paths["quyet_dinh"].read_bytes()
    )
    canonical = client.get(f"/api/v1/documents/{document_id}/canonical").json()["canonical"]
    field_id = next(f for f in canonical["extracted_fields"] if f["name"] == "deadline")["id"]

    client.post(
        f"/api/v1/documents/{document_id}/feedback",
        json={
            "feedback_type": "critical_field_correction",
            "field_id": field_id,
            "corrected_value": "2026-08-20",
        },
    )
    client.post(
        f"/api/v1/documents/{document_id}/feedback",
        json={
            "feedback_type": "critical_field_correction",
            "field_id": field_id,
            "corrected_value": "2026-08-25",
        },
    )

    after = client.get(f"/api/v1/documents/{document_id}/canonical").json()["canonical"]
    field = next(f for f in after["extracted_fields"] if f["id"] == field_id)
    assert field["corrected_value"] == "2026-08-25"


@pytest.mark.parametrize("field_id", [None, "", " \t "])
def test_critical_correction_rejects_missing_field_id(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
    field_id: str | None,
) -> None:
    document_id, _ = _process_document_with_deadline(
        client, upload, session, storage, settings, fixture_paths
    )
    request_id = "req_feedback_missing_field_id"
    before_count = _feedback_count(session, document_id)

    response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        headers={"X-Request-ID": request_id},
        json={
            "feedback_type": "critical_field_correction",
            "field_id": field_id,
            "corrected_value": "2026-08-25",
        },
    )

    _assert_feedback_field_required(response, request_id, ["field_id"])
    assert _feedback_count(session, document_id) == before_count == 0


@pytest.mark.parametrize("corrected_value", [None, "", " \t "])
def test_critical_correction_rejects_missing_corrected_value(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
    corrected_value: str | None,
) -> None:
    document_id, field = _process_document_with_deadline(
        client, upload, session, storage, settings, fixture_paths
    )
    request_id = "req_feedback_missing_corrected_value"
    before_count = _feedback_count(session, document_id)

    response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        headers={"X-Request-ID": request_id},
        json={
            "feedback_type": "critical_field_correction",
            "field_id": field["id"],
            "corrected_value": corrected_value,
        },
    )

    _assert_feedback_field_required(response, request_id, ["corrected_value"])
    assert _feedback_count(session, document_id) == before_count == 0


def test_critical_correction_rejects_both_required_values_missing(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    document_id, _ = _process_document_with_deadline(
        client, upload, session, storage, settings, fixture_paths
    )
    request_id = "req_feedback_missing_both"
    before_count = _feedback_count(session, document_id)

    response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        headers={"X-Request-ID": request_id},
        json={
            "feedback_type": "critical_field_correction",
            "field_id": " \t ",
            "corrected_value": None,
        },
    )

    _assert_feedback_field_required(response, request_id, ["field_id", "corrected_value"])
    assert _feedback_count(session, document_id) == before_count == 0


def test_critical_correction_rejects_unknown_current_field_id(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    document_id, field = _process_document_with_deadline(
        client, upload, session, storage, settings, fixture_paths
    )
    unknown_field_id = f"{field['id']}_unknown"
    request_id = "req_feedback_unknown_field"
    before_count = _feedback_count(session, document_id)

    response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        headers={"X-Request-ID": request_id},
        json={
            "feedback_type": "critical_field_correction",
            "field_id": unknown_field_id,
            "corrected_value": "2026-08-25",
        },
    )

    _assert_feedback_field_invalid(response, request_id, document_id, unknown_field_id)
    assert _feedback_count(session, document_id) == before_count == 0


def test_critical_correction_rejects_stale_field_id_after_reprocess(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    document_id, first_field = _process_document_with_deadline(
        client, upload, session, storage, settings, fixture_paths
    )
    stale_field_id = first_field["id"]
    first_run = session.scalar(
        select(ParseRun).where(ParseRun.document_id == document_id, ParseRun.version == 1)
    )
    assert first_run is not None
    first_raw_canonical = deepcopy(first_run.canonical)

    reprocess_response = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert reprocess_response.status_code == 202
    assert process_next_job(session, storage, settings, "worker-a") is not None

    runs = session.scalars(
        select(ParseRun).where(ParseRun.document_id == document_id).order_by(ParseRun.version)
    ).all()
    assert [run.version for run in runs] == [1, 2]
    assert [run.is_current for run in runs] == [False, True]
    current_run = runs[-1]

    # The real parser is deterministic for the same bytes.  Model a changed current
    # parse identity in this test fixture without changing parser or production code.
    current_raw_canonical = deepcopy(current_run.canonical)
    for current_field in current_raw_canonical["extracted_fields"]:
        current_field["id"] = f"current_{current_field['id']}"
    current_run.canonical = current_raw_canonical
    session.commit()
    assert stale_field_id not in {
        field["id"] for field in current_raw_canonical["extracted_fields"]
    }

    document = session.get(Document, document_id)
    assert document is not None
    assert document.current_parse_run_id == current_run.id
    session.refresh(first_run)
    assert first_run.canonical == first_raw_canonical

    request_id = "req_feedback_stale_field"
    before_count = _feedback_count(session, document_id)
    response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        headers={"X-Request-ID": request_id},
        json={
            "feedback_type": "critical_field_correction",
            "field_id": stale_field_id,
            "corrected_value": "2026-08-25",
        },
    )

    _assert_feedback_field_invalid(response, request_id, document_id, stale_field_id)
    assert _feedback_count(session, document_id) == before_count == 0


def test_critical_correction_rejects_when_current_parse_run_is_unavailable(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    document_id, field = _process_document_with_deadline(
        client, upload, session, storage, settings, fixture_paths
    )
    document = session.get(Document, document_id)
    assert document is not None
    assert document.current_parse_run_id is not None

    # Keep the field ID valid for the processed run, then make the current pointer
    # unavailable without changing the production schema or parser behavior.
    document.current_parse_run_id = None
    session.commit()

    request_id = "req_feedback_no_current_parse_run"
    before_count = _feedback_count(session, document_id)
    response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        headers={"X-Request-ID": request_id},
        json={
            "feedback_type": "critical_field_correction",
            "field_id": field["id"],
            "corrected_value": "2026-08-25",
        },
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["retryable"] is False
    assert error["request_id"] == request_id
    assert error["details"] == {
        "document_id": document_id,
        "current_parse_run_id": None,
        "reason": "current_canonical_unavailable",
    }
    assert _feedback_count(session, document_id) == before_count == 0


def test_feedback_for_an_unknown_document_is_a_structured_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents/doc_missing/feedback",
        json={"feedback_type": "critical_field_correction", "field_id": "field_x"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_feedback_without_a_field_id_is_still_recorded(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
) -> None:
    document_id = _process_one_document(client, upload, session, storage, settings, pdf_bytes)

    response = client.post(
        f"/api/v1/documents/{document_id}/feedback",
        json={"feedback_type": "general_comment", "comment": "Trông ổn."},
    )
    assert response.status_code == 201
    assert response.json()["field_id"] is None
