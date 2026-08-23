"""Evidence expansion and bounded assembly for grounded retrieval (Phase 4).

`expand_evidence` walks ancestors only, so expanding one `Kế hoạch` task can never
pull in a sibling task's owner or deadline. `assemble_evidence` then applies the
Phase 3.5 budget contract and assigns the `c1..cN` citation ids that Task E1
validates the model's output against.
"""

from __future__ import annotations

from .assembler import Evidence, EvidenceSet, assemble_evidence
from .expansion import (
    DEFAULT_MAX_ANCESTOR_DEPTH,
    MAX_ANCESTOR_DEPTH,
    expand_evidence,
)

__all__ = [
    "DEFAULT_MAX_ANCESTOR_DEPTH",
    "MAX_ANCESTOR_DEPTH",
    "Evidence",
    "EvidenceSet",
    "assemble_evidence",
    "expand_evidence",
]
