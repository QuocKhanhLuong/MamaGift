"""Benchmark manifest and ground-truth schemas.

The manifest is JSONL: one benchmark document per line. Public manifests reference
sanitized/synthetic fixtures committed to the repository. Private manifests may point
at absolute paths outside Git; they are never committed
(`docs/05_TEST_STRATEGY.md` section 3).
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RouteLabel(StrEnum):
    BORN_DIGITAL = "born_digital"
    SCANNED = "scanned"
    MIXED = "mixed"
    GARBLED_TEXT_LAYER = "garbled_text_layer"
    ENCRYPTED = "encrypted"
    UNSUPPORTED = "unsupported"


class Provenance(StrEnum):
    SYNTHETIC = "synthetic"
    SANITIZED = "sanitized"
    PRIVATE = "private"


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    route_label: RouteLabel
    difficulty: Difficulty
    provenance: Provenance
    ground_truth: str | None = None
    notes: str = ""

    def resolve_path(self, root: Path) -> Path:
        candidate = Path(self.path)
        return candidate if candidate.is_absolute() else root / candidate

    def resolve_ground_truth(self, root: Path) -> Path | None:
        if self.ground_truth is None:
            return None
        candidate = Path(self.ground_truth)
        return candidate if candidate.is_absolute() else root / candidate


class Heading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: int = Field(ge=1)
    text: str = Field(min_length=1)


class TableTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    cells: list[list[str]]


class GroundTruth(BaseModel):
    """Progressive ground truth. Absent layers make their metrics unavailable,
    never zero — a missing label is not a parser failure."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)

    # Level A — document invariants
    page_count: int | None = Field(default=None, ge=1)
    critical_fields: dict[str, str] = Field(default_factory=dict)

    # Level B — structure
    reading_order: list[str] = Field(default_factory=list)
    headings: list[Heading] = Field(default_factory=list)
    lists: list[list[str]] = Field(default_factory=list)
    tables: list[TableTruth] = Field(default_factory=list)
    header_footer_texts: list[str] = Field(default_factory=list)

    # Level C — exact transcription, keyed by page number as a string
    transcript: dict[str, str] = Field(default_factory=dict)


class ManifestError(ValueError):
    pass


def load_manifest(path: str | Path) -> list[ManifestEntry]:
    """Parse and validate a JSONL manifest, reporting the offending line number."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ManifestError(f"manifest not found: {manifest_path}")

    entries: list[ManifestEntry] = []
    seen: set[str] = set()

    for line_number, raw_line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{manifest_path}:{line_number}: invalid JSON: {exc}") from exc
        try:
            entry = ManifestEntry.model_validate(payload)
        except ValidationError as exc:
            raise ManifestError(f"{manifest_path}:{line_number}: {exc}") from exc

        if entry.document_id in seen:
            raise ManifestError(
                f"{manifest_path}:{line_number}: duplicate document_id {entry.document_id}"
            )
        seen.add(entry.document_id)
        entries.append(entry)

    if not entries:
        raise ManifestError(f"{manifest_path}: manifest contains no entries")
    return entries


def load_ground_truth(path: str | Path) -> GroundTruth:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return GroundTruth.model_validate(payload)


def check_manifest_files(entries: list[ManifestEntry], root: Path) -> list[str]:
    """Return human-readable problems with a manifest's referenced files."""
    problems: list[str] = []
    for entry in entries:
        pdf_path = entry.resolve_path(root)
        if not pdf_path.is_file():
            problems.append(f"{entry.document_id}: missing PDF {pdf_path}")
        truth_path = entry.resolve_ground_truth(root)
        if truth_path is not None and not truth_path.is_file():
            problems.append(f"{entry.document_id}: missing ground truth {truth_path}")
        if entry.provenance is Provenance.PRIVATE and not Path(entry.path).is_absolute():
            problems.append(
                f"{entry.document_id}: private documents must use an absolute path "
                "outside the repository"
            )
    return problems
