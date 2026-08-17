# Real PDF smoke batch 01 — Results

Date: 2026-08-17
Branch: `eval/real-pdf-batch-01`

This is evaluation evidence only. It does not select a production parser and must not close ADR-001 by itself.

## Sources

Six public official Vietnamese administrative PDFs were downloaded at workflow runtime from `datafiles.chinhphu.vn`; no raw PDFs are committed to the repository:

- `13-2026-TT-BGDDT.pdf`
- `19-2026-TT-BGDDT.pdf`
- `22-2026-TT-BGDDT.pdf`
- `38-2026-QD-TTg.pdf`
- `41-2026-TT-BGDDT.pdf`
- `47-2026-TT-BGDDT.pdf`

## Run 1 — Router + Phase 2 ingestion using CI/dev PyMuPDF baseline

GitHub Actions run: `32029713431`
Artifact: `real-pdf-smoke-32029713431` (`9288429183`)

### Router results

All six documents were routed as `scanned`.

| File | Route confidence | Pages | Text-page ratio | Image-page ratio | Mean chars/page |
|---|---:|---:|---:|---:|---:|
| 13/2026/TT-BGDĐT | 1.000 | 15 | 0.000 | 1.000 | 0.533 |
| 19/2026/TT-BGDĐT | 1.000 | 4 | 0.000 | 1.000 | 2.000 |
| 22/2026/TT-BGDĐT | 1.000 | 10 | 0.000 | 1.000 | 0.800 |
| 38/2026/QĐ-TTg | 0.933 | 15 | 0.067 | 0.933 | 12.933 |
| 41/2026/TT-BGDĐT | 1.000 | 19 | 0.000 | 1.000 | 0.684 |
| 47/2026/TT-BGDĐT | 1.000 | 3 | 0.000 | 1.000 | 3.333 |

### Ingestion results

The control-plane flow remained honest: every document reached `READY_FOR_REVIEW`, every parse run was `strategy_decided=false`, `degraded=true`, and `requires_user_review=true`.

However PyMuPDF extracted effectively no usable document text from this batch:

| File | Canonical pages | Blocks | Text chars | Extracted critical fields |
|---|---:|---:|---:|---:|
| 13/2026/TT-BGDĐT | 15 | 17 | 8 | 0 |
| 19/2026/TT-BGDĐT | 4 | 6 | 8 | 0 |
| 22/2026/TT-BGDĐT | 10 | 12 | 8 | 0 |
| 38/2026/QĐ-TTg | 15 | 19 | 193 | 0 |
| 41/2026/TT-BGDĐT | 19 | 21 | 13 | 0 |
| 47/2026/TT-BGDĐT | 3 | 6 | 10 | 0 |

All six reported the required critical-field warnings for missing document number, issuer, issue date and title.

**Finding:** PyMuPDF remains suitable only as a CI/dev baseline and inspection utility for this scan-heavy corpus. The `scanned` route requires a real OCR/layout provider.

## Run 2 — Real PP-StructureV3 through the MamaGift adapter

GitHub Actions run: `32029916860`
Job: `95387380804`
Artifact: `real-ocr-smoke-32029916860` (`9288634137`)

Provider configuration:

- `PPStructureAdapter` adapter version `1.0`
- `paddleocr==3.3.2`
- `paddlepaddle==3.2.0`
- CPU
- `lang=vi`
- source document: `19-2026-TT-BGDDT.pdf`

The provider healthcheck succeeded and the adapter ran through the normal MamaGift provider-neutral interface.

### OCR result

- Route: `scanned`
- Pages: 4
- Blocks: 50
- Non-empty blocks: 50
- Extracted text characters: 7,735
- Hierarchy nodes after Vietnamese admin parsing: **0**
- Extracted critical fields: **1** (`issue_date` only)
- `requires_user_review=true`

Compared with the PyMuPDF baseline on the same PDF (8 text characters), PP-StructureV3 recovered substantial document content.

### Critical correctness failure

The OCR text for the actual document header included a degraded form of:

`Hà Nội, ngày 31 tháng 03 năm 2026`

but the admin parser did not recognize it. It later matched a referenced date in the document title/body and emitted:

- field: `issue_date`
- value: `2024-12-30`
- confidence: **0.95**
- source: page 1 / block `b_1_0003`

This is a high-confidence wrong critical field. It is more serious than returning the field as unknown and must block production promotion.

### OCR quality / semantic-parser interaction

Representative OCR output included strings such as:

- `B GIÁO DC VÀ ĐÀO TO`
- `S: 19 /2026/TT-BGDĐT`
- `Điu 1. Sa đi khon 1 ca Điu 2 như sau:`

The OCR recovered the document meaning reasonably well but lost many Vietnamese diacritics. As a consequence:

- issuer detection failed;
- document-number detection failed despite the number being visually present in OCR text;
- title detection failed;
- `Điều/Khoản/Điểm` hierarchy detection failed completely because the rule parser currently depends too strongly on correctly accented tokens.

The OCR initialization also downloaded more model components than expected even with several optional recognition features disabled; this is a runtime/cost concern, not yet a correctness blocker.

## Decision after batch 01

Do **not** accept ADR-001 yet and do not widen the benchmark blindly before fixing the newly exposed correctness path.

Recommended next engineering work, in order:

1. Fix issue-date extraction so a true document-header date is strongly preferred and referenced dates cannot receive high confidence as the document issue date.
2. Add a real/sanitized regression fixture equivalent to `19/2026/TT-BGDĐT`: actual issue date `2026-03-31`, referenced date `2024-12-30`.
3. Make Vietnamese administrative structure and number/issuer/title recognition tolerant to common OCR accent loss and spacing corruption while retaining raw OCR text and provenance.
4. Compare OCR recognition configurations/models for Vietnamese diacritic preservation before promoting PP-StructureV3 as the `scanned` winner.
5. Only then expand to the >=30-document benchmark and compare providers/routes with authored ground truth.
