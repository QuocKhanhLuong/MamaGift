"""MamaGift document pipeline primitives.

Phase 1 delivered the provider-neutral parser interface, the PDF inspection router
and `CanonicalDocument` v1 normalization. Phase 2 adds the configurable parser
strategy, the Vietnamese administrative parser and the ingestion pipeline that joins
them. Retrieval and model-backed features belong to later phases.
"""

from .admin import ADMIN_PARSER_VERSION, parse_admin_document
from .canonical import (
    SCHEMA_VERSION,
    BBox,
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    ExtractedField,
    Extractor,
    HierarchyKind,
    HierarchyNode,
    ParserRun,
    QualityReport,
    ReviewStatus,
)
from .errors import ParserError, ParserErrorCode, ParserErrorModel
from .interface import (
    ADAPTER_CONTRACT_VERSION,
    AdapterMetadata,
    BaseDocumentParser,
    DocumentParser,
    HealthReport,
    ParserCapabilities,
    ParseRequest,
    ProviderBlock,
    ProviderPage,
    ProviderParseResult,
)
from .normalize import (
    NORMALIZER_VERSION,
    NormalizationOptions,
    normalize_provider_result,
    normalize_text,
)
from .pipeline import (
    PIPELINE_VERSION,
    IngestionResult,
    ParseAttempt,
    run_ingestion,
)
from .preview import DEFAULT_PREVIEW_DPI, render_page_png
from .router import (
    ROUTER_VERSION,
    InspectionReport,
    PageClass,
    PageSignals,
    PdfValidation,
    Route,
    inspect_pdf,
    validate_pdf_bytes,
)
from .strategy import (
    BASELINE_PARSER,
    PARSER_STRATEGY_VERSION,
    ParserSelection,
    ParserStrategy,
    RoutePlan,
    load_strategy,
    select_parser,
    undecided_strategy,
)

__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "ADMIN_PARSER_VERSION",
    "BASELINE_PARSER",
    "DEFAULT_PREVIEW_DPI",
    "NORMALIZER_VERSION",
    "PARSER_STRATEGY_VERSION",
    "PIPELINE_VERSION",
    "ROUTER_VERSION",
    "SCHEMA_VERSION",
    "AdapterMetadata",
    "BBox",
    "BaseDocumentParser",
    "BlockProvenance",
    "BlockType",
    "CanonicalBlock",
    "CanonicalDocument",
    "CanonicalPage",
    "CanonicalTable",
    "DocumentParser",
    "ExtractedField",
    "Extractor",
    "HealthReport",
    "HierarchyKind",
    "HierarchyNode",
    "IngestionResult",
    "InspectionReport",
    "NormalizationOptions",
    "PageClass",
    "PageSignals",
    "PdfValidation",
    "ParseAttempt",
    "ParseRequest",
    "ParserCapabilities",
    "ParserError",
    "ParserErrorCode",
    "ParserErrorModel",
    "ParserRun",
    "ParserSelection",
    "ParserStrategy",
    "ProviderBlock",
    "ProviderPage",
    "ProviderParseResult",
    "QualityReport",
    "ReviewStatus",
    "Route",
    "RoutePlan",
    "inspect_pdf",
    "load_strategy",
    "normalize_provider_result",
    "normalize_text",
    "parse_admin_document",
    "render_page_png",
    "run_ingestion",
    "select_parser",
    "undecided_strategy",
    "validate_pdf_bytes",
]
