"""Tests for the Phase 3.5 structure-aware `Chunk` contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamagift_retrieval.chunk import Chunk, ChunkType, validate_chunk_tree

pytestmark = pytest.mark.unit


def _chunk(**overrides: object) -> Chunk:
    defaults: dict[str, object] = {
        "chunk_id": "chunk_doc1_run1_a",
        "parent_chunk_id": None,
        "document_id": "doc_1",
        "parse_run_id": "run_1",
        "document_version": 1,
        "document_type": "quyet_dinh",
        "document_number": "57/QĐ-UBND",
        "issuer": "ỦY BAN NHÂN DÂN XÃ MAI GIANG",
        "issued_date": "2026-03-03",
        "section_path": ["Điều 1"],
        "chunk_type": ChunkType.LEGAL_ARTICLE,
        "text": "Ban hành quy chế quản lý hồ sơ hành chính.",
        "source_block_ids": ["b_1_0001"],
        "source_page_numbers": [1],
        "metadata": {},
    }
    defaults.update(overrides)
    return Chunk(**defaults)  # type: ignore[arg-type]


def test_chunk_requires_at_least_one_source_block_id() -> None:
    with pytest.raises(ValidationError):
        _chunk(source_block_ids=[])


def test_chunk_requires_at_least_one_source_page_number() -> None:
    with pytest.raises(ValidationError):
        _chunk(source_page_numbers=[])


def test_chunk_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Chunk(**{**_chunk().model_dump(), "not_a_real_field": "x"})


def test_validate_chunk_tree_accepts_a_valid_parent_child_pair() -> None:
    parent = _chunk(chunk_id="chunk_doc1_run1_parent", parent_chunk_id=None)
    child = _chunk(chunk_id="chunk_doc1_run1_child", parent_chunk_id="chunk_doc1_run1_parent")
    validate_chunk_tree([parent, child])


def test_validate_chunk_tree_rejects_a_dangling_parent_reference() -> None:
    orphan = _chunk(chunk_id="chunk_doc1_run1_orphan", parent_chunk_id="chunk_doc1_run1_missing")
    with pytest.raises(ValueError, match="unknown parent"):
        validate_chunk_tree([orphan])


def test_validate_chunk_tree_rejects_duplicate_chunk_ids() -> None:
    one = _chunk(chunk_id="chunk_doc1_run1_dup")
    two = _chunk(chunk_id="chunk_doc1_run1_dup")
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        validate_chunk_tree([one, two])


def test_validate_chunk_tree_rejects_parent_from_a_different_document() -> None:
    parent = _chunk(chunk_id="chunk_docA_run1_parent", document_id="doc_A", parent_chunk_id=None)
    child = _chunk(
        chunk_id="chunk_docB_run1_child",
        document_id="doc_B",
        parent_chunk_id="chunk_docA_run1_parent",
    )
    with pytest.raises(ValueError, match="different document"):
        validate_chunk_tree([parent, child])


def test_validate_chunk_tree_rejects_parent_from_a_different_parse_run() -> None:
    parent = _chunk(chunk_id="chunk_doc1_runA_parent", parse_run_id="run_A", parent_chunk_id=None)
    child = _chunk(
        chunk_id="chunk_doc1_runB_child",
        parse_run_id="run_B",
        parent_chunk_id="chunk_doc1_runA_parent",
    )
    with pytest.raises(ValueError, match="different document"):
        validate_chunk_tree([parent, child])
