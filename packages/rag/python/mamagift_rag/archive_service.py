"""Grounded question answering across many current archive documents.

This is the deliberate sibling of :class:`mamagift_rag.service.QaService`, not a
generalisation of it. Their scope guards are mirror images: ``QaService`` refuses an archive
wildcard and requires a pinned document, while ``ArchiveQaService`` requires an archive
wildcard and refuses a pinned document. Neither can quietly do the other's job, which is what
keeps selected-document QA structurally incapable of cross-document retrieval.

Everything downstream of retrieval is the Phase 4 machinery reused unchanged --
``build_grounded_prompt`` (and therefore the untrusted-data delimiters and the system policy
forbidding scope widening) and ``parse_and_validate_answer`` (and therefore the citation
allow-list). There is no second prompt, no second citation validator, and no second RAG stack.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_contracts.llm import CompletionRequest
from mamagift_retrieval.archive.constants import ARCHIVE_EVIDENCE_BUDGET_CHARS
from mamagift_retrieval.archive.filters import ArchiveFilter
from mamagift_retrieval.archive.freshness import resolve_freshness
from mamagift_retrieval.archive.protocol import ArchiveDocumentRef, ArchiveIndex
from mamagift_retrieval.archive.retriever import ArchiveRetriever
from mamagift_retrieval.budget import EvidenceBudget
from mamagift_retrieval.evidence.archive_assembler import (
    assemble_archive_evidence,
    group_evidence_by_document,
)
from mamagift_retrieval.evidence.assembler import EvidenceSet
from mamagift_retrieval.providers import ChatCompletionProvider, EmbeddingProvider
from mamagift_retrieval.rerank import Reranker
from mamagift_retrieval.scope import EvidenceScope

from .prompt import build_grounded_prompt
from .schema import Citation, ModelRef, RetrievalRef
from .validation import parse_and_validate_answer

ArchiveQaStatus = Literal["answered", "insufficient_evidence", "ai_worker_unavailable", "failed"]

# Only the archive category is funded. The other four are zero on purpose: spending from
# `selected_document` here would make the budget breakdown misreport where an archive answer's
# context actually came from, and short-term/episodic memory are not Phase 5 concerns.
_ARCHIVE_BUDGET = EvidenceBudget(
    selected_document_chars=0,
    conversation_short_term_chars=0,
    user_long_term_memory_chars=0,
    episodic_memory_chars=0,
    archive_semantic_chars=ARCHIVE_EVIDENCE_BUDGET_CHARS,
)

_UNKNOWN_MODEL = ModelRef(provider="unknown", model="unknown", version="unknown")
_NO_DOCUMENTS_TEXT = "Không tìm thấy văn bản nào phù hợp trong kho tài liệu."
_ABSTENTION_TEXT = "Không đủ bằng chứng trong kho tài liệu để trả lời câu hỏi này."
_FAILED_TEXT = "Không thể hoàn tất việc trả lời dựa trên kho tài liệu."
_UNAVAILABLE_TEXT = "Trợ lý AI hiện không khả dụng. Vui lòng thử lại sau."


class ArchiveDocumentGroup(BaseModel):
    """One cited document and the citations that belong to it."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    document_number: str | None = None
    title: str | None = None
    document_type: str | None = None
    issuer: str | None = None
    issued_date: str | None = None
    document_version: int = Field(ge=1)
    parse_run_id: str = Field(min_length=1)
    citation_ids: list[str]


class ArchiveRelationRef(BaseModel):
    """An evidence-backed relation surfaced alongside an answer.

    `review_state` travels with the relation so a caller can never present an `unverified`
    machine-extracted relation as an established legal fact.
    """

    model_config = ConfigDict(extra="forbid")

    relation_type: str
    review_state: str
    confidence: float
    source_document_id: str
    target_document_id: str | None = None
    target_document_number: str | None = None
    citation_ids: list[str]


class ArchiveQaAnswer(BaseModel):
    """A validated cross-document answer with citations grouped by source document."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    status: ArchiveQaStatus
    citations: list[Citation]
    document_groups: list[ArchiveDocumentGroup]
    relations: list[ArchiveRelationRef]
    freshness_caveat: str | None = None
    retrieval: RetrievalRef
    model: ModelRef


class ArchiveQaService:
    """Run the archive retrieval-to-grounded-answer pipeline."""

    def __init__(
        self,
        *,
        chat_provider: ChatCompletionProvider,
        embedding_provider: EmbeddingProvider,
        archive_index: ArchiveIndex,
        reranker: Reranker,
        retriever: ArchiveRetriever | None = None,
        budget: EvidenceBudget | None = None,
        max_output_tokens: int = 512,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self._chat_provider = chat_provider
        self._retriever = retriever or ArchiveRetriever(
            index=archive_index,
            embedding_provider=embedding_provider,
            reranker=reranker,
        )
        self._budget = budget or _ARCHIVE_BUDGET
        self._max_output_tokens = max_output_tokens

    async def answer(
        self,
        question: str,
        *,
        scope: EvidenceScope,
        filters: ArchiveFilter | None = None,
        relations: Sequence[ArchiveRelationRef] | None = None,
    ) -> ArchiveQaAnswer:
        """Answer ``question`` using only current-version evidence in the archive scope."""
        query_id = f"qry_{uuid4().hex}"
        try:
            self._validate_request_scope(scope)
            retrieved = await self._retriever.retrieve(question, scope=scope, filters=filters)
            allowed = set(retrieved.allowed_document_ids)
            caveat = resolve_freshness(retrieved.documents, question).caveat

            if not retrieved.documents:
                return self._simple(
                    _NO_DOCUMENTS_TEXT, "insufficient_evidence", query_id, _UNKNOWN_MODEL, None
                )

            evidence = assemble_archive_evidence(
                retrieved.candidates,
                scope=scope,
                budget=self._budget,
                query_id=query_id,
                allowed_documents=allowed,
            )
            if not evidence.evidence:
                return self._simple(
                    _ABSTENTION_TEXT, "insufficient_evidence", query_id, _UNKNOWN_MODEL, caveat
                )

            request = CompletionRequest(
                messages=build_grounded_prompt(question, evidence),
                max_output_tokens=self._max_output_tokens,
                temperature=0.0,
                response_format="json_object",
            )
            try:
                completion = await self._chat_provider.complete(request)
            except WorkerError as exc:
                return self._simple(*self._worker_failure(exc), query_id, _UNKNOWN_MODEL, caveat)

            model = ModelRef(
                provider=completion.provider, model=completion.model, version="unknown"
            )
            parsed = parse_and_validate_answer(completion.text, evidence, model=model)
            if parsed.status in {"insufficient_evidence", "failed"}:
                return self._simple(parsed.answer, parsed.status, query_id, model, caveat)

            # Independent post-validation archive guard. `parse_and_validate_answer` already
            # bound every citation to an evidence item, but the archive path is the one that
            # can span documents, so the allow-list is checked once more against the set built
            # before retrieval rather than trusted transitively.
            if any(citation.document_id not in allowed for citation in parsed.citations):
                return self._simple(_FAILED_TEXT, "failed", query_id, model, caveat)

            try:
                groups = self._build_groups(parsed.citations, evidence, retrieved.documents)
            except ValueError:
                return self._simple(_FAILED_TEXT, "failed", query_id, model, caveat)

            return ArchiveQaAnswer(
                answer=parsed.answer,
                status="answered",
                citations=list(parsed.citations),
                document_groups=groups,
                relations=self._filter_relations(relations, parsed.citations, groups),
                freshness_caveat=caveat,
                retrieval=RetrievalRef(query_id=query_id),
                model=model,
            )
        except WorkerError as exc:
            return self._simple(*self._worker_failure(exc), query_id, _UNKNOWN_MODEL, None)
        except Exception:
            return self._simple(_FAILED_TEXT, "failed", query_id, _UNKNOWN_MODEL, None)

    @staticmethod
    def _validate_request_scope(scope: EvidenceScope) -> None:
        """The exact mirror of :meth:`QaService._validate_request_scope`.

        That one rejects an archive wildcard; this one rejects a pinned document. Keeping both
        strict is what makes the two services incapable of substituting for one another.
        """
        if not scope.archive_scope:
            raise ValueError("archive QA scope must be an archive wildcard (archive_scope=True)")
        if scope.document_id is not None:
            raise ValueError("archive QA scope must not pin document_id")
        if scope.document_version is not None:
            raise ValueError("archive QA scope must not pin document_version")
        if scope.parse_run_id is not None:
            raise ValueError("archive QA scope must not pin parse_run_id")

    @staticmethod
    def _worker_failure(exc: WorkerError) -> tuple[str, ArchiveQaStatus]:
        if exc.code in {
            WorkerErrorCode.UNAVAILABLE,
            WorkerErrorCode.TIMEOUT,
            WorkerErrorCode.MODEL_NOT_LOADED,
        }:
            return _UNAVAILABLE_TEXT, "ai_worker_unavailable"
        return _FAILED_TEXT, "failed"

    @staticmethod
    def _build_groups(
        citations: Sequence[Citation],
        evidence: EvidenceSet,
        documents: Sequence[ArchiveDocumentRef],
    ) -> list[ArchiveDocumentGroup]:
        """Regroup validated citations by document, preserving first-appearance order.

        This is a pure regrouping: every citation lands in exactly one group and no group
        invents a document. A violation raises rather than returning a partial grouping,
        because a citation that belongs to no visible group would be unreachable in the UI.
        """
        cited_ids = {item.citation_id for item in evidence.evidence}
        meta = {doc.document_id: doc for doc in documents}
        order = [doc_id for doc_id in group_evidence_by_document(evidence)]

        by_document: dict[str, list[str]] = {}
        for citation in citations:
            if citation.citation_id not in cited_ids:
                raise ValueError(f"citation {citation.citation_id!r} is not in the evidence set")
            by_document.setdefault(citation.document_id, []).append(citation.citation_id)

        groups: list[ArchiveDocumentGroup] = []
        for document_id in order:
            citation_ids = by_document.pop(document_id, None)
            if not citation_ids:
                continue
            document = meta.get(document_id)
            if document is None:
                raise ValueError(f"cited document {document_id!r} is not in the allow-list")
            groups.append(
                ArchiveDocumentGroup(
                    document_id=document.document_id,
                    document_number=document.document_number,
                    title=document.title,
                    document_type=document.document_type,
                    issuer=document.issuer,
                    issued_date=(
                        document.issued_date.isoformat() if document.issued_date else None
                    ),
                    document_version=document.document_version,
                    parse_run_id=document.parse_run_id,
                    citation_ids=citation_ids,
                )
            )
        if by_document:
            raise ValueError(f"citations for ungrouped documents: {sorted(by_document)}")
        return groups

    @staticmethod
    def _filter_relations(
        relations: Sequence[ArchiveRelationRef] | None,
        citations: Sequence[Citation],
        groups: Sequence[ArchiveDocumentGroup],
    ) -> list[ArchiveRelationRef]:
        """Pass through only caller-supplied relations that the answer actually cites.

        Relations are never synthesised here and are never derived from the model's answer
        text: they come from `document_relations` rows with their own provenance. A relation
        whose citations are not in this answer, or which touches no cited document, is dropped
        rather than shown without support.
        """
        if not relations:
            return []
        citation_ids = {citation.citation_id for citation in citations}
        cited_documents = {group.document_id for group in groups}
        kept: list[ArchiveRelationRef] = []
        for relation in relations:
            if not relation.citation_ids:
                continue
            if not set(relation.citation_ids) <= citation_ids:
                continue
            touches = {relation.source_document_id}
            if relation.target_document_id is not None:
                touches.add(relation.target_document_id)
            if not touches & cited_documents:
                continue
            kept.append(relation)
        return kept

    @staticmethod
    def _simple(
        text: str,
        status: ArchiveQaStatus,
        query_id: str,
        model: ModelRef,
        caveat: str | None,
    ) -> ArchiveQaAnswer:
        return ArchiveQaAnswer(
            answer=text,
            status=status,
            citations=[],
            document_groups=[],
            relations=[],
            freshness_caveat=caveat,
            retrieval=RetrievalRef(query_id=query_id),
            model=model,
        )


__all__ = [
    "ArchiveDocumentGroup",
    "ArchiveQaAnswer",
    "ArchiveQaService",
    "ArchiveQaStatus",
    "ArchiveRelationRef",
]
