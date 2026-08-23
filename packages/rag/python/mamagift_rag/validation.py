"""Strict parsing and provenance validation for grounded model answers."""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from mamagift_retrieval.evidence import Evidence, EvidenceSet
from mamagift_retrieval.scope import EvidenceScope, scope_matches

from .schema import Citation, ModelRef, QaAnswer, RetrievalRef

INSUFFICIENT_EVIDENCE_MESSAGE = (
    "Tôi chưa có đủ thông tin trong tài liệu được truy xuất để trả lời câu hỏi này "
    "một cách đáng tin cậy."
)
FAILED_VALIDATION_MESSAGE = "Không thể xác thực câu trả lời từ mô hình; vui lòng thử lại."


class _RawAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    status: Literal["answered", "insufficient_evidence", "ai_worker_unavailable", "failed"]
    citations: list[Citation]


def _refs(evidence: EvidenceSet, model: ModelRef) -> tuple[RetrievalRef, ModelRef]:
    return RetrievalRef(query_id=evidence.query_id), model


def _failed_answer(evidence: EvidenceSet, model: ModelRef) -> QaAnswer:
    retrieval, model_ref = _refs(evidence, model)
    return QaAnswer(
        answer=FAILED_VALIDATION_MESSAGE,
        status="failed",
        citations=[],
        retrieval=retrieval,
        model=model_ref,
    )


def _abstention_answer(evidence: EvidenceSet, model: ModelRef) -> QaAnswer:
    retrieval, model_ref = _refs(evidence, model)
    return QaAnswer(
        answer=INSUFFICIENT_EVIDENCE_MESSAGE,
        status="insufficient_evidence",
        citations=[],
        retrieval=retrieval,
        model=model_ref,
    )


def _parse_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) < 3:
            raise ValueError("empty fenced response")
        text = "\n".join(lines[1:-1]).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return cast(dict[str, Any], parsed)


def _scope_for_evidence(item: Evidence, scope: EvidenceScope) -> EvidenceScope:
    return EvidenceScope(
        family_id=scope.family_id,
        document_id=item.document_id,
        document_version=item.document_version,
        parse_run_id=item.parse_run_id,
        user_id=scope.user_id,
        thread_id=scope.thread_id,
        archive_scope=scope.archive_scope,
    )


def _validate_citation(citation: Citation, item: Evidence, evidence: EvidenceSet) -> None:
    """Reject forged citation metadata and provenance outside the request scope."""

    if citation.document_id != item.document_id:
        raise ValueError(f"citation {citation.citation_id!r} has mismatched document_id")
    if not scope_matches(_scope_for_evidence(item, evidence.scope), evidence.scope):
        raise ValueError(f"citation {citation.citation_id!r} has out-of-scope provenance")
    if citation.page_number not in item.page_numbers:
        raise ValueError(f"citation {citation.citation_id!r} has an unknown page")
    allowed_blocks = set(item.source_block_ids)
    if any(block_id not in allowed_blocks for block_id in citation.block_ids):
        raise ValueError(f"citation {citation.citation_id!r} has an unknown source block")
    if citation.quote is not None and citation.quote not in item.text:
        raise ValueError(f"citation {citation.citation_id!r} quote is not in evidence")


def parse_and_validate_answer(
    raw_text: str,
    evidence: EvidenceSet,
    *,
    model: ModelRef,
) -> QaAnswer:
    """Parse a model JSON response and enforce the evidence allow-list.

    Validation failures intentionally return ``failed`` rather than an empty
    successful answer.  A model can request abstention, but it cannot smuggle
    citations from another document or parse run into that branch.
    """

    try:
        payload = _parse_json(raw_text)
        raw = _RawAnswer.model_validate(payload)
        by_id = {item.citation_id: item for item in evidence.evidence}
        validated_citations: list[Citation] = []
        for citation in raw.citations:
            item = by_id.get(citation.citation_id)
            if item is None:
                raise ValueError(f"unknown citation_id {citation.citation_id!r}")
            _validate_citation(citation, item, evidence)
            validated_citations.append(citation)
    except (ValueError, TypeError, json.JSONDecodeError, ValidationError):
        return _failed_answer(evidence, model)

    if raw.status == "insufficient_evidence":
        return _abstention_answer(evidence, model)
    if raw.status == "answered" and not validated_citations:
        return _abstention_answer(evidence, model)

    retrieval, model_ref = _refs(evidence, model)
    return QaAnswer(
        answer=raw.answer,
        status=raw.status,
        citations=validated_citations,
        retrieval=retrieval,
        model=model_ref,
    )


__all__ = [
    "FAILED_VALIDATION_MESSAGE",
    "INSUFFICIENT_EVIDENCE_MESSAGE",
    "parse_and_validate_answer",
]
