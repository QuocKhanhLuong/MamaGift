# Real-PDF Correctness — Design Review

- **Run:** `20260817T132911Z`
- **Stage:** design
- **Scope:** review of the shared dirty-tree changes and the requested strategy/research documents
- **Decision:** **not ready for six-PDF evidence**; bounded corrections are required

## Evidence boundary

Reviewed `docs/research/2026-08-17-real-pdf-correctness.md`,
`docs/strategies/2026-08-17-real-pdf-correctness.md`,
`docs/decisions/ADR-001-parser-selection.md`, `docs/PHASE_STATUS.md`,
`docs/03_DOCUMENT_PIPELINE.md`, and `docs/05_TEST_STRATEGY.md` against the current
changes in:

- `packages/docpipe/python/mamagift_docpipe/admin/parser.py`
- `packages/docpipe/python/mamagift_docpipe/admin/patterns.py`
- `tools/parser_bench/critical_fields.py`
- `tests/unit/test_admin_parser_ocr.py`

At the initial inspection, the private manifest, six official PDFs, independently
authored labels, and `docs/eval/real-pdf-batch-01-results.md` were absent. An untracked
evaluation file appeared later during the shared run and was inspected without being
edited; it still reports the official six-document run as blocked. No real-PDF result
or parser selection evidence can be inferred. Its statements that benchmark and admin
semantics are already the same are not supported by the current `runner.py` call path
or the separate benchmark extractor, so this design review does not treat them as
acceptance evidence.

Observed on the current tree:

- `make admin-parser-golden-tests`: **13 passed**.
- `make parser-benchmark-smoke`: **11 passed**.
- `UV_CACHE_DIR=.uv-cache PYTHONPATH=packages/contracts/python:packages/docpipe/python uv run pytest -q tests/unit/test_admin_parser_ocr.py`: **8 passed**.
- `make parser-contract-tests`: **173 passed, 1 skipped**.
- `make backend-typecheck`: **passed**.
- `make backend-format-check`: **failed**; all three changed Python files need Ruff formatting.
- `make backend-lint`: **failed**; `patterns.py:61` has E501.
- `git diff --check`: **passed**.

The earlier research report records a different intermediate dirty-tree failure
snapshot. The results above are the final checks run for this review; neither set
constitutes real-PDF evidence.

## Options and recommendation

### Option A — One conservative semantic path (recommended)

Keep the existing canonical/admin model and make benchmark scoring call the same
administrative enrichment path, or extract one shared conservative critical-field
selector used by both paths. Add only the missing candidate guards, integrity checks,
and tests.

This is the smallest correctness-preserving change and removes benchmark/product
semantic drift. It requires runner wiring and careful preservation of the existing
canonical schema, but no endpoint, migration, parser strategy, or ADR change.

### Option B — Keep two extractors and enforce parity tests

Retain the benchmark-only extractor and add a parity suite against
`parse_admin_document` for every critical-field fixture.

This has lower immediate integration cost, but duplicates date/number/provenance
semantics and makes future drift likely. It is not sufficient for the strategy’s
FR-05 unless parity is continuously proven, including source provenance and
ambiguity behavior.

### Option C — Defer correctness changes until the private Phase 1 benchmark

Run the six-PDF/30-PDF evidence process first and treat the current implementation as
experimental.

This protects ADR-001 from premature conclusions, but leaves known wrong-date and
benchmark-integrity paths active. It is acceptable only as an explicit blocked state,
not as a passing implementation gate.

**Recommendation:** Option A, bounded to the corrections below. Do not broaden this
increment into parser selection, OCR model work, schema redesign, or real-PDF
publication.

## Requirement review

| Requirement | Assessment | Concrete evidence / required correction |
|---|---|---|
| Context-aware issue-date scoring | **Partial; blocker** | `parser.py:626-694` adds page, header, top-of-page, nearby, and provider provenance signals, but it never links a place/date carrier to the extracted issuer/admin context. It also scans all non-furniture blocks and can select a body/later-page date. Implement the strategy’s page-one heading-area guard and explicit issuer/place context relation; date-carrier provenance must remain only the carrier block. |
| Referenced-date suppression | **Blocker** | `parser.py:672-675` falls back from `unreferenced` to `evidence`; when every date is marked referenced/effective, a referenced date is still emitted as `issue_date`. Suppression is also block-local (`parser.py:484-492`), so markers split across OCR blocks are not reliably associated. Return unavailable when no unreferenced defensible candidate exists and cover split-block context. |
| Ambiguity review | **Mostly satisfied in product path** | Close conflicting numbers are capped below the `0.75` review threshold (`parser.py:551-566`); conflicting dates are capped below threshold (`parser.py:676-685`); `_quality` then sets `requires_user_review`. Retained values have one supporting block/page. Add explicit tests for unequal-score conflicts and field-specific ambiguity semantics; do not rely only on generic low-confidence warnings. |
| OCR aliases without raw mutation | **Pass for covered cases; scope caution** | The bounded aliases and compact dates in `patterns.py` preserve source text; `parse_admin_document` constructs a new document and the 8 OCR tests pass. The diff additionally broadens `CHUONG`, `MUC`, `DIEU`, `DIU`, `KHOAN`, and `PHU LUC` forms beyond the strategy’s named observed matrix. Constrain those aliases or add reviewed synthetic coverage and evidence; no general fuzzy repair is authorized. |
| Conflicting-number conservatism | **Product path passes current regression** | `_extract_number` groups normalized values and retains a low-confidence candidate on close conflict. Keep exact source block/page provenance and ensure exact-vs-alias conflicts cannot become unreviewed. The benchmark implementation has different candidate filtering and remains unproven against this contract. |
| Provenance | **Product path pass; benchmark gap** | `ExtractedField` provenance is preserved and current golden/OCR tests verify it. `tools/parser_bench/critical_fields.py` returns only a value dictionary, while `runner.py:205-215` scores that divergent result and never enriches with `parse_admin_document`. Benchmark evidence therefore cannot prove field source provenance. |
| Benchmark consistency/integrity | **Blocker** | The current diff does not touch `tools/parser_bench/runner.py` or `manifest.py`. The runner still uses a separate extractor; `_DEADLINE` does not match `chậm nhất là ngày` and `_iso_date` does not reject impossible dates (`critical_fields.py:35-38,50-51,219-221`). Private absolute paths are not checked for repository containment (`manifest.py:143-157`), and ground-truth `document_id` is not checked against the manifest entry before scoring. The later untracked eval report’s claim of shared semantics conflicts with these source-backed call paths. These are required FR-05 corrections. |
| Phase 1 / ADR-001 / private-PDF boundary | **Pass as a boundary, not an exit** | No current change selects a provider, changes routing, or edits ADR-001. `ADR-001` must remain `PENDING EVIDENCE`; six PDFs cannot satisfy its ≥30-document requirement. Private PDFs, manifests, labels, excerpts, and raw artifacts must stay outside Git. |

## Required corrections before implementation acceptance

1. Correct the product issue-date selector: no referenced-only fallback; restrict
   selection to a defensible page-one administrative heading carrier; include explicit
   issuer/place context evidence and bounded cross-block reference/deadline context.
2. Preserve the current one-field-per-name schema and raw block text. For unresolved
   date/number conflicts, either omit the field or retain one candidate below `0.75`
   with `needs_review`, exact source block/page, and a field-specific quality warning.
3. Remove benchmark/product drift through Option A. The benchmark must exercise the
   same conservative semantics and expose or validate supporting canonical provenance;
   it must not copy parser output into expected truth.
4. Add the missing benchmark integrity corrections: repository containment for private
   absolute paths, manifest/ground-truth ID equality before scoring, valid-calendar
   deadline parsing including `chậm nhất là ngày`, and unavailable rather than zero
   when labels are missing.
5. Add deterministic coverage for the strategy matrix not covered by the current 8
   OCR tests: deadline-before-issue, reference/effective-only dates, invalid dates,
   numeric carrier dates, unapproved aliases, repeated-run determinism, benchmark
   identity/path checks, and provenance mismatch. Keep all committed inputs synthetic
   or sanitized.
6. Resolve the current format/lint failures in the changed files, then rerun the full
   final gates. Formatting is a required correction, not a reason to weaken the gate.

These are corrections to the current bounded implementation, not a rewrite. No new
endpoint, database migration, parser provider, OCR model, candidate-list schema, or
ADR decision is justified here; adding any would be YAGNI and outside the strategy.

## Final execution contracts

The implementation handoff is accepted only when the final code state satisfies all
of the following:

### Gate A — focused correctness

```bash
UV_CACHE_DIR=.uv-cache uv run pytest \
  tests/unit/test_admin_parser_ocr.py \
  tests/unit/test_benchmark_harness.py \
  tests/unit/test_metrics.py \
  tests/golden/test_admin_parser_golden.py -q
```

All approved cases pass, with no skipped or xfailed acceptance case.

### Gate B/C — Phase 1/2 and repository regression

```bash
make admin-parser-golden-tests parser-contract-tests ingestion-integration \
  backend-format-check backend-lint backend-typecheck
make check
```

Every command must exit zero from the final implementation state. Report actual
counts and skips; do not reuse historical phase-status counts.

### Gate D — six-PDF smoke

The six-PDF smoke is explicitly **UNAVAILABLE/BLOCKED in this checkout** because the
manifest, six PDFs, independently authored labels, and applicable live heavy-provider
environment are absent. No smoke pass, score, or provenance result may be claimed.

When supplied outside Git, validate and run exactly through the corrected benchmark
path:

```bash
PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  UV_CACHE_DIR=.uv-cache uv run python -m tools.parser_bench validate \
  --manifest /absolute/path/to/manifest.jsonl

PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  UV_CACHE_DIR=.uv-cache uv run python -m tools.parser_bench run \
  --manifest /absolute/path/to/manifest.jsonl \
  --parsers pymupdf,mineru,marker,docling,ppstructure \
  --output artifacts/parser-bench/real-pdf-batch-01
```

The external result must contain exactly six opaque cases, independent labels,
provider/version/configuration/run metadata, source hashes, field review/provenance
outcomes, and per-case `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN`. Missing input,
provider, ground truth, or live OCR capability is `BLOCKED`, never a fallback pass.
The result must state that ADR-001 remains `PENDING EVIDENCE` and that six cases do
not meet the ≥30-document Phase 1 exit criterion.

## Risks and handoff

- **Highest risk:** a plausible reference/effective date still reaches the product
  as `issue_date` when it is the only candidate.
- **Evidence risk:** current synthetic/contract passes establish software behavior only;
  they say nothing about private Vietnamese PDF quality or heavy-provider runtime.
- **Privacy risk:** publishing paths, excerpts, names, or raw provider artifacts would
  violate the project’s private-PDF boundary.
- **Maintenance risk:** retaining two critical-field oracles will reintroduce drift;
  prefer one semantic implementation or an explicit shared enrichment stage.

No production code, tests, existing documentation, evaluation artifact, commit, or
private input was modified by this review; only this design artifact is added. The
untracked evaluation artifact that appeared during the run was preserved untouched.
