"""Tests for deterministic relation extraction and persistence.

Guards:
1. Each cue class extracts the right relation_type with the right target number.
2. Precedence: a block containing multiple cues (e.g. 'căn cứ' and 'thay thế') for the same
   target emits ONE relation with the highest precedence
   (supersedes > replaces > amends > references).
3. Anti-invention gate: a cue with no document number nearby emits NOTHING.
4. Distance limit: a document number beyond the window (120 chars) is not attached.
5. Verbatim provenance: target_raw_text is a true substring of the source block text.
6. Provenance: source_block_ids and page_numbers are non-empty and accurate.
7. Self-reference guard: references to the document's own number are dropped.
8. Deduplication: identical (relation_type, target_document_number) across blocks are merged.
9. Persistence: review_state defaults to 'unverified'; re-running is idempotent.
10. Target resolution: exactly 1 match sets target_document_id; 0 or >1 matches leave it None.
11. Archive isolation: NO documents row is ever created to satisfy a relation.
12. Atomic replace: re-persisting removes old relations for that parse run.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Document, DocumentRelation, ParseRun
from app.relation_extraction import persist_relations
from mamagift_docpipe import (
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    ExtractedField,
    Extractor,
    ParserRun,
    QualityReport,
)
from mamagift_docpipe.relations import (
    RELATION_WINDOW_CHARS,
    ExtractedRelation,
    extract_relations,
    normalize_identifier,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixture helpers for CanonicalDocument and database sessions
# ---------------------------------------------------------------------------


def _make_block(
    block_id: str,
    page_number: int,
    text_content: str,
    reading_order: int = 0,
) -> CanonicalBlock:
    return CanonicalBlock(
        id=block_id,
        type=BlockType.PARAGRAPH,
        text=text_content,
        reading_order=reading_order,
        provenance=BlockProvenance(page_number=page_number),
    )


def _make_document(
    blocks: list[CanonicalBlock],
    *,
    document_id: str = "doc_test_1",
    parse_run_id: str = "prun_test_1",
    own_document_number: str | None = None,
) -> CanonicalDocument:
    pages_dict: dict[int, list[CanonicalBlock]] = {}
    for block in blocks:
        pages_dict.setdefault(block.provenance.page_number, []).append(block)

    pages: list[CanonicalPage] = []
    for p_num, page_blocks in sorted(pages_dict.items()):
        reordered_blocks = [
            b.model_copy(update={"reading_order": idx}) for idx, b in enumerate(page_blocks)
        ]
        pages.append(
            CanonicalPage(
                page_number=p_num,
                width=595.0,
                height=842.0,
                blocks=reordered_blocks,
            )
        )
    if not pages:
        pages = [CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=[])]

    extracted_fields: list[ExtractedField] = []
    if own_document_number:
        extracted_fields.append(
            ExtractedField(
                id="field_doc_num",
                name="document_number",
                raw_value=own_document_number,
                normalized_value=normalize_identifier(own_document_number),
                extractor=Extractor(name="test", version="1.0"),
            )
        )

    return CanonicalDocument(
        document_id=document_id,
        parser_run=ParserRun(
            id=parse_run_id,
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="hash123",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=pages,
        extracted_fields=extracted_fields,
        quality_report=QualityReport(route="born_digital", route_confidence=1.0),
    )


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False, future=True)


@pytest.fixture
def db_session(session_factory) -> Session:
    with session_factory() as session:
        yield session


def _seed_db_doc(
    session: Session,
    doc_id: str,
    doc_number: str | None = None,
) -> Document:
    now = datetime.now(UTC)
    doc = Document(
        id=doc_id,
        filename=f"{doc_id}.pdf",
        content_type="application/pdf",
        byte_size=1024,
        checksum_sha256=f"hash_{doc_id}",
        storage_uri=f"local://{doc_id}",
        document_number=doc_number,
        created_at=now,
        updated_at=now,
    )
    session.add(doc)
    session.flush()
    return doc


def _seed_db_parse_run(
    session: Session,
    run_id: str,
    doc_id: str,
    canonical_doc: CanonicalDocument,
    version: int = 1,
) -> ParseRun:
    now = datetime.now(UTC)
    prun = ParseRun(
        id=run_id,
        document_id=doc_id,
        version=version,
        is_current=True,
        parser_name="pymupdf",
        parser_version="1.0",
        configuration_hash="hash123",
        strategy_decided=True,
        degraded=False,
        route="born_digital",
        schema_version="1.0",
        canonical=canonical_doc.model_dump(mode="json"),
        inspection={},
        quality_report={},
        started_at=now,
        finished_at=now,
        created_at=now,
    )
    session.add(prun)
    session.flush()
    return prun


# ---------------------------------------------------------------------------
# 1. Cue classes extraction and confidence verification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cue_phrase", "expected_type", "expected_conf"),
    [
        ("thay thế", "supersedes", 0.9),
        ("thay thế cho", "supersedes", 0.9),
        ("bãi bỏ", "replaces", 0.9),
        ("hủy bỏ", "replaces", 0.9),
        ("chấm dứt hiệu lực", "replaces", 0.9),
        ("sửa đổi", "amends", 0.9),
        ("bổ sung", "amends", 0.9),
        ("sửa đổi, bổ sung", "amends", 0.9),
        ("căn cứ", "references", 0.6),
        ("theo", "references", 0.6),
        ("quy định tại", "references", 0.6),
        ("tại", "references", 0.6),
    ],
)
def test_each_cue_class_extracts_right_relation_type_and_confidence(
    cue_phrase: str,
    expected_type: str,
    expected_conf: float,
) -> None:
    text_content = f"{cue_phrase} Quyết định số 57/QĐ-UBND ngày 03/03/2026 của UBND xã Mai Giang."
    block = _make_block("b_1_0001", 1, text_content)
    doc = _make_document([block])

    relations = extract_relations(doc)
    assert len(relations) == 1
    rel = relations[0]
    assert rel.relation_type == expected_type
    assert rel.target_document_number == "57/QĐ-UBND"
    assert rel.confidence == pytest.approx(expected_conf)
    assert rel.source_block_ids == ["b_1_0001"]
    assert rel.page_numbers == [1]


# ---------------------------------------------------------------------------
# 2. Precedence rules
# ---------------------------------------------------------------------------


def test_precedence_supersedes_over_references_for_same_target() -> None:
    """Block containing 'căn cứ' and 'thay thế' for same target emits ONE supersedes relation."""
    text_content = (
        "Căn cứ Quyết định số 57/QĐ-UBND ngày 01/01/2025; "
        "đồng thời thay thế Quyết định số 57/QĐ-UBND kể từ ngày ký."
    )
    block = _make_block("b_1_0001", 1, text_content)
    doc = _make_document([block])

    relations = extract_relations(doc)
    assert len(relations) == 1
    assert relations[0].relation_type == "supersedes"
    assert relations[0].target_document_number == "57/QĐ-UBND"
    assert relations[0].confidence == pytest.approx(0.9)


def test_precedence_full_hierarchy() -> None:
    """Assert hierarchy: supersedes > replaces > amends > references."""
    # replaces vs amends
    text_replaces_amends = (
        "bổ sung Nghị định số 45/2026/NĐ-CP và bãi bỏ Nghị định số 45/2026/NĐ-CP."
    )
    doc1 = _make_document([_make_block("b1", 1, text_replaces_amends)])
    rel1 = extract_relations(doc1)
    assert len(rel1) == 1
    assert rel1[0].relation_type == "replaces"

    # amends vs references
    text_amends_ref = "Căn cứ Thông tư số 19/2026/TT-BGDĐT, sửa đổi Thông tư số 19/2026/TT-BGDĐT."
    doc2 = _make_document([_make_block("b2", 1, text_amends_ref)])
    rel2 = extract_relations(doc2)
    assert len(rel2) == 1
    assert rel2[0].relation_type == "amends"


def test_distinct_targets_in_same_block_preserve_respective_types() -> None:
    """Two different targets in the same block each get their own relation."""
    text_content = "Căn cứ Thông tư số 19/2026/TT-BGDĐT; thay thế Quyết định số 57/QĐ-UBND."
    block = _make_block("b_1_0001", 1, text_content)
    doc = _make_document([block])

    relations = extract_relations(doc)
    assert len(relations) == 2
    types_by_target = {r.target_document_number: r.relation_type for r in relations}
    assert types_by_target["19/2026/TT-BGDĐT"] == "references"
    assert types_by_target["57/QĐ-UBND"] == "supersedes"


# ---------------------------------------------------------------------------
# 3. Anti-invention gate (cue with no target nearby emits nothing)
# ---------------------------------------------------------------------------


def test_anti_invention_gate_cue_with_no_document_number_emits_nothing() -> None:
    """A cue with no document number nearby yields NOTHING — never guess a target."""
    prose_texts = [
        "Căn cứ quy định của pháp luật hiện hành và tình hình thực tế địa phương.",
        "Theo hướng dẫn của cấp trên về công tác tuyển sinh.",
        "Quy định tại các văn bản hướng dẫn có liên quan.",
        "Thay thế các quy định trước đây trái với quyết định này.",
        "Bãi bỏ toàn bộ các điều khoản không còn phù hợp.",
    ]
    blocks = [
        _make_block(f"b_{i}", 1, text_line, reading_order=i)
        for i, text_line in enumerate(prose_texts)
    ]
    doc = _make_document(blocks)

    relations = extract_relations(doc)
    assert relations == []


# ---------------------------------------------------------------------------
# 4. Window boundary test
# ---------------------------------------------------------------------------


def test_document_number_beyond_window_is_not_attached() -> None:
    """A document number beyond the window is not attached to the cue."""
    # Distance = 150 chars (> RELATION_WINDOW_CHARS=120)
    padding = "a" * (RELATION_WINDOW_CHARS + 30)
    text_content = f"Căn cứ {padding} 57/QĐ-UBND"
    block = _make_block("b_1_0001", 1, text_content)
    doc = _make_document([block])

    relations = extract_relations(doc)
    assert relations == []


def test_document_number_within_window_is_attached() -> None:
    """A document number within the window is attached to the cue."""
    # Distance = 50 chars (<= RELATION_WINDOW_CHARS=120)
    padding = " quy định chi tiết tại điều khoản liên quan số "
    assert len(padding) <= RELATION_WINDOW_CHARS
    text_content = f"Căn cứ{padding}57/QĐ-UBND"
    block = _make_block("b_1_0001", 1, text_content)
    doc = _make_document([block])

    relations = extract_relations(doc)
    assert len(relations) == 1
    assert relations[0].target_document_number == "57/QĐ-UBND"


# ---------------------------------------------------------------------------
# 5. Verbatim target_raw_text assertion
# ---------------------------------------------------------------------------


def test_target_raw_text_is_verbatim_substring_of_block_text() -> None:
    """target_raw_text is a verbatim substring of the source block text."""
    block_texts = [
        "Căn cứ Quyết định số 57/QĐ-UBND ngày 03/03/2026 của UBND xã Mai Giang;",
        "thay thế cho Kế hoạch số 12/KH-UBND ngày 01/01/2026;",
        "sửa đổi, bổ sung Thông tư số 19/2026/TT-BGDĐT ban hành năm 2026.",
    ]
    blocks = [
        _make_block(f"b_{i}", 1, text_content, reading_order=i)
        for i, text_content in enumerate(block_texts)
    ]
    doc = _make_document(blocks)

    relations = extract_relations(doc)
    assert len(relations) == 3

    for rel in relations:
        assert rel.target_raw_text
        found = any(rel.target_raw_text in b.text for b in blocks)
        assert found, f"target_raw_text {rel.target_raw_text!r} not in any block text"


# ---------------------------------------------------------------------------
# 6. Provenance (source_block_ids and page_numbers non-empty)
# ---------------------------------------------------------------------------


def test_source_block_ids_and_page_numbers_are_correct_and_non_empty() -> None:
    """source_block_ids and page_numbers are correct and non-empty for every relation."""
    b1 = _make_block("b_1_0001", 1, "Căn cứ Quyết định số 57/QĐ-UBND")
    b2 = _make_block("b_2_0005", 2, "Theo Thông tư số 19/2026/TT-BGDĐT")
    doc = _make_document([b1, b2])

    relations = extract_relations(doc)
    assert len(relations) == 2

    rel_57 = next(r for r in relations if r.target_document_number == "57/QĐ-UBND")
    assert rel_57.source_block_ids == ["b_1_0001"]
    assert rel_57.page_numbers == [1]

    rel_19 = next(r for r in relations if r.target_document_number == "19/2026/TT-BGDĐT")
    assert rel_19.source_block_ids == ["b_2_0005"]
    assert rel_19.page_numbers == [2]


# ---------------------------------------------------------------------------
# 7. Self-reference guard
# ---------------------------------------------------------------------------


def test_self_reference_guard_drops_own_document_number() -> None:
    """A relation whose target number equals the document's OWN document number is DROPPED."""
    # Document's own number is 12/KH-UBND
    block_self = _make_block("b1", 1, "Căn cứ Kế hoạch số 12/KH-UBND ngày 01/01/2026;")
    block_other = _make_block("b2", 1, "Căn cứ Quyết định số 57/QĐ-UBND ngày 03/03/2026;")
    doc = _make_document([block_self, block_other], own_document_number="12/KH-UBND")

    relations = extract_relations(doc)
    assert len(relations) == 1
    assert relations[0].target_document_number == "57/QĐ-UBND"


# ---------------------------------------------------------------------------
# 8. Deduplication merges block IDs and pages
# ---------------------------------------------------------------------------


def test_deduplication_merges_block_ids_and_pages() -> None:
    """Deduplicate identical (relation_type, target_num) pairs, merging block IDs and pages."""
    b1 = _make_block("b_1_0001", 1, "Căn cứ Quyết định số 57/QĐ-UBND")
    b2 = _make_block("b_1_0004", 1, "Theo Quyết định số 57/QĐ-UBND")
    b3 = _make_block("b_2_0010", 2, "Quy định tại Quyết định số 57/QĐ-UBND")
    doc = _make_document([b1, b2, b3])

    relations = extract_relations(doc)
    assert len(relations) == 1
    rel = relations[0]
    assert rel.relation_type == "references"
    assert rel.target_document_number == "57/QĐ-UBND"
    assert rel.source_block_ids == ["b_1_0001", "b_1_0004", "b_2_0010"]
    assert rel.page_numbers == [1, 2]


# ---------------------------------------------------------------------------
# 9. Persistence: default review_state and idempotency
# ---------------------------------------------------------------------------


def test_persistence_review_state_and_idempotency(db_session: Session) -> None:
    """Persistence: rows land with review_state='unverified'; re-running is idempotent."""
    b1 = _make_block("b1", 1, "Căn cứ Quyết định số 57/QĐ-UBND")
    canonical_doc = _make_document([b1], document_id="doc_src_1", parse_run_id="prun_src_1")

    _seed_db_doc(db_session, "doc_src_1", doc_number="10/KH")
    prun = _seed_db_parse_run(db_session, "prun_src_1", "doc_src_1", canonical_doc)

    # First run
    rows1 = persist_relations(db_session, prun)
    assert len(rows1) == 1
    assert rows1[0].review_state == "unverified"
    assert rows1[0].source_parse_run_id == "prun_src_1"
    assert rows1[0].source_document_id == "doc_src_1"

    # Second run: same data -> must NOT fail with IntegrityError, must return identical rows
    rows2 = persist_relations(db_session, prun)
    assert len(rows2) == 1
    assert rows2[0].id == rows1[0].id

    total_rows = db_session.scalars(select(DocumentRelation)).all()
    assert len(total_rows) == 1


# ---------------------------------------------------------------------------
# 10. Target resolution: one match, zero matches, two matches
# ---------------------------------------------------------------------------


def test_target_resolution_cases(db_session: Session) -> None:
    """Target resolution:
    - exactly ONE match: sets target_document_id
    - ZERO matches: target_document_id=None, number kept
    - TWO matches: target_document_id=None, number kept (ambiguity not guessed)
    """
    # 1. Target matching ONE document (57/QĐ-UBND -> doc_match_1)
    _seed_db_doc(db_session, "doc_match_1", doc_number="57/QĐ-UBND")

    # 2. Target matching TWO documents (ambiguous: 99/TB-VP -> doc_dup_1, doc_dup_2)
    _seed_db_doc(db_session, "doc_dup_1", doc_number="99/TB-VP")
    _seed_db_doc(db_session, "doc_dup_2", doc_number=" 99 / TB - VP ")

    # Source document + parse run
    b1 = _make_block("b1", 1, "Căn cứ Quyết định số 57/QĐ-UBND")
    b2 = _make_block("b2", 1, "Theo Văn bản số 123/KH-UNKNOWN")
    b3 = _make_block("b3", 1, "Căn cứ Thông báo số 99/TB-VP")
    canonical_doc = _make_document([b1, b2, b3], document_id="doc_src", parse_run_id="prun_src")

    _seed_db_doc(db_session, "doc_src", doc_number="01/CV")
    prun = _seed_db_parse_run(db_session, "prun_src", "doc_src", canonical_doc)

    rows = persist_relations(db_session, prun)
    assert len(rows) == 3

    # One match
    rel_57 = next(r for r in rows if r.target_document_number == "57/QĐ-UBND")
    assert rel_57.target_document_id == "doc_match_1"

    # Zero matches
    rel_unknown = next(r for r in rows if r.target_document_number == "123/KH-UNKNOWN")
    assert rel_unknown.target_document_id is None
    assert rel_unknown.target_document_number == "123/KH-UNKNOWN"

    # Two matches (ambiguity unresolved)
    rel_dup = next(r for r in rows if r.target_document_number == "99/TB-VP")
    assert rel_dup.target_document_id is None
    assert rel_dup.target_document_number == "99/TB-VP"


# ---------------------------------------------------------------------------
# 11. No documents row is ever created
# ---------------------------------------------------------------------------


def test_no_documents_row_is_ever_created(db_session: Session) -> None:
    """NEVER inserts into documents when persisting a relation to an unknown target."""
    _seed_db_doc(db_session, "doc_src", doc_number="01/CV")

    b = _make_block("b1", 1, "thay thế Quyết định số 999/QĐ-UNKNOWN")
    canonical_doc = _make_document([b], document_id="doc_src", parse_run_id="prun_src")
    prun = _seed_db_parse_run(db_session, "prun_src", "doc_src", canonical_doc)

    count_before = db_session.scalar(text("SELECT count(*) FROM documents"))
    assert count_before == 1

    persisted = persist_relations(db_session, prun)
    assert len(persisted) == 1
    assert persisted[0].target_document_id is None

    count_after = db_session.scalar(text("SELECT count(*) FROM documents"))
    assert count_after == count_before == 1


# ---------------------------------------------------------------------------
# 12. Re-persisting removes old relations for that parse run
# ---------------------------------------------------------------------------


def test_repersisting_after_canonical_changes_removes_old_relations(db_session: Session) -> None:
    """Re-persisting after the canonical changes removes the old relations for that parse run."""
    _seed_db_doc(db_session, "doc_src", doc_number="01/CV")

    # Initial version has 2 relations
    b1 = _make_block("b1", 1, "Căn cứ Quyết định số 57/QĐ-UBND")
    b2 = _make_block("b2", 1, "Theo Thông tư số 19/2026/TT-BGDĐT")
    canonical_v1 = _make_document([b1, b2], document_id="doc_src", parse_run_id="prun_src")
    prun = _seed_db_parse_run(db_session, "prun_src", "doc_src", canonical_v1)

    persisted_v1 = persist_relations(db_session, prun)
    assert len(persisted_v1) == 2

    # Updated canonical with only 1 different relation
    b_new = _make_block("b_new", 1, "thay thế Nghị định số 45/2026/NĐ-CP")
    canonical_v2 = _make_document([b_new], document_id="doc_src", parse_run_id="prun_src")
    prun.canonical = canonical_v2.model_dump(mode="json")
    db_session.flush()

    persisted_v2 = persist_relations(db_session, prun)
    assert len(persisted_v2) == 1
    assert persisted_v2[0].relation_type == "supersedes"
    assert persisted_v2[0].target_document_number == "45/2026/NĐ-CP"

    # Verify DB has only 1 relation total for this parse run
    current_relations = db_session.scalars(
        select(DocumentRelation).where(DocumentRelation.source_parse_run_id == "prun_src")
    ).all()
    assert len(current_relations) == 1
    assert current_relations[0].target_document_number == "45/2026/NĐ-CP"


# ---------------------------------------------------------------------------
# Extra: Explicit relations argument in persist_relations
# ---------------------------------------------------------------------------


def test_persist_relations_with_explicit_relations_argument(db_session: Session) -> None:
    """When explicit relations sequence is passed to persist_relations, it is stored."""
    _seed_db_doc(db_session, "doc_src", doc_number="01/CV")
    canonical_empty = _make_document([], document_id="doc_src", parse_run_id="prun_src")
    prun = _seed_db_parse_run(db_session, "prun_src", "doc_src", canonical_empty)

    explicit_rel = ExtractedRelation(
        relation_type="amends",
        target_document_number="57/QĐ-UBND",
        target_raw_text="sửa đổi Quyết định số 57/QĐ-UBND",
        source_block_ids=["b_manual"],
        page_numbers=[1],
        confidence=0.9,
    )

    rows = persist_relations(db_session, prun, relations=[explicit_rel])
    assert len(rows) == 1
    assert rows[0].relation_type == "amends"
    assert rows[0].source_block_ids == ["b_manual"]
