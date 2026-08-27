"""Unit tests for multi-document archive evidence assembler (Task D3)."""

from __future__ import annotations

import pytest

from mamagift_retrieval.archive.constants import (
    ARCHIVE_EVIDENCE_BUDGET_CHARS,
    ARCHIVE_MAX_DOCUMENTS,
    ARCHIVE_PER_DOCUMENT_CHAR_CAP,
)
from mamagift_retrieval.budget import EvidenceBudget, assemble_bounded_context
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.evidence.archive_assembler import (
    assemble_archive_evidence,
    group_evidence_by_document,
)
from mamagift_retrieval.evidence.assembler import Evidence, EvidenceSet
from mamagift_retrieval.index.entries import ScoredChunk
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit


def _archive_scope(**overrides: object) -> EvidenceScope:
    values: dict[str, object] = {
        "family_id": "mamagift",
        "archive_scope": True,
        "document_id": None,
        "document_version": None,
        "parse_run_id": None,
    }
    values.update(overrides)
    return EvidenceScope.model_validate(values)


def _candidate(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "doc-1",
    document_version: int | None = 1,
    parse_run_id: str = "parse-1",
    pages: list[int] | None = None,
    blocks: list[str] | None = None,
    section: list[str] | None = None,
) -> ScoredChunk:
    chunk = Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        section_path=section or ["Phần I", "Điều 1"],
        chunk_type=ChunkType.PARAGRAPH,
        text=text,
        source_block_ids=blocks or [f"block-{chunk_id}"],
        source_page_numbers=pages or [1],
    )
    return ScoredChunk(chunk=chunk, score=1.0, rank=1, retriever="reranked")


def _budget(archive_semantic: int = ARCHIVE_EVIDENCE_BUDGET_CHARS) -> EvidenceBudget:
    return EvidenceBudget(
        selected_document_chars=0,
        conversation_short_term_chars=0,
        user_long_term_memory_chars=0,
        episodic_memory_chars=0,
        archive_semantic_chars=archive_semantic,
    )


def test_multi_document_citation_order_and_provenance() -> None:
    """1. Multi-document input produces dense c1..cN citations and preserves all provenance."""
    candidates = [
        _candidate(
            "chunk-1",
            "Nội dung văn bản 1",
            document_id="doc-1",
            document_version=1,
            parse_run_id="run-1",
            pages=[1, 2],
            blocks=["b1", "b2"],
            section=["Chương I"],
        ),
        _candidate(
            "chunk-2",
            "Nội dung văn bản 2",
            document_id="doc-2",
            document_version=3,
            parse_run_id="run-2",
            pages=[5],
            blocks=["b5"],
            section=["Chương II", "Điều 3"],
        ),
        _candidate(
            "chunk-3",
            "Nội dung thêm của văn bản 1",
            document_id="doc-1",
            document_version=1,
            parse_run_id="run-1",
            pages=[3],
            blocks=["b3"],
            section=["Chương I", "Điều 2"],
        ),
    ]

    result = assemble_archive_evidence(
        candidates,
        scope=_archive_scope(),
        budget=_budget(),
        query_id="query-42",
    )

    assert result.query_id == "query-42"
    assert result.scope == _archive_scope()
    assert [item.citation_id for item in result.evidence] == ["c1", "c2", "c3"]

    item1, item2, item3 = result.evidence
    assert item1.document_id == "doc-1"
    assert item1.document_version == 1
    assert item1.parse_run_id == "run-1"
    assert item1.page_numbers == [1, 2]
    assert item1.source_block_ids == ["b1", "b2"]
    assert item1.section_path == ["Chương I"]
    assert item1.text == "Nội dung văn bản 1"

    assert item2.document_id == "doc-2"
    assert item2.document_version == 3
    assert item2.parse_run_id == "run-2"
    assert item2.page_numbers == [5]
    assert item2.source_block_ids == ["b5"]
    assert item2.section_path == ["Chương II", "Điều 3"]
    assert item2.text == "Nội dung văn bản 2"

    assert item3.document_id == "doc-1"
    assert item3.document_version == 1
    assert item3.parse_run_id == "run-1"
    assert item3.page_numbers == [3]
    assert item3.source_block_ids == ["b3"]
    assert item3.section_path == ["Chương I", "Điều 2"]
    assert item3.text == "Nội dung thêm của văn bản 1"


@pytest.mark.parametrize(
    "override_field,override_val,match_error",
    [
        ("archive_scope", False, "archive index requires an archive scope"),
        ("document_id", "doc-pinned", "archive scope must not pin document_id"),
        ("parse_run_id", "run-pinned", "archive scope must not pin parse_run_id"),
        ("document_version", 2, "archive scope must not pin document_version"),
        ("family_id", "wrong-family", "not authoritative"),
    ],
)
def test_validate_archive_scope_is_enforced(
    override_field: str, override_val: object, match_error: str
) -> None:
    """2. validate_archive_scope rejects non-archive or pinned scopes."""
    scope = _archive_scope(**{override_field: override_val})
    candidates = [_candidate("chunk-1", "Text", document_id="doc-1")]

    with pytest.raises(ValueError, match=match_error):
        assemble_archive_evidence(
            candidates,
            scope=scope,
            budget=_budget(),
            query_id="query-1",
        )


def test_duplicate_chunk_id_is_rejected() -> None:
    """3. Duplicate chunk_id raises ValueError."""
    candidates = [
        _candidate("chunk-dup", "Text A", document_id="doc-1"),
        _candidate("chunk-dup", "Text B", document_id="doc-2"),
    ]
    with pytest.raises(ValueError, match="duplicate evidence chunk_id 'chunk-dup'"):
        assemble_archive_evidence(
            candidates,
            scope=_archive_scope(),
            budget=_budget(),
            query_id="query-1",
        )


def test_candidate_outside_allowed_documents_raises() -> None:
    """4. A candidate outside allowed_documents raises naming the chunk."""
    candidates = [
        _candidate("chunk-ok", "Text OK", document_id="doc-1"),
        _candidate("chunk-bad", "Text Bad", document_id="doc-unauthorized"),
    ]
    with pytest.raises(
        ValueError, match="candidate chunk 'chunk-bad' document_id 'doc-unauthorized'"
    ):
        assemble_archive_evidence(
            candidates,
            scope=_archive_scope(),
            budget=_budget(),
            query_id="query-1",
            allowed_documents={"doc-1", "doc-2"},
        )


def test_per_document_cap_drops_greedy_candidate_without_fragmentation() -> None:
    """5. Per-document cap limits greedy document chunks and preserves other documents intact."""
    long_chunk_text = "A" * 2000
    doc1_chunks = [
        _candidate(f"chunk-doc1-{i}", long_chunk_text, document_id="doc-1") for i in range(1, 6)
    ]
    doc2_chunk = _candidate("chunk-doc2-1", "B" * 2000, document_id="doc-2")

    candidates = [*doc1_chunks, doc2_chunk]

    result = assemble_archive_evidence(
        candidates,
        scope=_archive_scope(),
        budget=_budget(archive_semantic=20_000),
        query_id="query-cap",
        per_document_char_cap=3000,
    )

    # doc-1 chunk 1 (2000 chars) -> running 2000. Admitted.
    # doc-1 chunk 2 (2000 chars) -> running 4000. Admitted.
    # doc-1 chunks 3, 4, 5 -> running 4000 >= 3000 cap -> DROPPED entirely.
    # doc-2 chunk 1 (2000 chars) -> running 2000. Admitted.
    assert len(result.evidence) == 3
    assert [item.citation_id for item in result.evidence] == ["c1", "c2", "c3"]
    assert [item.chunk_id for item in result.evidence] == [
        "chunk-doc1-1",
        "chunk-doc1-2",
        "chunk-doc2-1",
    ]

    # Assert no admitted Evidence text is a mid-chunk fragment of a dropped candidate
    for item in result.evidence:
        assert len(item.text) == 2000
        if item.document_id == "doc-1":
            assert item.text == "A" * 2000
        else:
            assert item.document_id == "doc-2"
            assert item.text == "B" * 2000


def test_max_documents_cap_enforced() -> None:
    """6. 12 documents, max_documents=3 -> exactly 3 distinct document_ids appear."""
    candidates = [
        _candidate(f"chunk-{i}", f"Text from doc {i}", document_id=f"doc-{i}") for i in range(1, 13)
    ]

    result = assemble_archive_evidence(
        candidates,
        scope=_archive_scope(),
        budget=_budget(),
        query_id="query-docs-cap",
        max_documents=3,
    )

    distinct_doc_ids = {item.document_id for item in result.evidence}
    assert len(distinct_doc_ids) == 3
    assert distinct_doc_ids == {"doc-1", "doc-2", "doc-3"}
    assert len(result.evidence) == 3
    assert [item.citation_id for item in result.evidence] == ["c1", "c2", "c3"]


def test_budget_breakdown_uses_archive_semantic_category() -> None:
    """7. Used characters recorded under archive_semantic, selected_document used_chars is 0."""
    candidates = [
        _candidate("chunk-1", "Nội dung tài liệu 1", document_id="doc-1"),
        _candidate("chunk-2", "Nội dung tài liệu 2", document_id="doc-2"),
    ]
    total_offered = len("Nội dung tài liệu 1") + len("Nội dung tài liệu 2")

    result = assemble_archive_evidence(
        candidates,
        scope=_archive_scope(),
        budget=_budget(archive_semantic=10_000),
        query_id="query-budget",
    )

    archive_usage = next(c for c in result.budget.categories if c.category == "archive_semantic")
    selected_usage = next(c for c in result.budget.categories if c.category == "selected_document")

    assert archive_usage.offered_chars == total_offered
    assert archive_usage.used_chars == total_offered
    assert archive_usage.truncated is False

    assert selected_usage.offered_chars == 0
    assert selected_usage.used_chars == 0
    assert selected_usage.truncated is False
    assert result.budget.total_used_chars() == total_offered


def test_budget_truncation_is_visible() -> None:
    """8. Tiny archive_semantic_chars budget shows truncated=True and bounds assembled text."""
    candidates = [
        _candidate("chunk-1", "0123456789", document_id="doc-1"),
        _candidate("chunk-2", "abcdefghij", document_id="doc-2"),
    ]

    result = assemble_archive_evidence(
        candidates,
        scope=_archive_scope(),
        budget=_budget(archive_semantic=14),
        query_id="query-trunc",
    )

    archive_usage = next(c for c in result.budget.categories if c.category == "archive_semantic")
    assert archive_usage.offered_chars == 20
    assert archive_usage.used_chars == 14
    assert archive_usage.truncated is True

    # First chunk gets full 10 chars, second chunk gets remaining 4 chars
    assert result.evidence[0].text == "0123456789"
    assert result.evidence[1].text == "abcd"
    assert sum(len(item.text) for item in result.evidence) == 14


def test_empty_candidate_list_returns_empty_evidence_set() -> None:
    """9. Empty candidate list returns an EvidenceSet with evidence == [] without raising."""
    result = assemble_archive_evidence(
        [],
        scope=_archive_scope(),
        budget=_budget(),
        query_id="query-empty",
    )

    assert result.evidence == []
    assert result.scope == _archive_scope()
    assert result.query_id == "query-empty"

    archive_usage = next(c for c in result.budget.categories if c.category == "archive_semantic")
    assert archive_usage.offered_chars == 0
    assert archive_usage.used_chars == 0
    assert archive_usage.truncated is False


def test_group_evidence_by_document_ordering_and_keys() -> None:
    """10. group_evidence_by_document returns documents in first-appearance order."""
    candidates = [
        _candidate("c-docA-1", "A1", document_id="doc-A"),
        _candidate("c-docB-1", "B1", document_id="doc-B"),
        _candidate("c-docA-2", "A2", document_id="doc-A"),
        _candidate("c-docC-1", "C1", document_id="doc-C"),
    ]

    result = assemble_archive_evidence(
        candidates,
        scope=_archive_scope(),
        budget=_budget(),
        query_id="query-group",
    )

    grouped = group_evidence_by_document(result)

    assert list(grouped.keys()) == ["doc-A", "doc-B", "doc-C"]
    assert [e.citation_id for e in grouped["doc-A"]] == ["c1", "c3"]
    assert [e.citation_id for e in grouped["doc-B"]] == ["c2"]
    assert [e.citation_id for e in grouped["doc-C"]] == ["c4"]

    # Single-document input yields one key
    single_doc_candidates = [
        _candidate("c-single-1", "S1", document_id="doc-single"),
        _candidate("c-single-2", "S2", document_id="doc-single"),
    ]
    single_result = assemble_archive_evidence(
        single_doc_candidates,
        scope=_archive_scope(),
        budget=_budget(),
        query_id="query-single",
    )
    single_grouped = group_evidence_by_document(single_result)
    assert list(single_grouped.keys()) == ["doc-single"]
    assert len(single_grouped["doc-single"]) == 2


@pytest.mark.parametrize(
    "max_docs,char_cap",
    [
        (0, 3000),
        (-1, 3000),
        (8, 0),
        (8, -10),
    ],
)
def test_invalid_max_documents_and_char_cap_raise_value_error(max_docs: int, char_cap: int) -> None:
    """11. max_documents <= 0 and per_document_char_cap <= 0 raise ValueError."""
    candidates = [_candidate("chunk-1", "Text", document_id="doc-1")]
    with pytest.raises(ValueError, match="(max_documents|per_document_char_cap) must be positive"):
        assemble_archive_evidence(
            candidates,
            scope=_archive_scope(),
            budget=_budget(),
            query_id="query-err",
            max_documents=max_docs,
            per_document_char_cap=char_cap,
        )


def test_unversioned_candidate_chunk_raises() -> None:
    """Candidate with document_version=None raises naming the chunk."""
    candidates = [_candidate("chunk-no-ver", "Text", document_version=None)]
    with pytest.raises(
        ValueError, match="candidate chunk 'chunk-no-ver' has no document_version provenance"
    ):
        assemble_archive_evidence(
            candidates,
            scope=_archive_scope(),
            budget=_budget(),
            query_id="query-no-ver",
        )


def test_candidate_violating_evidence_scope_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Candidate failing scope_matches raises naming the chunk."""
    import mamagift_retrieval.evidence.archive_assembler as assembler_mod

    candidates = [_candidate("chunk-bad-scope", "Text", document_id="doc-1")]
    monkeypatch.setattr(assembler_mod, "scope_matches", lambda cand, allowed: False)

    with pytest.raises(
        ValueError, match="candidate chunk 'chunk-bad-scope' violates requested EvidenceScope"
    ):
        assemble_archive_evidence(
            candidates,
            scope=_archive_scope(),
            budget=_budget(),
            query_id="query-bad-scope",
        )


def test_group_evidence_by_document_empty_document_id_raises() -> None:
    """group_evidence_by_document raises ValueError if an Evidence item has empty document_id."""
    _, breakdown = assemble_bounded_context(_budget(), {})
    evidence_item = Evidence(
        citation_id="c1",
        chunk_id="chunk-1",
        document_id="   ",
        parse_run_id="run-1",
        document_version=1,
        page_numbers=[1],
        source_block_ids=["b1"],
        section_path=["S1"],
        text="text",
    )
    evidence_set = EvidenceSet(
        scope=_archive_scope(),
        evidence=[evidence_item],
        budget=breakdown,
        query_id="query-1",
    )

    with pytest.raises(ValueError, match="has empty document_id"):
        group_evidence_by_document(evidence_set)


def test_frozen_defaults_are_actually_wired() -> None:
    """The frozen constants must be the defaults, not merely available to callers.

    Every other cap test passes its limits explicitly, so none of them would notice if the
    signature silently defaulted to something permissive. This one calls with no caps at all
    and relies on the module constants taking effect.
    """
    # ARCHIVE_MAX_DOCUMENTS documents' worth of candidates, plus two more that must be dropped.
    candidates = [
        _candidate(f"chunk-{i}", "x" * 10, document_id=f"doc-{i}")
        for i in range(ARCHIVE_MAX_DOCUMENTS + 2)
    ]
    result = assemble_archive_evidence(
        candidates,
        scope=_archive_scope(),
        budget=_budget(archive_semantic=100_000),
        query_id="query-defaults",
    )
    assert len({item.document_id for item in result.evidence}) == ARCHIVE_MAX_DOCUMENTS

    # One document offering more than ARCHIVE_PER_DOCUMENT_CHAR_CAP characters is capped.
    chunk_chars = 1_000
    greedy = [
        _candidate(f"greedy-{i}", "y" * chunk_chars, document_id="doc-greedy")
        for i in range(ARCHIVE_PER_DOCUMENT_CHAR_CAP // chunk_chars + 3)
    ]
    capped = assemble_archive_evidence(
        greedy,
        scope=_archive_scope(),
        budget=_budget(archive_semantic=100_000),
        query_id="query-defaults-cap",
    )
    assert len(capped.evidence) < len(greedy)
    admitted_chars = sum(len(item.text) for item in capped.evidence)
    assert admitted_chars <= ARCHIVE_PER_DOCUMENT_CHAR_CAP + chunk_chars
