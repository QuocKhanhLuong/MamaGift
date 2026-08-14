"""Scan tracked text files for common credential signatures."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIGNATURES = {
    "private key": re.compile(r"-----BEGIN [A-Z0-9 ]+ PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "credential assignment": re.compile(
        r"(?i)\b(?:password|secret|token|api[_-]?key)\s*[:=]\s*['\"]([A-Za-z0-9+/=_-]{24,})['\"]"
    ),
}


def tracked_paths() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [path for path in output.decode().split("\0") if path]


def main() -> int:
    paths = tracked_paths()
    findings: list[str] = []
    for path in paths:
        file_path = ROOT / path
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, signature in SIGNATURES.items():
            if signature.search(content):
                findings.append(f"{name}: {path}")

    if findings:
        print("Secret scan failed:")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1

    print(f"Secret scan passed ({len(paths)} tracked files inspected).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
