"""Configurable parser strategy.

`docs/decisions/ADR-001-parser-selection.md` is still `PENDING EVIDENCE`: no
production parser is selected, and one must not be invented here. The strategy is
therefore data, not code — a route table loaded from configuration — so that closing
ADR-001 is a configuration change rather than a rewrite.

Two rules are enforced structurally rather than by convention:

1. PyMuPDF is the CI/dev baseline. It can only become a production primary when the
   configuration explicitly records that a benchmark promoted it.
2. When no primary parser is configured for a route, the pipeline may fall back to the
   baseline in development/CI, and the resulting run is marked degraded so no caller
   can mistake it for a production-quality parse.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .adapters import ADAPTER_REGISTRY, capabilities_for
from .errors import ParserError, ParserErrorCode
from .router import Route

PARSER_STRATEGY_VERSION = "1.0"

# The documented baseline/utility parser. Never a production default.
BASELINE_PARSER = "pymupdf"

# Capability names the router emits; see `InspectionReport.recommended_parser_capability`.
CAPABILITY_BORN_DIGITAL = "born_digital_text"
CAPABILITY_OCR = "ocr"
CAPABILITY_BOTH = "ocr_and_text"
CAPABILITY_NONE = "none"

PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})


class RoutePlan(BaseModel):
    """Which parser serves one route, and what to try when it fails."""

    model_config = ConfigDict(extra="forbid")

    capability: str
    primary: str | None = None
    fallbacks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_names(self) -> Self:
        for name in [self.primary, *self.fallbacks]:
            if name is not None and name not in ADAPTER_REGISTRY:
                raise ValueError(f"unknown parser adapter in strategy: {name}")
        return self


class ParserStrategy(BaseModel):
    """The full route table plus the ADR state it was derived from."""

    model_config = ConfigDict(extra="forbid")

    version: str = PARSER_STRATEGY_VERSION
    adr_status: str = "PENDING EVIDENCE"
    decided: bool = False
    # Present for configuration round-tripping only; it names the fixed BASELINE_PARSER
    # and may not be reconfigured, or the promotion guard below could be side-stepped.
    baseline_parser: str = BASELINE_PARSER
    # Set only by a benchmark that actually promoted the baseline.
    baseline_promoted_by_benchmark: bool = False
    # Development and CI may run the baseline when nothing is decided yet.
    allow_baseline_when_undecided: bool = True
    routes: dict[str, RoutePlan] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_strategy(self) -> Self:
        if self.baseline_parser != BASELINE_PARSER:
            raise ValueError(
                f"baseline_parser must be {BASELINE_PARSER!r}, not {self.baseline_parser!r}; "
                "the baseline is fixed by ADR-001 and cannot be redefined by configuration"
            )

        for route_name, plan in self.routes.items():
            if route_name not in {route.value for route in Route}:
                raise ValueError(f"unknown route in strategy: {route_name}")
            if plan.primary == BASELINE_PARSER and not self.baseline_promoted_by_benchmark:
                raise ValueError(
                    f"route {route_name!r} names the baseline parser "
                    f"{BASELINE_PARSER!r} as primary, but "
                    "baseline_promoted_by_benchmark is false; ADR-001 has not promoted it"
                )

        if self.decided:
            missing = [name for name, plan in self.routes.items() if plan.primary is None]
            if missing:
                raise ValueError(f"strategy is marked decided but routes lack a primary: {missing}")

        return self

    def plan_for(self, route: Route | str) -> RoutePlan:
        route_value = route.value if isinstance(route, Route) else route
        plan = self.routes.get(route_value)
        if plan is not None:
            return plan
        return RoutePlan(capability=_capability_for_route(route_value))


class ParserSelection(BaseModel):
    """The parser chosen for one document, and why."""

    model_config = ConfigDict(extra="forbid")

    route: str
    capability: str
    parser_name: str
    chain: list[str] = Field(default_factory=list)
    is_baseline: bool = False
    strategy_decided: bool = False
    degraded: bool = False
    capability_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason: str = ""


def _capability_for_route(route_value: str) -> str:
    if route_value in (Route.SCANNED.value, Route.GARBLED_TEXT_LAYER.value):
        return CAPABILITY_OCR
    if route_value == Route.MIXED.value:
        return CAPABILITY_BOTH
    if route_value == Route.BORN_DIGITAL.value:
        return CAPABILITY_BORN_DIGITAL
    return CAPABILITY_NONE


def undecided_strategy() -> ParserStrategy:
    """The honest default while ADR-001 is `PENDING EVIDENCE`: no primary anywhere."""
    return ParserStrategy(
        routes={
            route.value: RoutePlan(capability=_capability_for_route(route.value))
            for route in (
                Route.BORN_DIGITAL,
                Route.SCANNED,
                Route.MIXED,
                Route.GARBLED_TEXT_LAYER,
            )
        }
    )


def load_strategy(path: str | Path | None) -> ParserStrategy:
    """Load a strategy from JSON, or return the undecided default when unset."""
    if path is None:
        return undecided_strategy()

    config_path = Path(path)
    if not config_path.is_file():
        raise ParserError(
            ParserErrorCode.PARSER_STRATEGY_UNDECIDED,
            f"parser strategy configuration not found: {config_path}",
            parser_name="strategy",
        )

    payload: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    return ParserStrategy.model_validate(payload)


def _capability_gaps(parser_name: str, capability: str) -> list[str]:
    caps = capabilities_for(parser_name)
    required: list[str] = []
    if capability in (CAPABILITY_OCR, CAPABILITY_BOTH):
        required.append("ocr")
    if capability in (CAPABILITY_BORN_DIGITAL, CAPABILITY_BOTH):
        required.append("born_digital_text")
    return [name for name in required if not getattr(caps, name)]


def select_parser(
    route: Route | str,
    strategy: ParserStrategy,
    environment: str = "development",
) -> ParserSelection:
    """Choose the parser for a route.

    Raises `ParserError` rather than guessing when nothing valid can be selected: a
    silent wrong parser is exactly the failure ADR-001 exists to prevent.
    """
    route_value = route.value if isinstance(route, Route) else route
    plan = strategy.plan_for(route_value)

    if plan.capability == CAPABILITY_NONE:
        raise ParserError(
            ParserErrorCode.UNSUPPORTED_INPUT,
            f"route {route_value!r} is not parseable and must not reach parser selection",
            parser_name="strategy",
        )

    warnings: list[str] = []
    chain = [name for name in [plan.primary, *plan.fallbacks] if name is not None]

    if plan.primary is None:
        is_production = environment.lower() in PRODUCTION_ENVIRONMENTS
        if is_production or not strategy.allow_baseline_when_undecided:
            raise ParserError(
                ParserErrorCode.PARSER_STRATEGY_UNDECIDED,
                (
                    f"no production parser is configured for route {route_value!r}; "
                    "ADR-001 must be decided before this environment can parse"
                ),
                parser_name="strategy",
                details={"route": route_value, "environment": environment},
            )

        warnings.append(
            f"parser strategy is undecided for route {route_value!r}; "
            f"running the {BASELINE_PARSER} baseline for development/CI only"
        )
        selected = BASELINE_PARSER
        chain = [selected]
        degraded = True
        reason = "baseline_fallback_strategy_undecided"
    else:
        selected = plan.primary
        degraded = False
        reason = "configured_primary"

    gaps = _capability_gaps(selected, plan.capability)
    if gaps:
        degraded = True
        warnings.append(
            f"parser {selected!r} does not provide required capability/capabilities "
            f"{gaps} for route {route_value!r}"
        )

    return ParserSelection(
        route=route_value,
        capability=plan.capability,
        parser_name=selected,
        chain=chain,
        is_baseline=selected == BASELINE_PARSER,
        strategy_decided=strategy.decided,
        degraded=degraded,
        capability_gaps=gaps,
        warnings=warnings,
        reason=reason,
    )
