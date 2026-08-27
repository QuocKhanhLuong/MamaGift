"""SQL-backed implementation of ArchiveIndex across current documents in one family."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pgvector.sqlalchemy
from sqlalchemy import (
    Engine,
    Select,
    func,
    select,
    type_coerce,
)
from sqlalchemy.orm import Session, sessionmaker

from app.models import Document, DocumentChunk, ParseRun
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.index.entries import ScoredChunk
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.lexical import DEFAULT_BM25_B, DEFAULT_BM25_K1
from mamagift_retrieval.search.vi_tokenize import tokenize_vi

from .filters import ArchiveFilter, normalize_identifier
from .protocol import (
    ArchiveDocumentRef,
    ArchiveIndexStats,
    validate_archive_scope,
)


def _infer_chunk_type(chunk_id_str: str, section_path: list[str]) -> ChunkType:
    """Infer chunk type from section path or chunk ID. Copied from sql_index._infer_chunk_type."""
    if section_path:
        last_section = section_path[-1].strip().lower()
        if last_section.startswith("chương"):
            return ChunkType.LEGAL_CHAPTER
        if last_section.startswith("mục"):
            return ChunkType.LEGAL_SECTION
        if last_section.startswith("điều"):
            return ChunkType.LEGAL_ARTICLE
        if last_section.startswith("khoản"):
            return ChunkType.LEGAL_CLAUSE
        if last_section.startswith("điểm"):
            return ChunkType.LEGAL_POINT
        if last_section.startswith("phụ lục"):
            return ChunkType.APPENDIX
    if ":task:" in chunk_id_str:
        return ChunkType.PLAN_TASK
    if ":plan_section:" in chunk_id_str:
        return ChunkType.PLAN_SECTION
    return ChunkType.PARAGRAPH


def _build_chunk(chunk_row: DocumentChunk, doc_row: Document) -> Chunk:
    """Construct a Chunk object populating metadata from the joined Document row."""
    if not chunk_row.page_numbers or not chunk_row.source_block_ids:
        raise ValueError(f"stored chunk {chunk_row.id!r} has missing or empty source provenance")
    section_path = list(chunk_row.section_path) if chunk_row.section_path else []
    page_numbers = list(chunk_row.page_numbers)
    source_block_ids = list(chunk_row.source_block_ids)
    chunk_type = _infer_chunk_type(chunk_row.id, section_path)
    issued_date_str = doc_row.issued_date.isoformat() if doc_row.issued_date is not None else None
    return Chunk(
        chunk_id=chunk_row.id,
        parent_chunk_id=chunk_row.parent_chunk_id,
        document_id=chunk_row.document_id,
        parse_run_id=chunk_row.parse_run_id,
        document_version=chunk_row.document_version,
        document_type=doc_row.document_type,
        document_number=doc_row.document_number,
        issuer=doc_row.issuer,
        issued_date=issued_date_str,
        section_path=section_path,
        chunk_type=chunk_type,
        text=chunk_row.text,
        source_block_ids=source_block_ids,
        source_page_numbers=page_numbers,
        metadata={},
    )


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Exact cosine similarity between two vectors. Copied from sql_index._cosine_similarity."""
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"vector dimension mismatch: query vector has {len(vec_a)} dimensions, "
            f"chunk embedding has {len(vec_b)} dimensions"
        )
    dot = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0
    for a, b in zip(vec_a, vec_b, strict=True):
        dot += a * b
        norm_a_sq += a * a
        norm_b_sq += b * b

    norm_a = math.sqrt(norm_a_sq)
    norm_b = math.sqrt(norm_b_sq)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _current_version_select(*entities: Any) -> Select[Any]:
    """Base query enforcing the current-version invariant across document chunks.

    THE CURRENT-VERSION INVARIANT:
    Two independent facts must agree for a chunk to be visible in the archive:
    1. `parse_runs.is_current IS TRUE` (the parse run asserts it is current)
    2. `documents.current_parse_run_id = parse_runs.id` (the document pointer points to this run)

    If a document's `current_parse_run_id` points elsewhere while a stale parse run still has
    `is_current = true`, or vice versa, the row must yield NOTHING. No parameter or code path
    can omit or relax either predicate.
    """
    if not entities:
        entities = (DocumentChunk, Document, ParseRun)
    return (
        select(*entities)
        .select_from(DocumentChunk)
        .join(
            ParseRun,
            (ParseRun.id == DocumentChunk.parse_run_id)
            & (ParseRun.document_id == DocumentChunk.document_id)
            & (ParseRun.version == DocumentChunk.document_version),
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id,
        )
        .where(
            ParseRun.is_current.is_(True),
            Document.current_parse_run_id == ParseRun.id,
        )
    )


class SqlArchiveIndex:
    """SQL-backed implementation of ArchiveIndex across current documents in one family."""

    def __init__(
        self,
        session_or_factory: sessionmaker[Session] | Session | Engine | Callable[[], Session],
        *,
        embedding_version: str | None = None,
        default_embedding_version: str | None = None,
    ) -> None:
        self._session_or_factory = session_or_factory
        self._embedding_version = embedding_version or default_embedding_version

    @contextmanager
    def _get_session(self) -> Iterator[Session]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        elif isinstance(self._session_or_factory, Engine):
            with Session(self._session_or_factory, expire_on_commit=False) as session:
                yield session
        elif callable(self._session_or_factory):
            session = self._session_or_factory()
            try:
                yield session
            finally:
                session.close()
        else:
            raise TypeError(
                f"unsupported session_or_factory type: {type(self._session_or_factory)}"
            )

    def _apply_filters(
        self,
        session: Session,
        stmt: Select[Any],
        filters: ArchiveFilter | None,
    ) -> Select[Any]:
        if filters is None:
            return stmt

        if filters.document_ids is not None:
            stmt = stmt.where(Document.id.in_(filters.document_ids))

        if filters.document_types is not None:
            stmt = stmt.where(Document.document_type.in_(filters.document_types))

        if filters.issuers is not None:
            lowered_issuers = [i.lower() for i in filters.issuers]
            dialect_name = session.bind.dialect.name if session.bind is not None else "sqlite"
            if dialect_name == "postgresql":
                stmt = stmt.where(
                    Document.issuer.is_not(None),
                    func.lower(Document.issuer).in_(lowered_issuers),
                )
            else:
                # SQLite built-in lower() only lowers ASCII (missing Unicode Vietnamese 'Đ' -> 'đ')
                target_issuers = set(lowered_issuers)
                doc_rows = session.execute(
                    select(Document.id, Document.issuer).where(Document.issuer.is_not(None))
                ).all()
                matching_doc_ids = [
                    doc_id
                    for doc_id, doc_iss in doc_rows
                    if doc_iss is not None and doc_iss.lower() in target_issuers
                ]
                stmt = stmt.where(Document.id.in_(matching_doc_ids))

        if filters.issued_date_from is not None:
            stmt = stmt.where(
                Document.issued_date.is_not(None),
                Document.issued_date >= filters.issued_date_from,
            )

        if filters.issued_date_to is not None:
            stmt = stmt.where(
                Document.issued_date.is_not(None),
                Document.issued_date <= filters.issued_date_to,
            )

        if not filters.include_requires_review:
            stmt = stmt.where(Document.requires_user_review.is_(False))

        if filters.document_numbers is not None:
            norm_targets = set(filters.normalized_document_numbers() or [])
            doc_rows = session.execute(
                select(Document.id, Document.document_number).where(
                    Document.document_number.is_not(None)
                )
            ).all()
            matching_doc_ids = [
                doc_id
                for doc_id, doc_num in doc_rows
                if doc_num is not None and normalize_identifier(doc_num) in norm_targets
            ]
            stmt = stmt.where(Document.id.in_(matching_doc_ids))

        return stmt

    def current_documents(
        self,
        scope: EvidenceScope,
        filters: ArchiveFilter | None = None,
    ) -> list[ArchiveDocumentRef]:
        """Every current document matching `filters`, ordered by document_id ascending."""
        validate_archive_scope(scope)
        if filters is not None and filters.matches_nothing():
            return []

        with self._get_session() as session:
            stmt = _current_version_select(Document, ParseRun.version)
            stmt = self._apply_filters(session, stmt, filters)
            stmt = stmt.distinct().order_by(Document.id.asc())

            results: list[ArchiveDocumentRef] = []
            seen_doc_ids: set[str] = set()
            for doc, doc_version in session.execute(stmt).all():
                if doc.id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc.id)
                results.append(
                    ArchiveDocumentRef(
                        document_id=doc.id,
                        parse_run_id=doc.current_parse_run_id,
                        document_version=doc_version,
                        document_type=doc.document_type,
                        document_number=doc.document_number,
                        title=doc.title,
                        issuer=doc.issuer,
                        issued_date=doc.issued_date,
                        requires_user_review=doc.requires_user_review,
                    )
                )

            results.sort(key=lambda ref: ref.document_id)
            return results

    def search_dense(
        self,
        scope: EvidenceScope,
        query_vector: list[float],
        top_k: int,
        filters: ArchiveFilter | None = None,
    ) -> list[ScoredChunk]:
        """Exact vector search over current-version chunks, ranked 1-based, descending score."""
        validate_archive_scope(scope)
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
        if not query_vector:
            raise ValueError("query_vector cannot be empty")
        if filters is not None and filters.matches_nothing():
            return []

        with self._get_session() as session:
            stmt = _current_version_select(DocumentChunk, Document)
            stmt = stmt.where(DocumentChunk.embedding.is_not(None))

            target_version = self._embedding_version
            if target_version is not None:
                stmt = stmt.where(DocumentChunk.embedding_version == target_version)
            else:
                version_stmt = (
                    _current_version_select(DocumentChunk.embedding_version)
                    .where(DocumentChunk.embedding.is_not(None))
                    .where(DocumentChunk.embedding_version.is_not(None))
                )
                version_stmt = self._apply_filters(session, version_stmt, filters)
                first_version = session.scalars(version_stmt.limit(1)).first()
                if first_version is not None:
                    stmt = stmt.where(DocumentChunk.embedding_version == first_version)

            stmt = self._apply_filters(session, stmt, filters)

            dialect_name = session.bind.dialect.name if session.bind is not None else "sqlite"
            if dialect_name == "postgresql":
                dist_expr = type_coerce(
                    DocumentChunk.embedding, pgvector.sqlalchemy.Vector
                ).cosine_distance(query_vector)

                pg_stmt = stmt.add_columns(dist_expr.label("distance"))
                pg_stmt = pg_stmt.order_by(dist_expr.asc(), DocumentChunk.id.asc()).limit(top_k)

                rows = session.execute(pg_stmt).all()
                results: list[ScoredChunk] = []
                for idx, row in enumerate(rows):
                    chunk_row: DocumentChunk = row[0]
                    doc_row: Document = row[1]
                    distance = float(row[2])
                    score = 1.0 - distance
                    chunk = _build_chunk(chunk_row, doc_row)
                    results.append(
                        ScoredChunk(
                            chunk=chunk,
                            score=score,
                            rank=idx + 1,
                            retriever="dense",
                        )
                    )
                return results
            else:
                rows = session.execute(stmt).all()
                candidates: list[tuple[float, Chunk]] = []
                for chunk_row, doc_row in rows:
                    if chunk_row.embedding is None:
                        continue
                    score = _cosine_similarity(query_vector, chunk_row.embedding)
                    chunk = _build_chunk(chunk_row, doc_row)
                    candidates.append((score, chunk))

                candidates.sort(key=lambda item: (-item[0], item[1].chunk_id))
                top_results = candidates[:top_k]
                return [
                    ScoredChunk(
                        chunk=chunk,
                        score=score,
                        rank=idx + 1,
                        retriever="dense",
                    )
                    for idx, (score, chunk) in enumerate(top_results)
                ]

    def search_lexical(
        self,
        scope: EvidenceScope,
        query: str,
        top_k: int,
        filters: ArchiveFilter | None = None,
    ) -> list[ScoredChunk]:
        """BM25 search over current-version chunks, ranked 1-based, descending score."""
        validate_archive_scope(scope)
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
        if query is None or not query.strip():
            return []
        if filters is not None and filters.matches_nothing():
            return []

        query_tokens = tokenize_vi(query)
        if not query_tokens:
            return []
        query_tf = Counter(query_tokens)

        with self._get_session() as session:
            stmt = _current_version_select(DocumentChunk, Document)
            stmt = self._apply_filters(session, stmt, filters)
            rows = session.execute(stmt).all()

            if not rows:
                return []

            chunks: list[Chunk] = [_build_chunk(chunk_row, doc_row) for chunk_row, doc_row in rows]
            num_docs = len(chunks)

            doc_tf: dict[str, dict[str, int]] = {}
            doc_len: dict[str, int] = {}
            doc_freq: dict[str, int] = Counter()

            for chunk in chunks:
                tokens = tokenize_vi(chunk.text)
                doc_len[chunk.chunk_id] = len(tokens)
                tf = Counter(tokens)
                doc_tf[chunk.chunk_id] = dict(tf)
                for term in tf:
                    doc_freq[term] += 1

            total_len = sum(doc_len.values())
            avgdl = (total_len / num_docs) if num_docs > 0 else 0.0

            candidates: list[tuple[float, Chunk]] = []
            for chunk in chunks:
                chunk_id = chunk.chunk_id
                tf_map = doc_tf.get(chunk_id, {})
                dl = doc_len.get(chunk_id, 0)
                len_norm = (
                    (1.0 - DEFAULT_BM25_B + DEFAULT_BM25_B * (dl / avgdl)) if avgdl > 0.0 else 1.0
                )

                score = 0.0
                has_match = False

                for term, qtf in query_tf.items():
                    f = tf_map.get(term, 0)
                    if f > 0:
                        has_match = True
                        df = doc_freq.get(term, 0)
                        idf = math.log(1.0 + (num_docs - df + 0.5) / (df + 0.5))
                        tf_norm = (f * (DEFAULT_BM25_K1 + 1.0)) / (f + DEFAULT_BM25_K1 * len_norm)
                        score += qtf * idf * tf_norm

                if has_match and score > 0.0:
                    candidates.append((score, chunk))

            candidates.sort(key=lambda item: (-item[0], item[1].chunk_id))
            top_candidates = candidates[:top_k]

            return [
                ScoredChunk(
                    chunk=chunk,
                    score=score,
                    rank=idx + 1,
                    retriever="lexical",
                )
                for idx, (score, chunk) in enumerate(top_candidates)
            ]

    def stats(
        self,
        scope: EvidenceScope,
        filters: ArchiveFilter | None = None,
    ) -> ArchiveIndexStats:
        """Counts for the current-version corpus matching `filters`."""
        validate_archive_scope(scope)
        if filters is not None and filters.matches_nothing():
            return ArchiveIndexStats(
                total_documents=0,
                total_chunks=0,
                embedded_chunks=0,
                embedding_model=None,
                embedding_version=self._embedding_version,
            )

        with self._get_session() as session:
            stmt = _current_version_select(DocumentChunk, Document)
            stmt = self._apply_filters(session, stmt, filters)
            rows = session.execute(stmt).all()

            if not rows:
                return ArchiveIndexStats(
                    total_documents=0,
                    total_chunks=0,
                    embedded_chunks=0,
                    embedding_model=None,
                    embedding_version=self._embedding_version,
                )

            seen_docs: set[str] = set()
            total_chunks = len(rows)
            embedded_chunks = 0
            embedding_model: str | None = None
            embedding_version: str | None = self._embedding_version

            for chunk_row, doc_row in rows:
                seen_docs.add(doc_row.id)
                if chunk_row.embedding is not None:
                    embedded_chunks += 1
                    if embedding_model is None and chunk_row.embedding_model is not None:
                        embedding_model = chunk_row.embedding_model
                    if embedding_version is None and chunk_row.embedding_version is not None:
                        embedding_version = chunk_row.embedding_version

            return ArchiveIndexStats(
                total_documents=len(seen_docs),
                total_chunks=total_chunks,
                embedded_chunks=embedded_chunks,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
            )


__all__ = ["SqlArchiveIndex"]
