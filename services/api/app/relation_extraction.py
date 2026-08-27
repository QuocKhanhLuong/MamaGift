"""Relation extraction and persistence pipeline for cross-document memory.

Relations are extracted deterministically from canonical block text by regex. There is NO code
path in which a language model creates a relation. Every relation carries the provenance of the
span it came from. A relation naming a document the archive does not hold is recorded with
`target_document_id=None` and a normalised `target_document_number` — a `documents` row is
NEVER created to satisfy a relation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mamagift_docpipe import CanonicalDocument
from mamagift_docpipe.relations import (
    ExtractedRelation,
    extract_relations,
    normalize_identifier,
)

from .models import Document, DocumentRelation, ParseRun, RelationReviewState


def persist_relations(
    session: Session,
    parse_run: ParseRun,
    *,
    relations: Sequence[ExtractedRelation] | None = None,
) -> list[DocumentRelation]:
    """Extract and atomically persist relations for a completed parse run.

    - When `relations` is None, relations are extracted from `parse_run.canonical`.
    - Resolves targets against existing documents:
        - exactly 1 match: sets `target_document_id`.
        - 0 matches: leaves `target_document_id=None`, keeps `target_document_number`.
        - >1 matches: leaves `target_document_id=None` (ambiguity is never resolved by guessing).
    - Idempotently replaces previous relation rows for this parse run using deterministic IDs.
    - NEVER inserts or modifies rows in the `documents` table.
    """
    if relations is None:
        canonical_doc = CanonicalDocument.model_validate(parse_run.canonical)
        extracted_relations: Sequence[ExtractedRelation] = extract_relations(canonical_doc)
    else:
        extracted_relations = relations

    # Fetch candidate documents for target resolution
    candidate_docs = list(
        session.scalars(select(Document).where(Document.document_number.is_not(None))).all()
    )

    # Build target number lookup mapping: normalized_number -> list of matching Document rows
    doc_lookup: dict[str, list[Document]] = {}
    for doc in candidate_docs:
        if doc.document_number:
            norm_num = normalize_identifier(doc.document_number)
            doc_lookup.setdefault(norm_num, []).append(doc)

    # Prepare DocumentRelation rows
    relation_rows: list[DocumentRelation] = []
    for rel in extracted_relations:
        target_doc_id: str | None = None
        if rel.target_document_number:
            matches = doc_lookup.get(rel.target_document_number, [])
            if len(matches) == 1:
                target_doc_id = matches[0].id
            else:
                # 0 matches or ambiguous (>1 matches): leave target_document_id as None
                target_doc_id = None

        identity_key = (
            f"{parse_run.id}:{rel.relation_type}:{rel.target_document_number}:{target_doc_id}"
        )
        relation_id = f"rel_{hashlib.sha256(identity_key.encode('utf-8')).hexdigest()[:32]}"

        row = DocumentRelation(
            id=relation_id,
            source_document_id=parse_run.document_id,
            source_parse_run_id=parse_run.id,
            source_document_version=parse_run.version,
            source_block_ids=rel.source_block_ids,
            page_numbers=rel.page_numbers,
            relation_type=rel.relation_type,
            target_document_id=target_doc_id,
            target_document_number=rel.target_document_number,
            target_raw_text=rel.target_raw_text,
            confidence=rel.confidence,
            review_state=RelationReviewState.UNVERIFIED.value,
        )
        relation_rows.append(row)

    # Atomically replace parse run's existing relations (delete-then-insert)
    session.execute(
        delete(DocumentRelation).where(DocumentRelation.source_parse_run_id == parse_run.id)
    )
    for row in relation_rows:
        session.add(row)
    session.flush()

    return relation_rows
