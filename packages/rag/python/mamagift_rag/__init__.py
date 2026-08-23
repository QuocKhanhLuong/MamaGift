"""Grounded generation for a single selected document (Phase 4).

Every factual answer is grounded in retrieved evidence and cites only ids from
that request's allow-list. Document text is untrusted input: instructions inside
a document never change system policy, request tools, expose secrets, or widen
retrieval scope.
"""

from .prompt import build_grounded_prompt
from .schema import Citation, ModelRef, QaAnswer, RetrievalRef
from .service import QaService
from .validation import parse_and_validate_answer

__all__ = [
    "Citation",
    "ModelRef",
    "QaAnswer",
    "QaService",
    "RetrievalRef",
    "build_grounded_prompt",
    "parse_and_validate_answer",
]
