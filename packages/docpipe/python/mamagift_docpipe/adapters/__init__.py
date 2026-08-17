"""Parser adapter registry.

Every benchmark candidate is reachable by name. Constructing an adapter never imports
its provider, so the registry is safe to enumerate on a CPU-only CI runner.
"""

from __future__ import annotations

from typing import Any

from ..interface import BaseDocumentParser, DocumentParser, ParserCapabilities
from .docling_adapter import DoclingAdapter
from .marker_adapter import MarkerAdapter
from .mineru_adapter import MinerUAdapter
from .ppstructure_adapter import PPStructureAdapter
from .pymupdf_adapter import PyMuPDFAdapter
from .recorded import RECORDED_SUFFIX, RecordedParser

# Ordered so the lightweight baseline is always first.
ADAPTER_REGISTRY: dict[str, type[BaseDocumentParser]] = {
    "pymupdf": PyMuPDFAdapter,
    "mineru": MinerUAdapter,
    "marker": MarkerAdapter,
    "docling": DoclingAdapter,
    "ppstructure": PPStructureAdapter,
}

# Adapters light enough to run end to end inside mandatory CI.
CI_SAFE_ADAPTERS = frozenset({"pymupdf"})


def available_adapter_names() -> list[str]:
    return list(ADAPTER_REGISTRY)


def build_adapter(name: str, configuration: dict[str, Any] | None = None) -> DocumentParser:
    """Build an adapter by registry name.

    A `<name>+recorded` suffix builds a replay adapter for that parser instead, which
    is how heavy candidates take part in CI contract tests.
    """
    if name.endswith(RECORDED_SUFFIX):
        base_name = name[: -len(RECORDED_SUFFIX)]
        if base_name not in ADAPTER_REGISTRY:
            raise KeyError(f"unknown parser adapter: {base_name}")
        config = configuration or {}
        return RecordedParser(
            base_name,
            recordings_dir=config.get("recordings_dir", "benchmarks/parser/recordings"),
            capabilities=capabilities_for(base_name),
        )

    if name not in ADAPTER_REGISTRY:
        raise KeyError(f"unknown parser adapter: {name}")
    return ADAPTER_REGISTRY[name](configuration)


def capabilities_for(name: str) -> ParserCapabilities:
    return ADAPTER_REGISTRY[name]().metadata.capabilities


__all__ = [
    "ADAPTER_REGISTRY",
    "CI_SAFE_ADAPTERS",
    "RECORDED_SUFFIX",
    "DoclingAdapter",
    "MarkerAdapter",
    "MinerUAdapter",
    "PPStructureAdapter",
    "PyMuPDFAdapter",
    "RecordedParser",
    "available_adapter_names",
    "build_adapter",
    "capabilities_for",
]
