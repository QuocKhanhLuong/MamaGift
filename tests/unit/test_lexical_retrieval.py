"""Unit tests for Phase 4 Vietnamese lexical (BM25) retrieval."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.index import IndexEntry, IndexStats
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_K1,
    BM25Index,
    BM25LexicalRetriever,
    BM25Params,
    LexicalRetriever,
    ScoredChunk,
    tokenize_vi,
)


def _make_chunk(
    chunk_id: str,
    doc_id: str = "doc_01",
    parse_run_id: str = "run_01",
    doc_version: int = 1,
    text: str = "Test chunk text",
    parent_chunk_id: str | None = None,
    section_path: list[str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=parent_chunk_id,
        document_id=doc_id,
        parse_run_id=parse_run_id,
        document_version=doc_version,
        section_path=section_path or ["Điều 1. Quy định chung"],
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text=text,
        source_block_ids=[f"block_{chunk_id}"],
        source_page_numbers=[1],
        metadata={},
    )


# ============================================================================
# 1. Exact document-number retrieval
# ============================================================================


def test_exact_document_number_retrieval() -> None:
    doc_id = "doc_test_num"
    run_id = "run_test_num"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    c1 = _make_chunk(
        "c_kh_12",
        doc_id,
        run_id,
        1,
        text=(
            "Kế hoạch số 12/KH-UBND ngày 31 tháng 03 năm 2026 về việc triển khai công tác giáo dục."
        ),
    )
    c2 = _make_chunk(
        "c_kh_15",
        doc_id,
        run_id,
        1,
        text="Kế hoạch số 15/KH-UBND ngày 15 tháng 04 năm 2026 về việc phòng chống thiên tai.",
    )
    c3 = _make_chunk(
        "c_nd_45",
        doc_id,
        run_id,
        1,
        text=(
            "Nghị định số 45/2026/NĐ-CP quy định chi tiết thi hành một số điều "
            "của Luật Tổ chức chính quyền."
        ),
    )
    c4 = _make_chunk(
        "c_bc_15",
        doc_id,
        run_id,
        1,
        text="Báo cáo số 15/BC-BGDĐT về tổng kết năm học 2025-2026 của Bộ Giáo dục và Đào tạo.",
    )
    c_fragment = _make_chunk(
        "c_fragment",
        doc_id,
        run_id,
        1,
        text="Công văn có mã 12 KH UBND nhưng không chứa số văn bản đầy đủ.",
    )

    index = BM25Index([c1, c2, c3, c4, c_fragment], scope=scope)

    # Query 1: "12/KH-UBND"
    hits_12 = index.search("12/KH-UBND", scope=scope, top_k=5)
    assert len(hits_12) >= 1
    assert hits_12[0].chunk.chunk_id == "c_kh_12"
    assert hits_12[0].rank == 1
    assert [hit.chunk.chunk_id for hit in hits_12] == ["c_kh_12"]
    assert hits_12[0].retriever == "lexical"

    # Query 2: "Số: 45/2026/NĐ-CP"
    hits_45 = index.search("Số: 45/2026/NĐ-CP", scope=scope, top_k=5)
    assert len(hits_45) >= 1
    assert hits_45[0].chunk.chunk_id == "c_nd_45"
    assert hits_45[0].rank == 1

    # Query 3: "15/BC-BGDĐT"
    hits_bc = index.search("15/BC-BGDĐT", scope=scope, top_k=5)
    assert len(hits_bc) >= 1
    assert hits_bc[0].chunk.chunk_id == "c_bc_15"
    assert hits_bc[0].rank == 1


# ============================================================================
# 2. Diacritic-sensitive query
# ============================================================================


def test_diacritic_sensitive_query() -> None:
    doc_id = "doc_diacritics"
    run_id = "run_diacritics"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    c_with_diacritics = _make_chunk(
        "c_with_dia",
        doc_id,
        run_id,
        1,
        text="UBND tỉnh yêu cầu thực hiện kế hoạch phân công nhiệm vụ cho các đơn vị.",
    )
    c_without_diacritics = _make_chunk(
        "c_no_dia",
        doc_id,
        run_id,
        1,
        text="UBND tinh yeu cau thuc hien ke hoach phan cong nhiem vu cho cac don vi.",
    )
    c_other = _make_chunk(
        "c_other",
        doc_id,
        run_id,
        1,
        text="Báo cáo tình hình kinh tế xã hội địa phương năm 2026.",
    )

    index = BM25Index([c_with_diacritics, c_without_diacritics, c_other], scope=scope)

    # Query with Vietnamese diacritics
    hits_dia = index.search("thực hiện kế hoạch", scope=scope, top_k=5)
    assert len(hits_dia) == 1
    assert hits_dia[0].chunk.chunk_id == "c_with_dia"
    assert hits_dia[0].rank == 1

    # Query without diacritics
    hits_no_dia = index.search("thuc hien ke hoach", scope=scope, top_k=5)
    assert len(hits_no_dia) == 1
    assert hits_no_dia[0].chunk.chunk_id == "c_no_dia"
    assert hits_no_dia[0].rank == 1


# ============================================================================
# 3. Legal-hierarchy marker query
# ============================================================================


def test_legal_hierarchy_marker_retrieval() -> None:
    doc_id = "doc_legal"
    run_id = "run_legal"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    c_d1 = _make_chunk(
        "c_d1",
        doc_id,
        run_id,
        1,
        text="Điều 1. Phạm vi điều chỉnh và đối tượng áp dụng của quyết định này.",
    )
    c_d2 = _make_chunk(
        "c_d2",
        doc_id,
        run_id,
        1,
        text="Điều 2. Nguyên tắc thực hiện. Khoản 1. Các cơ quan quản lý chịu trách nhiệm chính.",
    )
    c_d3 = _make_chunk(
        "c_d3",
        doc_id,
        run_id,
        1,
        text="Điều 3. Trách nhiệm thi hành. Khoản 2. Điểm a) Thực hiện chế độ báo cáo định kỳ.",
    )
    c_ch1 = _make_chunk(
        "c_ch1",
        doc_id,
        run_id,
        1,
        text="Chương I: Quy định chung về cơ cấu tổ chức.",
    )
    c_pl1 = _make_chunk(
        "c_pl1",
        doc_id,
        run_id,
        1,
        text="Phụ lục I: Danh mục biểu mẫu kèm theo.",
    )

    index = BM25Index([c_d1, c_d2, c_d3, c_ch1, c_pl1], scope=scope)

    # Query "Điều 1" -> c_d1 must be #1
    hits_d1 = index.search("Điều 1", scope=scope, top_k=5)
    assert len(hits_d1) >= 1
    assert hits_d1[0].chunk.chunk_id == "c_d1"
    assert hits_d1[0].rank == 1

    # Query "Khoản 2" -> c_d3 must be #1
    hits_k2 = index.search("Khoản 2", scope=scope, top_k=5)
    assert len(hits_k2) >= 1
    assert hits_k2[0].chunk.chunk_id == "c_d3"
    assert hits_k2[0].rank == 1

    # Query "Điểm a" -> c_d3 must be #1
    hits_da = index.search("Điểm a", scope=scope, top_k=5)
    assert len(hits_da) >= 1
    assert hits_da[0].chunk.chunk_id == "c_d3"
    assert hits_da[0].rank == 1

    # Query "Chương I" -> c_ch1 must be #1
    hits_ch1 = index.search("Chương I", scope=scope, top_k=5)
    assert len(hits_ch1) >= 1
    assert hits_ch1[0].chunk.chunk_id == "c_ch1"
    assert hits_ch1[0].rank == 1

    # Query "Phụ lục I" -> c_pl1 must be #1
    hits_pl1 = index.search("Phụ lục I", scope=scope, top_k=5)
    assert len(hits_pl1) >= 1
    assert hits_pl1[0].chunk.chunk_id == "c_pl1"
    assert hits_pl1[0].rank == 1


# ============================================================================
# 4. Deterministic ordering across repeated runs
# ============================================================================


def test_deterministic_ordering_across_repeated_runs() -> None:
    doc_id = "doc_determ"
    run_id = "run_determ"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    chunks = [
        _make_chunk(
            f"c_{i:02d}",
            doc_id,
            run_id,
            1,
            text=f"Điều {i}. Nội dung nhiệm vụ số {i} về quản lý ngân sách.",
        )
        for i in range(1, 15)
    ]
    index = BM25Index(chunks, scope=scope)

    baseline_results = index.search("nhiệm vụ quản lý ngân sách", scope=scope, top_k=10)
    baseline_ids = [hit.chunk.chunk_id for hit in baseline_results]
    baseline_scores = [hit.score for hit in baseline_results]
    baseline_ranks = [hit.rank for hit in baseline_results]

    for _ in range(50):
        repeated = index.search("nhiệm vụ quản lý ngân sách", scope=scope, top_k=10)
        assert [hit.chunk.chunk_id for hit in repeated] == baseline_ids
        assert [hit.score for hit in repeated] == baseline_scores
        assert [hit.rank for hit in repeated] == baseline_ranks


# ============================================================================
# 5. Explicit tie-break behaviour
# ============================================================================


def test_explicit_tie_break_behaviour() -> None:
    doc_id = "doc_tie"
    run_id = "run_tie"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    # Identical text produces identical BM25 scores
    c_gamma = _make_chunk("c_gamma", doc_id, run_id, 1, text="Quy định chung về tổ chức bộ máy")
    c_alpha = _make_chunk("c_alpha", doc_id, run_id, 1, text="Quy định chung về tổ chức bộ máy")
    c_beta = _make_chunk("c_beta", doc_id, run_id, 1, text="Quy định chung về tổ chức bộ máy")

    # Pass in unsorted order
    index = BM25Index([c_gamma, c_alpha, c_beta], scope=scope)
    hits = index.search("tổ chức bộ máy", scope=scope, top_k=10)

    assert len(hits) == 3
    # Scores must be equal
    assert math.isclose(hits[0].score, hits[1].score)
    assert math.isclose(hits[1].score, hits[2].score)

    # Ordering must be lexicographical by chunk_id: c_alpha, c_beta, c_gamma
    assert [hit.chunk.chunk_id for hit in hits] == ["c_alpha", "c_beta", "c_gamma"]
    assert [hit.rank for hit in hits] == [1, 2, 3]


# ============================================================================
# 6. Empty query and empty index
# ============================================================================


def test_empty_query_and_empty_index() -> None:
    doc_id = "doc_empty"
    run_id = "run_empty"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    c1 = _make_chunk("c1", doc_id, run_id, 1, text="Nội dung văn bản quy phạm.")
    index = BM25Index([c1], scope=scope)

    # Empty query strings
    assert index.search("", scope=scope, top_k=5) == []
    assert index.search("   \n\t  ", scope=scope, top_k=5) == []
    assert index.search("!@#$%^&*()", scope=scope, top_k=5) == []

    # Query with non-matching terms
    assert index.search("từ_khóa_hoàn_toàn_không_tồn_tại", scope=scope, top_k=5) == []

    # Empty index
    empty_index = BM25Index([], scope=scope)
    assert empty_index.search("quy phạm", scope=scope, top_k=5) == []
    assert empty_index.total_chunks == 0


# ============================================================================
# 7. Scope and version isolation
# ============================================================================


def test_scope_and_version_isolation() -> None:
    doc_a = "doc_a"
    doc_b = "doc_b"

    scope_a_r1 = EvidenceScope(
        family_id="fam_01", document_id=doc_a, parse_run_id="run_a1", document_version=1
    )
    scope_a_r2 = EvidenceScope(
        family_id="fam_01", document_id=doc_a, parse_run_id="run_a2", document_version=2
    )
    scope_b_r1 = EvidenceScope(
        family_id="fam_01", document_id=doc_b, parse_run_id="run_b1", document_version=1
    )

    c_a1 = _make_chunk(
        "ca1", doc_a, "run_a1", 1, text="Kế hoạch phát triển công nghệ tài chính doc A v1"
    )
    c_a2 = _make_chunk(
        "ca2", doc_a, "run_a2", 2, text="Kế hoạch phát triển công nghệ trí tuệ nhân tạo doc A v2"
    )
    c_b1 = _make_chunk(
        "cb1", doc_b, "run_b1", 1, text="Kế hoạch phát triển công nghệ thông tin doc B v1"
    )

    # Combined index with multiple chunks
    multi_index = BM25Index(
        [c_a1, c_a2, c_b1], scope=EvidenceScope(family_id="fam_01", archive_scope=True)
    )

    # Search scoped to doc_a, run_a1
    hits_a1 = multi_index.search("công nghệ", scope=scope_a_r1, top_k=10)
    assert len(hits_a1) == 1
    assert hits_a1[0].chunk.chunk_id == "ca1"
    assert hits_a1[0].chunk.document_id == doc_a
    assert hits_a1[0].chunk.parse_run_id == "run_a1"

    # Search scoped to doc_a, run_a2
    hits_a2 = multi_index.search("công nghệ", scope=scope_a_r2, top_k=10)
    assert len(hits_a2) == 1
    assert hits_a2[0].chunk.chunk_id == "ca2"
    assert hits_a2[0].chunk.document_id == doc_a
    assert hits_a2[0].chunk.parse_run_id == "run_a2"

    # Search scoped to doc_b, run_b1
    hits_b1 = multi_index.search("công nghệ", scope=scope_b_r1, top_k=10)
    assert len(hits_b1) == 1
    assert hits_b1[0].chunk.chunk_id == "cb1"
    assert hits_b1[0].chunk.document_id == doc_b
    assert hits_b1[0].chunk.parse_run_id == "run_b1"

    wrong_family = EvidenceScope(
        family_id="different-family",
        document_id=doc_a,
        parse_run_id="run_a1",
        document_version=1,
    )
    assert multi_index.search("công nghệ", scope=wrong_family, top_k=10) == []


def test_document_only_scope_is_rejected_before_retrieval() -> None:
    scope = EvidenceScope(
        family_id="fam_01",
        document_id="doc_unpinned",
        document_version=1,
        parse_run_id="run_01",
    )
    chunk = _make_chunk("c1", "doc_unpinned", "run_01", 1, text="nội dung")
    index = BM25Index([chunk], scope=scope)
    unpinned = EvidenceScope(family_id="fam_01", document_id="doc_unpinned")

    with pytest.raises(ValueError, match="scope must specify parse_run_id or document_version"):
        index.search("nội dung", scope=unpinned, top_k=5)

    retriever = BM25LexicalRetriever.from_chunks([chunk], scope=scope)
    with pytest.raises(ValueError, match="scope must specify parse_run_id or document_version"):
        retriever.search("nội dung", scope=unpinned, top_k=5)


# ============================================================================
# 8. Scope contradiction and validation errors
# ============================================================================


def test_scope_contradiction_in_index_init_raises() -> None:
    doc_id = "doc_contra"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id="run_01", document_version=1
    )

    c_wrong_doc = _make_chunk("c1", "other_doc", "run_01", 1)
    with pytest.raises(ValueError, match="contradicts scope document_id"):
        BM25Index([c_wrong_doc], scope=scope)

    c_wrong_run = _make_chunk("c2", doc_id, "other_run", 1)
    with pytest.raises(ValueError, match="contradicts scope parse_run_id"):
        BM25Index([c_wrong_run], scope=scope)

    c_wrong_ver = _make_chunk("c3", doc_id, "run_01", 2)
    with pytest.raises(ValueError, match="contradicts scope document_version"):
        BM25Index([c_wrong_ver], scope=scope)


def test_duplicate_chunk_id_raises() -> None:
    c1 = _make_chunk("c_dup", "doc_01", "run_01", 1)
    c2 = _make_chunk("c_dup", "doc_01", "run_01", 1)
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        BM25Index([c1, c2])


def test_invalid_arguments_raise() -> None:
    doc_id = "doc_args"
    scope = EvidenceScope(family_id="fam_01", document_id=doc_id, parse_run_id="run_01")
    scope_no_doc = EvidenceScope(family_id="fam_01", parse_run_id="run_01")

    c = _make_chunk("c1", doc_id, "run_01")
    index = BM25Index([c], scope=scope)

    # top_k <= 0
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        index.search("query", scope=scope, top_k=0)
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        index.search("query", scope=scope, top_k=-1)

    # scope missing document_id
    with pytest.raises(ValueError, match="scope must specify document_id"):
        index.search("query", scope=scope_no_doc, top_k=5)

    # Invalid BM25 parameters
    with pytest.raises(ValueError, match="k1 must be non-negative"):
        BM25Index([c], k1=-0.5)
    with pytest.raises(ValueError, match="b must be between 0.0 and 1.0"):
        BM25Index([c], b=1.5)
    with pytest.raises(ValueError, match="b must be between 0.0 and 1.0"):
        BM25Index([c], b=-0.1)


# ============================================================================
# 9. BM25 scoring mathematical verification & named constants
# ============================================================================


def test_bm25_constants_and_params() -> None:
    assert DEFAULT_BM25_K1 == 1.5
    assert DEFAULT_BM25_B == 0.75

    params = BM25Params()
    assert params.k1 == 1.5
    assert params.b == 0.75

    custom = BM25Params(k1=1.2, b=0.8)
    assert custom.k1 == 1.2
    assert custom.b == 0.8

    with pytest.raises(ValidationError):
        BM25Params(extra_field="invalid")  # extra forbid


def test_bm25_exact_score_calculation() -> None:
    doc_id = "doc_math"
    run_id = "run_math"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    # Document 1: "luật quy định" (2 tokens)
    # Document 2: "luật hướng dẫn thi hành" (4 tokens)
    c1 = _make_chunk("c1", doc_id, run_id, 1, text="luật quy định")
    c2 = _make_chunk("c2", doc_id, run_id, 1, text="luật hướng dẫn thi hành")

    index = BM25Index([c1, c2], scope=scope, k1=1.5, b=0.75)

    # N = 2
    # doc1 tokens: ['luật', 'quy', 'định'] (3 tokens)
    # doc2 tokens: ['luật', 'hướng', 'dẫn', 'thi', 'hành'] (5 tokens)
    # avgdl = (3 + 5) / 2 = 4.0
    # For query "luật":
    # df("luật") = 2
    # IDF("luật") = ln(1 + (2 - 2 + 0.5) / (2 + 0.5)) = ln(1 + 0.5 / 2.5) = ln(1.2) ≈ 0.1823215568
    # For c1: dl = 3, len_norm = 1 - 0.75 + 0.75 * (3 / 4.0) = 0.25 + 0.5625 = 0.8125
    # tf("luật", c1) = 1
    # tf_norm(c1) = 1 * (1.5 + 1.0) / (1 + 1.5 * 0.8125)
    #             = 2.5 / (1 + 1.21875) = 2.5 / 2.21875 ≈ 1.12676056
    # score(c1) = 0.1823215568 * 1.12676056 ≈ 0.205433

    # For c2: dl = 5, len_norm = 1 - 0.75 + 0.75 * (5 / 4.0) = 0.25 + 0.9375 = 1.1875
    # tf("luật", c2) = 1
    # tf_norm(c2) = 1 * 2.5 / (1 + 1.5 * 1.1875) = 2.5 / (1 + 1.78125) = 2.5 / 2.78125 ≈ 0.8988764
    # score(c2) = 0.1823215568 * 0.8988764 ≈ 0.163884

    hits = index.search("luật", scope=scope, top_k=5)
    assert len(hits) == 2
    assert hits[0].chunk.chunk_id == "c1"
    assert hits[1].chunk.chunk_id == "c2"

    expected_idf = math.log(1.0 + 0.5 / 2.5)
    expected_c1_score = expected_idf * (2.5 / (1.0 + 1.5 * (0.25 + 0.75 * (3.0 / 4.0))))
    expected_c2_score = expected_idf * (2.5 / (1.0 + 1.5 * (0.25 + 0.75 * (5.0 / 4.0))))

    assert math.isclose(hits[0].score, expected_c1_score, rel_tol=1e-5)
    assert math.isclose(hits[1].score, expected_c2_score, rel_tol=1e-5)


# ============================================================================
# 10. Date tokenization and retrieval
# ============================================================================


def test_date_tokenization_and_retrieval() -> None:
    doc_id = "doc_date"
    run_id = "run_date"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    c1 = _make_chunk(
        "c_d2026",
        doc_id,
        run_id,
        1,
        text="Hà Nội, ngày 31 tháng 03 năm 2026 ban hành quyết định số 01.",
    )
    c2 = _make_chunk(
        "c_d2025",
        doc_id,
        run_id,
        1,
        text="Hà Nội, ngày 15 tháng 08 năm 2025 ban hành quyết định số 02.",
    )

    index = BM25Index([c1, c2], scope=scope)

    hits_date = index.search("ngày 31 tháng 03 năm 2026", scope=scope, top_k=5)
    assert len(hits_date) >= 1
    assert hits_date[0].chunk.chunk_id == "c_d2026"
    assert hits_date[0].rank == 1

    hits_slash = index.search("31/03/2026", scope=scope, top_k=5)
    assert len(hits_slash) >= 1
    assert hits_slash[0].chunk.chunk_id == "c_d2026"
    assert hits_slash[0].rank == 1


# ============================================================================
# 11. BM25LexicalRetriever and DocumentIndex Pass-Through
# ============================================================================


def test_bm25_lexical_retriever_from_chunks_and_alias() -> None:
    doc_id = "doc_retriever"
    run_id = "run_retriever"
    scope = EvidenceScope(
        family_id="fam_01", document_id=doc_id, parse_run_id=run_id, document_version=1
    )

    c = _make_chunk("c1", doc_id, run_id, 1, text="Văn bản hướng dẫn thi hành luật")

    retriever = BM25LexicalRetriever.from_chunks([c], scope=scope)
    assert isinstance(retriever, LexicalRetriever)

    # Style 1: search(query, scope=scope)
    hits1 = retriever.search("hướng dẫn", scope=scope, top_k=5)
    assert len(hits1) == 1
    assert hits1[0].chunk.chunk_id == "c1"
    assert hits1[0].retriever == "lexical"


class FakeDocumentIndex:
    """Fake DocumentIndex to test pass-through behavior."""

    def __init__(self, returned_document_version: int | None = None) -> None:
        self.last_scope: EvidenceScope | None = None
        self.last_query: str | None = None
        self.last_top_k: int | None = None
        self.returned_document_version = returned_document_version

    def replace(self, scope: EvidenceScope, entries: list[IndexEntry]) -> IndexStats:
        return IndexStats(
            document_id=scope.document_id or "", parse_run_id=scope.parse_run_id or ""
        )

    def search_dense(
        self, scope: EvidenceScope, query_vector: list[float], top_k: int
    ) -> list[ScoredChunk]:
        return []

    def search_lexical(self, scope: EvidenceScope, query: str, top_k: int) -> list[ScoredChunk]:
        self.last_scope = scope
        self.last_query = query
        self.last_top_k = top_k
        c = _make_chunk(
            "c_passthrough",
            scope.document_id or "",
            scope.parse_run_id or "",
            self.returned_document_version or scope.document_version or 1,
            text="Pass-through text",
        )
        return [ScoredChunk(chunk=c, score=0.95, rank=1, retriever="lexical")]

    def drop(self, scope: EvidenceScope) -> int:
        return 0

    def stats(self, scope: EvidenceScope) -> IndexStats:
        return IndexStats(
            document_id=scope.document_id or "", parse_run_id=scope.parse_run_id or ""
        )


def test_document_index_scope_passthrough() -> None:
    fake_index = FakeDocumentIndex()
    retriever = BM25LexicalRetriever(fake_index)

    scope = EvidenceScope(
        family_id="fam_01", document_id="doc_pass", parse_run_id="run_pass", document_version=3
    )
    results = retriever.search("nhiệm vụ", scope=scope, top_k=7)

    assert fake_index.last_scope == scope
    assert fake_index.last_query == "nhiệm vụ"
    assert fake_index.last_top_k == 7
    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c_passthrough"
    assert results[0].rank == 1
    assert results[0].score == 0.95
    assert results[0].retriever == "lexical"
    assert results[0].chunk.document_id == scope.document_id
    assert results[0].chunk.document_version == scope.document_version
    assert results[0].chunk.parse_run_id == scope.parse_run_id


def test_document_index_rejects_returned_provenance_mismatch() -> None:
    fake_index = FakeDocumentIndex(returned_document_version=2)
    retriever = BM25LexicalRetriever(fake_index)
    scope = EvidenceScope(
        family_id="fam_01", document_id="doc_pass", parse_run_id="run_pass", document_version=3
    )

    with pytest.raises(ValueError, match="violates requested EvidenceScope"):
        retriever.search("nhiệm vụ", scope=scope, top_k=7)


# ============================================================================
# 12. Tokenizer and Text Normalization Tests
# ============================================================================


def test_vi_tokenization_details() -> None:
    assert tokenize_vi("") == []
    assert tokenize_vi("   ") == []

    # Diacritics
    tokens_dia = tokenize_vi("Ủy ban Nhân dân Thành phố Hà Nội")
    assert "ủy" in tokens_dia
    assert "ban" in tokens_dia
    assert "nhân" in tokens_dia
    assert "dân" in tokens_dia
    assert "thành" in tokens_dia
    assert "phố" in tokens_dia
    assert "hà" in tokens_dia
    assert "nội" in tokens_dia

    # Document numbers
    tokens_doc = tokenize_vi("Công văn số 123/QĐ-UBND/2026 ngày ban hành")
    assert "123/qđ-ubnd/2026" in tokens_doc
    assert "123" not in tokens_doc
    assert "qđ" not in tokens_doc
    assert "ubnd" not in tokens_doc
    assert "2026" not in tokens_doc

    # Legal markers
    tokens_legal = tokenize_vi("Điều 12a và Khoản 3 Điểm b Chương IV Mục 2 Phụ lục II")
    assert "điều_12a" in tokens_legal
    assert "khoản_3" in tokens_legal
    assert "điểm_b" in tokens_legal
    assert "chương_iv" in tokens_legal
    assert "mục_2" in tokens_legal
    assert "phụ_lục_ii" in tokens_legal


# ============================================================================
# 13. ScoredChunk Contract
# ============================================================================


def test_scored_chunk_contract() -> None:
    c = _make_chunk("c_sc", "doc_sc", "run_sc", 1)
    sc = ScoredChunk(chunk=c, score=1.234, rank=1, retriever="lexical")
    assert sc.chunk.chunk_id == "c_sc"
    assert sc.score == 1.234
    assert sc.rank == 1
    assert sc.retriever == "lexical"

    with pytest.raises(ValidationError):
        ScoredChunk(chunk=c, score=1.0, rank=0, retriever="lexical")  # rank must be ge=1

    with pytest.raises(ValidationError):
        ScoredChunk(chunk=c, score=1.0, rank=1, retriever="invalid")  # invalid retriever
