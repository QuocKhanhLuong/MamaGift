"""Phase 3.5 retrieval-foundation primitives: evidence scope, chunk contract,
deterministic hierarchical chunking, a naive lexical baseline seam and the
context/evidence budget contract. No embeddings, vector store, memory backend or
reranker are implemented here (docs/09_CODEX_EXECUTION.md non-goals for this phase).
"""

from .scope import EvidenceScope, EvidenceSource, authority_rank, resolve_conflict, scope_matches

__all__ = [
    "EvidenceScope",
    "EvidenceSource",
    "authority_rank",
    "resolve_conflict",
    "scope_matches",
]
