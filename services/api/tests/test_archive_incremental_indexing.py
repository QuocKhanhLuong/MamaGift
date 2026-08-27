"""Phase 5 exit criterion: a newly indexed document becomes archive-answerable at once.

These tests drive the real path -- upload, parse, index -- and then query the archive index
through the same FastAPI application object, with no restart, no rebuild step and no model
training. They also cover the failure-isolation requirement: one document whose indexing fails
must not stop the others from becoming answerable.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.indexing import IndexingError, index_parse_run, index_parse_run_sync
from app.models import Document, DocumentRelation, ParseRun
from app.settings import Settings
from app.state_machine import DocumentStatus
from app.storage import LocalObjectStorage
from app.worker import process_next_job
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.scope import EvidenceScope

EMBEDDING_VERSION = "fake-bge-m3-v1"


def _provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(dimension=1024, embedding_version=EMBEDDING_VERSION)


def _archive(session: Session) -> SqlArchiveIndex:
    return SqlArchiveIndex(session, default_embedding_version=EMBEDDING_VERSION)


def _archive_scope() -> EvidenceScope:
    return EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=True)


def _upload_and_parse(
    client: TestClient,
    upload: Any,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    pdf_bytes: bytes,
    filename: str,
) -> tuple[str, ParseRun]:
    response = upload(client, pdf_bytes, filename=filename)
    assert response.status_code == 202
    document_id = response.json()["document"]["id"]
    run = process_next_job(session, storage, settings, "worker-test", auto_index=False)
    assert run is not None and run.document_id == document_id
    return document_id, run


def test_newly_indexed_document_is_immediately_archive_retrievable(
    client: TestClient,
    upload: Any,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    """Exit criteria 1, 2 and 3: retrievable at once, no restart, no fine-tuning."""
    archive = _archive(session)
    assert archive.current_documents(_archive_scope()) == []

    document_id, parse_run = _upload_and_parse(
        client,
        upload,
        session,
        storage,
        settings,
        fixture_paths["quyet_dinh"].read_bytes(),
        "quyet-dinh.pdf",
    )

    # Nothing is answerable before indexing: the document exists but has no chunks.
    assert archive.current_documents(_archive_scope()) == []

    provider = _provider()
    stats = index_parse_run_sync(session, parse_run, embedding_provider=provider)
    assert stats.total_chunks > 0

    # The SAME index object, in the SAME process, now sees the document. No restart, no
    # separate archive build step, and the embedding provider was only ever asked to embed --
    # never to train.
    documents = archive.current_documents(_archive_scope())
    assert [doc.document_id for doc in documents] == [document_id]
    assert documents[0].parse_run_id == parse_run.id
    assert documents[0].document_version == parse_run.version

    lexical = archive.search_lexical(_archive_scope(), "quyết định", top_k=10)
    assert lexical, "a freshly indexed document must be lexically retrievable"
    assert {hit.chunk.document_id for hit in lexical} == {document_id}

    query_vector = asyncio.run(provider.embed_query("quyết định")).vectors[0]
    dense = archive.search_dense(_archive_scope(), query_vector, top_k=10)
    assert dense
    assert {hit.chunk.document_id for hit in dense} == {document_id}


def test_second_document_joins_the_archive_without_reindexing_the_first(
    client: TestClient,
    upload: Any,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    """Indexing is incremental: adding a document does not touch the existing one."""
    archive = _archive(session)
    first_id, first_run = _upload_and_parse(
        client,
        upload,
        session,
        storage,
        settings,
        fixture_paths["quyet_dinh"].read_bytes(),
        "quyet-dinh.pdf",
    )
    index_parse_run_sync(session, first_run, embedding_provider=_provider())
    first_stats = archive.stats(_archive_scope())

    second_id, second_run = _upload_and_parse(
        client,
        upload,
        session,
        storage,
        settings,
        fixture_paths["cong_van"].read_bytes(),
        "cong-van.pdf",
    )
    index_parse_run_sync(session, second_run, embedding_provider=_provider())

    documents = {doc.document_id for doc in archive.current_documents(_archive_scope())}
    assert documents == {first_id, second_id}

    after = archive.stats(_archive_scope())
    assert after.total_documents == 2
    assert after.total_chunks > first_stats.total_chunks


def test_one_failed_indexing_job_does_not_stop_the_other_documents(
    client: TestClient,
    upload: Any,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    """Mandatory case 14: a failing document is isolated, not contagious."""
    good_id, good_run = _upload_and_parse(
        client,
        upload,
        session,
        storage,
        settings,
        fixture_paths["quyet_dinh"].read_bytes(),
        "quyet-dinh.pdf",
    )
    index_parse_run_sync(session, good_run, embedding_provider=_provider())

    bad_id, bad_run = _upload_and_parse(
        client,
        upload,
        session,
        storage,
        settings,
        fixture_paths["cong_van"].read_bytes(),
        "cong-van.pdf",
    )

    class _ExplodingProvider(FakeEmbeddingProvider):
        async def embed_documents(self, texts: list[str]) -> Any:
            raise RuntimeError("embedding backend exploded")

    with pytest.raises(IndexingError):
        asyncio.run(
            index_parse_run(
                session,
                bad_run,
                embedding_provider=_ExplodingProvider(
                    dimension=1024, embedding_version=EMBEDDING_VERSION
                ),
            )
        )

    failed = session.get(Document, bad_id)
    assert failed is not None
    assert failed.status == DocumentStatus.PARSE_FAILED.value
    assert failed.error_code

    # The healthy document is untouched and still answerable.
    healthy = session.get(Document, good_id)
    assert healthy is not None
    assert healthy.status == DocumentStatus.READY.value

    archive = _archive(session)
    documents = {doc.document_id for doc in archive.current_documents(_archive_scope())}
    assert documents == {good_id}, "the failed document must not appear, the healthy one must"

    hits = archive.search_lexical(_archive_scope(), "quyết định", top_k=10)
    assert hits and {hit.chunk.document_id for hit in hits} == {good_id}

    # The failed document recovers on retry with a working provider, and joins the archive
    # without the healthy document being reindexed or disturbed.
    index_parse_run_sync(session, bad_run, embedding_provider=_provider())
    recovered = session.get(Document, bad_id)
    assert recovered is not None and recovered.status == DocumentStatus.READY.value
    assert recovered.error_code is None

    documents = {doc.document_id for doc in archive.current_documents(_archive_scope())}
    assert documents == {good_id, bad_id}


def test_relation_extraction_failure_does_not_fail_indexing(
    client: TestClient,
    upload: Any,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chunks make a document answerable; relations are an additional, optional signal.

    A relation-extraction bug must therefore never make a document unanswerable.
    """
    document_id, parse_run = _upload_and_parse(
        client,
        upload,
        session,
        storage,
        settings,
        fixture_paths["quyet_dinh"].read_bytes(),
        "quyet-dinh.pdf",
    )

    def _explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("relation extraction exploded")

    monkeypatch.setattr("app.indexing.persist_relations", _explode)
    stats = index_parse_run_sync(session, parse_run, embedding_provider=_provider())

    assert stats.total_chunks > 0
    doc = session.get(Document, document_id)
    assert doc is not None and doc.status == DocumentStatus.READY.value
    assert _archive(session).current_documents(_archive_scope())


def test_indexing_records_relations_alongside_chunks(
    client: TestClient,
    upload: Any,
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    fixture_paths: dict[str, Any],
) -> None:
    """Relations are written in the same indexing pass, and never invent a document."""
    documents_before = session.query(Document).count()
    _, parse_run = _upload_and_parse(
        client,
        upload,
        session,
        storage,
        settings,
        fixture_paths["quyet_dinh"].read_bytes(),
        "quyet-dinh.pdf",
    )
    index_parse_run_sync(session, parse_run, embedding_provider=_provider())

    relations = session.query(DocumentRelation).all()
    for relation in relations:
        assert relation.review_state == "unverified"
        assert relation.source_parse_run_id == parse_run.id
        assert relation.source_block_ids, "a relation must carry block provenance"
        assert relation.page_numbers
        assert relation.target_document_id is not None or relation.target_document_number

    # Exactly one document was uploaded; no relation may have conjured another.
    assert session.query(Document).count() == documents_before + 1
