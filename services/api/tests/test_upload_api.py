"""Upload API tests: validation, duplicates, durability."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Job
from app.routers.documents import UPLOAD_CHUNK_BYTES
from app.settings import Settings
from app.state_machine import DocumentStatus, JobStatus
from app.storage import LocalObjectStorage, checksum_of


def test_upload_accepts_a_pdf_and_queues_a_job(
    upload, client: TestClient, pdf_bytes: bytes, session: Session
) -> None:
    response = upload(client, pdf_bytes)

    assert response.status_code == 202
    payload = response.json()
    assert payload["document"]["status"] == DocumentStatus.QUEUED_FOR_PARSE.value
    assert payload["document"]["checksum_sha256"] == checksum_of(pdf_bytes)
    assert payload["document"]["byte_size"] == len(pdf_bytes)
    assert payload["job"]["status"] == JobStatus.QUEUED.value
    assert payload["duplicate_of_existing"] is False

    # Extracted fields stay null until a parse run produces them.
    assert payload["document"]["document_number"] is None
    assert payload["document"]["title"] is None

    stored = session.scalars(select(Document)).all()
    assert len(stored) == 1


def test_original_bytes_are_durable_before_the_job_exists(
    upload, client: TestClient, pdf_bytes: bytes, session: Session, storage: LocalObjectStorage
) -> None:
    response = upload(client, pdf_bytes)
    document_id = response.json()["document"]["id"]

    document = session.get(Document, document_id)
    assert document is not None
    assert storage.exists(document.storage_uri)
    assert storage.read(document.storage_uri) == pdf_bytes
    assert checksum_of(storage.read(document.storage_uri)) == document.checksum_sha256

    job = session.scalar(select(Job).where(Job.document_id == document_id))
    assert job is not None, "a job must never exist without durable input"


def test_duplicate_byte_upload_returns_the_existing_document(
    upload, client: TestClient, pdf_bytes: bytes, session: Session
) -> None:
    first = upload(client, pdf_bytes).json()
    second_response = upload(client, pdf_bytes, filename="another-name.pdf")

    assert second_response.status_code == 200
    second = second_response.json()
    assert second["duplicate_of_existing"] is True
    assert second["document"]["id"] == first["document"]["id"]
    assert second["job"]["id"] == first["job"]["id"]

    assert len(session.scalars(select(Document)).all()) == 1
    assert len(session.scalars(select(Job)).all()) == 1


def test_non_pdf_extension_is_rejected(client: TestClient, pdf_bytes: bytes) -> None:
    response = client.post(
        "/api/v1/documents",
        files={"file": ("notes.txt", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_wrong_content_type_is_rejected(client: TestClient, pdf_bytes: bytes) -> None:
    response = client.post(
        "/api/v1/documents",
        files={"file": ("cong-van.pdf", pdf_bytes, "image/png")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_oversized_upload_is_rejected(upload, client: TestClient, pdf_bytes: bytes) -> None:
    oversized = pdf_bytes + b"\0" * (2 * 1024 * 1024)
    response = upload(client, oversized)

    assert response.status_code == 413
    body = response.json()["error"]
    assert body["code"] == "file_too_large"
    assert body["details"]["limit"] == 2 * 1024 * 1024


def test_oversized_upload_is_rejected_before_the_body_is_buffered(
    upload, client: TestClient, pdf_bytes: bytes, session: Session, settings: Settings
) -> None:
    """Reading stops just past the limit instead of materialising the whole body."""
    oversized = pdf_bytes + b"\0" * (settings.max_upload_bytes * 4)
    response = upload(client, oversized)

    assert response.status_code == 413
    details = response.json()["error"]["details"]
    assert details["byte_size"] <= settings.max_upload_bytes + UPLOAD_CHUNK_BYTES
    assert details["byte_size"] < len(oversized)
    assert session.scalars(select(Document)).all() == []


def test_malformed_pdf_is_rejected(upload, client: TestClient) -> None:
    response = upload(client, b"this is definitely not a pdf", filename="broken.pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_pdf"


def test_empty_upload_is_rejected(upload, client: TestClient) -> None:
    response = upload(client, b"", filename="empty.pdf")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_pdf"


def test_encrypted_pdf_is_rejected_at_upload(upload, client: TestClient, fixture_paths) -> None:
    response = upload(client, fixture_paths["encrypted"].read_bytes(), filename="ma-hoa.pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "encrypted_pdf"


def test_error_envelope_matches_the_contract(upload, client: TestClient) -> None:
    response = upload(client, b"nope", filename="broken.pdf")
    error = response.json()["error"]

    assert set(error) == {"code", "message", "retryable", "request_id", "details"}
    assert error["request_id"].startswith("req_")
    assert "Traceback" not in error["message"]


def test_unknown_document_returns_the_error_contract(client: TestClient) -> None:
    response = client.get("/api/v1/documents/doc_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
