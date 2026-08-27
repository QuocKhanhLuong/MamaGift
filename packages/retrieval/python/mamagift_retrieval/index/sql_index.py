"""SQL-backed implementation of single-document version-keyed DocumentIndex."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import (
    CursorResult,
    Engine,
    delete,
    select,
)
from sqlalchemy.orm import Session, sessionmaker

from app.models import DocumentChunk
from mamagift_retrieval.chunk import Chunk, ChunkType, validate_chunk_tree
from mamagift_retrieval.scope import EvidenceScope, scope_matches

from .entries import IndexEntry, IndexStats, ScoredChunk
from .protocol import AUTHORITATIVE_FAMILY_ID

_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def _validate_authoritative_family(scope: EvidenceScope) -> None:
    if not scope.family_id:
        raise ValueError("scope must specify family_id")
    if scope.family_id != AUTHORITATIVE_FAMILY_ID:
        raise ValueError(
            f"scope family_id {scope.family_id!r} is not authoritative; "
            f"expected {AUTHORITATIVE_FAMILY_ID!r}"
        )
    _reject_archive_scope(scope)


def _reject_archive_scope(scope: EvidenceScope) -> None:
    """Refuse an archive wildcard on the single-document index.

    `scope_matches` treats `archive_scope=True` as "any document in the family", so a
    caller that set it here would turn every method below into a family-wide query the
    moment a future refactor relaxed the `document_id` requirement. Cross-document
    retrieval belongs to `mamagift_retrieval.archive`; this index must stay incapable
    of it rather than merely unlikely to do it.
    """
    if scope.archive_scope:
        raise ValueError(
            "DocumentIndex scope must not be an archive wildcard; "
            "use ArchiveIndex for cross-document retrieval"
        )


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _infer_chunk_type(chunk_id_str: str, section_path: list[str]) -> ChunkType:
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


def _row_to_chunk(row: DocumentChunk) -> Chunk:
    if not row.page_numbers or not row.source_block_ids:
        raise ValueError(f"stored chunk {row.id!r} has missing or empty source provenance")
    section_path = list(row.section_path) if row.section_path else []
    page_numbers = list(row.page_numbers)
    source_block_ids = list(row.source_block_ids)
    chunk_type = _infer_chunk_type(row.id, section_path)
    return Chunk(
        chunk_id=row.id,
        parent_chunk_id=row.parent_chunk_id,
        document_id=row.document_id,
        parse_run_id=row.parse_run_id,
        document_version=row.document_version,
        section_path=section_path,
        chunk_type=chunk_type,
        text=row.text,
        source_block_ids=source_block_ids,
        source_page_numbers=page_numbers,
        # Restoring this is what keeps a plan task bound to its own owner and deadline
        # across the database round trip.
        metadata=dict(row.chunk_metadata or {}),
    )


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
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


class SqlDocumentIndex:
    """SQL-backed implementation of DocumentIndex over `document_chunks` table."""

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

    def replace(self, scope: EvidenceScope, entries: list[IndexEntry]) -> IndexStats:
        _validate_authoritative_family(scope)
        if not scope.document_id:
            raise ValueError("scope must specify document_id")
        if scope.document_version is None:
            raise ValueError("scope must specify document_version")
        if not scope.parse_run_id:
            raise ValueError("scope must specify parse_run_id")

        if entries:
            validate_chunk_tree([e.chunk for e in entries])
            seen_indices: set[int] = set()
            emb_versions: set[str] = set()
            emb_models: set[str] = set()
            for entry in entries:
                if entry.chunk.document_id != scope.document_id:
                    raise ValueError(
                        f"entry chunk document_id {entry.chunk.document_id!r} "
                        f"contradicts scope document_id {scope.document_id!r}"
                    )
                if entry.chunk.parse_run_id != scope.parse_run_id:
                    raise ValueError(
                        f"entry chunk parse_run_id {entry.chunk.parse_run_id!r} "
                        f"contradicts scope parse_run_id {scope.parse_run_id!r}"
                    )
                if entry.chunk.document_version != scope.document_version:
                    raise ValueError(
                        f"entry chunk document_version {entry.chunk.document_version!r} "
                        f"contradicts scope document_version {scope.document_version!r}"
                    )
                if not entry.chunk.source_page_numbers or not entry.chunk.source_block_ids:
                    raise ValueError(
                        f"entry chunk {entry.chunk.chunk_id!r} missing source provenance"
                    )
                candidate_scope = EvidenceScope(
                    family_id=scope.family_id,
                    document_id=entry.chunk.document_id,
                    document_version=entry.chunk.document_version,
                    parse_run_id=entry.chunk.parse_run_id,
                    user_id=scope.user_id,
                    thread_id=scope.thread_id,
                )
                if not scope_matches(candidate_scope, scope):
                    raise ValueError(
                        f"entry chunk {entry.chunk.chunk_id!r} scope "
                        f"violates requested EvidenceScope"
                    )
                if entry.chunk_index in seen_indices:
                    raise ValueError(f"duplicate chunk_index {entry.chunk_index}")
                seen_indices.add(entry.chunk_index)

                if entry.embedding is not None:
                    if len(entry.embedding) == 0:
                        raise ValueError(
                            f"entry chunk {entry.chunk.chunk_id!r} has zero-length embedding"
                        )
                    if entry.embedding_version:
                        emb_versions.add(entry.embedding_version)
                    if entry.embedding_model:
                        emb_models.add(entry.embedding_model)

            if len(emb_versions) > 1:
                raise ValueError(
                    f"entries contain mixed embedding_versions: {sorted(emb_versions)}"
                )
            if len(emb_models) > 1:
                raise ValueError(f"entries contain mixed embedding_models: {sorted(emb_models)}")

        with self._get_session() as session:
            trans_cm = session.begin_nested() if session.in_transaction() else session.begin()
            with trans_cm:
                del_stmt = delete(DocumentChunk).where(
                    DocumentChunk.document_id == scope.document_id,
                    DocumentChunk.parse_run_id == scope.parse_run_id,
                    DocumentChunk.document_version == scope.document_version,
                )
                session.execute(del_stmt)

                for entry in entries:
                    tok_count = (
                        entry.token_count
                        if entry.token_count > 0
                        else len(entry.chunk.text.split())
                    )
                    row = DocumentChunk(
                        id=entry.chunk.chunk_id,
                        document_id=entry.chunk.document_id,
                        parse_run_id=entry.chunk.parse_run_id,
                        document_version=entry.chunk.document_version,
                        chunk_index=entry.chunk_index,
                        parent_chunk_id=entry.chunk.parent_chunk_id,
                        section_path=entry.chunk.section_path,
                        page_numbers=entry.chunk.source_page_numbers,
                        source_block_ids=entry.chunk.source_block_ids,
                        text=entry.chunk.text,
                        token_count=tok_count,
                        chunk_metadata=dict(entry.chunk.metadata),
                        embedding=entry.embedding,
                        embedding_model=entry.embedding_model,
                        embedding_version=entry.embedding_version,
                    )
                    session.add(row)
                session.flush()

        total_chunks = len(entries)
        embedded_chunks = sum(1 for e in entries if e.embedding is not None)
        embedding_model = next(
            (e.embedding_model for e in entries if e.embedding_model is not None), None
        )
        embedding_version = next(
            (e.embedding_version for e in entries if e.embedding_version is not None), None
        )

        return IndexStats(
            document_id=scope.document_id,
            parse_run_id=scope.parse_run_id,
            document_version=scope.document_version,
            total_chunks=total_chunks,
            embedded_chunks=embedded_chunks,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
        )

    def search_dense(
        self,
        scope: EvidenceScope,
        query_vector: list[float],
        top_k: int,
    ) -> list[ScoredChunk]:
        """Perform exact brute-force cosine similarity search over scoped chunks.

        Rows with missing or stale embedding_version are excluded.
        Candidates are sorted in descending order of score, with chunk_id ascending as a
        stable tie-break for equal scores: `(-score, chunk.chunk_id)`.
        """
        _validate_authoritative_family(scope)
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
        if not query_vector:
            raise ValueError("query_vector cannot be empty")
        if not scope.document_id:
            raise ValueError("scope must specify document_id")
        if scope.document_version is None and scope.parse_run_id is None:
            raise ValueError("scope must specify parse_run_id or document_version")

        with self._get_session() as session:
            stmt = select(DocumentChunk).where(DocumentChunk.document_id == scope.document_id)
            if scope.parse_run_id is not None:
                stmt = stmt.where(DocumentChunk.parse_run_id == scope.parse_run_id)
            if scope.document_version is not None:
                stmt = stmt.where(DocumentChunk.document_version == scope.document_version)
            rows = list(session.scalars(stmt).all())

            target_embedding_version = self._embedding_version
            if target_embedding_version is None:
                for r in rows:
                    if r.embedding is not None and r.embedding_version is not None:
                        target_embedding_version = r.embedding_version
                        break

            candidates: list[tuple[float, Chunk]] = []
            for row in rows:
                row_scope = EvidenceScope(
                    family_id=AUTHORITATIVE_FAMILY_ID,
                    document_id=row.document_id,
                    document_version=row.document_version,
                    parse_run_id=row.parse_run_id,
                    user_id=scope.user_id,
                    thread_id=scope.thread_id,
                )
                if not scope_matches(row_scope, scope):
                    continue
                if row.embedding is None:
                    continue
                if (
                    target_embedding_version is not None
                    and row.embedding_version != target_embedding_version
                ):
                    continue

                sim = _cosine_similarity(query_vector, row.embedding)
                chunk = _row_to_chunk(row)
                candidates.append((sim, chunk))

        # Stable tie-break: descending score, then ascending chunk_id
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
    ) -> list[ScoredChunk]:
        """Perform lexical term-overlap search over chunks in the scoped document version.

        Candidates are sorted in descending order of score, with chunk_id ascending as a
        stable tie-break for equal scores: `(-score, chunk.chunk_id)`.
        """
        _validate_authoritative_family(scope)
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
        if not scope.document_id:
            raise ValueError("scope must specify document_id")
        if scope.document_version is None and scope.parse_run_id is None:
            raise ValueError("scope must specify parse_run_id or document_version")

        if query is None:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        with self._get_session() as session:
            stmt = select(DocumentChunk).where(DocumentChunk.document_id == scope.document_id)
            if scope.parse_run_id is not None:
                stmt = stmt.where(DocumentChunk.parse_run_id == scope.parse_run_id)
            if scope.document_version is not None:
                stmt = stmt.where(DocumentChunk.document_version == scope.document_version)
            rows = list(session.scalars(stmt).all())

            candidates: list[tuple[float, Chunk]] = []
            for row in rows:
                row_scope = EvidenceScope(
                    family_id=AUTHORITATIVE_FAMILY_ID,
                    document_id=row.document_id,
                    document_version=row.document_version,
                    parse_run_id=row.parse_run_id,
                    user_id=scope.user_id,
                    thread_id=scope.thread_id,
                )
                if not scope_matches(row_scope, scope):
                    continue

                chunk_tokens = _tokenize(row.text)
                overlap = query_tokens & chunk_tokens
                if not overlap:
                    continue

                score = len(overlap) / len(query_tokens)
                chunk = _row_to_chunk(row)
                candidates.append((score, chunk))

        # Stable tie-break: descending score, then ascending chunk_id
        candidates.sort(key=lambda item: (-item[0], item[1].chunk_id))
        top_results = candidates[:top_k]

        return [
            ScoredChunk(
                chunk=chunk,
                score=score,
                rank=idx + 1,
                retriever="lexical",
            )
            for idx, (score, chunk) in enumerate(top_results)
        ]

    def drop(self, scope: EvidenceScope) -> int:
        """Delete all chunks for the scoped document version / parse run.

        Returns the number of deleted rows.
        """
        _validate_authoritative_family(scope)
        if not scope.document_id:
            raise ValueError("scope must specify document_id")
        if scope.document_version is None and scope.parse_run_id is None:
            raise ValueError("scope must specify parse_run_id or document_version")

        with self._get_session() as session:
            trans_cm = session.begin_nested() if session.in_transaction() else session.begin()
            with trans_cm:
                stmt = delete(DocumentChunk).where(
                    DocumentChunk.document_id == scope.document_id,
                )
                if scope.parse_run_id is not None:
                    stmt = stmt.where(DocumentChunk.parse_run_id == scope.parse_run_id)
                if scope.document_version is not None:
                    stmt = stmt.where(DocumentChunk.document_version == scope.document_version)
                result = session.execute(stmt)
                deleted_count = int(result.rowcount) if isinstance(result, CursorResult) else 0
                return deleted_count

    def stats(self, scope: EvidenceScope) -> IndexStats:
        """Return indexing statistics for the scoped document version / parse run."""
        _validate_authoritative_family(scope)
        if not scope.document_id:
            raise ValueError("scope must specify document_id")
        if scope.document_version is None and scope.parse_run_id is None:
            raise ValueError("scope must specify parse_run_id or document_version")

        with self._get_session() as session:
            stmt = select(DocumentChunk).where(DocumentChunk.document_id == scope.document_id)
            if scope.parse_run_id is not None:
                stmt = stmt.where(DocumentChunk.parse_run_id == scope.parse_run_id)
            if scope.document_version is not None:
                stmt = stmt.where(DocumentChunk.document_version == scope.document_version)
            rows = list(session.scalars(stmt).all())

            matching_rows: list[DocumentChunk] = []
            for row in rows:
                row_scope = EvidenceScope(
                    family_id=AUTHORITATIVE_FAMILY_ID,
                    document_id=row.document_id,
                    document_version=row.document_version,
                    parse_run_id=row.parse_run_id,
                    user_id=scope.user_id,
                    thread_id=scope.thread_id,
                )
                if scope_matches(row_scope, scope):
                    matching_rows.append(row)

            total_chunks = len(matching_rows)
            embedded_chunks = sum(1 for r in matching_rows if r.embedding is not None)
            embedding_model = next(
                (r.embedding_model for r in matching_rows if r.embedding_model is not None), None
            )
            embedding_version = next(
                (r.embedding_version for r in matching_rows if r.embedding_version is not None),
                None,
            )
            doc_version = scope.document_version
            parse_run_id = scope.parse_run_id or ""

            return IndexStats(
                document_id=scope.document_id,
                parse_run_id=parse_run_id,
                document_version=doc_version,
                total_chunks=total_chunks,
                embedded_chunks=embedded_chunks,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
            )
