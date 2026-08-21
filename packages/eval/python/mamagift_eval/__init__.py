"""Phase 3.5 evaluation-foundation primitives: deterministic eval case schemas,
document-type slicing, per-type/plan metrics and the failure-analysis taxonomy. No
LLM evaluator or RAGAS integration is implemented here.
"""

from .document_types import DOCUMENT_TYPE_SLICES, slice_by_document_type
from .metrics import (
    deadline_accuracy,
    nested_hierarchy_f1,
    table_appendix_preservation,
    task_deadline_association_accuracy,
    task_order_accuracy,
    task_owner_association_accuracy,
    task_recall,
)
from .schemas import ExpectedTaskRelation, ParserSemanticCase, RetrievalQACase
from .taxonomy import FailureDiagnosis, FailureLabel, classify_failure

__all__ = [
    "DOCUMENT_TYPE_SLICES",
    "ExpectedTaskRelation",
    "FailureDiagnosis",
    "FailureLabel",
    "ParserSemanticCase",
    "RetrievalQACase",
    "classify_failure",
    "deadline_accuracy",
    "nested_hierarchy_f1",
    "slice_by_document_type",
    "table_appendix_preservation",
    "task_deadline_association_accuracy",
    "task_order_accuracy",
    "task_owner_association_accuracy",
    "task_recall",
]
