"""Parser strategy tests.

ADR-001 is `PENDING EVIDENCE`, so these tests pin the two properties that keep the
decision honest: the baseline can never be hard-coded as a production parser, and an
undecided strategy refuses to run in production instead of silently guessing.
"""

from __future__ import annotations

import json

import pytest

from mamagift_docpipe import (
    ParserError,
    ParserErrorCode,
    ParserStrategy,
    Route,
    RoutePlan,
    load_strategy,
    select_parser,
    undecided_strategy,
)

pytestmark = pytest.mark.unit


def test_default_strategy_is_undecided() -> None:
    strategy = undecided_strategy()
    assert strategy.decided is False
    assert strategy.adr_status == "PENDING EVIDENCE"
    assert all(plan.primary is None for plan in strategy.routes.values())


def test_baseline_cannot_be_a_production_primary() -> None:
    with pytest.raises(ValueError, match="baseline_promoted_by_benchmark"):
        ParserStrategy(
            decided=True,
            routes={"born_digital": RoutePlan(capability="born_digital_text", primary="pymupdf")},
        )


def test_baseline_may_be_primary_only_when_a_benchmark_promoted_it() -> None:
    strategy = ParserStrategy(
        decided=True,
        adr_status="ACCEPTED",
        baseline_promoted_by_benchmark=True,
        routes={
            "born_digital": RoutePlan(capability="born_digital_text", primary="pymupdf"),
            "scanned": RoutePlan(capability="ocr", primary="ppstructure"),
            "mixed": RoutePlan(capability="ocr_and_text", primary="mineru"),
            "garbled_text_layer": RoutePlan(capability="ocr", primary="ppstructure"),
        },
    )
    selection = select_parser(Route.BORN_DIGITAL, strategy, environment="production")
    assert selection.parser_name == "pymupdf"
    assert selection.degraded is False
    assert selection.strategy_decided is True


def test_baseline_promotion_guard_survives_a_reconfigured_baseline_parser() -> None:
    """Pointing `baseline_parser` elsewhere must not launder pymupdf into a primary.

    The guard once compared against the mutable field, so renaming the baseline made
    `primary: pymupdf` look like an ordinary decided parser: not degraded, not baseline.
    """
    with pytest.raises(ValueError, match="baseline_parser must be"):
        ParserStrategy(
            decided=True,
            adr_status="ACCEPTED",
            baseline_parser="docling",
            baseline_promoted_by_benchmark=False,
            routes={
                "born_digital": RoutePlan(capability="born_digital_text", primary="pymupdf"),
                "scanned": RoutePlan(capability="ocr", primary="ppstructure"),
                "mixed": RoutePlan(capability="ocr_and_text", primary="mineru"),
                "garbled_text_layer": RoutePlan(capability="ocr", primary="ppstructure"),
            },
        )


def test_decided_strategy_requires_a_primary_for_every_route() -> None:
    with pytest.raises(ValueError, match="lack a primary"):
        ParserStrategy(
            decided=True,
            routes={"born_digital": RoutePlan(capability="born_digital_text")},
        )


def test_undecided_strategy_falls_back_to_the_baseline_outside_production() -> None:
    selection = select_parser(Route.BORN_DIGITAL, undecided_strategy(), environment="development")

    assert selection.parser_name == "pymupdf"
    assert selection.is_baseline is True
    assert selection.degraded is True
    assert selection.reason == "baseline_fallback_strategy_undecided"
    assert any("undecided" in warning for warning in selection.warnings)


def test_undecided_strategy_refuses_to_run_in_production() -> None:
    with pytest.raises(ParserError) as excinfo:
        select_parser(Route.BORN_DIGITAL, undecided_strategy(), environment="production")

    assert excinfo.value.code == ParserErrorCode.PARSER_STRATEGY_UNDECIDED
    assert excinfo.value.retryable is False


def test_capability_gap_is_reported_not_hidden() -> None:
    """The baseline has no OCR, so a scanned route must be reported as degraded."""
    selection = select_parser(Route.SCANNED, undecided_strategy(), environment="development")

    assert selection.capability == "ocr"
    assert selection.capability_gaps == ["ocr"]
    assert selection.degraded is True


@pytest.mark.parametrize("route", [Route.ENCRYPTED, Route.UNSUPPORTED])
def test_unparseable_routes_never_reach_parser_selection(route: Route) -> None:
    with pytest.raises(ParserError) as excinfo:
        select_parser(route, undecided_strategy())
    assert excinfo.value.code == ParserErrorCode.UNSUPPORTED_INPUT


def test_unknown_adapter_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown parser adapter"):
        RoutePlan(capability="ocr", primary="not-a-parser")


def test_strategy_round_trips_through_configuration(tmp_path) -> None:
    strategy = ParserStrategy(
        decided=True,
        adr_status="ACCEPTED",
        routes={
            "born_digital": RoutePlan(
                capability="born_digital_text", primary="mineru", fallbacks=["docling"]
            ),
            "scanned": RoutePlan(capability="ocr", primary="ppstructure"),
            "mixed": RoutePlan(capability="ocr_and_text", primary="mineru"),
            "garbled_text_layer": RoutePlan(capability="ocr", primary="ppstructure"),
        },
    )
    path = tmp_path / "strategy.json"
    path.write_text(json.dumps(strategy.model_dump(mode="json")), encoding="utf-8")

    loaded = load_strategy(path)
    assert loaded == strategy

    selection = select_parser(Route.BORN_DIGITAL, loaded, environment="production")
    assert selection.chain == ["mineru", "docling"]


def test_missing_configuration_is_a_structured_error(tmp_path) -> None:
    with pytest.raises(ParserError) as excinfo:
        load_strategy(tmp_path / "absent.json")
    assert excinfo.value.code == ParserErrorCode.PARSER_STRATEGY_UNDECIDED


def test_no_strategy_path_means_undecided() -> None:
    assert load_strategy(None) == undecided_strategy()
