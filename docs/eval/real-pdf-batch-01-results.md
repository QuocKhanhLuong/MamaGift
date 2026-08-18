# `real-pdf-batch-01` correctness results

Date: 2026-08-17, updated 2026-08-18 (twice: software hardening, then a live six-document rerun)
Status: software hardening complete (benchmark/production semantic unification,
benchmark-integrity gates); the six official documents were recovered from the public
government portal and run live. Zero Severity-3 wrong-value failures. PP-StructureV3
OCR remains unavailable, so real critical-field coverage is still zero — see
"Decision gate" below (`FIX_BEFORE_EXPANDING`).

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

## Official six-document rerun (2026-08-18, live)

No longer blocked on missing inputs. The same six public official documents named in
this task were recovered from the Vietnamese Government's official legal-document
portal (`vanban.chinhphu.vn` / `datafiles.chinhphu.vn`), run through the real harness,
and scored against ground truth authored independently — from the portal listing and
corroborating secondary legal sites (`thuvienphapluat.vn`, `luatvietnam.vn`) — **before**
any parser output was inspected. Source PDFs, the private manifest, and ground-truth
files were kept in `/Users/alvinluong/mamagift-private-eval/real-pdf-batch-01/`,
outside this repository; nothing under that path was committed. Only opaque case IDs
and SHA-256 prefixes are recorded below.

Command actually run:

```bash
PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  UV_CACHE_DIR=.uv-cache uv run python -m tools.parser_bench run \
  --manifest /Users/alvinluong/mamagift-private-eval/real-pdf-batch-01/manifest.jsonl \
  --parsers pymupdf,ppstructure \
  --output artifacts/parser-bench/real-pdf-batch-01
```

`mineru`, `marker`, and `docling` were not requested: none has a hypothesis for these
born-official/scanned documents beyond what PyMuPDF/PP-StructureV3 already cover, and
none is installed in this environment; omitting them is not a substitution for a
result. Run at commit `0c6694f8f81ab9b9516d414b04f8f4a0f2cbd494`, `pymupdf 1.28.2
(mupdf 1.28.2)`, adapter configuration hash `44136fa355b3678a`, device `cpu`,
2026-08-18T05:14:02Z–05:14:10Z.

### What the six PDFs actually are

Every one of the six is a scanned, digitally-signed gazette copy: PyMuPDF's text layer
is 8–195 characters per document (a signature-verification stamp fragment, e.g. the
digits of the document number and signing date), not the document body. This was
discovered by reading the raw PyMuPDF text extraction directly — independently of
`parse_admin_document`'s candidate selection — before authoring ground truth, and is
the same class of gap ADR-001 and prior evidence already flagged: PP-StructureV3
(`paddleocr`) is required for the OCR route and remains **not installed**
(`provider_unavailable`, all six `ppstructure` runs `failed`). This is not a new
defect; it is the same environment blocker recorded in every prior pass in this file.

### Per-document results (`pymupdf`, real PP-StructureV3 = BLOCKED for all six)

| File (case ID) | SHA-256 (16) | Route | Route conf. | Pages | Text chars | Blocks | Document type | Document number | Issuer | Issue date | Title | Deadline | Hierarchy | `requires_user_review` | Warnings |
|---|---|---|---:|---:|---:|---:|---|---|---|---|---|---|---:|---|---|
| `13-2026-TT-BGDDT.pdf` | `02a08b8b8c2d2e48` | scanned | 1.00 | 15 | 8 | 17 | not found | not found | not found | not found | not found | not found | 0 | **true** | `document_number: not found`; `issuer: not found`; `issue_date: not found`; `title: not found` |
| `19-2026-TT-BGDDT.pdf` | `c21c999d74611aa6` | scanned | 1.00 | 4 | 8 | 6 | not found | not found | not found | not found | not found | not found | 0 | **true** | same four `not found` warnings |
| `22-2026-TT-BGDDT.pdf` | `3bed04448f0564fb` | scanned | 1.00 | 10 | 8 | 12 | not found | not found | not found | not found | not found | not found | 0 | **true** | same four `not found` warnings |
| `38-2026-QD-TTg.pdf` | `4818b92f86c99b23` | scanned | 0.93 | 15 | 193 | 19 | not found | not found | not found | not found | not found | not found | 0 | **true** | same four `not found` warnings |
| `41-2026-TT-BGDDT.pdf` | `2282255d5ae73c6f` | scanned | 1.00 | 19 | 13 | 21 | not found | not found | not found | not found | not found | not found | 0 | **true** | same four `not found` warnings |
| `47-2026-TT-BGDDT.pdf` | `a97c052c41b899d5` | scanned | 1.00 | 3 | 10 | 6 | not found | not found | not found | not found | not found | not found | 0 | **true** | same four `not found` warnings |

`document_type`, `document_number`, `issuer`, `issue_date`, `title`, and `deadline`
are the `parse_admin_document` result on the same canonical document
`run_document` persisted, computed by calling the exact function the unified
benchmark path (and `run_ingestion`) uses — not a separate read. No `ExtractedField`
was produced for any of the six documents on any field: `extracted_fields` is `[]` in
every case. **This is honest absence, not a wrong guess**: every required field is
reported `not found` with a matching `critical_field_warnings` entry, and
`requires_user_review` is `true`. `PP-StructureV3`: **BLOCKED** for all six
(`provider_unavailable`: `paddleocr is not installed`) — not attempted with a
substitute engine, per the task's adapter-only constraint.

### Severity-3 failure evaluation (requirement 6)

| Failure class | Count | Detail |
|---|---:|---|
| Wrong document number | **0** | Never emitted; either the correct value or `not found` |
| Wrong issue date | **0** | Never emitted; either the correct value or `not found` |
| Wrong deadline | **0** | No deadline emitted or expected (none of the six titles carry an explicit deadline) |
| Wrong source/provenance | **0** | No field was emitted with provenance to verify; nothing to be wrong about |

The benchmark's `critical_field_accuracy` scorer reports `0.0` for all six documents
(`document_number` and `issue_date` both counted "wrong" because a missing value does
not equal the expected string — see `tools/parser_bench/metrics.py::critical_field_accuracy`,
line 417). That scorer does not distinguish "wrong value" from "absent value," so the
raw number understates correctness here: **zero Severity-3 wrong-value failures**
occurred; the six failures the scorer counts are all coverage gaps caused by the
missing OCR provider, not fabricated facts. This distinction, not the raw score, is
what this section reports.

## Known regression case: real-document confirmation

`19-2026-TT-BGDDT.pdf` (case `19_2026_tt_bgddt`, SHA-256 `c21c999d74611aa6…`) is the
real `19/2026/TT-BGDĐT`. Independent ground truth, authored from the portal listing
before this run: true issue date **2026-03-31**, referencing Thông tư 29/2024/TT-BGDĐT
dated **2024-12-30**. This is the exact date pair named as the historical regression.

Result: `parse_admin_document` emitted **no `issue_date` field at all** — not the
correct date, and critically **not** the old wrong value at high confidence. The
document has no usable text layer without OCR, so the parser correctly reports
`issue_date: not found` and `requires_user_review: true` rather than guessing. The old
failure mode (`issue_date = 2024-12-30` at high, unreviewed confidence) **does not
reappear**, on the real document. This satisfies one of the two outcomes the task
called acceptable — conservative `NEEDS_REVIEW`/unavailable — though not the
"correct value with defensible provenance" outcome, because no OCR text reached the
admin parser to select from. The synthetic regression tests
(`tests/unit/test_admin_parser_ocr.py`, see the earlier section) remain the only
evidence that the *contextual date-selection logic itself* — as opposed to its
behavior on zero input — prefers the header carrier over the reference date.

### Official six before/after summary

| Evidence | 2026-08-17 (blocked) | 2026-08-18 (live) |
|---|---|---|
| Six PDF identities, manifest, ground truth | Absent from checkout | Recovered from the public government portal; private, outside Git |
| Router / PyMuPDF / admin extraction | Not run | Run live on all six; route `scanned` (5× conf. 1.00, 1× conf. 0.93) |
| PP-StructureV3 real OCR | Blocked, provider unavailable | Still blocked, same cause (`paddleocr` not installed) — unchanged |
| Critical-field correctness | Unknown | Zero Severity-3 wrong-value failures; zero fields extracted (all coverage gaps from missing OCR, reported honestly as `not found`) |
| `19/2026/TT-BGDĐT` regression | Unverified on the real document | Confirmed: old wrong `2024-12-30 @ high confidence` does not reappear; result is `not found` + `requires_user_review: true` |

## Decision gate

**`FIX_BEFORE_EXPANDING`**

No unresolved Severity-3 wrong-value failure exists — that specific bar is met. The
recommendation is still not to expand, for a narrower reason than a wrong-value bug:
all six real official documents from this batch are scanned, digitally-signed gazette
PDFs with no usable born-digital text layer. Without a working OCR-capable adapter,
every additional document drawn from the same public source (`chinhphu.vn`) will
almost certainly reproduce the same all-fields-`not found`, zero-coverage result. That
would not be *misleading* — nothing wrong is asserted — but it would not exercise the
correctness logic this task hardened (contextual issue-date selection, ambiguity
handling, OCR-alias matching) at all, and a 15-document report where every real case
says "not found" would not be meaningfully closer to informing ADR-001 than the
current six.

Minimum fix required before expanding:

1. Install and record a working OCR-capable adapter — `PP-StructureV3` (`paddleocr`)
   is already implemented and contract-tested; it only needs to be installed and
   healthchecked in an environment with the necessary weights/runtime.
2. Rerun this same six-document manifest with that provider available and confirm at
   least the born-digital-appearing fraction of real documents (there may be none in
   this batch — all six are scans) produces `parse_admin_document` fields to actually
   evaluate the hardened contextual selection and ambiguity logic against.
3. Only then draw 9 more real documents to reach 15, mixing in confirmed born-digital
   cases if the corpus allows it, so the larger batch can measure more than "OCR was
   unavailable" on every row.

## Remaining blockers before a 30+ document benchmark

- Install and record the real OCR provider/configuration needed for the scanned
  route; `PP-StructureV3` remains unavailable in this environment (unchanged blocker
  across all three passes recorded in this file).
- `mineru`, `marker`, and `docling` remain uninstalled and unmeasured against any real
  document; no evidence exists for them beyond contract tests on recorded fixtures.
- Expand only after the OCR provider is available and results are manually reviewed;
  the 30+ corpus and all Phase 1 hard gates remain unmet.
- ADR-001 remains `PENDING EVIDENCE`; six documents — even with real OCR — would still
  be below the required ≥30-document threshold.

No ADR-001 decision, parser-strategy change, Phase 4/RAG/chat implementation, raw OCR
mutation, or private-PDF commit was made in any pass.
