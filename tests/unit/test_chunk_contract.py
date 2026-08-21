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


def test_chunk_type_complete_enum_members() -> None:
    expected = {
        "LEGAL_CHAPTER": "legal_chapter",
        "LEGAL_SECTION": "legal_section",
        "LEGAL_ARTICLE": "legal_article",
        "LEGAL_CLAUSE": "legal_clause",
        "LEGAL_POINT": "legal_point",
        "APPENDIX": "appendix",
        "PLAN_SECTION": "plan_section",
        "PLAN_TASK": "plan_task",
        "PARAGRAPH": "paragraph",
    }
    assert {member.name: member.value for member in ChunkType} == expected


def test_chunk_requires_source_block_ids_omitted() -> None:
    data = _chunk().model_dump()
    del data["source_block_ids"]
    with pytest.raises(ValidationError):
        Chunk(**data)


def test_chunk_requires_source_block_ids_non_empty() -> None:
    with pytest.raises(ValidationError):
        _chunk(source_block_ids=[])


def test_chunk_requires_source_page_numbers_omitted() -> None:
    data = _chunk().model_dump()
    del data["source_page_numbers"]
    with pytest.raises(ValidationError):
        Chunk(**data)


def test_chunk_requires_source_page_numbers_non_empty() -> None:
    with pytest.raises(ValidationError):
        _chunk(source_page_numbers=[])


def test_chunk_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Chunk(**{**_chunk().model_dump(), "not_a_real_field": "x"})


def test_validate_chunk_tree_accepts_valid_hierarchy() -> None:
    root = _chunk(chunk_id="chunk_root", parent_chunk_id=None)
    child1 = _chunk(chunk_id="chunk_child1", parent_chunk_id="chunk_root")
    grandchild = _chunk(chunk_id="chunk_grandchild", parent_chunk_id="chunk_child1")
    child2 = _chunk(chunk_id="chunk_child2", parent_chunk_id="chunk_root")
    validate_chunk_tree([root, child1, grandchild, child2])


def test_validate_chunk_tree_rejects_duplicate_chunk_ids() -> None:
    one = _chunk(chunk_id="chunk_doc1_run1_dup")
    two = _chunk(chunk_id="chunk_doc1_run1_dup")
    with pytest.raises(ValueError, match="duplicate chunk_id 'chunk_doc1_run1_dup'"):
        validate_chunk_tree([one, two])


def test_validate_chunk_tree_rejects_unknown_parent() -> None:
    orphan = _chunk(chunk_id="chunk_doc1_run1_orphan", parent_chunk_id="chunk_doc1_run1_missing")
    with pytest.raises(
        ValueError,
        match="chunk 'chunk_doc1_run1_orphan' references unknown parent 'chunk_doc1_run1_missing'",
    ):
        validate_chunk_tree([orphan])


def test_validate_chunk_tree_rejects_cross_document_parent() -> None:
    parent = _chunk(chunk_id="chunk_docA_run1_parent", document_id="doc_A", parent_chunk_id=None)
    child = _chunk(
        chunk_id="chunk_docB_run1_child",
        document_id="doc_B",
        parent_chunk_id="chunk_docA_run1_parent",
    )
    with pytest.raises(ValueError, match="different document: 'doc_A' != 'doc_B'"):
        validate_chunk_tree([parent, child])


def test_validate_chunk_tree_rejects_cross_parse_run_parent() -> None:
    parent = _chunk(chunk_id="chunk_doc1_runA_parent", parse_run_id="run_A", parent_chunk_id=None)
    child = _chunk(
        chunk_id="chunk_doc1_runB_child",
        parse_run_id="run_B",
        parent_chunk_id="chunk_doc1_runA_parent",
    )
    with pytest.raises(ValueError, match="different parse run: 'run_A' != 'run_B'"):
        validate_chunk_tree([parent, child])


def test_validate_chunk_tree_rejects_cross_version_parent() -> None:
    parent = _chunk(
        chunk_id="chunk_doc1_run1_v1_parent",
        document_version=1,
        parent_chunk_id=None,
    )
    child = _chunk(
        chunk_id="chunk_doc1_run1_v2_child",
        document_version=2,
        parent_chunk_id="chunk_doc1_run1_v1_parent",
    )
    with pytest.raises(ValueError, match="different document version: 1 != 2"):
        validate_chunk_tree([parent, child])


def test_validate_chunk_tree_rejects_self_parent() -> None:
    self_loop = _chunk(
        chunk_id="chunk_doc1_run1_self",
        parent_chunk_id="chunk_doc1_run1_self",
    )
    with pytest.raises(
        ValueError,
        match="chunk 'chunk_doc1_run1_self' cannot be its own parent",
    ):
        validate_chunk_tree([self_loop])


def test_validate_chunk_tree_rejects_cycle() -> None:
    chunk_a = _chunk(chunk_id="chunk_a", parent_chunk_id="chunk_c")
    chunk_b = _chunk(chunk_id="chunk_b", parent_chunk_id="chunk_a")
    chunk_c = _chunk(chunk_id="chunk_c", parent_chunk_id="chunk_b")
    with pytest.raises(ValueError, match="cycle detected in chunk tree involving chunk 'chunk_a'"):
        validate_chunk_tree([chunk_a, chunk_b, chunk_c])
