"""Validate the planning baseline and Phase 0 repository hygiene."""

from __future__ import annotations

import os
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
