"""Document-type slices for per-document-type evaluation reporting (Phase 3.5).

Evaluation/reporting must support per-document-type metrics, not only one
aggregate score. This module names the slices and groups arbitrary case/result
objects by their `document_type` attribute.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

DOCUMENT_TYPE_SLICES: tuple[str, ...] = (
    "cong_van",
    "quyet_dinh",
    "ke_hoach",
    "thong_tu",
    "nghi_dinh",
    "table_appendix",
    "scanned",
)


class _HasDocumentType(Protocol):
    document_type: str


T = TypeVar("T", bound=_HasDocumentType)


def slice_by_document_type(items: Iterable[T]) -> dict[str, list[T]]:
    """Group items by `document_type`, keyed only by names in `DOCUMENT_TYPE_SLICES`.

    An item whose `document_type` is not one of the known slices raises
    `ValueError` rather than being silently dropped into an "other" bucket a
    report might miss.
    """
    slices: dict[str, list[T]] = {name: [] for name in DOCUMENT_TYPE_SLICES}
    for item in items:
        if item.document_type not in slices:
            raise ValueError(
                f"unknown document_type slice {item.document_type!r}; "
                f"expected one of {DOCUMENT_TYPE_SLICES}"
            )
        slices[item.document_type].append(item)
    return slices
