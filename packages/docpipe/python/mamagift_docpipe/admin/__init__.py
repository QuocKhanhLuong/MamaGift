"""Vietnamese administrative document structure and critical-field extraction."""

from .parser import (
    ADMIN_PARSER_VERSION,
    EXTRACTOR_NAME,
    REQUIRED_FIELDS,
    REVIEW_CONFIDENCE_THRESHOLD,
    parse_admin_document,
)

__all__ = [
    "ADMIN_PARSER_VERSION",
    "EXTRACTOR_NAME",
    "REQUIRED_FIELDS",
    "REVIEW_CONFIDENCE_THRESHOLD",
    "parse_admin_document",
]
