"""Configurable BGE-M3-compatible HTTP embedding provider adapter."""

from __future__ import annotations

import types
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
        if not base_url or not base_url.strip():
            raise ValueError("base_url must not be empty")
        if not model_id or not model_id.strip():
            raise ValueError("model_id must not be empty")
        if dimension <= 0:
            raise ValueError(f"Dimension must be a positive integer, got {dimension}")
        if not embedding_version or not embedding_version.strip():
            raise ValueError("embedding_version must not be empty")
        if timeout <= 0:
            raise ValueError(f"Timeout must be positive, got {timeout}")

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
        exc_tb: types.TracebackType | None,
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

        # Surface metadata mismatch if reported at the top-level payload
        if isinstance(resp_json, dict):
            reported_model = resp_json.get("model")
            if reported_model is not None and reported_model != self._model_id:
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Embedding model mismatch: expected '{self._model_id}', "
                    f"received '{reported_model}'",
                    retryable=False,
                    status_code=502,
                )
            reported_version = resp_json.get("embedding_version")
            if reported_version is not None and reported_version != self._embedding_version:
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Embedding version mismatch: expected '{self._embedding_version}', "
                    f"received '{reported_version}'",
                    retryable=False,
                    status_code=502,
                )

        raw_items: list[Any]
        if isinstance(resp_json, dict) and "data" in resp_json:
            data = resp_json["data"]
            if not isinstance(data, list):
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Expected 'data' field to be a list, got {type(data).__name__}",
                    retryable=False,
                    status_code=502,
                )
            raw_items = data
        elif isinstance(resp_json, list):
            raw_items = resp_json
        else:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Unsupported embedding response structure: {type(resp_json).__name__}",
                retryable=False,
                status_code=502,
            )

        n_expected = len(texts)
        if len(raw_items) != n_expected:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Embedding count mismatch: expected {n_expected}, received {len(raw_items)}",
                retryable=True,
                status_code=502,
            )

        # Check per-item indices if present.
        # If any item carries an 'index', EVERY item must carry an integer index,
        # and the indices must form an exact complete permutation of 0..N-1
        # (no gaps, duplicates, or out-of-range values).
        # If no items carry indices, arrival order is explicitly assumed to match
        # input texts (item[i] -> texts[i]).
        indexed_items: list[int] = []
        for i, item in enumerate(raw_items):
            if isinstance(item, dict) and "index" in item:
                idx = item["index"]
                if not isinstance(idx, int) or isinstance(idx, bool):
                    raise WorkerError(
                        WorkerErrorCode.UPSTREAM_ERROR,
                        f"Embedding index at position {i} is not an integer: {idx!r}",
                        retryable=False,
                        status_code=502,
                    )
                indexed_items.append(idx)

        sorted_items: list[Any]
        if len(indexed_items) == n_expected:
            # All items have indices: validate exact permutation of 0..N-1
            expected_set = set(range(n_expected))
            actual_set = set(indexed_items)
            if actual_set != expected_set or len(indexed_items) != len(actual_set):
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Embedding response indices {indexed_items} do not form a complete "
                    f"permutation of 0..{n_expected - 1}",
                    retryable=False,
                    status_code=502,
                )
            # Reorder items strictly according to their declared index
            sorted_items = [None] * n_expected
            for item in raw_items:
                sorted_items[item["index"]] = item
        elif len(indexed_items) == 0:
            # No items carry an index: arrival order is explicitly assumed to correspond 1:1.
            sorted_items = raw_items
        else:
            # Partial indices present (some items have index, others do not) - invalid payload
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Embedding response carries partial indices "
                f"({len(indexed_items)}/{n_expected} items)",
                retryable=False,
                status_code=502,
            )

        vectors: list[list[float]] = []
        for i, item in enumerate(sorted_items):
            if isinstance(item, dict):
                # Also check per-item model/version metadata if present
                item_model = item.get("model")
                if item_model is not None and item_model != self._model_id:
                    raise WorkerError(
                        WorkerErrorCode.UPSTREAM_ERROR,
                        f"Embedding model mismatch at item {i}: expected '{self._model_id}', "
                        f"received '{item_model}'",
                        retryable=False,
                        status_code=502,
                    )
                item_version = item.get("embedding_version")
                if item_version is not None and item_version != self._embedding_version:
                    raise WorkerError(
                        WorkerErrorCode.UPSTREAM_ERROR,
                        f"Embedding version mismatch at item {i}: "
                        f"expected '{self._embedding_version}', received '{item_version}'",
                        retryable=False,
                        status_code=502,
                    )

                if "embedding" not in item:
                    raise WorkerError(
                        WorkerErrorCode.UPSTREAM_ERROR,
                        f"Missing 'embedding' field in response item {i}",
                        retryable=False,
                        status_code=502,
                    )
                vec = item["embedding"]
            elif isinstance(item, list):
                vec = item
            else:
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Unsupported embedding item at index {i}: {type(item).__name__}",
                    retryable=False,
                    status_code=502,
                )

            if not isinstance(vec, list):
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Embedding vector at index {i} must be a list, got {type(vec).__name__}",
                    retryable=False,
                    status_code=502,
                )

            if len(vec) != self._dimension:
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Embedding dimension mismatch at index {i}: "
                    f"expected {self._dimension}, received {len(vec)}",
                    retryable=True,
                    status_code=502,
                )

            # Validate numeric elements
            if not all(isinstance(val, (int, float)) and not isinstance(val, bool) for val in vec):
                raise WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Embedding vector at index {i} contains non-numeric values",
                    retryable=False,
                    status_code=502,
                )

            vectors.append([float(val) for val in vec])

        return EmbeddingResult(
            vectors=vectors,
            model=self._model_id,
            dimension=self._dimension,
            embedding_version=self._embedding_version,
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        """Embed a single query text into a dense vector."""
        return await self.embed_documents([text])
