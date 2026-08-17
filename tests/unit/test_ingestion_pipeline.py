"""Ingestion pipeline tests at the document-pipeline layer (no database)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mamagift_docpipe import (
    ParserError,
    ParserErrorCode,
    Route,
    run_ingestion,
    undecided_strategy,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "parser" / "fixtures"


def test_pipeline_produces_structure_fields_and_provenance() -> None:
    result = run_ingestion(FIXTURES / "quyet_dinh_dieu_khoan.pdf", document_id="doc_1")

    assert result.inspection.route == Route.BORN_DIGITAL
    assert result.canonical.hierarchy
    assert result.canonical.extracted_fields

    for block in result.canonical.iter_blocks():
        assert block.provenance.page_number >= 1

    for field in result.canonical.extracted_fields:
        assert field.source_block_ids
        assert field.source_page_numbers
        assert field.confidence is not None


def test_pipeline_records_the_parser_selection_in_metadata() -> None:
    result = run_ingestion(FIXTURES / "cong_van_born_digital.pdf", document_id="doc_2")
    pipeline = result.canonical.metadata["pipeline"]

    assert pipeline["parser_selection"]["parser_name"] == "pymupdf"
    assert pipeline["parser_selection"]["degraded"] is True
    assert pipeline["attempts"] == [{"parser_name": "pymupdf", "succeeded": True, "error": None}]


def test_encrypted_input_never_reaches_a_parser() -> None:
    with pytest.raises(ParserError) as excinfo:
        run_ingestion(FIXTURES / "tai_lieu_ma_hoa.pdf", document_id="doc_3")

    assert excinfo.value.code == ParserErrorCode.ENCRYPTED_PDF
    assert excinfo.value.retryable is False


def test_malformed_input_is_a_structured_error() -> None:
    with pytest.raises(ParserError) as excinfo:
        run_ingestion(FIXTURES / "tep_khong_hop_le.pdf", document_id="doc_4")

    assert excinfo.value.code == ParserErrorCode.INVALID_PDF


def test_production_refuses_to_run_while_adr_001_is_undecided() -> None:
    with pytest.raises(ParserError) as excinfo:
        run_ingestion(
            FIXTURES / "cong_van_born_digital.pdf",
            document_id="doc_5",
            strategy=undecided_strategy(),
            environment="production",
        )

    assert excinfo.value.code == ParserErrorCode.PARSER_STRATEGY_UNDECIDED


def test_quality_report_marks_a_degraded_run_for_review() -> None:
    result = run_ingestion(FIXTURES / "cong_van_born_digital.pdf", document_id="doc_6")
    report = result.canonical.quality_report

    assert report.requires_user_review is True
    assert report.text_quality_score == 1.0
    assert report.structure_quality_score is not None
    assert any("undecided" in warning for warning in report.warnings)


def test_pipeline_output_is_deterministic() -> None:
    first = run_ingestion(FIXTURES / "quyet_dinh_dieu_khoan.pdf", document_id="doc_7").canonical
    second = run_ingestion(FIXTURES / "quyet_dinh_dieu_khoan.pdf", document_id="doc_7").canonical

    assert first.model_dump(mode="json")["pages"] == second.model_dump(mode="json")["pages"]
    assert first.hierarchy == second.hierarchy
    assert first.extracted_fields == second.extracted_fields
