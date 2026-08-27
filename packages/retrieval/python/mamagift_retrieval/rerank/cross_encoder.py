"""HTTP CrossEncoder adapter, kept behind the :class:`Reranker` protocol."""

from __future__ import annotations

import types
from typing import Protocol

import httpx

from mamagift_contracts.rerank import RerankRequest, RerankResult
from mamagift_retrieval.search.types import ScoredChunk

from .protocol import validate_archive_rerank_candidates, validate_rerank_candidates


class RerankerSettings(Protocol):
    """Settings fields consumed by the adapter factory.

    ``ai_worker_base_url`` is the existing worker endpoint setting; the reranker
    model is independently configurable alongside the Phase 4 model settings.
    """

    ai_worker_base_url: str
    ai_worker_token: str | None
    reranker_model: str


class CrossEncoderReranker:
    """Configurable CrossEncoder HTTP client with local contract enforcement."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        reranker_version: str | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        cross_document: bool = False,
    ) -> None:
        clean_base = base_url.strip() if base_url else ""
        clean_model = model.strip() if model else ""
        if not clean_base:
            raise ValueError("base_url must be a non-empty string")
        if not clean_model:
            raise ValueError("model must be a non-empty string")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self.base_url = clean_base.rstrip("/")
        self.model = clean_model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._reranker_version = reranker_version or f"{clean_model}-v1"
        if not self._reranker_version.strip():
            raise ValueError("reranker_version must not be empty")
        self._client = client
        self._owns_client = client is None
        self._cross_document = cross_document

    @classmethod
    def from_settings(
        cls,
        settings: RerankerSettings,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> CrossEncoderReranker:
        """Build the adapter from application settings without importing Settings."""

        return cls(
            base_url=settings.ai_worker_base_url,
            model=settings.reranker_model,
            api_key=settings.ai_worker_token,
            timeout_seconds=timeout_seconds,
            client=client,
        )

    @property
    def reranker_version(self) -> str:
        return self._reranker_version

    @property
    def supports_cross_document(self) -> bool:
        return self._cross_document

    def _endpoint(self) -> str:
        if self.base_url.endswith("/rerank"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/rerank"
        return f"{self.base_url}/v1/rerank"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def close(self) -> None:
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> CrossEncoderReranker:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self.close()

    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        if self._cross_document:
            validate_archive_rerank_candidates(candidates)
        else:
            validate_rerank_candidates(candidates)
        if not query.strip():
            raise ValueError("query must not be empty")
        if not candidates or top_k <= 0:
            return []

        # Send every candidate. The caller's top_k is applied only after the complete
        # upstream ordering has been validated, preventing premature truncation.
        request = RerankRequest(
            query=query,
            documents=[candidate.chunk.text for candidate in candidates],
            top_k=None,
            model=self.model,
        )
        client = await self._get_client()
        try:
            response = await client.post(
                self._endpoint(),
                json=request.model_dump(mode="json"),
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise RuntimeError("CrossEncoder request timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"CrossEncoder request failed: {exc}") from exc

        try:
            result = RerankResult.model_validate(response.json())
        except Exception as exc:
            raise RuntimeError("CrossEncoder returned an invalid rerank response") from exc

        expected_indexes = set(range(len(candidates)))
        actual_indexes = [item.index for item in result.results]
        if len(actual_indexes) != len(candidates) or set(actual_indexes) != expected_indexes:
            raise ValueError("CrossEncoder must return each candidate exactly once")

        reranked = [
            ScoredChunk(
                chunk=candidates[item.index].chunk,
                score=item.score,
                rank=position,
                retriever="reranked",
            )
            for position, item in enumerate(result.results, start=1)
        ]
        return reranked[:top_k]


CrossEncoderAdapter = CrossEncoderReranker

__all__ = ["CrossEncoderAdapter", "CrossEncoderReranker", "RerankerSettings"]
