"""Configurable BGE-M3-compatible HTTP embedding provider adapter."""

from __future__ import annotations

from typing import Any

import httpx

from mamagift_contracts.embedding import EmbeddingResult
from mamagift_contracts.errors import WorkerError, WorkerErrorCode


class BgeM3EmbeddingProvider:
    """HTTP client adapter for BGE-M3 (or compatible) embedding models.

    Conforms to EmbeddingProvider protocol. Base URL, model identifier,
    credentials, dimension, and embedding version are fully configurable.
    """

    def __init__(
        self,
        base_url: str,
        model_id: str = "bge-m3",
        dimension: int = 1024,
        embedding_version: str = "bge-m3-v1",
        api_key: str | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        endpoint: str = "/v1/embeddings",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._dimension = dimension
        self._embedding_version = embedding_version
        self._token = auth_token or api_key
        self._timeout = timeout
        self._endpoint = endpoint
        self._client = client
        self._owns_client = client is None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def embedding_version(self) -> str:
        return self._embedding_version

    def _build_url(self) -> str:
        endpoint = self._endpoint.strip("/")
        if self._base_url.endswith("/v1") and endpoint.startswith("v1/"):
            endpoint = endpoint[3:]
        return f"{self._base_url}/{endpoint}"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> BgeM3EmbeddingProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """Embed a sequence of texts into dense vectors via HTTP API.

        Guarantees exact output vector ordering matching input texts:
        vectors[i] corresponds to texts[i].
        """
        if not texts:
            return EmbeddingResult(
                vectors=[],
                model=self._model_id,
                dimension=self._dimension,
                embedding_version=self._embedding_version,
            )

        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        url = self._build_url()
        payload = {
            "input": texts,
            "model": self._model_id,
        }

        client = await self._get_client()

        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise WorkerError(
                WorkerErrorCode.TIMEOUT,
                f"Embedding request timed out after {self._timeout}s: {exc}",
                retryable=True,
                status_code=504,
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError, httpx.RequestError) as exc:
            raise WorkerError(
                WorkerErrorCode.UNAVAILABLE,
                f"Failed to connect to embedding service at {self._base_url}: {exc}",
                retryable=True,
                status_code=503,
            ) from exc

        if response.status_code in (401, 403):
            raise WorkerError(
                WorkerErrorCode.UNAUTHORIZED,
                f"Unauthorized embedding request (HTTP {response.status_code}): {response.text}",
                retryable=False,
                status_code=response.status_code,
            )

        if response.status_code in (400, 422):
            raise WorkerError(
                WorkerErrorCode.BAD_REQUEST,
                f"Bad request to embedding service (HTTP {response.status_code}): {response.text}",
                retryable=False,
                status_code=response.status_code,
            )

        if response.status_code == 404:
            raise WorkerError(
                WorkerErrorCode.MODEL_NOT_LOADED,
                f"Embedding endpoint or model not found (HTTP 404): {response.text}",
                retryable=False,
                status_code=404,
            )

        if response.status_code == 503:
            raise WorkerError(
                WorkerErrorCode.UNAVAILABLE,
                f"Embedding service temporarily unavailable (HTTP 503): {response.text}",
                retryable=True,
                status_code=503,
            )

        if response.status_code >= 500:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Embedding upstream error (HTTP {response.status_code}): {response.text}",
                retryable=True,
                status_code=response.status_code,
            )

        if response.status_code != 200:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Unexpected status from service (HTTP {response.status_code}): {response.text}",
                retryable=False,
                status_code=response.status_code,
            )

        try:
            resp_json = response.json()
        except Exception as exc:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Invalid JSON response from embedding service: {exc}",
                retryable=True,
                status_code=502,
            ) from exc

        vectors: list[list[float]] = []

        if isinstance(resp_json, dict) and "data" in resp_json:
            data = resp_json["data"]
            if not isinstance(data, list):
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Expected 'data' field to be a list, got {type(data).__name__}",
                    retryable=False,
                    status_code=502,
                )
            # Sort by 'index' if provided to guarantee matching input order
            if data and isinstance(data[0], dict) and "index" in data[0]:
                sorted_items = sorted(data, key=lambda item: item.get("index", 0))
            else:
                sorted_items = data

            for item in sorted_items:
                if isinstance(item, dict) and "embedding" in item:
                    vectors.append(item["embedding"])
                elif isinstance(item, list):
                    vectors.append(item)
                else:
                    raise WorkerError(
                        WorkerErrorCode.UPSTREAM_ERROR,
                        f"Unsupported embedding item in data: {type(item).__name__}",
                        retryable=False,
                        status_code=502,
                    )
        elif isinstance(resp_json, list):
            for item in resp_json:
                if isinstance(item, list):
                    vectors.append(item)
                elif isinstance(item, dict) and "embedding" in item:
                    vectors.append(item["embedding"])
                else:
                    raise WorkerError(
                        WorkerErrorCode.UPSTREAM_ERROR,
                        f"Unsupported embedding item in list: {type(item).__name__}",
                        retryable=False,
                        status_code=502,
                    )
        else:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Unsupported embedding response structure: {type(resp_json).__name__}",
                retryable=False,
                status_code=502,
            )

        if len(vectors) != len(texts):
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Embedding count mismatch: expected {len(texts)}, received {len(vectors)}",
                retryable=True,
                status_code=502,
            )

        for i, vec in enumerate(vectors):
            if len(vec) != self._dimension:
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Embedding dimension mismatch at index {i}: "
                    f"expected {self._dimension}, received {len(vec)}",
                    retryable=True,
                    status_code=502,
                )

        return EmbeddingResult(
            vectors=vectors,
            model=self._model_id,
            dimension=self._dimension,
            embedding_version=self._embedding_version,
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        """Embed a single query text into a dense vector."""
        return await self.embed_documents([text])
