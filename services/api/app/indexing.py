"""Runtime indexing pipeline: turns a completed parse run into indexed, embedded chunks.

Conforms to Phase 4 Plan (§2, §3.6, §4 row D1).
Builds structure-aware chunks via `mamagift_retrieval.chunking.build_chunks`,
embeds them via an `EmbeddingProvider`, and atomically persists them
via `DocumentIndex.replace` into the `document_chunks` table.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mamagift_docpipe import CanonicalDocument
from mamagift_retrieval.chunk import Chunk, validate_chunk_tree
from mamagift_retrieval.chunking import build_chunks
from mamagift_retrieval.index import DocumentIndex, IndexEntry, IndexStats, SqlDocumentIndex
from mamagift_retrieval.providers import (
    BgeM3EmbeddingProvider,
    EmbeddingProvider,
    FakeEmbeddingProvider,
)
from mamagift_retrieval.scope import EvidenceScope

from .ingestion import set_document_status
from .models import Document, ParseRun
from .settings import Settings, get_settings
from .state_machine import DocumentStatus

AUTHORITATIVE_FAMILY_ID = "mamagift"


class IndexingError(Exception):
    """Raised when indexing a parse run or document fails."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "indexing_failure",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.details = details or {}


def get_default_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Return configured embedding provider based on environment settings."""
    app_settings = settings or get_settings()
    if app_settings.app_env == "test":
        return FakeEmbeddingProvider(
            model_id=app_settings.embedding_model,
            embedding_version=f"{app_settings.embedding_model}-v1",
        )
    return BgeM3EmbeddingProvider(
        base_url=app_settings.embedding_base_url,
        model_id=app_settings.embedding_model,
        embedding_version=f"{app_settings.embedding_model}-v1",
        api_key=app_settings.embedding_api_key,
        timeout=app_settings.embedding_timeout_seconds,
    )


def needs_reindex(stats: IndexStats, provider: EmbeddingProvider) -> bool:
    """Check whether indexed chunks are missing, incomplete, or from a stale embedding version."""
    if stats.total_chunks == 0:
        return True
    if stats.embedded_chunks < stats.total_chunks:
        return True
    if stats.embedding_version != provider.embedding_version:
        return True
    return False


async def index_parse_run(
    session: Session,
    parse_run: ParseRun,
    embedding_provider: EmbeddingProvider | None = None,
    document_index: DocumentIndex | None = None,
    *,
    scope: EvidenceScope | None = None,
    family_id: str = "mamagift",
    settings: Settings | None = None,
) -> IndexStats:
    """Index and embed all chunks for a completed parse run.

    Transitions document state: READY_FOR_REVIEW -> INDEXING -> READY.
    On failure, transitions INDEXING -> PARSE_FAILED, leaving ParseRun intact.
    """
    if not parse_run.id:
        raise IndexingError("parse_run must have a valid id", code="invalid_parse_run")

    authoritative_parse_run = session.get(ParseRun, parse_run.id)
    if authoritative_parse_run is None:
        raise IndexingError(
            f"parse run {parse_run.id!r} not found in database",
            code="parse_run_not_found",
        )
    parse_run = authoritative_parse_run

    if not parse_run.document_id:
        raise IndexingError("parse_run must have a valid document_id", code="invalid_parse_run")
    if parse_run.version is None or parse_run.version < 1:
        raise IndexingError(
            "parse_run must have a positive version number", code="invalid_parse_run"
        )
    if not parse_run.canonical:
        raise IndexingError("parse_run must contain a canonical document", code="invalid_parse_run")

    document = session.get(Document, parse_run.document_id)
    if document is None:
        raise IndexingError(
            f"document {parse_run.document_id!r} not found in database",
            code="document_not_found",
        )
    if parse_run.document_id != document.id:
        raise IndexingError(
            f"parse_run document_id {parse_run.document_id!r} "
            f"contradicts document.id {document.id!r}",
            code="scope_mismatch",
        )

    if family_id != AUTHORITATIVE_FAMILY_ID:
        raise IndexingError(
            f"family_id {family_id!r} is not the authoritative family {AUTHORITATIVE_FAMILY_ID!r}",
            code="scope_mismatch",
        )

    # Validate or construct EvidenceScope with the full 4-tuple
    if scope is not None:
        if not scope.family_id or scope.family_id != family_id:
            raise IndexingError(
                f"scope family_id {scope.family_id!r} contradicts expected family_id {family_id!r}",
                code="scope_mismatch",
            )
        if scope.document_id is not None and scope.document_id != parse_run.document_id:
            raise IndexingError(
                f"scope document_id {scope.document_id!r} "
                f"contradicts parse_run document_id {parse_run.document_id!r}",
                code="scope_mismatch",
            )
        if scope.document_version is not None and scope.document_version != parse_run.version:
            raise IndexingError(
                f"scope document_version {scope.document_version!r} "
                f"contradicts parse_run version {parse_run.version!r}",
                code="scope_mismatch",
            )
        if scope.parse_run_id is not None and scope.parse_run_id != parse_run.id:
            raise IndexingError(
                f"scope parse_run_id {scope.parse_run_id!r} "
                f"contradicts parse_run id {parse_run.id!r}",
                code="scope_mismatch",
            )
        effective_scope = EvidenceScope(
            family_id=scope.family_id,
            user_id=scope.user_id,
            thread_id=scope.thread_id,
            document_id=parse_run.document_id,
            document_version=parse_run.version,
            parse_run_id=parse_run.id,
        )
    else:
        effective_scope = EvidenceScope(
            family_id=family_id,
            document_id=parse_run.document_id,
            document_version=parse_run.version,
            parse_run_id=parse_run.id,
        )

    provider = embedding_provider or get_default_embedding_provider(settings)
    index = document_index or SqlDocumentIndex(
        session, default_embedding_version=provider.embedding_version
    )

    existing_stats = index.stats(effective_scope)
    if not needs_reindex(existing_stats, provider):
        return existing_stats

    # Transition to INDEXING
    curr_status = DocumentStatus(document.status)
    if curr_status == DocumentStatus.PARSE_FAILED:
        set_document_status(document, DocumentStatus.QUEUED_FOR_PARSE)
        set_document_status(document, DocumentStatus.PARSING)
        set_document_status(document, DocumentStatus.NORMALIZING)
        set_document_status(document, DocumentStatus.STRUCTURING)
        set_document_status(document, DocumentStatus.READY_FOR_REVIEW)
        set_document_status(document, DocumentStatus.INDEXING)
        session.commit()
    elif curr_status == DocumentStatus.READY_FOR_REVIEW:
        set_document_status(document, DocumentStatus.INDEXING)
        session.commit()
    elif curr_status == DocumentStatus.READY:
        set_document_status(document, DocumentStatus.QUEUED_FOR_PARSE)
        set_document_status(document, DocumentStatus.PARSING)
        set_document_status(document, DocumentStatus.NORMALIZING)
        set_document_status(document, DocumentStatus.STRUCTURING)
        set_document_status(document, DocumentStatus.READY_FOR_REVIEW)
        set_document_status(document, DocumentStatus.INDEXING)
        session.commit()
    else:
        # Delegate unsupported starts to the existing state machine so no rows can
        # be written without a legal READY_FOR_REVIEW -> INDEXING transition.
        set_document_status(document, DocumentStatus.INDEXING)

    try:
        # Reconstruct CanonicalDocument and build chunks
        canonical = CanonicalDocument.model_validate(parse_run.canonical)
        if canonical.document_id != parse_run.document_id:
            raise IndexingError(
                f"canonical document_id {canonical.document_id!r} != {parse_run.document_id!r}",
                code="provenance_violation",
            )
        expected_parser_run_id = f"prun_{parse_run.parser_name}_{parse_run.configuration_hash}"
        if canonical.parser_run.id != expected_parser_run_id:
            raise IndexingError(
                f"canonical parser_run.id {canonical.parser_run.id!r} "
                f"!= expected {expected_parser_run_id!r}",
                code="provenance_violation",
            )
        if canonical.parser_run.parser_name != parse_run.parser_name:
            raise IndexingError(
                f"canonical parser_name {canonical.parser_run.parser_name!r} "
                f"!= {parse_run.parser_name!r}",
                code="provenance_violation",
            )
        if canonical.parser_run.parser_version != parse_run.parser_version:
            raise IndexingError(
                f"canonical parser_version {canonical.parser_run.parser_version!r} "
                f"!= {parse_run.parser_version!r}",
                code="provenance_violation",
            )
        if canonical.parser_run.configuration_hash != parse_run.configuration_hash:
            raise IndexingError(
                f"canonical configuration_hash {canonical.parser_run.configuration_hash!r} "
                f"!= {parse_run.configuration_hash!r}",
                code="provenance_violation",
            )
        # The canonical artifact keeps the parser/provider run identity above.  The
        # derived chunk rows must instead bind to the authoritative database ParseRun
        # identity for the composite FK, without mutating the stored canonical JSON.
        chunk_canonical = canonical.model_copy(
            update={"parser_run": canonical.parser_run.model_copy(update={"id": parse_run.id})}
        )
        chunks: list[Chunk] = build_chunks(chunk_canonical, document_version=parse_run.version)

        # Enforce full provenance validation on all generated chunks
        for chunk in chunks:
            if chunk.document_id != parse_run.document_id:
                raise IndexingError(
                    f"chunk document_id {chunk.document_id!r} != {parse_run.document_id!r}",
                    code="provenance_violation",
                )
            if chunk.parse_run_id != parse_run.id:
                raise IndexingError(
                    f"chunk parse_run_id {chunk.parse_run_id!r} != {parse_run.id!r}",
                    code="provenance_violation",
                )
            if chunk.document_version != parse_run.version:
                raise IndexingError(
                    f"chunk document_version {chunk.document_version!r} != {parse_run.version!r}",
                    code="provenance_violation",
                )

        validate_chunk_tree(chunks)

        # Generate embeddings
        texts = [chunk.text for chunk in chunks]
        if texts:
            embed_result = await provider.embed_documents(texts)
            if len(embed_result.vectors) != len(texts):
                raise IndexingError(
                    f"embedding provider returned {len(embed_result.vectors)} "
                    f"vectors for {len(texts)} texts",
                    code="embedding_count_mismatch",
                )
            vectors: list[list[float]] | None = embed_result.vectors
            model_id: str | None = embed_result.model
            embedding_version: str | None = embed_result.embedding_version
        else:
            vectors = None
            model_id = provider.model_id
            embedding_version = provider.embedding_version

        # Prepare IndexEntry objects
        entries: list[IndexEntry] = []
        for idx, chunk in enumerate(chunks):
            vec = vectors[idx] if vectors is not None else None
            tok_count = len(chunk.text.split())
            entry = IndexEntry(
                chunk=chunk,
                chunk_index=idx,
                token_count=tok_count,
                embedding=vec,
                embedding_model=model_id,
                embedding_version=embedding_version,
            )
            entries.append(entry)

        # Atomic persistence through DocumentIndex.replace
        stats = index.replace(effective_scope, entries)

        # Transition INDEXING -> READY
        doc = session.get(Document, parse_run.document_id)
        if doc is not None:
            if DocumentStatus(doc.status) == DocumentStatus.INDEXING:
                set_document_status(doc, DocumentStatus.READY)
            doc.error_code = None
            doc.error_message = None
            session.commit()
        return stats

    except Exception as exc:
        session.rollback()
        # Retrieve document again after rollback to record failure state safely
        failed_doc = session.get(Document, parse_run.document_id)
        if failed_doc is not None:
            failed_doc.error_code = getattr(exc, "code", "indexing_failure")
            failed_doc.error_message = str(exc)
            if DocumentStatus(failed_doc.status) == DocumentStatus.INDEXING:
                set_document_status(failed_doc, DocumentStatus.PARSE_FAILED)
            session.commit()

        if isinstance(exc, IndexingError):
            raise
        raise IndexingError(
            f"indexing failed for parse run {parse_run.id}: {exc}",
            code=getattr(exc, "code", "indexing_failure"),
        ) from exc


def index_parse_run_sync(
    session: Session,
    parse_run: ParseRun,
    embedding_provider: EmbeddingProvider | None = None,
    document_index: DocumentIndex | None = None,
    *,
    scope: EvidenceScope | None = None,
    family_id: str = "mamagift",
    settings: Settings | None = None,
) -> IndexStats:
    """Synchronous wrapper for `index_parse_run`."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        raise RuntimeError(
            "index_parse_run_sync cannot run inside an active event loop; "
            "await index_parse_run instead"
        )
    return asyncio.run(
        index_parse_run(
            session=session,
            parse_run=parse_run,
            embedding_provider=embedding_provider,
            document_index=document_index,
            scope=scope,
            family_id=family_id,
            settings=settings,
        )
    )


async def index_document(
    session: Session,
    document_id: str,
    embedding_provider: EmbeddingProvider | None = None,
    document_index: DocumentIndex | None = None,
    *,
    version: int | None = None,
    parse_run_id: str | None = None,
    scope: EvidenceScope | None = None,
    family_id: str = "mamagift",
    settings: Settings | None = None,
) -> IndexStats:
    """Index a document's parse run (defaults to current parse run)."""
    stmt = select(ParseRun).where(ParseRun.document_id == document_id)
    if parse_run_id is not None:
        stmt = stmt.where(ParseRun.id == parse_run_id)
    elif version is not None:
        stmt = stmt.where(ParseRun.version == version)
    else:
        stmt = stmt.where(ParseRun.is_current.is_(True))

    parse_run = session.scalar(stmt)
    if parse_run is None:
        doc = session.get(Document, document_id)
        if doc is not None:
            doc.error_code = "parse_run_not_found"
            doc.error_message = f"no matching parse run found for document {document_id!r}"
            curr_status = DocumentStatus(doc.status)
            if curr_status == DocumentStatus.READY_FOR_REVIEW:
                set_document_status(doc, DocumentStatus.INDEXING)
                set_document_status(doc, DocumentStatus.PARSE_FAILED)
                session.commit()
            elif curr_status == DocumentStatus.INDEXING:
                set_document_status(doc, DocumentStatus.PARSE_FAILED)
                session.commit()
        raise IndexingError(
            f"no matching parse run found for document {document_id!r}",
            code="parse_run_not_found",
        )

    return await index_parse_run(
        session=session,
        parse_run=parse_run,
        embedding_provider=embedding_provider,
        document_index=document_index,
        scope=scope,
        family_id=family_id,
        settings=settings,
    )


def index_document_sync(
    session: Session,
    document_id: str,
    embedding_provider: EmbeddingProvider | None = None,
    document_index: DocumentIndex | None = None,
    *,
    version: int | None = None,
    parse_run_id: str | None = None,
    scope: EvidenceScope | None = None,
    family_id: str = "mamagift",
    settings: Settings | None = None,
) -> IndexStats:
    """Synchronous wrapper for `index_document`."""
    stmt = select(ParseRun).where(ParseRun.document_id == document_id)
    if parse_run_id is not None:
        stmt = stmt.where(ParseRun.id == parse_run_id)
    elif version is not None:
        stmt = stmt.where(ParseRun.version == version)
    else:
        stmt = stmt.where(ParseRun.is_current.is_(True))

    parse_run = session.scalar(stmt)
    if parse_run is None:
        doc = session.get(Document, document_id)
        if doc is not None:
            doc.error_code = "parse_run_not_found"
            doc.error_message = f"no matching parse run found for document {document_id!r}"
            curr_status = DocumentStatus(doc.status)
            if curr_status == DocumentStatus.READY_FOR_REVIEW:
                set_document_status(doc, DocumentStatus.INDEXING)
                set_document_status(doc, DocumentStatus.PARSE_FAILED)
                session.commit()
            elif curr_status == DocumentStatus.INDEXING:
                set_document_status(doc, DocumentStatus.PARSE_FAILED)
                session.commit()
        raise IndexingError(
            f"no matching parse run found for document {document_id!r}",
            code="parse_run_not_found",
        )

    return index_parse_run_sync(
        session=session,
        parse_run=parse_run,
        embedding_provider=embedding_provider,
        document_index=document_index,
        scope=scope,
        family_id=family_id,
        settings=settings,
    )
