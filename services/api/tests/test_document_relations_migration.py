"""Tests for Alembic migration 0006_phase5_document_relations and DocumentRelation model.

Verifies:
1. `upgrade head` creates `document_relations` with all expected columns, types, and constraints.
2. A valid relation row inserts and reads back, with `review_state` defaulting to 'unverified'.
3. A relation with BOTH target_document_id and target_document_number NULL is rejected (CHECK).
4. A relation naming a target not held in the archive is accepted with target_document_number
   and target_document_id=NULL without fabricating a documents row.
5. Confidence range constraint (0.0 <= confidence <= 1.0) is enforced.
6. Duplicate identity (same source_parse_run_id + relation_type + target) is rejected (UNIQUE).
7. Deleting the source document CASCADES the relation away.
8. Deleting TARGET doc sets target_document_id to NULL and preserves relation row (SET NULL).
9. Composite FK rejects mismatched (parse_run_id, document_id, version) provenance.
10. `downgrade base` from head succeeds and drops the table.
11. ORM mapping and StrEnums (RelationType, RelationReviewState) function correctly.
12. Deleting the source parse run CASCADES the relation away.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.models import (
    Document,
    DocumentRelation,
    ParseRun,
    RelationReviewState,
    RelationType,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = str(REPO_ROOT / "services" / "api" / "alembic.ini")


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = os.environ.get("MAMAGIFT_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


@pytest.fixture
def upgraded(database_url: str) -> Iterator[Engine]:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def _insert_document(
    connection: Any,
    doc_id: str = "doc_1",
    filename: str = "a.pdf",
    checksum: str | None = None,
    doc_number: str | None = None,
) -> None:
    now = datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO documents (id, filename, content_type, byte_size, "
            "checksum_sha256, storage_uri, status, document_number, requires_user_review, "
            "created_at, updated_at) VALUES "
            "(:id, :filename, 'application/pdf', 10, :checksum, :uri, "
            "'UPLOADED', :doc_number, :flag, :now, :now)"
        ),
        {
            "id": doc_id,
            "filename": filename,
            "checksum": checksum or f"sha_{doc_id}",
            "uri": f"local://{doc_id}",
            "doc_number": doc_number,
            "flag": False,
            "now": now,
        },
    )


def _insert_parse_run(
    connection: Any,
    run_id: str = "prun_1",
    doc_id: str = "doc_1",
    version: int = 1,
) -> None:
    now = datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO parse_runs (id, document_id, version, is_current, parser_name, "
            "parser_version, configuration_hash, strategy_decided, degraded, route, "
            "schema_version, canonical, inspection, quality_report, started_at, finished_at, "
            "created_at) VALUES (:id, :doc_id, :version, :flag, 'pymupdf', '1.0', 'hash', :flag, "
            ":flag, 'born_digital', '1.0', '{}', '{}', '{}', :now, :now, :now)"
        ),
        {"id": run_id, "doc_id": doc_id, "version": version, "now": now, "flag": False},
    )


def _insert_relation(
    connection: Any,
    relation_id: str = "rel_1",
    source_doc_id: str = "doc_1",
    source_prun_id: str = "prun_1",
    source_version: int = 1,
    source_blocks: list[str] | None = None,
    page_numbers: list[int] | None = None,
    relation_type: str = "references",
    target_doc_id: str | None = None,
    target_doc_number: str | None = "12/KH-UBND",
    target_raw_text: str = "Căn cứ Kế hoạch số 12/KH-UBND",
    confidence: float = 0.95,
    review_state: str | None = None,
) -> None:
    now = datetime.now(UTC)
    blocks_json = json.dumps(source_blocks if source_blocks is not None else ["b1"])
    pages_json = json.dumps(page_numbers if page_numbers is not None else [1])

    if review_state is not None:
        connection.execute(
            text(
                "INSERT INTO document_relations (id, source_document_id, source_parse_run_id, "
                "source_document_version, source_block_ids, page_numbers, relation_type, "
                "target_document_id, target_document_number, target_raw_text, confidence, "
                "review_state, created_at) VALUES "
                "(:id, :src_doc, :src_prun, :src_ver, :blocks, :pages, :rel_type, "
                ":tgt_doc, :tgt_num, :raw_text, :conf, :rev_state, :now)"
            ),
            {
                "id": relation_id,
                "src_doc": source_doc_id,
                "src_prun": source_prun_id,
                "src_ver": source_version,
                "blocks": blocks_json,
                "pages": pages_json,
                "rel_type": relation_type,
                "tgt_doc": target_doc_id,
                "tgt_num": target_doc_number,
                "raw_text": target_raw_text,
                "conf": confidence,
                "rev_state": review_state,
                "now": now,
            },
        )
    else:
        connection.execute(
            text(
                "INSERT INTO document_relations (id, source_document_id, source_parse_run_id, "
                "source_document_version, source_block_ids, page_numbers, relation_type, "
                "target_document_id, target_document_number, target_raw_text, confidence, "
                "created_at) VALUES "
                "(:id, :src_doc, :src_prun, :src_ver, :blocks, :pages, :rel_type, "
                ":tgt_doc, :tgt_num, :raw_text, :conf, :now)"
            ),
            {
                "id": relation_id,
                "src_doc": source_doc_id,
                "src_prun": source_prun_id,
                "src_ver": source_version,
                "blocks": blocks_json,
                "pages": pages_json,
                "rel_type": relation_type,
                "tgt_doc": target_doc_id,
                "tgt_num": target_doc_number,
                "raw_text": target_raw_text,
                "conf": confidence,
                "now": now,
            },
        )


def test_document_relations_columns_match_the_persistence_contract(upgraded: Engine) -> None:
    """Case 1: upgrade head creates document_relations with every expected column."""
    inspector = inspect(upgraded)
    assert "document_relations" in inspector.get_table_names()

    columns = {column["name"]: column for column in inspector.get_columns("document_relations")}

    expected_not_null = {
        "id",
        "source_document_id",
        "source_parse_run_id",
        "source_document_version",
        "source_block_ids",
        "page_numbers",
        "relation_type",
        "target_raw_text",
        "confidence",
        "review_state",
        "created_at",
    }
    expected_nullable = {
        "target_document_id",
        "target_document_number",
    }

    assert (expected_not_null | expected_nullable) <= set(columns.keys())

    for col_name in expected_not_null:
        assert columns[col_name]["nullable"] is False, f"Column {col_name} should be NOT NULL"

    for col_name in expected_nullable:
        assert columns[col_name]["nullable"] is True, f"Column {col_name} should be nullable"

    # Primary key check
    pk_constraint = inspector.get_pk_constraint("document_relations")
    assert pk_constraint["constrained_columns"] == ["id"]

    # Foreign keys check
    fks = inspector.get_foreign_keys("document_relations")

    # Source document FK (CASCADE)
    src_doc_fks = [
        fk
        for fk in fks
        if fk["referred_table"] == "documents"
        and fk["constrained_columns"] == ["source_document_id"]
        and fk["referred_columns"] == ["id"]
    ]
    assert len(src_doc_fks) == 1
    assert src_doc_fks[0].get("options", {}).get("ondelete") == "CASCADE"

    # Target document FK (SET NULL)
    tgt_doc_fks = [
        fk
        for fk in fks
        if fk["referred_table"] == "documents"
        and fk["constrained_columns"] == ["target_document_id"]
        and fk["referred_columns"] == ["id"]
    ]
    assert len(tgt_doc_fks) == 1
    assert tgt_doc_fks[0].get("options", {}).get("ondelete") == "SET NULL"

    # Provenance composite FK (CASCADE)
    prun_fks = [
        fk
        for fk in fks
        if fk["referred_table"] == "parse_runs"
        and fk["constrained_columns"]
        == ["source_parse_run_id", "source_document_id", "source_document_version"]
        and fk["referred_columns"] == ["id", "document_id", "version"]
    ]
    assert len(prun_fks) == 1
    assert prun_fks[0].get("options", {}).get("ondelete") == "CASCADE"

    # Indexes check
    indexes = inspector.get_indexes("document_relations")
    src_idx = [idx for idx in indexes if idx["column_names"] == ["source_document_id"]]
    assert len(src_idx) >= 1
    tgt_idx = [idx for idx in indexes if idx["column_names"] == ["target_document_id"]]
    assert len(tgt_idx) >= 1

    # Unique constraint check
    unique_constraints = inspector.get_unique_constraints("document_relations")
    unique_cols = [uc["column_names"] for uc in unique_constraints]
    unique_index_cols = [idx["column_names"] for idx in indexes if idx.get("unique")]
    all_unique = unique_cols + unique_index_cols
    assert [
        "source_parse_run_id",
        "relation_type",
        "target_document_number",
        "target_document_id",
    ] in all_unique


def test_document_relations_valid_insert_and_default_review_state(upgraded: Engine) -> None:
    """Case 2: A valid relation row inserts and reads back, defaulting review_state."""
    with upgraded.begin() as conn:
        _insert_document(conn, doc_id="doc_1", filename="a.pdf")
        _insert_parse_run(conn, run_id="prun_1", doc_id="doc_1", version=1)
        _insert_relation(
            conn,
            relation_id="rel_1",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            source_blocks=["b1", "b2"],
            page_numbers=[1, 2],
            relation_type="references",
            target_doc_id=None,
            target_doc_number="12/KH-UBND",
            target_raw_text="Căn cứ Kế hoạch 12/KH-UBND",
            confidence=0.9,
            review_state=None,  # Do not supply -> should default to 'unverified'
        )

    with upgraded.connect() as conn:
        row = (
            conn.execute(text("SELECT * FROM document_relations WHERE id = 'rel_1'"))
            .mappings()
            .one()
        )

    assert row["id"] == "rel_1"
    assert row["source_document_id"] == "doc_1"
    assert row["source_parse_run_id"] == "prun_1"
    assert row["source_document_version"] == 1
    blocks = (
        json.loads(row["source_block_ids"])
        if isinstance(row["source_block_ids"], str)
        else row["source_block_ids"]
    )
    assert blocks == ["b1", "b2"]
    pages = (
        json.loads(row["page_numbers"])
        if isinstance(row["page_numbers"], str)
        else row["page_numbers"]
    )
    assert pages == [1, 2]
    assert row["relation_type"] == "references"
    assert row["target_document_id"] is None
    assert row["target_document_number"] == "12/KH-UBND"
    assert row["target_raw_text"] == "Căn cứ Kế hoạch 12/KH-UBND"
    assert row["confidence"] == pytest.approx(0.9)
    assert row["review_state"] == "unverified"
    assert row["created_at"] is not None


def test_document_relations_both_targets_null_rejected(upgraded: Engine) -> None:
    """Case 3: Relation with BOTH target_document_id and target_document_number NULL is rejected."""
    with upgraded.begin() as conn:
        _insert_document(conn, doc_id="doc_1", filename="a.pdf")
        _insert_parse_run(conn, run_id="prun_1", doc_id="doc_1", version=1)

    # Both NULL -> MUST RAISE IntegrityError (ck_document_relations_target_present)
    with pytest.raises(IntegrityError):
        with upgraded.begin() as conn:
            _insert_relation(
                conn,
                relation_id="rel_invalid_both_null",
                source_doc_id="doc_1",
                source_prun_id="prun_1",
                source_version=1,
                target_doc_id=None,
                target_doc_number=None,
            )

    # target_document_number present only -> ACCEPTED
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_num_only",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            target_doc_id=None,
            target_doc_number="12/KH-UBND",
        )

    # target_document_id present only -> ACCEPTED
    with upgraded.begin() as conn:
        _insert_document(conn, doc_id="doc_2", filename="b.pdf")
        _insert_relation(
            conn,
            relation_id="rel_id_only",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            target_doc_id="doc_2",
            target_doc_number=None,
        )

    # Both present -> ACCEPTED
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_both_present",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            target_doc_id="doc_2",
            target_doc_number="12/KH-UBND",
        )


def test_document_relations_external_target_accepted_without_documents_row(
    upgraded: Engine,
) -> None:
    """Case 4: Target not in archive accepted without fabricating a documents row."""
    with upgraded.begin() as conn:
        _insert_document(conn, doc_id="doc_1", filename="source.pdf")
        _insert_parse_run(conn, run_id="prun_1", doc_id="doc_1", version=1)

    with upgraded.connect() as conn:
        count_before = conn.execute(text("SELECT count(*) FROM documents")).scalar()
    assert count_before == 1

    # Insert relation referencing a document not in the archive
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_external_target",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            target_doc_id=None,
            target_doc_number="99/2026/TT-BGDDT",
            target_raw_text="Theo Thông tư số 99/2026/TT-BGDĐT",
            confidence=0.98,
        )

    with upgraded.connect() as conn:
        count_after = conn.execute(text("SELECT count(*) FROM documents")).scalar()
        rel_row = (
            conn.execute(text("SELECT * FROM document_relations WHERE id = 'rel_external_target'"))
            .mappings()
            .one()
        )

    # Documents table was NOT mutated with a fake/fabricated row
    assert count_after == count_before == 1
    assert rel_row["target_document_id"] is None
    assert rel_row["target_document_number"] == "99/2026/TT-BGDDT"
    assert rel_row["target_raw_text"] == "Theo Thông tư số 99/2026/TT-BGDĐT"


def test_document_relations_confidence_range_enforced(upgraded: Engine) -> None:
    """Case 5: confidence > 1.0 and confidence < 0.0 are rejected; 0.0 and 1.0 are accepted."""
    with upgraded.begin() as conn:
        _insert_document(conn, doc_id="doc_1", filename="a.pdf")
        _insert_parse_run(conn, run_id="prun_1", doc_id="doc_1", version=1)

    # confidence = 1.5 -> rejected
    with pytest.raises(IntegrityError):
        with upgraded.begin() as conn:
            _insert_relation(
                conn,
                relation_id="rel_conf_high",
                source_doc_id="doc_1",
                source_prun_id="prun_1",
                source_version=1,
                confidence=1.5,
            )

    # confidence = -0.1 -> rejected
    with pytest.raises(IntegrityError):
        with upgraded.begin() as conn:
            _insert_relation(
                conn,
                relation_id="rel_conf_low",
                source_doc_id="doc_1",
                source_prun_id="prun_1",
                source_version=1,
                confidence=-0.1,
            )

    # confidence = 0.0 -> accepted
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_conf_zero",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            confidence=0.0,
            target_doc_number="10/QD",
        )

    # confidence = 1.0 -> accepted
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_conf_one",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            confidence=1.0,
            target_doc_number="11/QD",
        )

    # confidence = 0.5 -> accepted
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_conf_half",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            confidence=0.5,
            target_doc_number="12/QD",
        )

    with upgraded.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, confidence FROM document_relations WHERE id IN "
                "('rel_conf_zero', 'rel_conf_one', 'rel_conf_half') ORDER BY id ASC"
            )
        ).fetchall()
    assert len(rows) == 3


def test_document_relations_duplicate_identity_rejected(upgraded: Engine) -> None:
    """Case 6: Duplicate identity is rejected by UNIQUE constraint."""
    with upgraded.begin() as conn:
        _insert_document(conn, doc_id="doc_1", filename="a.pdf")
        _insert_document(conn, doc_id="doc_2", filename="b.pdf")
        _insert_parse_run(conn, run_id="prun_1", doc_id="doc_1", version=1)

        _insert_relation(
            conn,
            relation_id="rel_orig",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            relation_type="references",
            target_doc_id="doc_2",
            target_doc_number="123/QD-UBND",
        )

    # Duplicate exact identity -> rejected
    with pytest.raises(IntegrityError):
        with upgraded.begin() as conn:
            _insert_relation(
                conn,
                relation_id="rel_duplicate",
                source_doc_id="doc_1",
                source_prun_id="prun_1",
                source_version=1,
                relation_type="references",
                target_doc_id="doc_2",
                target_doc_number="123/QD-UBND",
            )

    # Different relation_type -> accepted
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_diff_type",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            relation_type="amends",
            target_doc_id="doc_2",
            target_doc_number="123/QD-UBND",
        )

    # Different target_document_number -> accepted
    with upgraded.begin() as conn:
        _insert_relation(
            conn,
            relation_id="rel_diff_tgt_num",
            source_doc_id="doc_1",
            source_prun_id="prun_1",
            source_version=1,
            relation_type="references",
            target_doc_id="doc_2",
            target_doc_number="456/QD-UBND",
        )


def test_document_relations_cascade_delete_on_source_document_delete(database_url: str) -> None:
    """Case 7: Deleting the source document CASCADES the relation away."""
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    try:
        with engine.begin() as conn:
            _insert_document(conn, doc_id="doc_src", filename="src.pdf")
            _insert_document(conn, doc_id="doc_tgt", filename="tgt.pdf")
            _insert_parse_run(conn, run_id="prun_src", doc_id="doc_src", version=1)
            _insert_relation(
                conn,
                relation_id="rel_cascade_src",
                source_doc_id="doc_src",
                source_prun_id="prun_src",
                source_version=1,
                target_doc_id="doc_tgt",
                target_doc_number="123/QD",
            )

        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM document_relations WHERE id = 'rel_cascade_src'")
                ).scalar()
                == 1
            )

        # Delete source document
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM documents WHERE id = 'doc_src'"))

        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM document_relations WHERE id = 'rel_cascade_src'")
                ).scalar()
                == 0
            )
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def test_document_relations_set_null_on_target_document_delete(database_url: str) -> None:
    """Case 8: Deleting TARGET doc sets target_document_id to NULL and leaves relation row."""
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    try:
        with engine.begin() as conn:
            _insert_document(conn, doc_id="doc_src", filename="src.pdf")
            _insert_document(conn, doc_id="doc_tgt", filename="tgt.pdf")
            _insert_parse_run(conn, run_id="prun_src", doc_id="doc_src", version=1)
            _insert_relation(
                conn,
                relation_id="rel_set_null_tgt",
                source_doc_id="doc_src",
                source_prun_id="prun_src",
                source_version=1,
                target_doc_id="doc_tgt",
                target_doc_number="123/QD-UBND",
                target_raw_text="Căn cứ Quyết định 123/QĐ-UBND",
            )

        with engine.connect() as conn:
            row_before = (
                conn.execute(text("SELECT * FROM document_relations WHERE id = 'rel_set_null_tgt'"))
                .mappings()
                .one()
            )
            assert row_before["target_document_id"] == "doc_tgt"
            assert row_before["target_document_number"] == "123/QD-UBND"

        # Delete target document
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM documents WHERE id = 'doc_tgt'"))

        with engine.connect() as conn:
            # Relation row SURVIVES (count is still 1)
            row_after = (
                conn.execute(text("SELECT * FROM document_relations WHERE id = 'rel_set_null_tgt'"))
                .mappings()
                .one()
            )
            # target_document_id is set to NULL
            assert row_after["target_document_id"] is None
            # Provenance and target_document_number remain intact
            assert row_after["target_document_number"] == "123/QD-UBND"
            assert row_after["target_raw_text"] == "Căn cứ Quyết định 123/QĐ-UBND"
            assert row_after["source_document_id"] == "doc_src"
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def test_document_relations_composite_fk_rejects_mismatched_provenance(upgraded: Engine) -> None:
    """Case 9: Composite FK rejects mismatched (parse_run_id, doc_id, version)."""
    with upgraded.begin() as conn:
        _insert_document(conn, doc_id="doc_1", filename="a.pdf")
        _insert_parse_run(conn, run_id="prun_1", doc_id="doc_1", version=1)
        _insert_document(conn, doc_id="doc_2", filename="b.pdf")
        _insert_parse_run(conn, run_id="prun_2", doc_id="doc_2", version=1)

    # 1. Nonexistent parse run id
    with pytest.raises(IntegrityError):
        with upgraded.begin() as conn:
            _insert_relation(
                conn,
                relation_id="rel_fk_ghost",
                source_doc_id="doc_1",
                source_prun_id="prun_ghost",
                source_version=1,
                target_doc_number="12/KH",
            )

    # 2. Mismatched document_id (prun_1 belongs to doc_1, not doc_2)
    with pytest.raises(IntegrityError):
        with upgraded.begin() as conn:
            _insert_relation(
                conn,
                relation_id="rel_fk_wrong_doc",
                source_doc_id="doc_2",
                source_prun_id="prun_1",
                source_version=1,
                target_doc_number="12/KH",
            )

    # 3. Mismatched version (prun_1 is version 1, not version 2)
    with pytest.raises(IntegrityError):
        with upgraded.begin() as conn:
            _insert_relation(
                conn,
                relation_id="rel_fk_wrong_ver",
                source_doc_id="doc_1",
                source_prun_id="prun_1",
                source_version=2,
                target_doc_number="12/KH",
            )


def test_document_relations_downgrade_removes_table(database_url: str) -> None:
    """Case 10: downgrade from head succeeds and drops document_relations table."""
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    try:
        tables_head = set(inspect(engine).get_table_names())
        assert "document_relations" in tables_head

        # Downgrade to 0005
        command.downgrade(config, "0005_phase5_pgvector")
        tables_p5 = set(inspect(engine).get_table_names())
        assert "document_relations" not in tables_p5
        assert "document_chunks" in tables_p5
        assert "documents" in tables_p5

        # Downgrade to base
        command.downgrade(config, "base")
        tables_base = set(inspect(engine).get_table_names())
        assert "document_relations" not in tables_base
        assert "documents" not in tables_base
    finally:
        engine.dispose()


def test_document_relations_orm_mapping_and_enums(upgraded: Engine) -> None:
    """Case 11: ORM mapping, relationships, and StrEnums function end-to-end."""
    now = datetime.now(UTC)
    with Session(upgraded) as session:
        doc_src = Document(
            id="doc_orm_src",
            filename="src.pdf",
            content_type="application/pdf",
            byte_size=100,
            checksum_sha256="sha256_orm_src",
            storage_uri="local://src",
            status="READY",
            created_at=now,
            updated_at=now,
        )
        doc_tgt = Document(
            id="doc_orm_tgt",
            filename="tgt.pdf",
            content_type="application/pdf",
            byte_size=100,
            checksum_sha256="sha256_orm_tgt",
            storage_uri="local://tgt",
            status="READY",
            created_at=now,
            updated_at=now,
        )
        prun_src = ParseRun(
            id="prun_orm_src",
            document_id="doc_orm_src",
            version=1,
            is_current=True,
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="hash_orm",
            strategy_decided=True,
            degraded=False,
            route="born_digital",
            schema_version="1.0",
            canonical={},
            inspection={},
            quality_report={},
            started_at=now,
            finished_at=now,
            created_at=now,
        )
        relation = DocumentRelation(
            id="rel_orm_1",
            source_document_id="doc_orm_src",
            source_parse_run_id="prun_orm_src",
            source_document_version=1,
            source_block_ids=["block_1", "block_2"],
            page_numbers=[1, 3],
            relation_type=RelationType.REPLACES.value,
            target_document_id="doc_orm_tgt",
            target_document_number="55/2026/QD-UBND",
            target_raw_text="Thay thế Quyết định số 55/2026/QĐ-UBND",
            confidence=0.92,
            review_state=RelationReviewState.CONFIRMED.value,
            created_at=now,
        )
        session.add_all([doc_src, doc_tgt, prun_src, relation])
        session.commit()

    with Session(upgraded) as session:
        fetched = session.get(DocumentRelation, "rel_orm_1")
        assert fetched is not None
        assert fetched.id == "rel_orm_1"
        assert fetched.relation_type == RelationType.REPLACES.value
        assert fetched.review_state == RelationReviewState.CONFIRMED.value
        assert fetched.source_block_ids == ["block_1", "block_2"]
        assert fetched.page_numbers == [1, 3]
        assert fetched.confidence == pytest.approx(0.92)
        assert fetched.target_document_number == "55/2026/QD-UBND"
        assert fetched.target_raw_text == "Thay thế Quyết định số 55/2026/QĐ-UBND"

        # Check relationships
        assert fetched.source_document is not None
        assert fetched.source_document.id == "doc_orm_src"
        assert fetched.target_document is not None
        assert fetched.target_document.id == "doc_orm_tgt"
        assert fetched.source_parse_run is not None
        assert fetched.source_parse_run.id == "prun_orm_src"


def test_document_relations_cascade_on_parse_run_delete(database_url: str) -> None:
    """Case 12: Deleting the source parse_run CASCADES the relation away."""
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    try:
        with engine.begin() as conn:
            _insert_document(conn, doc_id="doc_src", filename="src.pdf")
            _insert_parse_run(conn, run_id="prun_1", doc_id="doc_src", version=1)
            _insert_parse_run(conn, run_id="prun_2", doc_id="doc_src", version=2)
            _insert_relation(
                conn,
                relation_id="rel_prun_1",
                source_doc_id="doc_src",
                source_prun_id="prun_1",
                source_version=1,
                target_doc_number="12/KH",
            )
            _insert_relation(
                conn,
                relation_id="rel_prun_2",
                source_doc_id="doc_src",
                source_prun_id="prun_2",
                source_version=2,
                target_doc_number="13/KH",
            )

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM document_relations WHERE source_document_id = 'doc_src'")
            ).scalar()
            assert count == 2

        # Delete parse_run 1
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM parse_runs WHERE id = 'prun_1'"))

        with engine.connect() as conn:
            remaining = conn.execute(
                text("SELECT id FROM document_relations WHERE source_document_id = 'doc_src'")
            ).fetchall()
            assert [r.id for r in remaining] == ["rel_prun_2"]
    finally:
        engine.dispose()
        command.downgrade(config, "base")
