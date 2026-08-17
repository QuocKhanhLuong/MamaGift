"""MamaGift document pipeline primitives.

Phase 1 scope: the provider-neutral parser interface, the PDF inspection router, and
`CanonicalDocument` v1 normalization. Production ingestion, semantic extraction and
retrieval belong to later phases.
"""

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
from .router import (
    ROUTER_VERSION,
    InspectionReport,
    PageClass,
    PageSignals,
    Route,
    inspect_pdf,
)

__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "NORMALIZER_VERSION",
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
    "InspectionReport",
    "NormalizationOptions",
    "PageClass",
    "PageSignals",
    "ParseRequest",
    "ParserCapabilities",
    "ParserError",
    "ParserErrorCode",
    "ParserErrorModel",
    "ParserRun",
    "ProviderBlock",
    "ProviderPage",
    "ProviderParseResult",
    "QualityReport",
    "ReviewStatus",
    "Route",
    "inspect_pdf",
    "normalize_provider_result",
    "normalize_text",
]
