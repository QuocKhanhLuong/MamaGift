"""End-to-end ingestion: upload -> processing -> canonical result.

Runs on the CI-safe parser path (the PyMuPDF baseline), which is what
`docs/04_PHASE_PLAN.md` Phase 2 requires of mandatory CI.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.settings import Settings
from app.state_machine import DocumentStatus, JobStatus
from app.storage import LocalObjectStorage
from app.worker import process_next_job


def test_upload_process_and_retrieve_canonical_document(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    data = fixture_paths["quyet_dinh"].read_bytes()

    upload_response = upload(client, data, filename="quyet-dinh.pdf")
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]

    status = client.get(f"/api/v1/documents/{document_id}/status").json()
    assert status["document"]["status"] == DocumentStatus.QUEUED_FOR_PARSE.value
    assert status["current_parse_run"] is None

    # Nothing is available before the worker runs.
    assert client.get(f"/api/v1/documents/{document_id}/canonical").status_code == 404

    assert process_next_job(session, storage, settings, "worker-a") is not None

    status = client.get(f"/api/v1/documents/{document_id}/status").json()
    assert status["document"]["status"] == DocumentStatus.READY_FOR_REVIEW.value
    assert status["latest_job"]["status"] == JobStatus.SUCCEEDED.value
    assert status["current_parse_run"]["version"] == 1
    assert status["current_parse_run"]["route"] == "born_digital"

    document = status["document"]
    assert document["document_number"] == "57/QĐ-UBND"
    assert document["document_type"] == "quyet_dinh"
    assert document["issued_date"] == "2026-03-03"
    assert document["deadline"] == "2026-04-30"
    assert document["issuer"] == "ỦY BAN NHÂN DÂN XÃ MAI GIANG"

    canonical_response = client.get(f"/api/v1/documents/{document_id}/canonical")
    assert canonical_response.status_code == 200
    payload = canonical_response.json()
    canonical = payload["canonical"]

    assert canonical["schema_version"] == "1.0"
    assert canonical["document_id"] == document_id
    assert len(canonical["pages"]) == 2

    kinds = [node["kind"] for node in canonical["hierarchy"]]
    assert "article" in kinds and "chapter" in kinds and "appendix" in kinds
    assert canonical["tables"], "the appendix table must survive ingestion"

    fields = {field["name"]: field for field in canonical["extracted_fields"]}
    assert fields["document_number"]["normalized_value"] == "57/QĐ-UBND"
    for field in fields.values():
        # Every critical field keeps page and block provenance.
        assert field["source_block_ids"]
        assert field["source_page_numbers"]
        assert field["confidence"] is not None


def test_canonical_output_is_deterministic_across_runs(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    document_id = upload(client, fixture_paths["quyet_dinh"].read_bytes()).json()["document"]["id"]
    assert process_next_job(session, storage, settings, "worker-a") is not None
    first = client.get(f"/api/v1/documents/{document_id}/canonical").json()["canonical"]

    client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert process_next_job(session, storage, settings, "worker-a") is not None
    second = client.get(f"/api/v1/documents/{document_id}/canonical").json()["canonical"]

    def structural(payload: dict) -> dict:
        return {
            "pages": payload["pages"],
            "hierarchy": payload["hierarchy"],
            "tables": payload["tables"],
            "extracted_fields": payload["extracted_fields"],
        }

    assert structural(first) == structural(second)


def test_degraded_parser_strategy_is_surfaced_for_review(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
) -> None:
    """ADR-001 is undecided, so every run must be flagged, never silently trusted."""
    document_id = upload(client, pdf_bytes).json()["document"]["id"]
    assert process_next_job(session, storage, settings, "worker-a") is not None

    status = client.get(f"/api/v1/documents/{document_id}/status").json()
    run = status["current_parse_run"]

    assert run["strategy_decided"] is False
    assert run["degraded"] is True
    assert run["parser_name"] == "pymupdf"
    assert run["quality_report"]["requires_user_review"] is True
    assert any("undecided" in warning for warning in run["quality_report"]["warnings"])
    assert status["document"]["requires_user_review"] is True


def test_historical_versions_stay_retrievable(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
) -> None:
    document_id = upload(client, pdf_bytes).json()["document"]["id"]
    assert process_next_job(session, storage, settings, "worker-a") is not None
    client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert process_next_job(session, storage, settings, "worker-a") is not None

    detail = client.get(f"/api/v1/documents/{document_id}").json()
    assert [run["version"] for run in detail["parse_runs"]] == [2, 1]

    version_one = client.get(f"/api/v1/documents/{document_id}/canonical?version=1")
    assert version_one.status_code == 200
    assert version_one.json()["parse_run"]["version"] == 1
    assert version_one.json()["parse_run"]["is_current"] is False


def test_original_file_and_page_preview_are_served(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
) -> None:
    document_id = upload(client, pdf_bytes).json()["document"]["id"]

    original = client.get(f"/api/v1/documents/{document_id}/file")
    assert original.status_code == 200
    assert original.headers["content-type"] == "application/pdf"
    assert original.content == pdf_bytes, "the served original must be byte-identical"

    preview = client.get(f"/api/v1/documents/{document_id}/pages/1/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG")

    missing_page = client.get(f"/api/v1/documents/{document_id}/pages/99/preview")
    assert missing_page.status_code == 404
    assert missing_page.json()["error"]["code"] == "unsupported_input"


def test_document_list_is_paginated_and_filterable(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths,
) -> None:
    upload(client, fixture_paths["cong_van"].read_bytes(), filename="cong-van.pdf")
    upload(client, fixture_paths["quyet_dinh"].read_bytes(), filename="quyet-dinh.pdf")
    process_next_job(session, storage, settings, "worker-a")

    listing = client.get("/api/v1/documents?limit=1").json()
    assert listing["total"] == 2
    assert len(listing["items"]) == 1
    assert listing["limit"] == 1

    ready = client.get(f"/api/v1/documents?status={DocumentStatus.READY_FOR_REVIEW.value}").json()
    assert ready["total"] == 1
