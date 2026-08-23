"""Deterministic, model-free reranker used by tests and local development."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

from mamagift_retrieval.search.types import ScoredChunk

from .protocol import validate_rerank_candidates

CandidateOrder = Sequence[str | int]


class FakeReranker:
    """A reproducible reranker driven by canned chunk IDs or input positions.

    ``orderings`` may map a query to an ordering, or be one ordering used for every
    query. Any candidates omitted from a canned ordering remain in their input order,
    so the fake can never lose evidence. If no canned ordering exists, ``seed`` drives
    a deterministic shuffle of the input positions.
    """

    def __init__(
        self,
        orderings: Mapping[str, CandidateOrder] | CandidateOrder | None = None,
        *,
        ordering: CandidateOrder | None = None,
        seed: int = 0,
        reranker_version: str = "fake-reranker-v1",
    ) -> None:
        if ordering is not None and orderings is not None:
            raise ValueError("provide either orderings or ordering, not both")
        if not reranker_version.strip():
            raise ValueError("reranker_version must not be empty")

        self._seed = seed
        self._reranker_version = reranker_version
        self._ordering: tuple[str | int, ...] | None = None
        self._orderings: dict[str, tuple[str | int, ...]] = {}
        chosen = ordering if ordering is not None else orderings
        if isinstance(chosen, Mapping):
            self._orderings = {query: tuple(order) for query, order in chosen.items()}
        elif chosen is not None:
            self._ordering = tuple(chosen)

        for query, order in self._orderings.items():
            self._validate_order(query, order)
        if self._ordering is not None:
            self._validate_order("default", self._ordering)

    @property
    def reranker_version(self) -> str:
        return self._reranker_version

    @staticmethod
    def _validate_order(query: str, order: CandidateOrder) -> None:
        if len(order) != len(set(order)):
            raise ValueError(f"canned ordering for {query!r} contains duplicates")

    def _resolve_order(self, query: str, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        by_id = {candidate.chunk.chunk_id: candidate for candidate in candidates}
        order = self._orderings.get(query, self._orderings.get("*", self._ordering))
        if order is None:
            positions = list(range(len(candidates)))
            random.Random(self._seed).shuffle(positions)
            return [candidates[position] for position in positions]

        selected: list[ScoredChunk] = []
        selected_ids: set[str] = set()
        for item in order:
            if isinstance(item, int):
                if item < 0 or item >= len(candidates):
                    raise ValueError(f"canned candidate position {item} is out of range")
                candidate = candidates[item]
            else:
                candidate_by_id = by_id.get(item)
                if candidate_by_id is None:
                    raise ValueError(f"canned candidate {item!r} is not in the input")
                candidate = candidate_by_id
            if candidate.chunk.chunk_id in selected_ids:
                raise ValueError(f"canned ordering repeats {candidate.chunk.chunk_id!r}")
            selected.append(candidate)
            selected_ids.add(candidate.chunk.chunk_id)

        selected.extend(
            candidate for candidate in candidates if candidate.chunk.chunk_id not in selected_ids
        )
        return selected

    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        validate_rerank_candidates(candidates)
        if not candidates or top_k <= 0:
            return []

        ordered = self._resolve_order(query, candidates)
        total = len(ordered)
        reranked = [
            ScoredChunk(
                chunk=candidate.chunk,
                score=float(total - position),
                rank=position,
                retriever="reranked",
            )
            for position, candidate in enumerate(ordered, start=1)
        ]
        return reranked[:top_k]


__all__ = ["FakeReranker"]
