"""Recorded-output adapter.

Heavy parsers cannot run on mandatory CI runners, but their contract still has to be
tested. `RecordedParser` replays a `ProviderParseResult` captured from a real run over
a sanitized fixture, so every adapter goes through the same contract suite and the
same normalizer on a CPU-only runner.

A recording is raw provider evidence: it is replayed verbatim and never edited.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..errors import ParserError, ParserErrorCode
from ..interface import (
    AdapterMetadata,
    HealthReport,
    ParserCapabilities,
    ParseRequest,
    ProviderParseResult,
)

RECORDED_SUFFIX = "+recorded"


class RecordedParser:
    """Replays recorded provider output for one parser name.

    Implements `DocumentParser` structurally, so callers cannot tell a replayed run
    from a live one apart from the `recorded` flag in the provider artifact.
    """

    adapter_version = "1.0"

    def __init__(
        self,
        parser_name: str,
        recordings_dir: str | Path,
        capabilities: ParserCapabilities | None = None,
    ) -> None:
        self.parser_name = parser_name
        self.recordings_dir = Path(recordings_dir)
        self._capabilities = capabilities or ParserCapabilities()

    @property
    def name(self) -> str:
        return f"{self.parser_name}{RECORDED_SUFFIX}"

    def recording_path(self, document_id: str) -> Path:
        return self.recordings_dir / self.parser_name / f"{document_id}.json"

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=self.name,
            adapter_version=self.adapter_version,
            provider_package=None,
            provider_version=None,
            capabilities=self._capabilities,
            configuration={"recordings_dir": str(self.recordings_dir)},
            configuration_hash="recorded",
        )

    def healthcheck(self) -> HealthReport:
        available = (self.recordings_dir / self.parser_name).is_dir()
        return HealthReport(
            name=self.name,
            available=available,
            provider_version=None,
            device="cpu",
            detail="" if available else f"no recordings for {self.parser_name}",
        )

    def parse(self, request: ParseRequest) -> ProviderParseResult:
        path = self.recording_path(request.document_id)
        if not path.is_file():
            raise ParserError(
                ParserErrorCode.RECORDING_MISSING,
                f"no recorded output for {self.parser_name}/{request.document_id}",
                parser_name=self.name,
                details={"expected_path": str(path)},
            )

        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        try:
            recorded = ProviderParseResult.model_validate(payload)
        except ValidationError as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_FAILURE,
                f"recorded output for {self.parser_name} does not match the adapter contract",
                parser_name=self.name,
                details={"errors": exc.errors(include_url=False)},
            ) from exc

        if recorded.document_id != request.document_id:
            raise ParserError(
                ParserErrorCode.PROVIDER_FAILURE,
                f"recording is for {recorded.document_id}, requested {request.document_id}",
                parser_name=self.name,
            )

        artifact = dict(recorded.provider_artifact)
        artifact["recorded"] = True
        artifact["recording_path"] = str(path)
        return recorded.model_copy(update={"provider_artifact": artifact})
