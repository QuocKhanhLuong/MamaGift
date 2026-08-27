"""Metadata filters for archive-scoped retrieval.

There is deliberately no field here that relaxes current-version isolation. Retrieving only
the current parse run of each document is an invariant of the archive index, not a filter a
caller can switch off -- see `mamagift_retrieval.archive.protocol.ArchiveIndex`.
"""

from __future__ import annotations

import unicodedata
from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator


def normalize_identifier(value: str) -> str:
    """Normalise a Vietnamese administrative document number for exact matching.

    NFC-normalises, trims, removes whitespace around `/` and `-`, collapses remaining runs of
    whitespace, and uppercases. `" 19 / 2026 / TT-BGDĐT "` becomes `"19/2026/TT-BGDĐT"`.
    """
    if not isinstance(value, str):
        raise TypeError("identifier must be a string")
    text = unicodedata.normalize("NFC", value).strip()
    out: list[str] = []
    for index, char in enumerate(text):
        if char.isspace():
            prev = next((c for c in reversed(out) if not c.isspace()), "")
            nxt = ""
            for later in text[index + 1 :]:
                if not later.isspace():
                    nxt = later
                    break
            if prev in {"/", "-"} or nxt in {"/", "-"}:
                continue
            if out and out[-1].isspace():
                continue
            out.append(" ")
            continue
        out.append(char)
    return "".join(out).strip().upper()


class ArchiveFilter(BaseModel):
    """A metadata restriction over the archive's current documents.

    `None` means "no restriction on this field". An EMPTY LIST means "match nothing" and is
    never treated as "match everything": a caller that computed an empty candidate set must
    get an empty result, not the whole archive.
    """

    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] | None = None
    document_types: list[str] | None = None
    document_numbers: list[str] | None = None
    issuers: list[str] | None = None
    issued_date_from: date | None = None
    issued_date_to: date | None = None
    include_requires_review: bool = True

    @model_validator(mode="after")
    def _validate_range(self) -> ArchiveFilter:
        if (
            self.issued_date_from is not None
            and self.issued_date_to is not None
            and self.issued_date_from > self.issued_date_to
        ):
            raise ValueError(
                f"issued_date_from {self.issued_date_from} is after "
                f"issued_date_to {self.issued_date_to}"
            )
        return self

    def matches_nothing(self) -> bool:
        """Whether this filter can never select a document.

        An empty list on any field makes the whole filter unsatisfiable.
        """
        return any(
            values is not None and len(values) == 0
            for values in (
                self.document_ids,
                self.document_types,
                self.document_numbers,
                self.issuers,
            )
        )

    def normalized_document_numbers(self) -> list[str] | None:
        if self.document_numbers is None:
            return None
        return [normalize_identifier(value) for value in self.document_numbers]


__all__ = ["ArchiveFilter", "normalize_identifier"]
