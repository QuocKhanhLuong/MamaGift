"""Phase 3.5 evaluation-foundation primitives: deterministic eval case schemas,
document-type slicing, per-type/plan metrics and the failure-analysis taxonomy. No
LLM evaluator or RAGAS integration is implemented here.
"""

from .document_types import DOCUMENT_TYPE_SLICES, slice_by_document_type
from .failure_analysis import 
from .metrics import 
from .qa_metrics import 
from .ragas_adapter import 
from .retrieval_harness import 
from .schemas import ExpectedTaskRelation, ParserSemanticCase, RetrievalQACase
from .taxonomy import FailureDiagnosis, FailureLabel, classify_failure

__all__ = [
    "DOCUMENT_TYPE_SLICES",
    "ExpectedTaskRelation",
    "FailureAnalysisCase",
    "FailureAnalysisReport",
    "FailureDiagnosis",
    "FailureLabel",
    "ParserSemanticCase",
    "RAGAS_METRICS",
    "RagasAdapter",
    "RagasAvailableResult",
    "RagasBackend",
    "RagasEvaluationResult",
    "RagasMetricName",
    "RagasMetricResult",
    "RagasUnavailableResult",
    "RetrievalAggregateMetrics",
    "RetrievalCaseResult",
    "RetrievalEvaluationHarness",
    "RetrievalEvaluationReport",
    "RetrievalQACase",
    "RetrievalSearch",
    "abstention_correctness",
    "analyze_failure",
    "analyze_failure_case",
    "analyze_failures",
    "citation_completeness",
    "citation_correctness",
    "classify_failure",
    "deadline_accuracy",
    "deadline_correctness",
    "evaluate_retrieval",
    "load_retrieval_cases",
    "nested_hierarchy_f1",
    "responsible_party_correctness",
    "slice_by_document_type",
    "table_appendix_preservation",
    "task_action_completeness",
    "task_deadline_association_accuracy",
    "task_order_accuracy",
    "task_owner_association_accuracy",
    "task_recall",
]
