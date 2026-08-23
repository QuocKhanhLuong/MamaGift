"""Single-document grounded question answering API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mamagift_contracts.errors import WorkerError
from mamagift_rag import QaAnswer, QaService
from mamagift_retrieval.index import (
    AUTHORITATIVE_FAMILY_ID,
    DocumentIndex,
    SqlDocumentIndex,
)
from mamagift_retrieval.providers import (
    ChatCompletionProvider,
    EmbeddingProvider,
    FakeChatProvider,
    OpenAICompatibleChatProvider,
)
from mamagift_retrieval.rerank import FakeReranker
from mamagift_retrieval.scope import EvidenceScope

from .. import errors
from ..db import get_session
from ..indexing import get_default_embedding_provider
from ..models import Document, ParseRun
from ..schemas import QaRequest
from ..settings import Settings, get_settings

router = APIRouter(prefix="/api/v1/documents", tags=["qa"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_embedding_provider(settings: SettingsDep) -> EmbeddingProvider:
    """Select the configured embedding adapter, using the deterministic test fake."""

    return get_default_embedding_provider(settings)


EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


def get_document_index(
    session: SessionDep, embedding_provider: EmbeddingProviderDep
) -> DocumentIndex:
    """Bind the request's index to its configured embedding version."""

    return SqlDocumentIndex(session, default_embedding_version=embedding_provider.embedding_version)


DocumentIndexDep = Annotated[DocumentIndex, Depends(get_document_index)]


def _get_chat_provider(settings: Settings) -> ChatCompletionProvider:
    if settings.app_env == "test":
        return FakeChatProvider(model=settings.llm_model, provider_name="fake_chat")
    return OpenAICompatibleChatProvider(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        retry_backoff_seconds=settings.llm_retry_backoff_seconds,
    )


def get_qa_service(
    settings: SettingsDep,
    embedding_provider: EmbeddingProviderDep,
    document_index: DocumentIndexDep,
) -> QaService:
    """Compose QaService behind provider and index interfaces."""

    return QaService(
        chat_provider=_get_chat_provider(settings),
        embedding_provider=embedding_provider,
        document_index=document_index,
        reranker=FakeReranker(),
    )


QaServiceDep = Annotated[QaService, Depends(get_qa_service)]


def _load_document(session: Session, document_id: str) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise errors.ApiError(
            errors.NOT_FOUND,
            "document not found",
            status_code=404,
            details={"document_id": document_id},
        )
    return document


def _current_scope(session: Session, document: Document) -> EvidenceScope:
    """Resolve the database-owned current parse identity, never request input."""

    if document.current_parse_run_id is None:
        raise errors.ApiError(
            errors.DOCUMENT_NOT_INDEXED,
            "document has no current parse run",
            status_code=409,
            retryable=True,
            details={"document_id": document.id},
        )

    parse_run = session.get(ParseRun, document.current_parse_run_id)
    if parse_run is None:
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "document current parse run is unavailable",
            status_code=500,
            details={"document_id": document.id},
        )
    if parse_run.document_id != document.id or not parse_run.is_current:
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "document current parse run provenance is inconsistent",
            status_code=500,
            details={"document_id": document.id},
        )

    return EvidenceScope(
        family_id=AUTHORITATIVE_FAMILY_ID,
        document_id=document.id,
        document_version=parse_run.version,
        parse_run_id=parse_run.id,
    )


def _ensure_indexed(
    document_id: str, index: DocumentIndex, scope: EvidenceScope, provider: EmbeddingProvider
) -> None:
    try:
        stats = index.stats(scope)
    except (TypeError, ValueError) as exc:
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "document index rejected the current evidence scope",
            status_code=500,
            details={"document_id": document_id},
        ) from exc

    if (
        stats.total_chunks == 0
        or stats.embedded_chunks < stats.total_chunks
        or stats.embedding_version != provider.embedding_version
    ):
        raise errors.ApiError(
            errors.DOCUMENT_NOT_INDEXED,
            "document is not indexed for the current parse run",
            status_code=409,
            retryable=True,
            details={"document_id": document_id},
        )


@router.post("/{document_id}/qa", response_model=QaAnswer)
async def answer_document_question(
    session: SessionDep,
    document_id: str,
    payload: QaRequest,
    qa_service: QaServiceDep,
    document_index: DocumentIndexDep,
    embedding_provider: EmbeddingProviderDep,
) -> QaAnswer:
    """Answer using only the requested document's current indexed parse run."""

    document = _load_document(session, document_id)
    scope = _current_scope(session, document)
    _ensure_indexed(document.id, document_index, scope, embedding_provider)

    try:
        answer = await qa_service.answer(payload.question, scope=scope)
    except WorkerError as exc:
        raise errors.ApiError(
            errors.AI_WORKER_UNAVAILABLE,
            "AI worker is unavailable",
            status_code=503,
            retryable=True,
            details={"document_id": document.id},
        ) from exc
    except ValueError as exc:
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "QA service rejected the current evidence scope",
            status_code=500,
            details={"document_id": document.id},
        ) from exc

    if answer.status == "ai_worker_unavailable":
        raise errors.ApiError(
            errors.AI_WORKER_UNAVAILABLE,
            "AI worker is unavailable",
            status_code=503,
            retryable=True,
            details={"document_id": document.id},
        )

    if any(citation.document_id != document.id for citation in answer.citations):
        raise errors.ApiError(
            errors.QA_SCOPE_VIOLATION,
            "QA returned a citation outside the requested document",
            status_code=500,
            details={"document_id": document.id},
        )

    return answer


__all__ = [
    "answer_document_question",
    "get_document_index",
    "get_embedding_provider",
    "get_qa_service",
    "router",
]
