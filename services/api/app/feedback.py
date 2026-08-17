"""Feedback service — append-only correction events.

`docs/08_API_AND_DATA_CONTRACTS.md` section 13 and
`docs/09_CODEX_EXECUTION.md` section 8: a user correction is a new feedback event, not
a rewrite of the raw prediction in `parse_runs.canonical`. The corrected value is
layered onto the served canonical document at read time by `apply_corrections`.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import errors
from .models import Document, FeedbackEvent, ParseRun


def validate_feedback(
    session: Session,
    document: Document,
    *,
    feedback_type: str,
    field_id: str | None,
    corrected_value: str | None,
) -> None:
    """Validate the conditional fields for a critical field correction.

    General feedback remains intentionally permissive.  Critical corrections are
    checked against the document's current raw parse before any feedback event can
    be constructed or persisted.
    """
    if feedback_type != "critical_field_correction":
        return

    missing_fields = [
        name
        for name, value in (
            ("field_id", field_id),
            ("corrected_value", corrected_value),
        )
        if value is None or not value.strip()
    ]
    if missing_fields:
        raise errors.ApiError(
            errors.FEEDBACK_FIELD_REQUIRED,
            "field_id and corrected_value are required for a critical field correction",
            status_code=422,
            details={"missing_fields": missing_fields},
        )

    current_parse_run_id = document.current_parse_run_id
    run = session.get(ParseRun, current_parse_run_id) if current_parse_run_id else None
    if run is None or run.document_id != document.id:
        raise errors.ApiError(
            errors.CONFLICT,
            "the current canonical document is unavailable",
            status_code=409,
            details={
                "document_id": document.id,
                "current_parse_run_id": current_parse_run_id,
                "reason": "current_canonical_unavailable",
            },
        )

    canonical = run.canonical
    extracted_fields = canonical.get("extracted_fields") if isinstance(canonical, dict) else None
    if not isinstance(extracted_fields, list):
        raise errors.ApiError(
            errors.CONFLICT,
            "the current canonical document is unavailable",
            status_code=409,
            details={
                "document_id": document.id,
                "current_parse_run_id": current_parse_run_id,
                "reason": "current_canonical_unavailable",
            },
        )

    if not any(
        isinstance(field, dict) and field.get("id") == field_id for field in extracted_fields
    ):
        raise errors.ApiError(
            errors.FEEDBACK_FIELD_INVALID,
            "field_id is not present in the current canonical document",
            status_code=422,
            details={
                "document_id": document.id,
                "field_id": field_id,
                "reason": "not_in_current_canonical",
            },
        )


def submit_feedback(
    session: Session,
    document: Document,
    *,
    feedback_type: str,
    field_id: str | None,
    corrected_value: str | None,
    comment: str | None,
) -> FeedbackEvent:
    """Validate feedback and persist it through the append-only event seam."""
    validate_feedback(
        session,
        document,
        feedback_type=feedback_type,
        field_id=field_id,
        corrected_value=corrected_value,
    )
    return record_feedback(
        session,
        document,
        feedback_type=feedback_type,
        field_id=field_id,
        corrected_value=corrected_value,
        comment=comment,
    )


def record_feedback(
    session: Session,
    document: Document,
    *,
    feedback_type: str,
    field_id: str | None,
    corrected_value: str | None,
    comment: str | None,
) -> FeedbackEvent:
    event = FeedbackEvent(
        id=f"fb_{uuid.uuid4().hex[:20]}",
        document_id=document.id,
        feedback_type=feedback_type,
        field_id=field_id,
        corrected_value=corrected_value,
        comment=comment,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _latest_corrections_by_field(session: Session, document_id: str) -> dict[str, FeedbackEvent]:
    """The most recent `critical_field_correction` feedback per `field_id`."""
    rows = session.scalars(
        select(FeedbackEvent)
        .where(
            FeedbackEvent.document_id == document_id,
            FeedbackEvent.feedback_type == "critical_field_correction",
            FeedbackEvent.field_id.is_not(None),
        )
        .order_by(FeedbackEvent.created_at.asc())
    ).all()
    latest: dict[str, FeedbackEvent] = {}
    for row in rows:
        if row.field_id is not None:
            latest[row.field_id] = row
    return latest


def apply_corrections(
    session: Session, document_id: str, canonical: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of `canonical` with corrections overlaid onto `extracted_fields`.

    The stored artifact is never mutated: `raw_value`/`normalized_value` stay exactly
    as parsed, and `review_status`/`corrected_value` reflect the latest feedback.
    """
    corrections = _latest_corrections_by_field(session, document_id)
    if not corrections:
        return canonical

    overlaid = copy.deepcopy(canonical)
    for field in overlaid.get("extracted_fields", []):
        event = corrections.get(field.get("id"))
        if event is not None:
            field["review_status"] = "corrected"
            field["corrected_value"] = event.corrected_value
    return overlaid
