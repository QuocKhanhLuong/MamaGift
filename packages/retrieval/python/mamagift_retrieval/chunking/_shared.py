"""Shared helpers for chunk builders."""

from __future__ import annotations

from mamagift_docpipe import CanonicalDocument


def field_value(document: CanonicalDocument, name: str) -> str | None:
    """Read an extracted field's normalized value, falling back to its raw value.

    Returns `None` when the field was never extracted — chunk metadata must stay
    honestly absent rather than guessed, the same rule `parse_admin_document` follows.
    """
    for extracted in document.extracted_fields:
        if extracted.name == name:
            return extracted.normalized_value or extracted.raw_value
    return None
