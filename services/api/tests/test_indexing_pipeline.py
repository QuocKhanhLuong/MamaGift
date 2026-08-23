"""Unit and integration tests for runtime indexing pipeline (Phase 4 / Task D1).

Tests cover:
- Full parse-run to indexed-chunks pass with provenance preserved
- Idempotent re-indexing
- Re-parse producing isolated second parse run chunks
- Legal state machine transitions (READY_FOR_REVIEW -> INDEXING -> READY)
- Indexing failure leaving document intact, uncorrupted, and recoverable
- Embedding version change detection and forced reindex
- Worker integration with auto_index
- All guards and validators (for mutation testing verification)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import indexing, ingestion
from app.db import get_engine
from app.indexing import (
    IndexingError,
    get_default_embedding_provider,
    index_document,
    index_document_sync,
    index_parse_run_sync,
    needs_reindex,
)
from app.models import Document, DocumentChunk, ParseRun
from app.settings import Settings, get_settings
from app.state_machine import DocumentStatus, IllegalTransitionError
from app.storage import LocalObjectStorage
from app.worker import drain, process_next_job
from mamagift_contracts.embedding import EmbeddingResult
from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_docpipe import CanonicalDocument
from mamagift_retrieval.chunk import validate_chunk_tree
from mamagift_retrieval.chunking import build_chunks
from mamagift_retrieval.index import IndexStats, SqlDocumentIndex
from mamagift_retrieval.index.sql_index import _row_to_chunk
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.scope import EvidenceScope


def _create_and_parse_document(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
    filename: str = "quyet-dinh.pdf",
) -> tuple[str, ParseRun]:
    """Helper to upload a document and run the parse job up to READY_FOR_REVIEW."""
    resp = upload(client, pdf_bytes, filename=filename)
    assert resp.status_code == 202
    document_id = resp.json()["document"]["id"]

    run = process_next_job(session, storage, settings, "worker-test", auto_index=False)
    assert run is not None
    assert run.document_id == document_id

    doc = session.get(Document, document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY_FOR_REVIEW.value
    return document_id, run


# ---------------------------------------------------------------------------
# 1. Full parse-run to indexed-chunks pass with provenance preserved
# ---------------------------------------------------------------------------


def test_full_parse_run_to_indexed_chunks_provenance_preserved(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    provider = FakeEmbeddingProvider(dimension=1024, embedding_version="fake-bge-m3-v1")
    stats = index_parse_run_sync(session, parse_run, embedding_provider=provider)

    assert stats.document_id == document_id
    assert stats.parse_run_id == parse_run.id
    assert stats.document_version == parse_run.version
    assert stats.total_chunks > 0
    assert stats.embedded_chunks == stats.total_chunks
    assert stats.embedding_model == "fake-bge-m3"
    assert stats.embedding_version == "fake-bge-m3-v1"

    # Verify document status moved to READY
    doc = session.get(Document, document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY.value
    assert doc.error_code is None
    assert doc.error_message is None

    # Query chunk rows from DB
    chunk_rows = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
    )
    assert len(chunk_rows) == stats.total_chunks

    canonical = CanonicalDocument.model_validate(parse_run.canonical)
    expected_chunks = build_chunks(
        canonical.model_copy(
            update={"parser_run": canonical.parser_run.model_copy(update={"id": parse_run.id})}
        ),
        document_version=parse_run.version,
    )
    assert len(expected_chunks) == len(chunk_rows)

    # Verify provenance on every chunk row
    for idx, (row, expected) in enumerate(zip(chunk_rows, expected_chunks, strict=True)):
        assert row.document_id == document_id
        assert row.parse_run_id == parse_run.id
        assert row.document_version == parse_run.version
        assert row.chunk_index == idx
        assert row.id == expected.chunk_id
        assert row.parent_chunk_id == expected.parent_chunk_id
        assert row.source_block_ids == expected.source_block_ids
        assert row.page_numbers == expected.source_page_numbers
        assert row.section_path == expected.section_path
        assert row.text == expected.text
        assert row.text
        assert row.token_count > 0
        assert row.embedding is not None
        assert len(row.embedding) == 1024
        assert row.embedding_model == "fake-bge-m3"
        assert row.embedding_version == "fake-bge-m3-v1"
        assert isinstance(row.page_numbers, list)
        assert len(row.page_numbers) >= 1
        assert isinstance(row.source_block_ids, list)
        assert len(row.source_block_ids) >= 1
        assert isinstance(row.section_path, list)

    # Verify legal structure is present (Chương, Điều, etc.)
    section_paths = [row.section_path for row in chunk_rows if row.section_path]
    assert len(section_paths) > 0

    # Verify parent-child relationships form a valid tree
    chunks_for_tree = [_row_to_chunk(row) for row in chunk_rows]
    validate_chunk_tree(chunks_for_tree)


# ---------------------------------------------------------------------------
# 2. Idempotent re-index
# ---------------------------------------------------------------------------


def test_idempotent_reindex(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    provider = FakeEmbeddingProvider()
    stats1 = index_parse_run_sync(session, parse_run, embedding_provider=provider)
    chunks1 = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
    )

    # Re-index the same parse run
    stats2 = index_parse_run_sync(session, parse_run, embedding_provider=provider)
    chunks2 = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
    )

    assert stats1.total_chunks == stats2.total_chunks
    assert stats1.embedded_chunks == stats2.embedded_chunks
    assert len(chunks1) == len(chunks2)
    assert [c.id for c in chunks1] == [c.id for c in chunks2]
    assert [c.text for c in chunks1] == [c.text for c in chunks2]

    doc = session.get(Document, document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY.value


# ---------------------------------------------------------------------------
# 3. Re-parse produces second parse run whose chunks are isolated
# ---------------------------------------------------------------------------


def test_reparse_second_run_chunks_isolated(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, run_v1 = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    provider = FakeEmbeddingProvider()
    index = SqlDocumentIndex(session)
    index_parse_run_sync(session, run_v1, embedding_provider=provider, document_index=index)

    # Reprocess document to produce version 2
    reprocess_resp = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert reprocess_resp.status_code == 202

    run_v2 = process_next_job(session, storage, settings, "worker-test", auto_index=False)
    assert run_v2 is not None
    assert run_v2.version == 2
    assert run_v2.id != run_v1.id

    index_parse_run_sync(session, run_v2, embedding_provider=provider, document_index=index)

    # Check total rows in database: both v1 and v2 rows coexist
    all_chunks = list(
        session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()
    )
    v1_chunks = [c for c in all_chunks if c.parse_run_id == run_v1.id]
    v2_chunks = [c for c in all_chunks if c.parse_run_id == run_v2.id]
    assert len(v1_chunks) > 0
    assert len(v2_chunks) > 0
    assert len(all_chunks) == len(v1_chunks) + len(v2_chunks)

    # Query vector for dense search
    query_embedding = asyncio.run(provider.embed_query("quy định nhiệm vụ"))

    # Search scoped to v1
    scope_v1 = EvidenceScope(
        family_id="mamagift",
        document_id=document_id,
        document_version=1,
        parse_run_id=run_v1.id,
    )
    results_v1 = index.search_dense(scope_v1, query_embedding.vectors[0], top_k=10)
    assert len(results_v1) > 0
    for res in results_v1:
        assert res.chunk.document_version == 1
        assert res.chunk.parse_run_id == run_v1.id

    # Search scoped to v2
    scope_v2 = EvidenceScope(
        family_id="mamagift",
        document_id=document_id,
        document_version=2,
        parse_run_id=run_v2.id,
    )
    results_v2 = index.search_dense(scope_v2, query_embedding.vectors[0], top_k=10)
    assert len(results_v2) > 0
    for res in results_v2:
        assert res.chunk.document_version == 2
        assert res.chunk.parse_run_id == run_v2.id

    # Verify no cross-contamination between versions
    v1_ids = {r.chunk.chunk_id for r in results_v1}
    v2_ids = {r.chunk.chunk_id for r in results_v2}
    assert v1_ids.isdisjoint(v2_ids)


# ---------------------------------------------------------------------------
# 4. State machine transitions (READY_FOR_REVIEW -> INDEXING -> READY)
# ---------------------------------------------------------------------------


def test_state_machine_transitions_taken(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    doc = session.get(Document, document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY_FOR_REVIEW.value

    # Track intermediate status during index_parse_run
    provider = FakeEmbeddingProvider()
    observed_statuses: list[str] = []

    original_replace = SqlDocumentIndex.replace

    def spy_replace(self_idx, scope, entries):
        curr_doc = session.get(Document, document_id)
        if curr_doc is not None:
            observed_statuses.append(curr_doc.status)
        return original_replace(self_idx, scope, entries)

    with patch.object(SqlDocumentIndex, "replace", spy_replace):
        index_parse_run_sync(session, parse_run, embedding_provider=provider)

    assert observed_statuses == [DocumentStatus.INDEXING.value]

    session.refresh(doc)
    assert doc.status == DocumentStatus.READY.value


def test_unsupported_initial_state_is_rejected_without_index_rows(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, fixture_paths["quyet_dinh"].read_bytes()
    )
    document = session.get(Document, document_id)
    assert document is not None
    document.status = DocumentStatus.UPLOADED.value
    session.commit()

    with pytest.raises(IllegalTransitionError, match="UPLOADED -> INDEXING"):
        index_parse_run_sync(session, parse_run, embedding_provider=FakeEmbeddingProvider())

    assert session.get(Document, document_id).status == DocumentStatus.UPLOADED.value
    assert (
        session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id))
        is None
    )


# ---------------------------------------------------------------------------
# 5. Indexing failure leaves document intact, uncorrupted, and recoverable
# ---------------------------------------------------------------------------


def test_indexing_failure_leaves_document_intact_and_recoverable(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    saved_canonical = dict(parse_run.canonical)
    saved_quality_report = dict(parse_run.quality_report)
    saved_run_id = parse_run.id

    # Simulate failing embedding provider
    class BrokenEmbeddingProvider:
        model_id = "broken-embed"
        dimension = 1024
        embedding_version = "broken-v1"

        async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
            raise WorkerError(
                WorkerErrorCode.UNAVAILABLE,
                "embedding worker offline",
                retryable=True,
                status_code=503,
            )

        async def embed_query(self, text: str) -> EmbeddingResult:
            raise WorkerError(WorkerErrorCode.UNAVAILABLE, "offline")

    with pytest.raises(IndexingError) as exc_info:
        index_parse_run_sync(session, parse_run, embedding_provider=BrokenEmbeddingProvider())

    assert "embedding worker offline" in str(exc_info.value)

    # Verify document entered PARSE_FAILED
    doc = session.get(Document, document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.PARSE_FAILED.value
    assert doc.error_code is not None
    assert "embedding worker offline" in (doc.error_message or "")

    # Verify ParseRun and canonical artifact are completely intact and uncorrupted
    run_after_fail = session.get(ParseRun, saved_run_id)
    assert run_after_fail is not None
    assert run_after_fail.canonical == saved_canonical
    assert run_after_fail.quality_report == saved_quality_report
    assert run_after_fail.version == 1

    # Recovery: index with working provider
    working_provider = FakeEmbeddingProvider()
    stats = index_parse_run_sync(session, run_after_fail, embedding_provider=working_provider)
    assert stats.total_chunks > 0

    session.refresh(doc)
    assert doc.status == DocumentStatus.READY.value
    assert doc.error_code is None
    assert doc.error_message is None


# ---------------------------------------------------------------------------
# 6. Embedding version change forcing a reindex rather than silently mixing
# ---------------------------------------------------------------------------


def test_embedding_version_change_forces_reindex(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    provider_v1 = FakeEmbeddingProvider(embedding_version="fake-bge-m3-v1")
    index = SqlDocumentIndex(session, default_embedding_version="fake-bge-m3-v1")
    stats_v1 = index_parse_run_sync(
        session, parse_run, embedding_provider=provider_v1, document_index=index
    )

    assert not needs_reindex(stats_v1, provider_v1)

    class CountingEmbeddingProvider(FakeEmbeddingProvider):
        document_calls = 0

        async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
            self.document_calls += 1
            return await super().embed_documents(texts)

    # Change to provider v2 through the public runtime indexing pipeline.
    provider_v2 = CountingEmbeddingProvider(embedding_version="fake-bge-m3-v2")
    assert needs_reindex(stats_v1, provider_v2)

    # Search with v2 version filter excludes v1 rows
    scope = EvidenceScope(
        family_id="mamagift",
        document_id=document_id,
        document_version=parse_run.version,
        parse_run_id=parse_run.id,
    )
    query_embed = asyncio.run(provider_v2.embed_query("thông tin"))
    index_v2 = SqlDocumentIndex(session, embedding_version=provider_v2.embedding_version)
    results = index_v2.search_dense(scope, query_embed.vectors[0], top_k=5)
    assert len(results) == 0  # v1 chunks are excluded
    provider_v2.document_calls = 0

    stats_v2 = asyncio.run(
        index_document(
            session,
            document_id,
            embedding_provider=provider_v2,
            document_index=index,
        )
    )
    assert stats_v2.embedding_version == "fake-bge-m3-v2"
    assert not needs_reindex(stats_v2, provider_v2)
    assert provider_v2.document_calls == 1

    # A second runtime call with the same provider version is a no-op.
    stats_v2_repeat = asyncio.run(
        index_document(
            session,
            document_id,
            embedding_provider=provider_v2,
            document_index=index,
        )
    )
    assert stats_v2_repeat.embedding_version == "fake-bge-m3-v2"
    assert provider_v2.document_calls == 1

    # Search with v2 now succeeds
    results_v2 = index_v2.search_dense(scope, query_embed.vectors[0], top_k=5)
    assert len(results_v2) > 0


# ---------------------------------------------------------------------------
# 7. Worker integration with auto_index
# ---------------------------------------------------------------------------


def test_worker_process_next_job_with_auto_index(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    resp = upload(client, fixture_paths["quyet_dinh"].read_bytes(), filename="quyet-dinh.pdf")
    assert resp.status_code == 202
    document_id = resp.json()["document"]["id"]

    provider = FakeEmbeddingProvider()
    run = process_next_job(
        session, storage, settings, "worker-test", auto_index=True, embedding_provider=provider
    )
    assert run is not None
    assert run.document_id == document_id

    doc = session.get(Document, document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY.value

    chunks = list(
        session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()
    )
    assert len(chunks) > 0


def test_worker_drain_with_auto_index(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    upload(client, fixture_paths["quyet_dinh"].read_bytes(), filename="quyet-dinh.pdf")
    upload(client, fixture_paths["cong_van"].read_bytes(), filename="cong-van.pdf")

    provider = FakeEmbeddingProvider()
    processed = drain(
        session, storage, settings, "worker-test", auto_index=True, embedding_provider=provider
    )
    assert processed == 2

    docs = list(session.scalars(select(Document)).all())
    assert len(docs) == 2
    for doc in docs:
        assert doc.status == DocumentStatus.READY.value


# ---------------------------------------------------------------------------
# 8. Index document helpers (by ID and sync/async)
# ---------------------------------------------------------------------------


def test_index_document_by_id(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    provider = FakeEmbeddingProvider()
    index_parse_run_sync(session, parse_run, embedding_provider=provider)
    reprocess_resp = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert reprocess_resp.status_code == 202
    run_v2 = process_next_job(session, storage, settings, "worker-test", auto_index=False)
    assert run_v2 is not None
    assert run_v2.version == 2

    stats = asyncio.run(index_document(session, document_id, embedding_provider=provider))
    assert stats.document_id == document_id
    assert stats.parse_run_id == run_v2.id

    stats_v1 = asyncio.run(
        index_document(session, document_id, embedding_provider=provider, version=1)
    )
    assert stats_v1.parse_run_id == parse_run.id
    stats_by_id = asyncio.run(
        index_document(session, document_id, embedding_provider=provider, parse_run_id=parse_run.id)
    )
    assert stats_by_id.parse_run_id == parse_run.id


def test_index_document_sync_helper(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    provider = FakeEmbeddingProvider()
    index_parse_run_sync(session, parse_run, embedding_provider=provider)
    reprocess_resp = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert reprocess_resp.status_code == 202
    run_v2 = process_next_job(session, storage, settings, "worker-test", auto_index=False)
    assert run_v2 is not None
    assert run_v2.version == 2

    stats = index_document_sync(session, document_id, embedding_provider=provider)
    assert stats.document_id == document_id
    assert stats.parse_run_id == run_v2.id
    stats_v1 = index_document_sync(session, document_id, embedding_provider=provider, version=1)
    assert stats_v1.parse_run_id == parse_run.id
    stats_by_id = index_document_sync(
        session, document_id, embedding_provider=provider, parse_run_id=parse_run.id
    )
    assert stats_by_id.parse_run_id == parse_run.id


def test_index_document_not_found_raises(session: Session) -> None:
    with pytest.raises(IndexingError) as exc_info:
        index_document_sync(session, "doc_nonexistent")
    assert "no matching parse run found" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 9. Guard and validator tests (Quality Bar B)
# ---------------------------------------------------------------------------


def test_guard_parse_run_validation(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    # A detached object is addressed only by its identity; all other fields come
    # from the authoritative database row.
    invalid_run_1 = ParseRun(
        id="",
        document_id="doc_1",
        version=1,
        canonical={"document_id": "doc_1"},
    )
    with pytest.raises(IndexingError, match="valid id"):
        index_parse_run_sync(session, invalid_run_1)

    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, fixture_paths["quyet_dinh"].read_bytes()
    )

    parse_run.version = 0
    session.commit()
    with pytest.raises(IndexingError, match="positive version"):
        index_parse_run_sync(session, ParseRun(id=parse_run.id))

    parse_run.version = 1
    parse_run.canonical = {}
    session.commit()
    with pytest.raises(IndexingError, match="canonical document"):
        index_parse_run_sync(session, ParseRun(id=parse_run.id))


def test_guard_document_not_found(session: Session) -> None:
    run = ParseRun(
        id="prun_1",
        document_id="doc_nonexistent",
        version=1,
        canonical={"document_id": "doc_nonexistent", "schema_version": "1.0"},
    )
    with pytest.raises(IndexingError, match="parse run 'prun_1' not found"):
        index_parse_run_sync(session, run)


def test_guard_detached_or_ghost_parse_run_is_rejected(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, fixture_paths["quyet_dinh"].read_bytes()
    )
    detached = ParseRun(
        id="prun_ghost",
        document_id=document_id,
        version=parse_run.version,
        canonical=dict(parse_run.canonical),
    )

    with pytest.raises(IndexingError, match="parse run 'prun_ghost' not found"):
        index_parse_run_sync(session, detached, embedding_provider=FakeEmbeddingProvider())

    assert (
        session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id))
        is None
    )


def test_guard_canonical_identity_is_never_relabelled(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, fixture_paths["quyet_dinh"].read_bytes()
    )
    original_canonical = dict(parse_run.canonical)

    mismatched_document = dict(original_canonical)
    mismatched_document["document_id"] = "doc_foreign"
    parse_run.canonical = mismatched_document
    session.commit()
    with pytest.raises(IndexingError, match="canonical document_id"):
        index_parse_run_sync(session, parse_run, embedding_provider=FakeEmbeddingProvider())

    parse_run = session.get(ParseRun, parse_run.id)
    assert parse_run is not None
    mismatched_parser_run = dict(original_canonical)
    mismatched_parser_run["parser_run"] = dict(original_canonical["parser_run"])
    mismatched_parser_run["parser_run"]["id"] = "prun_foreign"
    parse_run.canonical = mismatched_parser_run
    session.commit()
    with pytest.raises(IndexingError, match="canonical parser_run.id"):
        index_parse_run_sync(session, parse_run, embedding_provider=FakeEmbeddingProvider())


def test_guard_scope_mismatch_rejections(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    # Mismatched family_id
    scope_bad_family = EvidenceScope(
        family_id="wrong_family",
        document_id=document_id,
        document_version=parse_run.version,
        parse_run_id=parse_run.id,
    )
    with pytest.raises(IndexingError, match="contradicts expected family_id"):
        index_parse_run_sync(session, parse_run, scope=scope_bad_family)

    with pytest.raises(IndexingError, match="authoritative family"):
        index_parse_run_sync(
            session,
            parse_run,
            family_id="other_family",
            embedding_provider=FakeEmbeddingProvider(),
        )

    # Mismatched document_id
    scope_bad_doc = EvidenceScope(
        family_id="mamagift",
        document_id="doc_other",
        document_version=parse_run.version,
        parse_run_id=parse_run.id,
    )
    with pytest.raises(IndexingError, match="contradicts parse_run document_id"):
        index_parse_run_sync(session, parse_run, scope=scope_bad_doc)

    # Mismatched document_version
    scope_bad_ver = EvidenceScope(
        family_id="mamagift",
        document_id=document_id,
        document_version=999,
        parse_run_id=parse_run.id,
    )
    with pytest.raises(IndexingError, match="contradicts parse_run version"):
        index_parse_run_sync(session, parse_run, scope=scope_bad_ver)

    # Mismatched parse_run_id
    scope_bad_run = EvidenceScope(
        family_id="mamagift",
        document_id=document_id,
        document_version=parse_run.version,
        parse_run_id="prun_other",
    )
    with pytest.raises(IndexingError, match="contradicts parse_run id"):
        index_parse_run_sync(session, parse_run, scope=scope_bad_run)


def test_guard_embedding_count_mismatch_raises(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    class BadVectorCountProvider:
        model_id = "bad-count"
        dimension = 1024
        embedding_version = "v1"

        async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
            # Return fewer vectors than texts
            return EmbeddingResult(
                vectors=[[0.1] * 1024],
                model=self.model_id,
                dimension=self.dimension,
                embedding_version=self.embedding_version,
            )

        async def embed_query(self, text: str) -> EmbeddingResult:
            return await self.embed_documents([text])

    with pytest.raises(IndexingError, match="embedding provider returned"):
        index_parse_run_sync(session, parse_run, embedding_provider=BadVectorCountProvider())


def test_needs_reindex_predicates() -> None:
    provider = FakeEmbeddingProvider(embedding_version="v1")

    # 1. total_chunks == 0
    assert needs_reindex(
        IndexStats(document_id="d", parse_run_id="p", total_chunks=0, embedded_chunks=0),
        provider,
    )

    # 2. embedded_chunks < total_chunks
    assert needs_reindex(
        IndexStats(
            document_id="d",
            parse_run_id="p",
            total_chunks=5,
            embedded_chunks=3,
            embedding_version="v1",
        ),
        provider,
    )

    # 3. version mismatch
    assert needs_reindex(
        IndexStats(
            document_id="d",
            parse_run_id="p",
            total_chunks=5,
            embedded_chunks=5,
            embedding_version="v0",
        ),
        provider,
    )

    # 4. up to date
    assert not needs_reindex(
        IndexStats(
            document_id="d",
            parse_run_id="p",
            total_chunks=5,
            embedded_chunks=5,
            embedding_version="v1",
        ),
        provider,
    )


def test_default_embedding_provider_test_and_prod(settings: Settings) -> None:
    # In test env
    test_settings = settings.model_copy(update={"app_env": "test"})
    p1 = get_default_embedding_provider(test_settings)
    assert isinstance(p1, FakeEmbeddingProvider)

    # In non-test env
    prod_settings = settings.model_copy(update={"app_env": "production"})
    p2 = get_default_embedding_provider(prod_settings)
    assert not isinstance(p2, FakeEmbeddingProvider)


def test_guard_chunk_provenance_mismatch(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    pdf_bytes = fixture_paths["quyet_dinh"].read_bytes()
    document_id, parse_run = _create_and_parse_document(
        client, upload, session, storage, settings, pdf_bytes
    )

    from mamagift_retrieval.chunk import Chunk, ChunkType

    # 1. chunk with wrong document_id
    def bad_doc_chunks(doc, document_version=None):
        return [
            Chunk(
                chunk_id="chunk:bad",
                document_id="doc_other",
                parse_run_id=parse_run.id,
                document_version=parse_run.version,
                chunk_type=ChunkType.PARAGRAPH,
                text="sample text",
                source_block_ids=["b1"],
                source_page_numbers=[1],
            )
        ]

    with patch("app.indexing.build_chunks", bad_doc_chunks):
        with pytest.raises(IndexingError, match="chunk document_id"):
            index_parse_run_sync(session, parse_run)

    # 2. chunk with wrong parse_run_id
    def bad_run_chunks(doc, document_version=None):
        return [
            Chunk(
                chunk_id="chunk:bad",
                document_id=parse_run.document_id,
                parse_run_id="prun_other",
                document_version=parse_run.version,
                chunk_type=ChunkType.PARAGRAPH,
                text="sample text",
                source_block_ids=["b1"],
                source_page_numbers=[1],
            )
        ]

    with patch("app.indexing.build_chunks", bad_run_chunks):
        with pytest.raises(IndexingError, match="chunk parse_run_id"):
            index_parse_run_sync(session, parse_run)

    # 3. chunk with wrong document_version
    def bad_ver_chunks(doc, document_version=None):
        return [
            Chunk(
                chunk_id="chunk:bad",
                document_id=parse_run.document_id,
                parse_run_id=parse_run.id,
                document_version=999,
                chunk_type=ChunkType.PARAGRAPH,
                text="sample text",
                source_block_ids=["b1"],
                source_page_numbers=[1],
            )
        ]

    with patch("app.indexing.build_chunks", bad_ver_chunks):
        with pytest.raises(IndexingError, match="chunk document_version"):
            index_parse_run_sync(session, parse_run)


def test_sqlite_foreign_keys_reject_violating_chunk_insert(
    session: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use the application engine so this proves the production connection listener,
    # not an unrelated test engine's local configuration.
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        engine.dispose()
        get_engine.cache_clear()
        pytest.skip("SQLite-specific foreign key enforcement test")

    try:
        with Session(engine) as app_session:
            document = Document(
                id="doc_fk",
                filename="fk.pdf",
                content_type="application/pdf",
                byte_size=1,
                checksum_sha256="sha_fk",
                storage_uri="local://fk",
            )
            app_session.add(document)
            app_session.commit()

            assert app_session.scalar(text("PRAGMA foreign_keys")) == 1
            app_session.add(
                DocumentChunk(
                    id="chunk_fk_ghost",
                    document_id=document.id,
                    parse_run_id="prun_ghost",
                    document_version=1,
                    chunk_index=0,
                    section_path=[],
                    page_numbers=[1],
                    source_block_ids=["b1"],
                    text="must be rejected",
                    token_count=3,
                )
            )
            with pytest.raises(IntegrityError):
                app_session.commit()
            app_session.rollback()
    finally:
        engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


def test_index_document_missing_parse_run_records_failure_on_document(
    session: Session,
) -> None:
    doc = Document(
        id="doc_unindexable_orphan",
        filename="orphan.pdf",
        content_type="application/pdf",
        byte_size=100,
        checksum_sha256="sha_orphan",
        storage_uri="local://orphan",
        status=DocumentStatus.READY_FOR_REVIEW.value,
    )
    session.add(doc)
    session.commit()

    with pytest.raises(IndexingError, match="no matching parse run found"):
        index_document_sync(session, "doc_unindexable_orphan")

    session.refresh(doc)
    assert doc.status == DocumentStatus.PARSE_FAILED.value
    assert doc.error_code == "parse_run_not_found"
    assert "no matching parse run found" in (doc.error_message or "")


def test_worker_drain_resilience_continues_when_indexing_fails(
    client: TestClient,
    upload,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    upload(client, fixture_paths["quyet_dinh"].read_bytes(), filename="failing-doc.pdf")
    upload(client, fixture_paths["cong_van"].read_bytes(), filename="succeeding-doc.pdf")

    docs = list(session.scalars(select(Document).order_by(Document.created_at.asc())).all())
    assert len(docs) == 2
    doc_fail, doc_success = docs[0], docs[1]

    provider = FakeEmbeddingProvider()
    real_index_sync = indexing.index_parse_run_sync

    def flaky_index_sync(
        sess: Session,
        parse_run: ParseRun,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if parse_run.document_id == doc_fail.id:
            # Simulate a missing parse run or indexing error for doc_fail
            failing_doc = sess.get(Document, doc_fail.id)
            if failing_doc is not None:
                failing_doc.error_code = "parse_run_not_found"
                failing_doc.error_message = (
                    f"no matching parse run found for document {doc_fail.id!r}"
                )
                if DocumentStatus(failing_doc.status) == DocumentStatus.READY_FOR_REVIEW:
                    ingestion.set_document_status(failing_doc, DocumentStatus.INDEXING)
                    ingestion.set_document_status(failing_doc, DocumentStatus.PARSE_FAILED)
                sess.commit()
            raise IndexingError(
                f"no matching parse run found for document {doc_fail.id!r}",
                code="parse_run_not_found",
            )
        return real_index_sync(sess, parse_run, *args, **kwargs)

    with patch.object(indexing, "index_parse_run_sync", side_effect=flaky_index_sync):
        processed = drain(
            session,
            storage,
            settings,
            "worker-test",
            auto_index=True,
            embedding_provider=provider,
        )

    assert processed == 2

    session.refresh(doc_fail)
    session.refresh(doc_success)

    assert doc_fail.status == DocumentStatus.PARSE_FAILED.value
    assert doc_fail.error_code == "parse_run_not_found"

    assert doc_success.status == DocumentStatus.READY.value
    assert doc_success.error_code is None
    success_chunks = list(
        session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_success.id)
        ).all()
    )
    assert len(success_chunks) > 0
