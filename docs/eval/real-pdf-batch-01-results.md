# `real-pdf-batch-01` correctness results

Date: 2026-08-17, updated 2026-08-18
Status: software hardening complete, including benchmark/production semantic
unification and benchmark-integrity gates; official six-document rerun remains
blocked by missing evaluation inputs

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
provenance. As of the 2026-08-18 hardening pass below, the benchmark critical-field
extractor no longer has its own version or decision logic: it calls
`parse_admin_document` directly and reports `admin-rule-v1`/`1.1`, the same values
`run_ingestion` produces.

The synthetic regression equivalent is actual issue date `2026-03-31` with referenced
date `2024-12-30`. It asserts that the referenced value cannot return as an
unreviewed/high-confidence `issue_date`; the header candidate is selected when its
administrative context is clear.

## Known regression case: `19/2026/TT-BGDĐT`

The task explicitly named a prior real-document regression: true issue date
`2026-03-31`, with a referenced date `2024-12-30` (from a citation such as "Căn cứ
Quyết định số ... ngày 30 tháng 12 năm 2024") that the old parser could surface as
`issue_date` at high confidence. The six official PDFs — and therefore this exact
document — are still absent from the checkout (see below), so this cannot be run live
and no document number, issuer, or page/block value for the real `19/2026/TT-BGDĐT`
is claimed here.

What is verified is the software behavior on the identical date pair, through the
same code path the real document would use:

- `tests/unit/test_admin_parser_ocr.py::test_header_issue_date_beats_older_referenced_date_despite_compact_ocr_spacing`
  builds a synthetic header carrying issue date `2026-03-31` (including the compact
  OCR spacing form `ngày31tháng03năm2026`) alongside a `Căn cứ Quyết định số
  99/QĐ-BGDĐT ngày 30 tháng 12 năm 2024` reference line, and asserts
  `parse_admin_document` selects `2026-03-31` with source provenance pointing only to
  the header block.
- `tests/unit/test_admin_parser_ocr.py::test_referenced_body_date_is_never_presented_as_a_high_confidence_issue_date`
  asserts that when only the `2024-12-30` reference date is present, `issue_date` is
  absent (not emitted at any confidence) rather than defaulting to that referenced
  value.

Both pass on the current tree (see Gate A below). The specific old failure mode —
`2024-12-30 @ high confidence` — does not reproduce on this synthetic equivalent.
Whether it reproduces on the real `19/2026/TT-BGDĐT` PDF is unverified until that file
is supplied; this section reports software evidence, not a real-document pass.

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

## 2026-08-18 hardening pass: unification and benchmark integrity

The prior pass (above) hardened `parse_admin_document` but left a second,
independently-implemented critical-field extractor in
`tools/parser_bench/critical_fields.py`, used only for benchmark scoring. A design
review (`docs/designs/2026-08-17-real-pdf-correctness.md`) found this divergence was
still live at `HEAD`: the benchmark runner never enriched through
`parse_admin_document`, so a passing or failing benchmark score did not establish
anything about the production admin-parser path, and vice versa. The review also
found the private-manifest containment check accepted an absolute path inside the
repository, and the runner never verified that a ground-truth file's `document_id`
matched its manifest entry.

This pass closes exactly those three gaps, plus the deterministic test matrix they
implied. No parser strategy, ADR-001 status, canonical schema, endpoint, or migration
changed.

### Benchmark/production unification (requirement 1)

`tools/parser_bench/critical_fields.py` no longer contains its own issue-date,
document-number, deadline, subject or issuer selection logic (previously ~250 lines
duplicating `admin/parser.py`'s candidate scoring, context detection and conflict
handling). It now calls `parse_admin_document` — the exact function `run_ingestion`
calls — and reads `document_number`, `issue_date`, `issuer`, `title`, `signer`, and
`deadline` from the resulting `extracted_fields`. A benchmark critical-field result is
therefore now evidence about the same code path production uses, not a second oracle
that can drift from it. `tests/unit/test_admin_parser_ocr.py`'s conflicting-candidate
case now asserts the benchmark extractor returns exactly the same retained-or-omitted
value as `parse_admin_document`, rather than a hard-coded, independently-decided
`None`.

### Benchmark integrity (requirement 2)

- `tools/parser_bench/manifest.py::check_manifest_files` now rejects a private
  document or ground-truth path that is absolute but still resolves inside the
  repository root, not only a relative one. It also loads each referenced ground-truth
  file and rejects one whose `document_id` does not match its manifest entry, before
  any parser or scoring code runs.
- `tools/parser_bench/runner.py::run_document` carries the same `document_id` check as
  a defensive second layer, raising `ManifestError` if a mismatch reaches it directly
  (bypassing the CLI's pre-flight `check_manifest_files` call) rather than silently
  scoring one document against another document's expected values.
- Calendar-date validation (`packages/docpipe/python/mamagift_docpipe/admin/patterns.py::_iso_or_none`)
  and the `chậm nhất là ngày` deadline marker were already present in the shared
  `admin/patterns.py` module used by `parse_admin_document`; unification above means
  the benchmark path now inherits both instead of using its own weaker copies (the old
  benchmark-only `_DEADLINE` regex and unvalidated `_iso_date` formatter are deleted).
- Missing ground-truth layers were already reported `unavailable` rather than `0.0` in
  `tools/parser_bench/metrics.py` (verified by
  `tests/unit/test_metrics.py::test_missing_ground_truth_layers_are_unavailable_never_zero`);
  this pass did not need to change that behavior, only confirm it still holds after the
  refactor.

### New/updated regression tests

- `tests/unit/test_benchmark_harness.py`: private absolute path inside the repository
  is rejected for both the document and ground-truth path; ground-truth
  `document_id` mismatch is rejected by `check_manifest_files`.
- `tests/benchmark/test_benchmark_smoke.py`: `run_document` itself raises
  `ManifestError` on a ground-truth identity mismatch, exercised through a real
  PyMuPDF parse of a committed synthetic fixture.
- `tests/unit/test_metrics.py`: a deadline expressed as `chậm nhất là ngày` appearing
  before the issue-date line stays a distinct `deadline` value and does not leak into
  `issue_date`; an abbreviated uppercase number label (`SO:`) is recognized and an
  invalid calendar date (`ngày 31 tháng 4`) is never emitted as `issue_date`.
- `tests/unit/test_admin_parser_ocr.py`: the conflicting-candidate case now asserts
  benchmark/product identity instead of a hard-coded benchmark-only `None`.

### Gate results (this checkout, this diff)

| Gate | Command | Result |
|---|---|---|
| A — focused correctness | `pytest tests/unit/test_admin_parser_ocr.py tests/unit/test_benchmark_harness.py tests/unit/test_metrics.py tests/golden/test_admin_parser_golden.py` | **82 passed** |
| B — Phase 1/2 regression | `make admin-parser-golden-tests parser-contract-tests ingestion-integration backend-format-check backend-lint backend-typecheck` | **13 + 181 (1 skipped) + 220 passed**, format/lint/typecheck clean |
| C — repository-wide | `make check` | **exit 0** (Python suites, benchmark smoke, web lint/typecheck/build/unit/E2E) |
| D — six-PDF smoke | see below | **BLOCKED**, unchanged |

The skip in Gate B is the documented provider-availability branch
(`tests/contract/test_parser_adapters.py:148`, `pymupdf` is installed so the
"unavailable" branch is skipped), not a new failure.

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

Still **BLOCKED** as of the 2026-08-18 pass: no external manifest, PDFs, or reviewed
ground truth were supplied to this checkout in either pass. No per-document official
rows are reported because the checkout does not contain the six input identities,
private manifest, PDFs, or reviewed ground truth. Assigning synthetic names or
expected values would fabricate evidence.

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
- Rerun router, PyMuPDF, live PP-StructureV3, and `parse_admin_document` for all six —
  now reachable through the unified benchmark path documented above — recording text
  chars, critical fields, hierarchy count, warnings, and review state per document
  without replacing unavailable values with guesses.
- Confirm the real `19/2026/TT-BGDĐT` document specifically against the synthetic
  regression above once it is supplied: the true issue date must be `2026-03-31`, not
  the referenced `2024-12-30`, and not at unreviewed high confidence either way.
- Expand only after those results are manually reviewed; the 30+ corpus and all Phase 1
  hard gates remain unmet.

No ADR-001 decision, parser-strategy change, Phase 4/RAG/chat implementation, raw OCR
mutation, or private-PDF commit was made in either pass.
