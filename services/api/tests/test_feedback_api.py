"""Correction feedback: submit -> overlay on canonical, raw prediction preserved.

`docs/08_API_AND_DATA_CONTRACTS.md` section 13; `docs/09_CODEX_EXECUTION.md` section 8.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.settings import Settings
from app.storage import LocalObjectStorage
from app.worker import process_next_job


def _process_one_document(client: TestClient, upload, session, storage, settings, pdf_bytes):
    document_id = upload(client, pdf_bytes).json()["document"]["id"]
    assert process_next_job(session, storage, settings, "worker-a") is not None
    return document_id


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
