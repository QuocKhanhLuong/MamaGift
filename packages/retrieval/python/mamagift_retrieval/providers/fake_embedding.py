"""Deterministic fake embedding provider for CI and testing."""

from __future__ import annotations

import hashlib
import math
import re

from mamagift_contracts.embedding import EmbeddingResult


def _generate_deterministic_vector(text: str, dimension: int) -> list[float]:
    """Generate a deterministic unit embedding vector from input text.

    Properties:
    - Same text always yields the identical vector.
    - Different texts yield different vectors (no collisions).
    - Texts with high token overlap yield positive cosine similarity.
    - Result vector has exact Euclidean (L2) norm of 1.0 and matches declared dimension.
    - Pure computation: no model, no network, no GPU.
    """
    if dimension <= 0:
        raise ValueError(f"Dimension must be a positive integer, got {dimension}")

    text_bytes = text.encode("utf-8")
    h = hashlib.sha256(text_bytes).digest()
    vec = [0.0] * dimension

    # 1. Full text seed and PRNG pass (guarantees text uniqueness & distinctness)
    seed = int.from_bytes(h[:8], byteorder="big", signed=False)
    state = seed if seed != 0 else 0x123456789ABCDEF0
    for i in range(dimension):
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        val = ((state >> 11) / (1 << 53)) * 2.0 - 1.0
        vec[i] += val

    # 2. Token-level contribution (provides meaningful cosine similarity for overlapping text)
    tokens = re.findall(r"\w+", text.lower())
    for token in tokens:
        th = hashlib.sha256(token.encode("utf-8")).digest()
        t_seed = int.from_bytes(th[:8], byteorder="big", signed=False)
        t_state = t_seed if t_seed != 0 else 0x987654321FEDCBA0
        for i in range(dimension):
            t_state = (t_state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            val = ((t_state >> 11) / (1 << 53)) * 2.0 - 1.0
            vec[i] += 0.5 * val

    # Normalize to unit vector (L2 norm = 1.0)
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        vec[0] = 1.0
        return vec

    return [x / norm for x in vec]


class FakeEmbeddingProvider:
    """Deterministic in-memory embedding provider for CI, offline tests, and unit tests."""

    def __init__(
        self,
        model_id: str = "fake-bge-m3",
        dimension: int = 1024,
        embedding_version: str = "fake-bge-m3-v1",
    ) -> None:
        self._model_id = model_id
        self._dimension = dimension
        self._embedding_version = embedding_version

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def embedding_version(self) -> str:
        return self._embedding_version

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """Embed a sequence of texts into deterministic dense unit vectors.

        Preserves exact input order: vectors[i] corresponds to texts[i].
        """
        if not texts:
            return EmbeddingResult(
                vectors=[],
                model=self._model_id,
                dimension=self._dimension,
                embedding_version=self._embedding_version,
            )

        vectors = [_generate_deterministic_vector(t, self._dimension) for t in texts]
        return EmbeddingResult(
            vectors=vectors,
            model=self._model_id,
            dimension=self._dimension,
            embedding_version=self._embedding_version,
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        """Embed a single query text into a deterministic dense unit vector."""
        return await self.embed_documents([text])
