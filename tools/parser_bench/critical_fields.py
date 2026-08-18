"""Benchmark critical-field extraction.

Scope guard: full Vietnamese administrative semantic extraction is Phase 2 work and
lives in `mamagift_docpipe.admin.parser.parse_admin_document`. This module does not
re-derive issue-date, document-number, deadline, issuer, title or signer selection
logic; it delegates to that exact function so a benchmark pass/fail means the same
thing as a `run_ingestion` pass/fail (`docs/decisions/2026-08-17-real-pdf-correctness`
design review, Option A). Keeping two independent selectors here would let benchmark
scores and production behavior drift apart silently.

Nothing is ever guessed. A field the admin parser could not locate stays `None`, so a
parser is never credited for a value this module invented.
"""

from __future__ import annotations

from mamagift_docpipe.admin import ADMIN_PARSER_VERSION, EXTRACTOR_NAME, parse_admin_document
from mamagift_docpipe.canonical import CanonicalDocument

__all__ = [
    "CRITICAL_FIELD_NAMES",
    "EXTRACTOR_NAME",
    "EXTRACTOR_VERSION",
    "SEVERITY_3_FIELDS",
    "extract_critical_fields",
    "severity_3_failures",
]

EXTRACTOR_VERSION = ADMIN_PARSER_VERSION

CRITICAL_FIELD_NAMES = (
    "document_number",
    "issue_date",
    "issuer",
    "title",
    "signer",
    "deadline",
)

# Fields where a wrong value is severity 3 in docs/05_TEST_STRATEGY.md section 8.
SEVERITY_3_FIELDS = frozenset({"document_number", "issue_date", "deadline"})


def extract_critical_fields(document: CanonicalDocument) -> dict[str, str | None]:
    """Extract benchmark critical fields through the shared administrative parser.

    This enriches `document` exactly as `run_ingestion` does and reads the resulting
    `extracted_fields`, so benchmark scoring exercises the same candidate ranking,
    ambiguity handling and provenance rules as production instead of a second,
    divergent implementation.
    """
    enriched = parse_admin_document(document)
    by_name = {field.name: field.normalized_value for field in enriched.extracted_fields}
    return {name: by_name.get(name) for name in CRITICAL_FIELD_NAMES}


def severity_3_failures(expected: dict[str, str], wrong_fields: list[str]) -> list[str]:
    """Which wrong fields are release-blocking rather than merely disappointing."""
    return [name for name in wrong_fields if name in SEVERITY_3_FIELDS and name in expected]
