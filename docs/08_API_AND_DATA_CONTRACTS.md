# API and Data Contracts

This document defines stable conceptual contracts Codex should preserve while implementation details evolve.

## 1. Contract principles

- External API contracts are application-oriented, not parser/model-oriented.
- Provider/model details are metadata, never required by frontend business logic.
- IDs are opaque stable strings/UUIDs.
- All timestamps are ISO 8601 UTC at the API/storage boundary.
- Every derived fact that matters to a user keeps provenance.
- Raw model/provider outputs are versioned artifacts, not API truth.

## 2. Document summary

```json
{
  "id": "doc_...",
  "filename": "cong-van.pdf",
  "checksum_sha256": "...",
  "status": "READY",
  "document_type": "cong_van",
  "document_number": "1234/SGDDT-GDTH",
  "title": "...",
  "issuer": "...",
  "issued_date": "2026-08-14",
  "current_parse_run_id": "prun_...",
  "created_at": "...",
  "updated_at": "..."
}
```

Nullable extracted fields must remain nullable. Do not substitute guessed placeholders.

## 3. Document status

Canonical document-level states:

```text
UPLOADED
INSPECTING
QUEUED_FOR_PARSE
PARSING
NORMALIZING
STRUCTURING
READY_FOR_REVIEW
INDEXING
READY
PARSE_FAILED
UNSUPPORTED
```

Worker availability is separate and must not be encoded by corrupting document state.

## 4. Job contract

```json
{
  "id": "job_...",
  "document_id": "doc_...",
  "kind": "parse",
  "status": "QUEUED",
  "attempt": 0,
  "idempotency_key": "...",
  "leased_by": null,
  "lease_expires_at": null,
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

Job status enum:

```text
QUEUED
LEASED
RUNNING
SUCCEEDED
FAILED_RETRYABLE
FAILED_TERMINAL
```

## 5. CanonicalDocument v1

Conceptual JSON shape:

```json
{
  "schema_version": "1.0",
  "document_id": "doc_...",
  "parser_run": {
    "id": "prun_...",
    "parser_name": "mineru",
    "parser_version": "...",
    "configuration_hash": "...",
    "started_at": "...",
    "finished_at": "..."
  },
  "metadata": {},
  "pages": [],
  "hierarchy": [],
  "tables": [],
  "extracted_fields": [],
  "quality_report": {}
}
```

## 6. Canonical page

```json
{
  "page_number": 1,
  "width": 595.0,
  "height": 842.0,
  "rotation": 0,
  "blocks": []
}
```

Coordinates use a documented common coordinate space per page. Provider-specific coordinate systems must be normalized.

## 7. Canonical block

```json
{
  "id": "b_1_0001",
  "type": "paragraph",
  "text": "...",
  "reading_order": 1,
  "bbox": [72.2, 150.0, 520.0, 180.5],
  "confidence": 0.98,
  "parent_id": "h_article_2",
  "attributes": {},
  "provenance": {
    "page_number": 1,
    "provider_block_id": "..."
  }
}
```

Initial block types:

```text
title
heading
paragraph
list_item
table
table_cell
caption
header
footer
page_number
signature
stamp_region
image
formula
unknown
```

Enums may grow through versioned schema changes.

## 8. Hierarchy node

```json
{
  "id": "h_clause_5_2",
  "kind": "clause",
  "label": "Khoản 2",
  "text": "...",
  "parent_id": "h_article_5",
  "source_block_ids": ["b_3_0012", "b_3_0013"],
  "ordinal": 2
}
```

Kinds may include:

```text
chapter
section
article
clause
point
appendix
custom_heading
```

## 9. Extracted field

Every important extracted field is represented separately from display metadata so provenance/correction can be tracked.

```json
{
  "id": "field_deadline_1",
  "name": "deadline",
  "raw_value": "trước ngày 25 tháng 8 năm 2026",
  "normalized_value": "2026-08-25",
  "value_type": "date",
  "confidence": 0.93,
  "review_status": "unreviewed",
  "source_block_ids": ["b_2_0007"],
  "source_page_numbers": [2],
  "extractor": {
    "name": "admin-rule-date-v1",
    "version": "1.0"
  }
}
```

Review status:

```text
unreviewed
needs_review
confirmed
corrected
rejected
```

## 10. Quality report

```json
{
  "route": "scanned",
  "route_confidence": 0.99,
  "text_quality_score": 0.91,
  "structure_quality_score": 0.88,
  "critical_field_warnings": [],
  "warnings": [],
  "requires_user_review": false
}
```

Scores are heuristic unless benchmark-calibrated; UI must not imply statistical guarantees without evidence.

## 11. Upload API

Recommended:

```text
POST /api/v1/documents
Content-Type: multipart/form-data
```

Response `202 Accepted`:

```json
{
  "document": { "id": "doc_...", "status": "UPLOADED" },
  "job": { "id": "job_...", "status": "QUEUED" }
}
```

Upload validation errors use structured codes:

```text
unsupported_media_type
file_too_large
invalid_pdf
encrypted_pdf
storage_failure
```

## 12. Document APIs

Recommended resource shape:

```text
GET /api/v1/documents
GET /api/v1/documents/{document_id}
GET /api/v1/documents/{document_id}/canonical
GET /api/v1/documents/{document_id}/file
GET /api/v1/documents/{document_id}/pages/{page}/preview
POST /api/v1/documents/{document_id}/reprocess
```

List supports pagination plus filters that exist in current phase, not speculative filters.

## 13. Feedback API

```text
POST /api/v1/documents/{document_id}/feedback
```

Example:

```json
{
  "feedback_type": "critical_field_correction",
  "field_id": "field_deadline_1",
  "corrected_value": "2026-08-25",
  "comment": null
}
```

Response includes immutable feedback-event ID.

The API never deletes or rewrites raw field prediction as part of correction submission.

## 14. Search API

Phase 3 metadata search may use:

```text
GET /api/v1/documents?query=...&type=...&issuer=...&from=...&to=...
```

Phase 5 archive retrieval can introduce:

```text
POST /api/v1/search
```

with explicit filter object.

## 15. Single-document Q&A API

```text
POST /api/v1/documents/{document_id}/qa
```

Request:

```json
{
  "question": "Văn bản này yêu cầu trường làm gì?"
}
```

Response:

```json
{
  "answer": "...",
  "status": "answered",
  "citations": [
    {
      "citation_id": "c1",
      "document_id": "doc_...",
      "page_number": 2,
      "block_ids": ["b_2_0005", "b_2_0006"],
      "quote": "optional bounded excerpt"
    }
  ],
  "retrieval": {
    "query_id": "qry_..."
  },
  "model": {
    "provider": "local-openai-compatible",
    "model": "configured-model",
    "version": "..."
  }
}
```

Status:

```text
answered
insufficient_evidence
ai_worker_unavailable
failed
```

## 16. Archive Q&A/search answer

Cross-document answers use the same citation object but may cite multiple document IDs.

The backend validates every citation against retrieved block allow-list before returning response.

## 17. AI worker health

```text
GET /internal/v1/health
```

Example:

```json
{
  "status": "online",
  "worker_version": "0.4.0",
  "capabilities": {
    "parse": true,
    "embed": true,
    "rerank": false,
    "llm": true
  },
  "models": {
    "llm": "...",
    "embedding": "...",
    "ocr": "..."
  }
}
```

## 18. AI worker parse job

The exact transport may be pull-based or request-based; preserve conceptual payload:

```json
{
  "job_id": "job_...",
  "idempotency_key": "...",
  "document_id": "doc_...",
  "input": {
    "object_uri": "...",
    "checksum_sha256": "..."
  },
  "parser": {
    "name": "selected-parser",
    "configuration": {}
  }
}
```

Result references versioned artifacts and includes parser metadata.

## 19. Error contract

All application APIs should converge on a predictable structure:

```json
{
  "error": {
    "code": "ai_worker_unavailable",
    "message": "...",
    "retryable": true,
    "request_id": "req_...",
    "details": {}
  }
}
```

Do not leak stack traces or secrets in API messages.

## 20. Compatibility

- API version prefix starts at `/api/v1`.
- CanonicalDocument has its own schema version independent of REST version.
- AI worker reports protocol/application version.
- Breaking changes require migration/update of fixtures and contract tests.
- Frontend must consume application DTOs, not database row shapes.
