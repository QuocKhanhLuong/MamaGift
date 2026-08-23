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
from .qa_metrics import (
    abstention_correctness,
    citation_completeness,
    citation_correctness,
    deadline_correctness,
    responsible_party_correctness,
    task_action_completeness,
)
from .retrieval_harness import (
    RetrievalAggregateMetrics,
    RetrievalCaseResult,
    RetrievalEvaluationHarness,
    RetrievalEvaluationReport,
    RetrievalSearch,
    evaluate_retrieval,
    load_retrieval_cases,
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
    "RetrievalAggregateMetrics",
    "RetrievalCaseResult",
    "RetrievalEvaluationHarness",
    "RetrievalEvaluationReport",
    "RetrievalSearch",
    "classify_failure",
    "deadline_accuracy",
    "nested_hierarchy_f1",
    "slice_by_document_type",
    "table_appendix_preservation",
    "task_deadline_association_accuracy",
    "task_order_accuracy",
    "task_owner_association_accuracy",
    "task_recall",
    "evaluate_retrieval",
    "load_retrieval_cases",
    "abstention_correctness",
    "citation_completeness",
    "citation_correctness",
    "deadline_correctness",
    "responsible_party_correctness",
    "task_action_completeness",
]
