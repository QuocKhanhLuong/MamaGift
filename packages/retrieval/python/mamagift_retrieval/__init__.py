"""Phase 3.5 retrieval-foundation primitives: evidence scope, chunk contract,
deterministic hierarchical chunking, a naive lexical baseline seam and the
context/evidence budget contract. No embeddings, vector store, memory backend or
reranker are implemented here (docs/09_CODEX_EXECUTION.md non-goals for this phase).
"""

from .budget import BudgetBreakdown, BudgetCategoryUsage, EvidenceBudget, assemble_bounded_context
from .chunk import Chunk, ChunkType, validate_chunk_tree
from .lexical import LexicalHit, LexicalIndex, RetrievalBaseline
from .scope import EvidenceScope, EvidenceSource, authority_rank, resolve_conflict, scope_matches

__all__ = [
    "BudgetBreakdown",
    "BudgetCategoryUsage",
    "Chunk",
    "ChunkType",
    "EvidenceBudget",
    "EvidenceScope",
    "EvidenceSource",
    "LexicalHit",
    "LexicalIndex",
    "RetrievalBaseline",
    "assemble_bounded_context",
    "authority_rank",
    "resolve_conflict",
    "scope_matches",
    "validate_chunk_tree",
]
