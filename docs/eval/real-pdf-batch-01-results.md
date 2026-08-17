# `real-pdf-batch-01` correctness results

Date: 2026-08-17
Status: software hardening complete; official six-document rerun blocked by missing
evaluation inputs

## Evidence boundary

At the start of this run, the requested `docs/eval/real-pdf-batch-01-results.md` was
absent from the checkout and every local Git ref. The six official PDFs, their private
manifest, reviewed ground truth, and the original batch output were also unavailable.
This file is therefore a new evidence-boundary report, not a recovered copy of the
original real-PDF results. No real-document value or expected answer is inferred here.

ADR-001 remains `PENDING EVIDENCE`; this report does not select a parser or satisfy the
30-document benchmark requirement.

## Correctness fixes

The previous administrative parser selected the first parseable non-deadline date and
could assign high confidence to a referenced date. Its header patterns also required
accented labels and ordinary spaces. The benchmark critical-field extractor had a
separate first-date rule.

The hardened path now:

- enumerates valid Vietnamese and numeric date candidates, including compact forms such
  as `ngày31tháng03năm2026` and `ngày 31 tháng03 năm 2026`;
- ranks candidates using page-one/header position, nearby issuer/number/title context,
  bounding-box position, block/provider provenance, and provider confidence;
- explicitly suppresses deadline/reference context, omits `issue_date` when only
  referenced dates exist, and lowers conflicting candidates to review-required instead
  of publishing a high-confidence guess;
- applies bounded OCR aliases for `Điều`/`Điu`, `Khoản`/`khon`, `Điểm`, `Số:`/`S:`,
  accentless administrative headings, subject labels, and compact spacing only during
  matching;
- keeps canonical block text/raw field text and source block/page provenance intact;
- applies the same conservative date/number semantics to benchmark critical-field
  extraction.

The administrative extractor is recorded as version `1.1` in canonical field
provenance; the benchmark critical-field extractor is `bench-critical-fields-1.1`.

The synthetic regression equivalent is actual issue date `2026-03-31` with referenced
date `2024-12-30`. It asserts that the referenced value cannot return as an
unreviewed/high-confidence `issue_date`; the header candidate is selected when its
administrative context is clear.

## Deterministic before/after evidence

The original code path was verified by inspection: `_extract_issue_date` returned the
first parseable date, while `_extract_number` returned the first number match. The new
OCR regression fixture initially exposed those failures, then passed after the parser
and benchmark changes.

The checked-in synthetic benchmark was also run before and after the fix with the same
command:

| Run | Corpus | PyMuPDF runs | Result |
|---|---:|---:|---|
| before | 8 synthetic PDFs | 8 (2 expected input failures) | score `0.882`, coverage `0.90`, no gates |
| after | 8 synthetic PDFs | 8 (2 expected input failures) | score `0.882`, coverage `0.90`, no gates |

The unchanged public score is a regression result, not real-PDF evidence. The two
failures are the encrypted and malformed synthetic fixtures.

## Public synthetic admin smoke (not the requested official six)

These values are from checked-in generated fixtures only. They must not be substituted
for the unavailable official-document results.

| Document | Text chars | Document number | Issuer | Issue date | Title | Hierarchy | Warnings | Review |
|---|---:|---|---|---|---|---:|---|---|
| `cong_van_born_digital` | 628 | `1234/UBND-VP` | `ỦY BAN NHÂN DÂN XÃ MAI GIANG` | `2026-08-14` | `hướng dẫn nộp hồ sơ tuyển sinh năm học 2026-2027` | 1 | parser strategy is undecided for route `born_digital`; PyMuPDF baseline is development/CI only | yes |
| `quyet_dinh_dieu_khoan` | 624 | `57/QĐ-UBND` | `ỦY BAN NHÂN DÂN XÃ MAI GIANG` | `2026-03-03` | `ban hành quy chế quản lý hồ sơ hành chính` | 8 | parser strategy is undecided for route `born_digital`; PyMuPDF baseline is development/CI only | yes |
| `trang_xoay` | 148 | `88/TB-UBND` | `ỦY BAN NHÂN DÂN XÃ MAI GIANG` | `2026-09-09` | `thông báo lịch tiếp công dân` | 0 | rotated pages detected: `[1]`; parser strategy undecided | yes |

Router and lightweight PyMuPDF benchmark coverage remained green for the full public
eight-document manifest. `pymupdf` was available at provider version
`1.28.2 (mupdf 1.28.2)`; `ppstructure` was unavailable because `paddleocr` is not
installed.

## Official six-document rerun

No per-document official rows are reported because the checkout does not contain the
six input identities, private manifest, PDFs, or reviewed ground truth. Assigning
synthetic names or expected values would fabricate evidence.

| Requested batch | Router | PyMuPDF baseline | PP-StructureV3 real OCR | Admin extraction | Required fields/warnings/review |
|---|---|---|---|---|---|
| `real-pdf-batch-01` — six official PDFs | **NOT RUN / BLOCKED** | **NOT RUN / BLOCKED** | **BLOCKED: provider and PDFs unavailable** | **NOT RUN / BLOCKED** | **BLOCKED: no manifest or reviewed ground truth** |

The executable private-benchmark seam is documented by the repository harness:

```bash
PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  uv run python -m tools.parser_bench run \
  --manifest /absolute/path/to/private/manifest.jsonl \
  --parsers pymupdf,mineru,marker,docling,ppstructure \
  --output artifacts/parser-bench/<run-id>
```

This command was not run with a placeholder path.

### Official six before/after availability summary

| Evidence | Before hardening | After hardening |
|---|---|---|
| Six PDF identities, private manifest, and reviewed ground truth | Absent from checkout/local refs | Still absent; no per-document result can be reported |
| Router / PyMuPDF / PP-StructureV3 / admin extraction | No reproducible batch input | Not run; blocked rather than substituted with synthetic values |
| Critical-field correctness comparison | Original report absent, so no numeric baseline recovered | Covered by synthetic regressions; public score unchanged at `0.882` because it is not the private six-document corpus |

The six-document before/after comparison is therefore an availability result, not a
claim that the real PDFs passed. Remaining correctness failures on that corpus are
unknown until the private inputs, provider configuration, and reviewed ground truth
are supplied.

## Remaining blockers before a 30+ document benchmark

- Supply the same six official PDFs, private manifest, and human-reviewed Level A/B
  ground truth outside Git; do not add private PDFs to the repository.
- Install and record the real OCR provider/configuration needed for scanned cases;
  PP-StructureV3 was not available in this environment.
- Rerun router, PyMuPDF, live PP-StructureV3, and `parse_admin_document` for all six,
  recording text chars, critical fields, hierarchy count, warnings, and review state
  per document without replacing unavailable values with guesses.
- Expand only after those results are manually reviewed; the 30+ corpus and all Phase 1
  hard gates remain unmet.

No ADR-001 decision, parser-strategy change, Phase 4/RAG/chat implementation, raw OCR
mutation, or private-PDF commit was made.
