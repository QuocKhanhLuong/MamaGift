"""Tests for the naive lexical retrieval baseline seam.

This is not a claim of retrieval quality — it exists so a later hybrid/reranked
implementation has something naive and deterministic to compare against, and so the
scope-leak rule is enforced at the retrieval boundary, not only at chunk-build time.
"""

from __future__ import annotations

import pytest

from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.lexical import LexicalHit, LexicalIndex
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit


def _chunk(chunk_id: str, document_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=None,
        document_id=document_id,
        parse_run_id="run_1",
        document_version=1,
        document_type="quyet_dinh",
        document_number=None,
        issuer=None,
        issued_date=None,
        section_path=[],
        chunk_type=ChunkType.PARAGRAPH,
        text=text,
        source_block_ids=["b_1_0000"],
        source_page_numbers=[1],
        metadata={},
    )


def _index() -> LexicalIndex:
    chunks = [
        _chunk("c1", "doc_1", "Kế hoạch tuyển sinh năm học 2026-2027"),
        _chunk("c2", "doc_1", "Danh sách học sinh trong độ tuổi tuyển sinh"),
        _chunk("c3", "doc_2", "Quy chế quản lý hồ sơ hành chính"),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_1"),
        "c2": EvidenceScope(family_id="fam_1", document_id="doc_1"),
        "c3": EvidenceScope(family_id="fam_1", document_id="doc_2"),
    }
    return LexicalIndex(chunks, scopes)


def test_search_returns_overlapping_chunk_first() -> None:
    hits = _index().search("tuyển sinh", scope=EvidenceScope(family_id="fam_1", archive_scope=True))
    assert hits[0].chunk_id in {"c1", "c2"}
    assert isinstance(hits[0], LexicalHit)


def test_search_never_returns_a_chunk_outside_the_requested_document_scope() -> None:
    hits = _index().search(
        "quản lý hồ sơ",
        scope=EvidenceScope(family_id="fam_1", document_id="doc_1"),
    )
    assert hits == []


def test_search_within_correct_document_scope_finds_the_chunk() -> None:
    hits = _index().search(
        "quản lý hồ sơ",
        scope=EvidenceScope(family_id="fam_1", document_id="doc_2"),
    )
    assert [hit.chunk_id for hit in hits] == ["c3"]


def test_search_across_a_different_family_finds_nothing() -> None:
    hits = _index().search(
        "tuyển sinh", scope=EvidenceScope(family_id="fam_other", archive_scope=True)
    )
    assert hits == []


def test_search_is_deterministic_and_respects_top_k() -> None:
    scope = EvidenceScope(family_id="fam_1", archive_scope=True)
    hits_1 = _index().search("tuyển sinh", scope=scope, top_k=1)
    hits_2 = _index().search("tuyển sinh", scope=scope, top_k=1)
    assert len(hits_1) == 1
    assert hits_1 == hits_2


def test_empty_query_returns_no_hits() -> None:
    assert _index().search("", scope=EvidenceScope(family_id="fam_1", archive_scope=True)) == []
