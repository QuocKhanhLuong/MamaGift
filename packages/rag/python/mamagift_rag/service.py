"""Orchestration service for scoped, grounded question answering."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal
from uuid import uuid4

from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_contracts.llm import CompletionRequest
from mamagift_retrieval.budget import EvidenceBudget
from mamagift_retrieval.chunk import Chunk
from mamagift_retrieval.evidence import EvidenceSet, assemble_evidence, expand_evidence
from mamagift_retrieval.index import DocumentIndex
from mamagift_retrieval.providers import ChatCompletionProvider, EmbeddingProvider
from mamagift_retrieval.rerank import Reranker
from mamagift_retrieval.scope import EvidenceScope, scope_matches
from mamagift_retrieval.search import BM25LexicalRetriever, DenseRetriever
from mamagift_retrieval.search.fusion import reciprocal_rank_fusion
from mamagift_retrieval.search.types import ScoredChunk

from .prompt import build_grounded_prompt
from .schema import Citation, ModelRef, QaAnswer, RetrievalRef
from .validation import parse_and_validate_answer

_DEFAULT_BUDGET = EvidenceBudget(
    selected_document_chars=12_000,
    conversation_short_term_chars=0,
    user_long_term_memory_chars=0,
    episodic_memory_chars=0,
    archive_semantic_chars=0,
)
_UNKNOWN_MODEL = ModelRef(provider="unknown", model="unknown", version="unknown")
_ABSTENTION_TEXT = "Không đủ bằng chứng trong tài liệu để trả lời câu hỏi này."
_NOT_INDEXED_TEXT = "Tài liệu chưa được lập chỉ mục."
_FAILED_TEXT = "Không thể hoàn tất việc trả lời dựa trên tài liệu này."
_UNAVAILABLE_TEXT = "Trợ lý AI hiện không khả dụng. Vui lòng thử lại sau."
QaStatus = Literal["answered", "insufficient_evidence", "ai_worker_unavailable", "failed"]


class QaService:
    """Run the complete retrieval-to-grounded-answer pipeline.

    All dependencies are protocols or deterministic retrieval helpers.  The service
    owns no persistence and keeps request state in local variables only.
    """

    def __init__(
        self,
        *,
        chat_provider: ChatCompletionProvider,
        embedding_provider: EmbeddingProvider,
        document_index: DocumentIndex,
        reranker: Reranker,
        chunk_tree: Iterable[Chunk] | None = None,
        budget: EvidenceBudget | None = None,
        lexical_top_k: int = 10,
        dense_top_k: int = 10,
        rerank_top_k: int = 10,
        max_output_tokens: int = 512,
    ) -> None:
        if lexical_top_k <= 0 or dense_top_k <= 0 or rerank_top_k <= 0:
            raise ValueError("retrieval top_k values must be positive")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")

        self._chat_provider = chat_provider
        self._embedding_provider = embedding_provider
        self._document_index = document_index
        self._reranker = reranker
        self._chunk_tree = tuple(chunk_tree or ())
        self._budget = budget or _DEFAULT_BUDGET
        self._lexical_top_k = lexical_top_k
        self._dense_top_k = dense_top_k
        self._rerank_top_k = rerank_top_k
        self._max_output_tokens = max_output_tokens

    async def answer(self, question: str, *, scope: EvidenceScope) -> QaAnswer:
        """Answer ``question`` using only evidence in the exact requested scope."""
        query_id = f"qry_{uuid4().hex}"
        try:
            self._validate_request_scope(scope)
            stats = self._document_index.stats(scope)
            if stats.total_chunks == 0:
                return self._finish(
                    self._fallback_answer(
                        _NOT_INDEXED_TEXT,
                        status="failed",
                        model=_UNKNOWN_MODEL,
                        evidence=self._empty_evidence(scope, query_id),
                    ),
                    query_id,
                )

            lexical = BM25LexicalRetriever(self._document_index).search(
                question,
                scope=scope,
                top_k=self._lexical_top_k,
            )
            dense = await DenseRetriever(
                index=self._document_index,
                embedding_provider=self._embedding_provider,
            ).search(question, scope, self._dense_top_k)
            self._validate_candidates(lexical, scope)
            self._validate_candidates(dense, scope)

            fused = reciprocal_rank_fusion([lexical, dense], scope)
            self._validate_candidates(fused, scope)
            reranked = await self._reranker.rerank(question, fused, self._rerank_top_k)
            self._validate_candidates(reranked, scope)

            expanded = expand_evidence(
                reranked,
                scope=scope,
                chunk_tree=self._chunk_tree,
            )
            self._validate_candidates(expanded, scope)
            evidence = assemble_evidence(
                expanded,
                scope=scope,
                budget=self._budget,
                query_id=query_id,
            )
            if not evidence.evidence:
                return self._finish(
                    self._fallback_answer(
                        _ABSTENTION_TEXT,
                        status="insufficient_evidence",
                        model=_UNKNOWN_MODEL,
                        evidence=evidence,
                    ),
                    query_id,
                )

            messages = build_grounded_prompt(question, evidence)
            request = CompletionRequest(
                messages=messages,
                max_output_tokens=self._max_output_tokens,
                temperature=0.0,
                response_format="json_object",
            )
            try:
                completion = await self._chat_provider.complete(request)
            except WorkerError as exc:
                if exc.code in {
                    WorkerErrorCode.UNAVAILABLE,
                    WorkerErrorCode.TIMEOUT,
                    WorkerErrorCode.MODEL_NOT_LOADED,
                }:
                    return self._finish(
                        self._fallback_answer(
                            _UNAVAILABLE_TEXT,
                            status="ai_worker_unavailable",
                            model=_UNKNOWN_MODEL,
                            evidence=evidence,
                        ),
                        query_id,
                    )
                return self._finish(
                    self._fallback_answer(
                        _FAILED_TEXT,
                        status="failed",
                        model=_UNKNOWN_MODEL,
                        evidence=evidence,
                    ),
                    query_id,
                )

            model = ModelRef(
                provider=completion.provider,
                model=completion.model,
                version="unknown",
            )
            try:
                parsed = parse_and_validate_answer(completion.text, evidence, model=model)
            except Exception:
                return self._finish(
                    self._fallback_answer(
                        _FAILED_TEXT,
                        status="failed",
                        model=model,
                        evidence=evidence,
                    ),
                    query_id,
                )
            return self._finish(parsed, query_id)
        except WorkerError as exc:
            status: QaStatus = (
                "ai_worker_unavailable"
                if exc.code
                in {
                    WorkerErrorCode.UNAVAILABLE,
                    WorkerErrorCode.TIMEOUT,
                    WorkerErrorCode.MODEL_NOT_LOADED,
                }
                else "failed"
            )
            text = _UNAVAILABLE_TEXT if status == "ai_worker_unavailable" else _FAILED_TEXT
            return self._finish(
                self._fallback_answer(
                    text,
                    status=status,
                    model=_UNKNOWN_MODEL,
                    evidence=self._empty_evidence(scope, query_id),
                ),
                query_id,
            )
        except Exception:
            return self._finish(
                self._fallback_answer(
                    _FAILED_TEXT,
                    status="failed",
                    model=_UNKNOWN_MODEL,
                    evidence=self._empty_evidence(scope, query_id),
                ),
                query_id,
            )

    @staticmethod
    def _validate_request_scope(scope: EvidenceScope) -> None:
        if scope.archive_scope:
            raise ValueError("QA scope must not be an archive wildcard")
        if scope.document_id is None:
            raise ValueError("QA scope must specify document_id")
        if scope.document_version is None:
            raise ValueError("QA scope must specify document_version")
        if scope.parse_run_id is None:
            raise ValueError("QA scope must specify parse_run_id")

    @staticmethod
    def _validate_candidates(candidates: Sequence[ScoredChunk], scope: EvidenceScope) -> None:
        for candidate in candidates:
            chunk = candidate.chunk
            candidate_scope = EvidenceScope(
                family_id=scope.family_id,
                user_id=scope.user_id,
                thread_id=scope.thread_id,
                document_id=chunk.document_id,
                document_version=chunk.document_version,
                parse_run_id=chunk.parse_run_id,
            )
            if not scope_matches(candidate_scope, scope):
                raise ValueError(
                    f"candidate chunk {chunk.chunk_id!r} violates requested EvidenceScope"
                )

    def _empty_evidence(self, scope: EvidenceScope, query_id: str) -> EvidenceSet:
        return assemble_evidence([], scope=scope, budget=self._budget, query_id=query_id)

    @staticmethod
    def _fallback_answer(
        text: str,
        *,
        status: QaStatus,
        model: ModelRef,
        evidence: EvidenceSet,
    ) -> QaAnswer:
        # E1 remains the sole owner of QaAnswer construction and validation.  Parsing
        # an empty citation list gives us its conservative abstention shape; the
        # service only changes the explicitly frozen operational status afterward.
        parsed = parse_and_validate_answer(
            '{"answer": "", "citations": []}',
            evidence,
            model=model,
        )
        return parsed.model_copy(update={"answer": text, "status": status, "citations": []})

    @staticmethod
    def _finish(answer: QaAnswer, query_id: str) -> QaAnswer:
        return answer.model_copy(update={"retrieval": RetrievalRef(query_id=query_id)})


__all__ = ["Citation", "QaAnswer", "QaService", "RetrievalRef", "ModelRef"]
