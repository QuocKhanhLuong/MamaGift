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


def _chunk(
    chunk_id: str,
    document_id: str,
    text: str,
    *,
    parse_run_id: str = "run_1",
    document_version: int | None = 1,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=None,
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
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


def test_search_returns_overlapping_chunk_first_with_exact_scores_and_ranking() -> None:
    hits = _index().search(
        "tuyển sinh năm học 2026",
        scope=EvidenceScope(family_id="fam_1", archive_scope=True),
    )
    assert len(hits) == 2
    assert hits[0] == LexicalHit(chunk_id="c1", score=1.0)
    assert hits[1] == LexicalHit(chunk_id="c2", score=0.6)
    assert hits[0].score == 1.0
    assert hits[1].score == 0.6
    assert hits[0].chunk_id == "c1"
    assert hits[1].chunk_id == "c2"


def test_search_tie_break_by_chunk_id_ascending() -> None:
    # Reverse input order to ensure chunk_id ascending tie-breaking determines output order
    chunks = [
        _chunk("c2", "doc_1", "Danh sách học sinh trong độ tuổi tuyển sinh"),
        _chunk("c1", "doc_1", "Kế hoạch tuyển sinh năm học 2026-2027"),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_1"),
        "c2": EvidenceScope(family_id="fam_1", document_id="doc_1"),
    }
    index = LexicalIndex(chunks, scopes)
    hits = index.search(
        "tuyển sinh",
        scope=EvidenceScope(family_id="fam_1", archive_scope=True),
    )
    assert hits == [
        LexicalHit(chunk_id="c1", score=1.0),
        LexicalHit(chunk_id="c2", score=1.0),
    ]


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
    assert hits == [LexicalHit(chunk_id="c3", score=1.0)]


def test_search_across_a_different_family_finds_nothing() -> None:
    hits = _index().search(
        "tuyển sinh", scope=EvidenceScope(family_id="fam_other", archive_scope=True)
    )
    assert hits == []


def test_search_is_deterministic_and_respects_top_k() -> None:
    scope = EvidenceScope(family_id="fam_1", archive_scope=True)
    hits_1 = _index().search("tuyển sinh năm học 2026", scope=scope, top_k=1)
    hits_2 = _index().search("tuyển sinh năm học 2026", scope=scope, top_k=1)
    assert len(hits_1) == 1
    assert hits_1 == [LexicalHit(chunk_id="c1", score=1.0)]
    assert hits_1 == hits_2


def test_empty_query_returns_no_hits() -> None:
    assert _index().search("", scope=EvidenceScope(family_id="fam_1", archive_scope=True)) == []
    assert (
        _index().search("   ---   ", scope=EvidenceScope(family_id="fam_1", archive_scope=True))
        == []
    )


def test_invalid_top_k_raises_value_error() -> None:
    scope = EvidenceScope(family_id="fam_1", archive_scope=True)
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        _index().search("tuyển sinh", scope=scope, top_k=0)
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        _index().search("tuyển sinh", scope=scope, top_k=-1)


def test_constructor_rejects_duplicate_chunk_ids() -> None:
    chunks = [
        _chunk("c1", "doc_1", "text 1"),
        _chunk("c1", "doc_1", "text 2"),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_1"),
    }
    with pytest.raises(ValueError, match="duplicate chunk_id 'c1'"):
        LexicalIndex(chunks, scopes)


def test_constructor_rejects_missing_chunk_scope() -> None:
    chunks = [
        _chunk("c1", "doc_1", "text 1"),
        _chunk("c2", "doc_1", "text 2"),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_1"),
    }
    with pytest.raises(ValueError, match="chunk 'c2' has no registered scope"):
        LexicalIndex(chunks, scopes)


def test_constructor_rejects_unknown_scope_id() -> None:
    chunks = [
        _chunk("c1", "doc_1", "text 1"),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_1"),
        "c_unknown": EvidenceScope(family_id="fam_1", document_id="doc_1"),
    }
    with pytest.raises(ValueError, match="unknown scope for chunk_id 'c_unknown'"):
        LexicalIndex(chunks, scopes)


def test_constructor_rejects_provenance_document_id_mismatch() -> None:
    chunks = [
        _chunk("c1", "doc_1", "text 1"),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_2"),
    }
    with pytest.raises(
        ValueError, match="document_id 'doc_1' does not match scope document_id 'doc_2'"
    ):
        LexicalIndex(chunks, scopes)


def test_constructor_rejects_provenance_document_version_mismatch() -> None:
    chunks = [
        _chunk("c1", "doc_1", "text 1", document_version=1),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_1", document_version=2),
    }
    with pytest.raises(
        ValueError, match="document_version 1 does not match scope document_version 2"
    ):
        LexicalIndex(chunks, scopes)


def test_constructor_rejects_provenance_parse_run_id_mismatch() -> None:
    chunks = [
        _chunk("c1", "doc_1", "text 1", parse_run_id="run_1"),
    ]
    scopes = {
        "c1": EvidenceScope(family_id="fam_1", document_id="doc_1", parse_run_id="run_2"),
    }
    with pytest.raises(
        ValueError, match="parse_run_id 'run_1' does not match scope parse_run_id 'run_2'"
    ):
        LexicalIndex(chunks, scopes)


def test_search_enforces_parse_run_isolation() -> None:
    index = _index()
    # c1 belongs to run_1; search scoped to run_2 must return nothing
    hits_wrong_run = index.search(
        "tuyển sinh",
        scope=EvidenceScope(family_id="fam_1", document_id="doc_1", parse_run_id="run_2"),
    )
    assert hits_wrong_run == []

    hits_wrong_run_archive = index.search(
        "tuyển sinh",
        scope=EvidenceScope(family_id="fam_1", archive_scope=True, parse_run_id="run_2"),
    )
    assert hits_wrong_run_archive == []

    # search scoped to matching run_1 returns hits
    hits_matching_run = index.search(
        "tuyển sinh",
        scope=EvidenceScope(family_id="fam_1", document_id="doc_1", parse_run_id="run_1"),
    )
    assert len(hits_matching_run) == 2
    assert hits_matching_run[0].chunk_id == "c1"


def test_search_enforces_version_isolation() -> None:
    index = _index()
    # c1 has document_version=1; search scoped to version 2 must return nothing
    hits_wrong_ver = index.search(
        "tuyển sinh",
        scope=EvidenceScope(family_id="fam_1", document_id="doc_1", document_version=2),
    )
    assert hits_wrong_ver == []

    hits_matching_ver = index.search(
        "tuyển sinh",
        scope=EvidenceScope(family_id="fam_1", document_id="doc_1", document_version=1),
    )
    assert len(hits_matching_ver) == 2
    assert hits_matching_ver[0].chunk_id == "c1"
