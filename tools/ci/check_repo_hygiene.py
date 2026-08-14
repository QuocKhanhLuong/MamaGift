"""Check tracked files for repository hygiene violations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_PARTS = {"private", "private_data", "real_school_docs"}
GENERATED_PARTS = {".venv", "node_modules", "dist", "coverage", ".pytest_cache", ".mypy_cache"}


def tracked_paths() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [path for path in output.decode().split("\0") if path]


def main() -> int:
    paths = tracked_paths()
    errors: list[str] = []
    for path in paths:
        parts = set(path.split("/"))
        basename = os.path.basename(path)
        file_path = ROOT / path

        if basename.startswith(".env") and basename != ".env.example":
            errors.append(f"real .env-like file committed: {path}")
        if parts & PRIVATE_PARTS:
            errors.append(f"private-data path committed: {path}")
        if parts & GENERATED_PARTS:
            errors.append(f"generated directory committed: {path}")
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
        print("Repository hygiene check failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    print(f"Repository hygiene check passed ({len(paths)} tracked files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
