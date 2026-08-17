"""Provider-neutral `DocumentParser` interface.

No product or benchmark code may import a parser provider directly. Every provider is
reached through an adapter implementing `DocumentParser`, so provider types never leak
into application logic (`docs/09_CODEX_EXECUTION.md` section 7).
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .errors import ParserErrorModel

ADAPTER_CONTRACT_VERSION = "1.0"


class ParserCapabilities(BaseModel):
    """What an adapter claims it can do. Claims are verified by the benchmark."""

    model_config = ConfigDict(extra="forbid")

    born_digital_text: bool = False
    ocr: bool = False
    layout_analysis: bool = False
    reading_order: bool = False
    tables: bool = False
    headings: bool = False
    lists: bool = False
    bounding_boxes: bool = False
    confidence_scores: bool = False
    requires_gpu: bool = False
    benefits_from_gpu: bool = False


class AdapterMetadata(BaseModel):
    """Stable adapter identity plus the exact provider version actually loaded."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    contract_version: str = ADAPTER_CONTRACT_VERSION
    provider_package: str | None = None
    provider_version: str | None = None
    capabilities: ParserCapabilities
    configuration: dict[str, Any] = Field(default_factory=dict)
    configuration_hash: str = Field(min_length=1)


class HealthReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    available: bool
    provider_version: str | None = None
    device: str = "cpu"
    detail: str = ""


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    pdf_path: Path
    page_limit: int | None = Field(default=None, ge=1)
    options: dict[str, Any] = Field(default_factory=dict)


class ProviderBlock(BaseModel):
    """One block as the provider reported it, before canonical normalization."""

    model_config = ConfigDict(extra="forbid")

    provider_block_id: str = Field(min_length=1)
    provider_type: str = Field(min_length=1)
    text: str = ""
    bbox: list[float] | None = None
    confidence: float | None = None
    order_hint: int | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProviderPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    width: float = Field(gt=0.0)
    height: float = Field(gt=0.0)
    rotation: int = 0
    blocks: list[ProviderBlock] = Field(default_factory=list)


class ProviderParseResult(BaseModel):
    """Raw parser artifact. Immutable input to normalization; never edited in place."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    adapter: AdapterMetadata
    device: str = "cpu"
    started_at: str = Field(min_length=1)
    finished_at: str = Field(min_length=1)
    duration_ms: float = Field(ge=0.0)
    pages: list[ProviderPage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ParserErrorModel] = Field(default_factory=list)
    provider_artifact: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class DocumentParser(Protocol):
    """The only parser surface the rest of MamaGift is allowed to depend on."""

    @property
    def metadata(self) -> AdapterMetadata: ...

    def healthcheck(self) -> HealthReport: ...

    def parse(self, request: ParseRequest) -> ProviderParseResult: ...


class BaseDocumentParser(ABC):
    """Shared adapter behavior: identity, config hashing, health reporting."""

    name: str
    adapter_version: str
    provider_package: str | None = None
    capabilities: ParserCapabilities

    def __init__(self, configuration: dict[str, Any] | None = None) -> None:
        self.configuration = dict(configuration or {})

    @property
    def configuration_hash(self) -> str:
        payload = json.dumps(self.configuration, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=self.name,
            adapter_version=self.adapter_version,
            provider_package=self.provider_package,
            provider_version=self.provider_version(),
            capabilities=self.capabilities,
            configuration=self.configuration,
            configuration_hash=self.configuration_hash,
        )

    def provider_version(self) -> str | None:
        """Exact installed provider version, or None when the provider is absent."""
        return None

    def healthcheck(self) -> HealthReport:
        version = self.provider_version()
        return HealthReport(
            name=self.name,
            available=version is not None,
            provider_version=version,
            device=self.device(),
            detail="" if version is not None else f"{self.provider_package} is not installed",
        )

    def device(self) -> str:
        return str(self.configuration.get("device", "cpu"))

    @abstractmethod
    def parse(self, request: ParseRequest) -> ProviderParseResult: ...
