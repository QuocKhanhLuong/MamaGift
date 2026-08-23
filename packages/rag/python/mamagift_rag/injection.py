"""Defence-in-depth helpers for untrusted document text.

Delimiters and the system policy in :mod:`mamagift_rag.prompt` are the primary
control.  Pattern detection is only a signal for observability and must never
be treated as a security boundary: novel prompt-injection wording can evade a
regular-expression list, while ordinary document prose can match one.
"""

from __future__ import annotations

import html
import re

UNTRUSTED_DOCUMENT_OPEN = "<UNTRUSTED_DOCUMENT_DATA>"
UNTRUSTED_DOCUMENT_CLOSE = "</UNTRUSTED_DOCUMENT_DATA>"

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions?\b", re.IGNORECASE),
    ),
    (
        "system_prompt_exfiltration",
        re.compile(r"\breveal\s+(?:your\s+)?system\s+prompt\b", re.IGNORECASE),
    ),
    (
        "external_action_request",
        re.compile(r"\bcall\s+an\s+external\s+service\b", re.IGNORECASE),
    ),
)


def scan_for_prompt_injection(text: str) -> tuple[str, ...]:
    """Return matching signal names without changing or discarding ``text``."""

    if not isinstance(text, str):
        raise TypeError("document text must be a string")
    return tuple(name for name, pattern in _INJECTION_PATTERNS if pattern.search(text))


def contains_prompt_injection(text: str) -> bool:
    """Return whether the defence-in-depth signal list matched ``text``."""

    return bool(scan_for_prompt_injection(text))


def escape_untrusted_text(text: str) -> str:
    """Escape markup so document text cannot close its surrounding data block."""

    if not isinstance(text, str):
        raise TypeError("document text must be a string")
    return html.escape(text, quote=False)


def wrap_untrusted_document(text: str, *, citation_id: str) -> str:
    """Wrap document text in a labelled, non-instructional data block.

    The original content is retained as data (apart from markup escaping),
    including text that looks like an instruction.  The citation label comes
    from the assembler's EvidenceSet and is escaped before entering markup.
    """

    if not citation_id:
        raise ValueError("citation_id must be non-empty")
    label = html.escape(citation_id, quote=True)
    return (
        f"{UNTRUSTED_DOCUMENT_OPEN}\n"
        f"[citation_id={label}]\n"
        f"{escape_untrusted_text(text)}\n"
        f"{UNTRUSTED_DOCUMENT_CLOSE}"
    )


__all__ = [
    "UNTRUSTED_DOCUMENT_CLOSE",
    "UNTRUSTED_DOCUMENT_OPEN",
    "contains_prompt_injection",
    "escape_untrusted_text",
    "scan_for_prompt_injection",
    "wrap_untrusted_document",
]
