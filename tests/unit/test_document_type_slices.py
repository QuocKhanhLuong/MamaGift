"""Tests for grouping arbitrary evaluation items by document-type slice."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mamagift_eval.document_types import DOCUMENT_TYPE_SLICES, slice_by_document_type

pytestmark = pytest.mark.unit


@dataclass
class _Item:
    document_type: str
    label: str


def test_known_slices_include_scanned_and_table_appendix() -> None:
    assert "scanned" in DOCUMENT_TYPE_SLICES
    assert "table_appendix" in DOCUMENT_TYPE_SLICES
    assert "ke_hoach" in DOCUMENT_TYPE_SLICES


def test_items_group_by_their_document_type() -> None:
    items = [_Item("ke_hoach", "a"), _Item("cong_van", "b"), _Item("ke_hoach", "c")]
    slices = slice_by_document_type(items)
    assert [item.label for item in slices["ke_hoach"]] == ["a", "c"]
    assert [item.label for item in slices["cong_van"]] == ["b"]
    assert slices["thong_tu"] == []


def test_every_known_slice_is_present_even_when_empty() -> None:
    slices = slice_by_document_type([])
    assert set(slices) == set(DOCUMENT_TYPE_SLICES)


def test_unknown_document_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown document_type"):
        slice_by_document_type([_Item("not_a_real_type", "x")])
