"""Phase 3.5/4 evaluation primitives: deterministic eval case schemas, document-type
slicing, per-type and plan metrics, the failure-analysis taxonomy and per-question
failure analysis, the single-document retrieval harness, MamaGift answer-quality
metrics, and the offline RAGAS adapter.

Everything here is deterministic and CPU-only. The RAGAS adapter degrades to a typed
UNAVAILABLE result rather than fabricating a score, so CI never depends on RAGAS, an
API key, or the network.
"""

from .document_types import (
    T,
    slice_by_document_type,
)
from .failure_analysis import (
    Context,
    ContextItem,
    FailureAnalysisCase,
    FailureAnalysisReport,
    analyze_failure,
    analyze_failure_case,
    analyze_failures,
)
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
    CitationReference,
    ClaimCitations,
    abstention_correctness,
    citation_completeness,
    citation_correctness,
    deadline_correctness,
    responsible_party_correctness,
    task_action_completeness,
)
from .ragas_adapter import (
    RAGAS_METRICS,
    RagasAdapter,
    RagasAvailableResult,
    RagasBackend,
    RagasEvaluationResult,
    RagasMetricName,
    RagasMetricResult,
    RagasUnavailableResult,
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
from .schemas import (
    ExpectedTaskRelation,
    ParserSemanticCase,
    RetrievalQACase,
)
from .taxonomy import (
    FailureDiagnosis,
    FailureLabel,
    classify_failure,
)

__all__ = [
    "CitationReference",
    "ClaimCitations",
    "Context",
    "ContextItem",
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
    "T",
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
