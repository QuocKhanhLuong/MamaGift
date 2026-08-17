"""The Phase 2 ingestion pipeline.

    inspect -> parser selection -> parse -> normalize -> Vietnamese admin parser
    -> quality report

Each stage is a separate layer over an immutable upstream artifact: the provider
result is never edited, normalization builds a new canonical document, and the
administrative parser builds another one from that
(`docs/09_CODEX_EXECUTION.md` section 8).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import build_adapter
from .admin import parse_admin_document
from .canonical import CanonicalDocument, QualityReport
from .errors import ParserError, ParserErrorCode, ParserErrorModel
from .interface import DocumentParser, ParseRequest, ProviderParseResult
from .normalize import normalize_provider_result
from .router import InspectionReport, Route, inspect_pdf
from .strategy import ParserSelection, ParserStrategy, select_parser, undecided_strategy

PIPELINE_VERSION = "1.0"

AdapterFactory = Callable[[str, dict[str, object] | None], DocumentParser]


@dataclass
class ParseAttempt:
    parser_name: str
    succeeded: bool
    error: ParserErrorModel | None = None


@dataclass
class IngestionResult:
    document_id: str
    inspection: InspectionReport
    selection: ParserSelection
    provider_result: ProviderParseResult
    canonical: CanonicalDocument
    attempts: list[ParseAttempt] = field(default_factory=list)


def _text_quality_score(inspection: InspectionReport) -> float | None:
    if not inspection.pages:
        return None
    mean_garbled = sum(page.garbled_char_ratio for page in inspection.pages) / len(inspection.pages)
    return round(max(0.0, min(1.0, 1.0 - mean_garbled)), 3)


def _blocked_route_error(inspection: InspectionReport) -> ParserError | None:
    if inspection.route == Route.ENCRYPTED:
        return ParserError(
            ParserErrorCode.ENCRYPTED_PDF,
            "document is password protected and cannot be parsed",
            parser_name="pipeline",
        )
    if inspection.route == Route.UNSUPPORTED:
        return ParserError(
            ParserErrorCode.INVALID_PDF,
            "document could not be read as a PDF",
            parser_name="pipeline",
            details={"warnings": inspection.warnings},
        )
    return None


def _parse_with_chain(
    chain: list[str],
    request: ParseRequest,
    adapter_factory: AdapterFactory,
) -> tuple[ProviderParseResult, list[ParseAttempt]]:
    attempts: list[ParseAttempt] = []
    last_error: ParserError | None = None

    for parser_name in chain:
        parser = adapter_factory(parser_name, None)
        try:
            result = parser.parse(request)
        except ParserError as exc:
            attempts.append(ParseAttempt(parser_name, succeeded=False, error=exc.model))
            last_error = exc
            if not exc.retryable:
                # Encrypted or malformed input will fail identically everywhere.
                raise
            continue
        attempts.append(ParseAttempt(parser_name, succeeded=True))
        return result, attempts

    if last_error is not None:
        raise last_error
    raise ParserError(
        ParserErrorCode.PARSER_STRATEGY_UNDECIDED,
        "no parser was available for this document",
        parser_name="pipeline",
    )


def run_ingestion(
    pdf_path: str | Path,
    document_id: str,
    strategy: ParserStrategy | None = None,
    environment: str = "development",
    page_limit: int | None = None,
    adapter_factory: AdapterFactory | None = None,
) -> IngestionResult:
    """Run the full ingestion pipeline for one PDF.

    Raises `ParserError` for input that must not be parsed (encrypted, malformed) and
    for an environment whose parser strategy is undecided.
    """
    active_strategy = strategy or undecided_strategy()
    factory: AdapterFactory = adapter_factory or _default_adapter_factory

    inspection = inspect_pdf(pdf_path, document_id=document_id)
    blocked = _blocked_route_error(inspection)
    if blocked is not None:
        raise blocked

    selection = select_parser(inspection.route, active_strategy, environment=environment)

    request = ParseRequest(
        document_id=document_id,
        pdf_path=Path(pdf_path),
        page_limit=page_limit,
    )
    provider_result, attempts = _parse_with_chain(selection.chain, request, factory)

    canonical = normalize_provider_result(provider_result, inspection=inspection)
    canonical = parse_admin_document(canonical)

    warnings = [*canonical.quality_report.warnings, *selection.warnings]
    quality = QualityReport(
        route=canonical.quality_report.route,
        route_confidence=canonical.quality_report.route_confidence,
        text_quality_score=_text_quality_score(inspection),
        structure_quality_score=canonical.quality_report.structure_quality_score,
        critical_field_warnings=canonical.quality_report.critical_field_warnings,
        warnings=warnings,
        requires_user_review=(canonical.quality_report.requires_user_review or selection.degraded),
    )

    metadata = dict(canonical.metadata)
    metadata["pipeline"] = {
        "version": PIPELINE_VERSION,
        "environment": environment,
        "parser_selection": selection.model_dump(mode="json"),
        "attempts": [
            {
                "parser_name": attempt.parser_name,
                "succeeded": attempt.succeeded,
                "error": None if attempt.error is None else attempt.error.model_dump(mode="json"),
            }
            for attempt in attempts
        ],
    }

    final = CanonicalDocument(
        schema_version=canonical.schema_version,
        document_id=canonical.document_id,
        parser_run=canonical.parser_run,
        metadata=metadata,
        pages=canonical.pages,
        hierarchy=canonical.hierarchy,
        tables=canonical.tables,
        extracted_fields=canonical.extracted_fields,
        quality_report=quality,
    )

    return IngestionResult(
        document_id=document_id,
        inspection=inspection,
        selection=selection,
        provider_result=provider_result,
        canonical=final,
        attempts=attempts,
    )


def _default_adapter_factory(name: str, configuration: dict[str, object] | None) -> DocumentParser:
    typed_configuration = dict(configuration) if configuration else None
    return build_adapter(name, typed_configuration)
