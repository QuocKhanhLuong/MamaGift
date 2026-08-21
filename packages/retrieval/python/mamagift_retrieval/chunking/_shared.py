"""Shared helpers for chunk builders."""

from __future__ import annotations

from urllib.parse import quote

from mamagift_docpipe import CanonicalDocument


def chunk_id(
    document_id: str,
    document_version: int | None,
    parse_run_id: str,
    suffix: str,
) -> str:
    """Build a deterministic, version-isolated, separator-safe chunk ID.

    The format is:
        chunk:<escaped_doc_id>:<version_tag>:<escaped_parse_run_id>:<escaped_suffix>

    where `version_tag` is `v{document_version}` (e.g. `v1`, `v2`) if `document_version`
    is not None, or `vnone` if `document_version` is None.
    All string components are URL-escaped with `quote(..., safe="")` to prevent
    delimiter collision or component forging.
    """
    version_part = f"v{document_version}" if document_version is not None else "vnone"
    parts = [
        quote(document_id, safe=""),
        version_part,
        quote(parse_run_id, safe=""),
        quote(suffix, safe=""),
    ]
    return f"chunk:{':'.join(parts)}"


def field_value(document: CanonicalDocument, name: str) -> str | None:
    """Read an extracted field's normalized value, falling back to its raw value.

    Returns `None` when the field was never extracted — chunk metadata must stay
    honestly absent rather than guessed, the same rule `parse_admin_document` follows.
    """
    for extracted in document.extracted_fields:
        if extracted.name == name:
            return extracted.normalized_value or extracted.raw_value
    return None
