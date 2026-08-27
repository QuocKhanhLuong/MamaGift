"""Validate the planning baseline and Phase 0 repository hygiene."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = [
    "README.md",
    ".env.example",
    "pyproject.toml",
    "uv.lock",
    "docs/00_PROJECT_CHARTER.md",
    "docs/01_ARCHITECTURE.md",
    "docs/02_INFRASTRUCTURE.md",
    "docs/03_DOCUMENT_PIPELINE.md",
    "docs/04_PHASE_PLAN.md",
    "docs/05_TEST_STRATEGY.md",
    "docs/06_CICD.md",
    "docs/07_DATA_AND_CONTINUAL_LEARNING.md",
    "docs/08_API_AND_DATA_CONTRACTS.md",
    "docs/09_CODEX_EXECUTION.md",
    "docs/10_DESIGN_SYSTEM.md",
    "docs/PHASE_STATUS.md",
    "docs/decisions/ADR-0001-phase0-stack.md",
    "docs/decisions/ADR-001-parser-selection.md",
    "docs/decisions/ADR-002-ingestion-parser-strategy.md",
    "configs/parser-strategy.example.json",
    "benchmarks/parser/manifest.jsonl",
    "benchmarks/parser/README.md",
    "tools/parser_bench/README.md",
    "docs/design/README.md",
    "docs/design/01_INFORMATION_ARCHITECTURE.md",
    "docs/design/02_DOCUMENT_FLOW.md",
    "docs/design/03_CHAT_FLOW.md",
    "docs/design/04_RESPONSIVE_STATES.md",
    "apps/web/package.json",
    "apps/web/package-lock.json",
    "infra/compose/docker-compose.yml",
    "services/api/alembic.ini",
]


# The closed set of phase execution statuses, per docs/PHASE_STATUS.md. A carried limitation
# belongs on a separate `Known blocker:` line, never welded into the status value: the tracker
# previously used `COMPLETE_WITH_EXTERNAL_OCR_BLOCKER`, which no tool could validate and which
# conflated "did the phase finish?" with "what is still missing?".
ALLOWED_PHASE_STATUSES = frozenset({"NOT_STARTED", "IN_PROGRESS", "BLOCKED", "COMPLETE", "PARKED"})
BLOCKED_BY_PHASE_RE = re.compile(r"^BLOCKED_BY_PHASE_[0-9]+(?:\.[0-9]+)?$")

_STATUS_LINE_RE = re.compile(r"^Status:\s*`?([A-Z_0-9.]+)`?\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|\s*[0-9.]+\s*\|[^|]*\|\s*([A-Z_0-9.]+)\s*\|", re.MULTILINE)


def _phase_table_section(text: str) -> str:
    """Just the `## Phase table` section.

    The file contains other tables (gate results, for instance) whose cells legitimately read
    PASS/FAIL; only the phase table carries phase statuses.
    """
    start = text.find("## Phase table")
    if start == -1:
        return ""
    end = text.find("\n## ", start + len("## Phase table"))
    return text[start:] if end == -1 else text[start:end]


def _status_is_allowed(status: str) -> bool:
    return status in ALLOWED_PHASE_STATUSES or bool(BLOCKED_BY_PHASE_RE.match(status))


def check_phase_statuses(text: str) -> list[str]:
    """Every phase status in PHASE_STATUS.md must come from the documented closed set.

    Both the prose `Status:` lines and the phase-table cells are checked, because the two
    drifted apart before: the table said one thing and the header another.
    """
    errors: list[str] = []
    found = False
    for match in _STATUS_LINE_RE.finditer(text):
        found = True
        status = match.group(1)
        if not _status_is_allowed(status):
            errors.append(
                f"PHASE_STATUS.md uses undocumented status {status!r} on a 'Status:' line; "
                f"allowed: {sorted(ALLOWED_PHASE_STATUSES)} or BLOCKED_BY_PHASE_<N>. "
                "Record a carried limitation on a separate 'Known blocker:' line instead."
            )
    for match in _TABLE_ROW_RE.finditer(_phase_table_section(text)):
        found = True
        status = match.group(1)
        if not _status_is_allowed(status):
            errors.append(
                f"PHASE_STATUS.md phase table uses undocumented status {status!r}; "
                f"allowed: {sorted(ALLOWED_PHASE_STATUSES)} or BLOCKED_BY_PHASE_<N>."
            )
    if not found:
        errors.append(
            "PHASE_STATUS.md contains no recognisable phase status; the tracker format changed "
            "and this check would silently pass."
        )
    return errors


def main() -> int:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        print("Missing required files:")
        print("\n".join(f"- {path}" for path in missing))
        return 1

    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    errors: list[str] = []
    private_parts = {"private", "private_data", "real_school_docs"}
    for path in filter(None, tracked):
        parts = set(path.split("/"))
        basename = os.path.basename(path)
        if basename.startswith(".env") and basename != ".env.example":
            errors.append(f"real .env-like file committed: {path}")
        if parts & private_parts:
            errors.append(f"private-data path committed: {path}")
        file_path = ROOT / path
        if file_path.is_file() and file_path.stat().st_size > 20 * 1024 * 1024:
            errors.append(f"tracked file exceeds 20 MiB: {path}")

    errors.extend(check_phase_statuses((ROOT / "docs/PHASE_STATUS.md").read_text(encoding="utf-8")))

    conflict_result = subprocess.run(
        ["git", "grep", "-n", "-E", r"^(<<<<<<<|=======|>>>>>>>)", "--", ":!*.lock"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if conflict_result.returncode == 0:
        errors.append("merge-conflict marker found")

    if errors:
        print("Repository documentation check failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    print(f"Documentation/repository check passed ({len(REQUIRED_FILES)} required files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
