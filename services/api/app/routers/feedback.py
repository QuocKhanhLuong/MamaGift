"""Feedback endpoint (`/api/v1/documents/{document_id}/feedback`).

`docs/08_API_AND_DATA_CONTRACTS.md` section 13.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import errors
from .. import feedback as feedback_service
from ..db import get_session
from ..models import Document
from ..schemas import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/api/v1/documents", tags=["feedback"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/{document_id}/feedback", response_model=FeedbackResponse, status_code=201)
def submit_feedback(
    session: SessionDep, document_id: str, payload: FeedbackRequest
) -> FeedbackResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise errors.ApiError(
            errors.NOT_FOUND,
            "document not found",
            status_code=404,
            details={"document_id": document_id},
        )

    event = feedback_service.record_feedback(
        session,
        document,
        feedback_type=payload.feedback_type,
        field_id=payload.field_id,
        corrected_value=payload.corrected_value,
        comment=payload.comment,
    )
    return FeedbackResponse.from_model(event)
