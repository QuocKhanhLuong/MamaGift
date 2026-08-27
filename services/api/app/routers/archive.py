"""Archive-wide grounded question answering API.

This router is the cross-document counterpart to `routers/qa.py`. The two are deliberately
separate endpoints over separate services: `/documents/{id}/qa` resolves one document's
current parse run and cannot widen, while `/archive/qa` never names a document and cannot
narrow to one. Neither can be used to do the other's job.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mamagift_contracts.errors import WorkerError
from mamagift_rag.archive_service import (
    ArchiveQaAnswer,
    ArchiveQaService,
    ArchiveRelationRef,
)
from mamagift_retrieval.archive import ArchiveFilter
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID, ArchiveIndex
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.providers import EmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker, Reranker
from mamagift_retrieval.scope import EvidenceScope

from .. import errors
from ..db import get_session
from ..models import DocumentRelation
from ..schemas import ArchiveQaRequest
from ..settings import Settings, get_settings
from .qa import get_chat_provider, get_embedding_provider

router = APIRouter(prefix="/api/v1/archive", tags=["archive"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


def get_archive_index(
    session: SessionDep, embedding_provider: EmbeddingProviderDep
) -> ArchiveIndex:
    """Bind the request's archive index to its configured embedding version."""

    return SqlArchiveIndex(session, default_embedding_version=embedding_provider.embedding_version)


ArchiveIndexDep = Annotated[ArchiveIndex, Depends(get_archive_index)]


def get_archive_reranker() -> Reranker:
    """The reranker used for archive retrieval.

    `cross_document=True` is required: the shipped rerankers validate their own candidates,
    and the default validator refuses a batch spanning several documents.
    """

    return FakeReranker(cross_document=True)


ArchiveRerankerDep = Annotated[Reranker, Depends(get_archive_reranker)]


def get_archive_qa_service(
    settings: SettingsDep,
    embedding_provider: EmbeddingProviderDep,
    archive_index: ArchiveIndexDep,
    reranker: ArchiveRerankerDep,
) -> ArchiveQaService:
    return ArchiveQaService(
        chat_provider=get_chat_provider(settings),
        embedding_provider=embedding_provider,
        archive_index=archive_index,
        reranker=reranker,
    )


ArchiveQaServiceDep = Annotated[ArchiveQaService, Depends(get_archive_qa_service)]


def _archive_scope() -> EvidenceScope:
    """The only scope this endpoint may use: a family-wide archive wildcard.

    The scope is constructed here from the authoritative family constant and is never taken
    from request input, so a client cannot pin, widen, or forge it.
    """

    return EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=True)


def _to_filter(payload: ArchiveQaRequest) -> ArchiveFilter | None:
    if payload.filters is None:
        return None
    return ArchiveFilter(**payload.filters.model_dump())


def _load_relations(session: Session, document_ids: set[str]) -> list[ArchiveRelationRef]:
    """Read evidence-backed relations for the cited documents.

    Relations come from `document_relations` rows only. Nothing here derives a relation from
    an answer, and `review_state` travels with each one so an unverified extraction is never
    presented as an established legal fact.
    """

    if not document_ids:
        return []
    rows = (
        session.query(DocumentRelation)
        .filter(DocumentRelation.source_document_id.in_(sorted(document_ids)))
        .all()
    )
    return [
        ArchiveRelationRef(
            relation_type=row.relation_type,
            review_state=row.review_state,
            confidence=row.confidence,
            source_document_id=row.source_document_id,
            target_document_id=row.target_document_id,
            target_document_number=row.target_document_number,
            citation_ids=[],
        )
        for row in rows
    ]


@router.post("/qa", response_model=ArchiveQaAnswer)
async def answer_archive_question(
    session: SessionDep,
    payload: ArchiveQaRequest,
    qa_service: ArchiveQaServiceDep,
    archive_index: ArchiveIndexDep,
) -> ArchiveQaAnswer:
    """Answer using only the current parse run of every matching archive document."""

    scope = _archive_scope()
    filters = _to_filter(payload)

    try:
        stats = archive_index.stats(scope, filters)
    except (TypeError, ValueError) as exc:
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "archive index rejected the evidence scope",
            status_code=500,
        ) from exc

    if stats.total_chunks == 0:
        raise errors.ApiError(
            errors.ARCHIVE_NOT_INDEXED,
            "no indexed document matches this request",
            status_code=409,
            retryable=True,
        )

    try:
        answer = await qa_service.answer(payload.question, scope=scope, filters=filters)
    except WorkerError as exc:
        raise errors.ApiError(
            errors.AI_WORKER_UNAVAILABLE,
            "AI worker is unavailable",
            status_code=503,
            retryable=True,
        ) from exc
    except ValueError as exc:
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "archive QA rejected the evidence scope",
            status_code=500,
        ) from exc

    if answer.status == "ai_worker_unavailable":
        raise errors.ApiError(
            errors.AI_WORKER_UNAVAILABLE,
            "AI worker is unavailable",
            status_code=503,
            retryable=True,
        )

    # Independent transport-boundary check. The service already grouped and validated, but a
    # citation that reached the client without a group would be unreachable in the UI, and a
    # group naming a document that was never retrieved would be a cross-document leak.
    grouped_ids = {cid for group in answer.document_groups for cid in group.citation_ids}
    if grouped_ids != {citation.citation_id for citation in answer.citations}:
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "archive answer citations are not fully grouped by document",
            status_code=500,
        )

    cited_documents = {group.document_id for group in answer.document_groups}
    relations = _relate(_load_relations(session, cited_documents), answer)
    return answer.model_copy(update={"relations": relations})


def _relate(
    candidates: list[ArchiveRelationRef], answer: ArchiveQaAnswer
) -> list[ArchiveRelationRef]:
    """Attach each relation to the citations of its source document.

    A relation with no citation in this answer is dropped rather than shown unsupported.
    """

    by_document: dict[str, list[str]] = {}
    for group in answer.document_groups:
        by_document[group.document_id] = list(group.citation_ids)

    attached: list[ArchiveRelationRef] = []
    for relation in candidates:
        citation_ids = by_document.get(relation.source_document_id, [])
        if not citation_ids:
            continue
        attached.append(relation.model_copy(update={"citation_ids": citation_ids}))
    return attached


__all__ = [
    "answer_archive_question",
    "get_archive_index",
    "get_archive_qa_service",
    "get_archive_reranker",
    "router",
]
