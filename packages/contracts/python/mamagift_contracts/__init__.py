"""Shared typed contracts for AI-worker and RAG pipeline boundaries."""

from .embedding import EmbeddingResult
from .errors import WorkerError, WorkerErrorBody, WorkerErrorCode, WorkerErrorResponse
from .llm import ChatMessage, CompletionRequest, CompletionResult, TokenUsage
from .rerank import RerankItem, RerankRequest, RerankResult
from .worker import (
    ParseJobAccepted,
    ParseJobInput,
    ParseJobRequest,
    ParserSpec,
    WorkerCapabilities,
    WorkerHealth,
)

__all__ = [
    "ParseJobAccepted",
    "ParseJobInput",
    "ParseJobRequest",
    "ParserSpec",
    "WorkerCapabilities",
    "WorkerHealth",
    "ChatMessage",
    "CompletionRequest",
    "CompletionResult",
    "TokenUsage",
    "EmbeddingResult",
    "RerankItem",
    "RerankRequest",
    "RerankResult",
    "WorkerErrorCode",
    "WorkerError",
    "WorkerErrorBody",
    "WorkerErrorResponse",
]
