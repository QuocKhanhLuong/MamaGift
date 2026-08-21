"""Phase 3.5 evaluation-foundation primitives: deterministic eval case schemas,
document-type slicing, per-type/plan metrics and the failure-analysis taxonomy. No
LLM evaluator or RAGAS integration is implemented here.
"""

from .schemas import ExpectedTaskRelation, ParserSemanticCase, RetrievalQACase

__all__ = [
    "ExpectedTaskRelation",
    "ParserSemanticCase",
    "RetrievalQACase",
]
