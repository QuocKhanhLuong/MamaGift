# Real-PDF parser correctness audit — 2026-08-17

## Scope and evidence boundary

This is a read-only audit for AgenTeam run `20260817T132911Z`, limited to
repository-backed parser correctness. The required planning/contract documents were
read: `docs/03_DOCUMENT_PIPELINE.md`, `docs/05_TEST_STRATEGY.md`,
`docs/08_API_AND_DATA_CONTRACTS.md`, `docs/09_CODEX_EXECUTION.md`, and
`docs/PHASE_STATUS.md`.

Checkout: branch `ateam/run/20260817T132911Z`, `HEAD`
`194bafe000d6d908139163fae4f695fb8265d9e3`. The requested
`docs/eval/real-pdf-batch-01-results.md` is absent from the checkout. A search of all
local Git refs (`git log --all -- ...` and `git rev-list --all --objects`) found no
copy of that path. There are therefore no repository-backed real-PDF batch results,
real-PDF ground truth, parser winner, or real-PDF findings to report. None are
inferred here.

The initial status check was clean. During this audit, concurrent uncommitted edits
appeared in `admin/parser.py`, `admin/patterns.py`, and
`tools/parser_bench/critical_fields.py`, with untracked strategy/test files also
appearing. Those changes are preserved and are not attributed to this audit. Findings
below explicitly distinguish the committed `HEAD` baseline from the later dirty-tree
snapshot.

The tracked public benchmark contains eight synthetic PDFs in
`benchmarks/parser/manifest.jsonl`: three have authored Level A/B/C ground truth and
five have route labels only. The benchmark README explicitly says this corpus is not
sufficient to choose a parser (`benchmarks/parser/README.md:56-73`). The phase status
also records that the private 30-document corpus and heavy-provider measurements are
unavailable (`docs/PHASE_STATUS.md:168-183`).

## Findings

### Confirmed implementation defects in the committed `HEAD` baseline

| Priority | Location | Current behavior | Correctness impact |
|---|---|---|---|
| P1 | `tools/parser_bench/critical_fields.py:33-40,48-70` | The benchmark extractor is case-sensitive for `Số`, extracts the first date in the whole joined document as `issue_date`, does not match `chậm nhất là ngày`, and formats dates without calendar validation. Reproduction: `SỐ: 57/QĐ-UBND` does not match; a deadline before the issue line is selected as the issue date; `chậm nhất là ngày 25 tháng 8 năm 2026` does not match. | Benchmark critical-field scores and severity-3 gates can be wrong even when the canonical/admin parser is correct. |
| P1 | `tools/parser_bench/runner.py:205-215` versus `packages/docpipe/python/mamagift_docpipe/admin/parser.py:648-676` | Benchmark scoring calls `tools.parser_bench.critical_fields.extract_critical_fields`, not `parse_admin_document`; the production Vietnamese admin extraction path is not what the benchmark evaluates for critical fields. | A passing benchmark result would not establish correctness of the production admin fields/provenance, and a failing result could be caused by a second, divergent extractor. |
| P1 | `tools/parser_bench/manifest.py:143-157` | The private-manifest check requires an absolute path but does not verify that it is outside the repository. Reproduction: an absolute path to the tracked synthetic PDF with `provenance=private` returns no validation problem. | A private PDF under the repository can be accepted by the manifest validator, contrary to `docs/05_TEST_STRATEGY.md:41-47` and `docs/09_CODEX_EXECUTION.md:102-108`. |
| P1 | `tools/parser_bench/manifest.py:75-95,138-140` and `tools/parser_bench/runner.py:205-208` | Ground truth validates its own schema but the runner never checks `truth.document_id == entry.document_id`. | A manifest can score one document against another document's ground truth without a validation error. This is a benchmark-integrity defect, not a real-PDF result. |
| P2 | `tools/parser_bench/metrics.py:149-165` | `diacritic_preservation` compares only the count of combining marks, not their positions or the normalized characters. | Text with different Vietnamese diacritics but the same number of marks can receive a perfect diacritic score; this conflicts with the Unicode/text-fidelity intent in `docs/03_DOCUMENT_PIPELINE.md:91-106`. |
| P2 | `tools/parser_bench/metrics.py:374-391` | Page attribution is considered correct when at least 50% of expected page words overlap, using sets. | Text moved to the wrong page, or a page with substantial missing content, can pass attribution; this is weaker than the documented page-provenance requirement. |

The concurrent dirty-tree edit to `tools/parser_bench/critical_fields.py` partially
addresses the first two baseline extractor issues by reusing admin patterns and
candidate selection. It is not part of `HEAD`, and no targeted benchmark tests were
added or validated for that edit; the baseline findings remain the exact committed
implementation audit.

### Admin-parser/OCR gaps observed in concurrent workspace input

After the initial clean checkout, an untracked file appeared:
`tests/unit/test_admin_parser_ocr.py`. It is preserved and was not authored, staged, or
treated as committed evidence. Concurrent uncommitted edits also appeared in the
tracked admin parser and patterns files. Against that current working tree, the
latest run produced **5 failed, 3 passed**. Its synthetic tests expose these current
behavior gaps:

- The concurrent pattern edits now recognize compact dates such as
  `ngày31tháng03năm2026`, but `_extract_issue_date` still classifies the selected
  header candidate as only `0.65` confidence when a referenced body date is also
  present (`admin/parser.py:_date_marker_kind`, `_extract_issue_date`). The test
  requires the unambiguous header candidate to remain at least `0.75` and identifies
  the missing reference classification for `Căn cứ Quyết định số ... ngày ...`.
- The subject pattern still recognizes accented `Về việc`/`V/v` but not the
  unaccented OCR form `Ve viec:` (`admin/patterns.py:53`). The current `S:` number
  alternative and bounded `Điu`/`khon` hierarchy alternatives do pass their direct
  regression cases; no failure is claimed for those current working-tree changes.
- Conflicting document-number candidates are currently omitted when their scores are
  close (`admin/parser.py:_extract_number`), rather than returning a selected
  low-confidence field with `needs_review` as the concurrent regression expects.

These are synthetic OCR text-layer observations, not evidence about any private PDF.
They should be resolved only with explicitly approved OCR-domain fixtures; no raw OCR
or private PDF was added. The concurrent tracked edits and untracked test remain
outside `HEAD` and were not changed by this audit.

## What is currently verified

The following commands ran successfully against the checked-in synthetic corpus:

- Before concurrent edits became visible: `make parser-benchmark-smoke` passed **11
  tests**, `make admin-parser-golden-tests` passed **13 tests**, and
  `make parser-contract-tests` passed **165 tests with 1 skip**. The direct combined
  run passed **55 tests**. Each run emitted only the recorded dependency deprecation
  warnings.
- On the current dirty tree, `make parser-benchmark-smoke` still passes **11 tests**;
  it also validates the eight-entry manifest and all six route labels.
- On the current dirty tree, `make admin-parser-golden-tests` reports **11 passed, 2
  failed**.
- The earlier contract result was **165 passed, 1 skipped**, five dependency
  deprecation warnings. The skip is the provider-availability branch documented by the
  test environment.

These tests establish deterministic harness, schema, routing, synthetic golden, and
resource-budget behavior only. They do not establish real-PDF parser correctness.
`docs/05_TEST_STRATEGY.md:17-27,96-143,349-355` explicitly separates deterministic
CI tests from manual real-document evaluation. The current dirty-tree golden failures
are recorded as a validation failure, not hidden by the earlier passing run.

After those concurrent edits became visible, the current dirty tree was rechecked with
`make admin-parser-golden-tests`: **11 passed, 2 failed**. Both failures are
`issue_date` confidence regressions in the existing tracked golden cases: the current
scoring returns `0.79`, below the expected `0.90`, even though the normalized date and
provenance remain correct. This is a current tracked-test failure and must be resolved
before treating the concurrent parser edits as validated.

## Smoke-input and command availability

Available now:

```text
tracked synthetic PDFs: 8
synthetic Level A/B/C ground truth documents: 3
route-only synthetic documents: 5
private manifest: unavailable
private PDFs: unavailable
real-PDF batch result artifact: unavailable
heavy-provider measured outputs: unavailable
```

The lightweight command is available and verified:

```bash
make parser-benchmark-smoke
```

The documented private run command is available in the harness but cannot be executed
in this checkout because its required manifest, PDFs, and reviewed ground truth are
not present:

```bash
PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  uv run python -m tools.parser_bench run \
  --manifest /absolute/path/to/private/manifest.jsonl \
  --parsers pymupdf,mineru,marker,docling,ppstructure \
  --output artifacts/parser-bench/<run-id>
```

No real-PDF smoke result, score, or ground-truth comparison is claimed. The parser
decision remains benchmark-gated as required by `docs/03_DOCUMENT_PIPELINE.md:21-41,
61-87,146-179` and `docs/09_CODEX_EXECUTION.md:70-108`; ADR-001 and parser strategy
were not edited.

## Bounded implementation and test plan

This plan is intentionally limited to correctness hardening; it does not select a
parser, change ADR-001, modify parser strategy, ingest raw OCR, or introduce private
PDFs.

1. Add manifest-integrity tests first: reject private paths inside the repository and
   reject a ground-truth file whose `document_id` differs from the manifest entry.
2. Make benchmark critical-field extraction share the same conservative date/number
   semantics as the admin path, or explicitly run a separate admin-enrichment scoring
   stage. Preserve absence as unavailable; never repair text by guessing. Add tests for
   uppercase/abbreviated number labels, deadline-before-issue ordering,
   `chậm nhất là ngày`, and invalid calendar dates.
3. Add synthetic, clearly labeled OCR regression cases for compact date spacing,
   unaccented subject labels, conflicting candidates, and hierarchy variants. Require
   source block/page provenance and `needs_review` for ambiguity. Keep raw input text
   unchanged in the canonical artifact.
4. Strengthen metric tests so Vietnamese diacritic correctness compares normalized
   text identity, and page attribution requires an explicit page-level contract rather
   than a 50% word-set heuristic. Keep missing labels unavailable, never zero.
5. Only after the private corpus and reviewed ground truth are supplied, run the
   private manifest through `validate` and the full benchmark, inspect per-document
   critical-field/provenance failures, and produce derived results. Do not use those
   results to rewrite ADR-001 until the minimum 30 representative real PDFs and the
   documented hard gates are satisfied.

## Non-actions and final status

I did not edit code, ADR-001, parser strategy, raw OCR, private PDFs, or existing user
changes. No commit was created. The workspace contains the requested report plus
concurrent uncommitted edits to `admin/parser.py`, `admin/patterns.py`, and
`tools/parser_bench/critical_fields.py`, and untracked strategy/test files including
`docs/strategies/2026-08-17-real-pdf-correctness.md` and
`tests/unit/test_admin_parser_ocr.py`; all remain untouched.

Conclusion: repository-backed synthetic and contract gates were green before the
concurrent edits, but the current dirty tree is not green because its admin golden
gate has two confidence failures. Real-PDF correctness is **not evaluated** and cannot
be inferred. The confirmed benchmark and admin-parser gaps above must be addressed
before any real-PDF batch result can support the parser decision.
