"""Parser adapter contract tests.

Every adapter satisfies the same suite. The lightweight PyMuPDF adapter runs a real
end-to-end parse; the heavy candidates run through recorded provider output so the
contract is still enforced on a CPU-only runner without downloading model weights
(`docs/04_PHASE_PLAN.md`, Phase 1 contract tests).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench_support import ALL_PARSERS, FIXTURES, RECORDED_PARSERS, RECORDINGS
from mamagift_docpipe import (
    ADAPTER_CONTRACT_VERSION,
    CanonicalDocument,
    DocumentParser,
    ParseRequest,
    ParserError,
    inspect_pdf,
    normalize_provider_result,
)
from mamagift_docpipe.adapters import ADAPTER_REGISTRY, RECORDED_SUFFIX, build_adapter

pytestmark = pytest.mark.contract

CONTRACT_DOCUMENT_ID = "contract_fixture"
LIGHTWEIGHT_PDF = FIXTURES / "cong_van_born_digital.pdf"


def adapter_for(parser_name: str) -> tuple[DocumentParser, ParseRequest]:
    """Build the CI-runnable adapter for a parser plus a request it can serve."""
    if parser_name == "pymupdf":
        return (
            build_adapter("pymupdf"),
            ParseRequest(document_id="cong_van_born_digital", pdf_path=LIGHTWEIGHT_PDF),
        )

    adapter = build_adapter(f"{parser_name}{RECORDED_SUFFIX}", {"recordings_dir": str(RECORDINGS)})
    return adapter, ParseRequest(document_id=CONTRACT_DOCUMENT_ID, pdf_path=LIGHTWEIGHT_PDF)


@pytest.mark.parametrize("parser_name", ADAPTER_REGISTRY)
def test_adapter_metadata_is_stable_and_complete(parser_name: str) -> None:
    adapter = build_adapter(parser_name)
    first, second = adapter.metadata, adapter.metadata

    assert first == second, "metadata must not change between reads"
    assert first.name == parser_name
    assert first.contract_version == ADAPTER_CONTRACT_VERSION
    assert first.adapter_version
    assert first.configuration_hash


@pytest.mark.parametrize("parser_name", ADAPTER_REGISTRY)
def test_configuration_hash_tracks_configuration(parser_name: str) -> None:
    """Two configurations must never share a hash; the benchmark records it."""
    default = build_adapter(parser_name).metadata.configuration_hash
    configured = build_adapter(parser_name, {"lang": "vi", "device": "cpu"})

    assert configured.metadata.configuration_hash != default
    assert configured.metadata.configuration == {"lang": "vi", "device": "cpu"}


@pytest.mark.parametrize("parser_name", ADAPTER_REGISTRY)
def test_adapter_satisfies_the_document_parser_protocol(parser_name: str) -> None:
    assert isinstance(build_adapter(parser_name), DocumentParser)


@pytest.mark.parametrize("parser_name", ADAPTER_REGISTRY)
def test_healthcheck_reports_provider_availability_without_importing_it(
    parser_name: str,
) -> None:
    health = build_adapter(parser_name).healthcheck()

    assert health.name == parser_name
    if health.available:
        assert health.provider_version
    else:
        assert health.provider_version is None
        assert health.detail


@pytest.mark.parametrize("parser_name", ALL_PARSERS)
def test_parse_result_normalizes_to_a_valid_canonical_document(parser_name: str) -> None:
    adapter, request = adapter_for(parser_name)
    result = adapter.parse(request)
    document = normalize_provider_result(result)

    assert isinstance(document, CanonicalDocument)
    assert document.schema_version == "1.0"
    assert document.document_id == request.document_id
    assert document.pages, "an adapter that parses successfully must produce pages"
    assert document.parser_run.parser_name == result.adapter.name
    assert document.parser_run.configuration_hash == result.adapter.configuration_hash


@pytest.mark.parametrize("parser_name", ALL_PARSERS)
def test_page_provenance_survives_normalization(parser_name: str) -> None:
    adapter, request = adapter_for(parser_name)
    document = normalize_provider_result(adapter.parse(request))

    for page in document.pages:
        for block in page.blocks:
            assert block.provenance.page_number == page.page_number
            assert block.provenance.provider_block_id, "provider block id must be retained"
            assert block.id

    orders = [block.reading_order for block in document.pages[0].blocks]
    assert len(orders) == len(set(orders)), "reading order must be unique within a page"


@pytest.mark.parametrize("parser_name", RECORDED_PARSERS)
def test_heavy_adapters_map_their_own_vocabulary_onto_canonical_types(
    parser_name: str,
) -> None:
    """Each provider names blocks differently; none may fall through to `unknown`."""
    adapter, request = adapter_for(parser_name)
    document = normalize_provider_result(adapter.parse(request))

    types = {block.type.value for block in document.iter_blocks()}
    assert "unknown" not in types, f"{parser_name} vocabulary is not fully mapped: {types}"
    assert "table" in types
    assert "paragraph" in types
    # MinerU labels headings "title" as well, so either is acceptable here.
    assert types & {"title", "heading"}


@pytest.mark.parametrize("parser_name", RECORDED_PARSERS)
def test_recorded_tables_normalize_with_their_cell_grid(parser_name: str) -> None:
    adapter, request = adapter_for(parser_name)
    document = normalize_provider_result(adapter.parse(request))

    assert len(document.tables) == 1
    table = document.tables[0]
    assert (table.n_rows, table.n_cols) == (3, 3)
    assert table.cells[0] == ["STT", "Tên hồ sơ", "Thời hạn lưu"]
    assert table.block_id in {block.id for block in document.iter_blocks()}


@pytest.mark.parametrize("parser_name", ADAPTER_REGISTRY)
def test_missing_provider_maps_to_the_common_error_schema(parser_name: str) -> None:
    """An uninstalled provider is a structured error, never an ImportError leak."""
    adapter = build_adapter(parser_name)
    if adapter.healthcheck().available:
        pytest.skip(f"{parser_name} provider is installed in this environment")

    with pytest.raises(ParserError) as excinfo:
        adapter.parse(ParseRequest(document_id="x", pdf_path=LIGHTWEIGHT_PDF))

    error = excinfo.value.model
    assert error.code.value == "provider_unavailable"
    assert error.parser_name == parser_name
    assert error.retryable is False
    assert set(error.model_dump()) == {
        "code",
        "message",
        "retryable",
        "parser_name",
        "details",
    }


def test_encrypted_input_maps_to_encrypted_pdf() -> None:
    adapter = build_adapter("pymupdf")
    with pytest.raises(ParserError) as excinfo:
        adapter.parse(
            ParseRequest(
                document_id="tai_lieu_ma_hoa",
                pdf_path=FIXTURES / "tai_lieu_ma_hoa.pdf",
            )
        )
    assert excinfo.value.code.value == "encrypted_pdf"


def test_malformed_input_maps_to_invalid_pdf() -> None:
    adapter = build_adapter("pymupdf")
    with pytest.raises(ParserError) as excinfo:
        adapter.parse(
            ParseRequest(
                document_id="tep_khong_hop_le",
                pdf_path=FIXTURES / "tep_khong_hop_le.pdf",
            )
        )
    assert excinfo.value.code.value == "invalid_pdf"


def test_missing_file_maps_to_unsupported_input() -> None:
    adapter = build_adapter("pymupdf")
    with pytest.raises(ParserError) as excinfo:
        adapter.parse(ParseRequest(document_id="x", pdf_path=Path("nope.pdf")))
    assert excinfo.value.code.value == "unsupported_input"


def test_missing_recording_maps_to_recording_missing() -> None:
    adapter = build_adapter("mineru+recorded", {"recordings_dir": str(RECORDINGS)})
    with pytest.raises(ParserError) as excinfo:
        adapter.parse(ParseRequest(document_id="khong_co", pdf_path=LIGHTWEIGHT_PDF))

    assert excinfo.value.code.value == "recording_missing"
    assert "expected_path" in excinfo.value.model.details


def test_recorded_output_is_flagged_so_it_cannot_pass_as_a_live_run() -> None:
    adapter, request = adapter_for("docling")
    result = adapter.parse(request)

    assert result.provider_artifact["recorded"] is True
    assert result.provider_artifact["synthetic_contract_fixture"] is True
    assert result.provider_artifact["not_benchmark_evidence"] is True


def test_unknown_adapter_name_is_rejected() -> None:
    with pytest.raises(KeyError):
        build_adapter("khong-ton-tai")
    with pytest.raises(KeyError):
        build_adapter("khong-ton-tai+recorded")


def test_router_and_adapter_agree_on_the_lightweight_fixture() -> None:
    """The one end-to-end path CI always runs: inspect, parse, normalize."""
    inspection = inspect_pdf(LIGHTWEIGHT_PDF, "cong_van_born_digital")
    adapter = build_adapter("pymupdf")
    result = adapter.parse(
        ParseRequest(document_id="cong_van_born_digital", pdf_path=LIGHTWEIGHT_PDF)
    )
    document = normalize_provider_result(result, inspection)

    assert document.quality_report.route == "born_digital"
    assert document.quality_report.route_confidence == pytest.approx(1.0)
    assert len(document.pages) == inspection.page_count
