# Real-PDF Critical-Field Correctness Strategy

- **Run:** `20260817T132911Z`
- **Stage:** `strategy`
- **Role:** PM
- **Author:** MamaGift PM agent
- **Date:** `2026-08-17`
- **Status:** Draft — software acceptance is specified; real-PDF evidence is blocked
- **Decision boundary:** ADR-001 remains `PENDING EVIDENCE`

## Context

MamaGift must not show a plausible but wrong issue date as an ordinary extracted fact.
For a family user verifying a Vietnamese administrative document, selecting a
reference date, deadline, or effective date instead of the document's issue date is a
Severity 3 failure. An equally harmful failure is hiding uncertainty or pointing the
user to a source block that does not support the displayed value.

The current Phase 2 administrative parser returns the first parseable date found in
the first 20 non-furniture blocks, excluding only configured deadline markers. It
raises confidence when the line contains a comma and `ngày`, but it does not compare
all plausible candidates or establish that the leading place belongs to the issuing
administrative authority. Issuer recognition is accent-insensitive but otherwise
prefix-based. Quality warnings cover missing and low-confidence fields, not explicit
candidate ambiguity.

The repository's eight PDF benchmark fixtures are synthetic and are not evidence of
real-document correctness. The requested `docs/eval/real-pdf-batch-01-results.md`, the
six official PDFs, their manifest, and independently authored expected values are not
present in this checkout. This strategy therefore defines the gates but records the
real-PDF gate as blocked. It does not infer expected dates, issuers, routes, or parser
outcomes.

## 2. Decision

Treat this as a bounded Phase 2 correctness increment with four outcomes, in order:

| Priority | Outcome | User benefit |
|---|---|---|
| P0 | Select an issue date from administrative context, not first occurrence | Prevents a plausible wrong date from appearing authoritative |
| P0 | Surface ambiguous critical facts as review-required with exact provenance | Lets the user verify uncertainty instead of correcting a hidden guess |
| P0 | Tolerate bounded, observed Vietnamese OCR forms | Preserves date, number, title, issuer, and hierarchy signals without general fuzzy guessing |
| P0 | Repair critical-field benchmark integrity | Ensures smoke scores exercise the same conservative semantics as the product path |
| P1 | Produce honest six-PDF smoke evidence when the external batch exists | Separates software confidence from real-document evidence |

The increment may change deterministic administrative-field extraction and its tests.
It must not select or promote a parser, change ingestion routing, or turn a six-file
smoke into the 30-document benchmark required to accept ADR-001.

## 3. Evidence basis and current constraints

This strategy is based on the current checkout:

- `packages/docpipe/python/mamagift_docpipe/admin/parser.py`: `_extract_issue_date`
  returns the first valid date candidate; `_extract_issuer` uses known prefixes;
  `_quality` warns only on missing or low-confidence required fields.
- `packages/docpipe/python/mamagift_docpipe/admin/patterns.py`: date parsing validates
  calendar dates; administrative text matching currently removes accents and changes
  case but does not handle bounded OCR edits.
- `packages/docpipe/python/mamagift_docpipe/pipeline.py`: `run_ingestion` is the real
  Phase 2 path and calls normalization followed by `parse_admin_document`.
- `tests/golden/test_admin_parser_golden.py`: current golden cases assert normalized
  values and page/block provenance, but contain one unambiguous issue-date carrier
  each.
- `docs/05_TEST_STRATEGY.md`: wrong dates and source citations are Severity 3; public
  fixtures must be synthetic or sanitized; private benchmark data stays outside Git.
- `benchmarks/parser/README.md`: committed fixtures exercise the harness but cannot
  choose a parser; private manifests use external absolute paths.
- `docs/decisions/ADR-001-parser-selection.md`: no production parser is selected and
  at least 30 representative real documents are required before acceptance.
- `docs/research/2026-08-17-real-pdf-correctness.md`: the task-specific read-only
  audit confirms divergent benchmark/admin critical-field extraction, weak private
  manifest containment checks, missing manifest/ground-truth identity validation, and
  synthetic OCR gaps for compact dates, abbreviated/unaccented labels, conflicting
  candidates, and hierarchy variants.

The research report also records green synthetic/contract gates and an untracked OCR
regression test that appeared concurrently. Neither those test results nor concurrent
uncommitted implementation changes are treated as proof that this strategy is met.
They are review inputs only; final evidence must come from the final implementation
state and the gates below.

## 4. Scope

### In scope

1. Issue-date candidate discovery, contextual ranking, deterministic selection, and
   explicit ambiguity behavior in the Phase 2 administrative parser.
2. A bounded matcher for Vietnamese authority and issue-place context that tolerates
   specified OCR variation without rewriting source text.
3. Provenance and review semantics for issue-date candidates produced by this logic.
4. Bounded OCR-domain matching for the observed date/number/subject/issuer/hierarchy
   forms documented by the task-specific research.
5. Minimum benchmark-integrity fixes needed to make critical-field smoke evidence
   truthful: product-path semantics, private-path containment, and manifest/ground-
   truth identity.
6. Synthetic unit/golden tests, regression gates, and an external six-PDF smoke gate.
7. A factual results artifact at `docs/eval/real-pdf-batch-01-results.md` only after
   the external inputs have actually been supplied and run.

### Constraints

- Keep the existing `CanonicalDocument` and `ExtractedField` public shapes unless a
  later technical review proves an additive field is unavoidable. No database
  migration is authorized by this strategy.
- OCR tolerance must use an explicit allow-list of observed administrative forms. It
  must not create a new canonical place field, rewrite source/issuer text, or become a
  general edit-distance matcher.
- A candidate date must be a valid calendar date. Invalid dates remain unavailable.
- The original block text, block ID, and page number remain the provenance source of
  truth.
- Real PDFs, absolute local paths, text excerpts, names, and other private content must
  not be committed. Derived evidence must be safe to publish.

## Functional Requirements

- FR-01: Select issue dates from administrative context rather than first occurrence.
- FR-02: Recognize only bounded, reviewed Vietnamese OCR forms.
- FR-03: Surface unresolved critical-field conflicts with review state and provenance.
- FR-04: Preserve existing administrative extraction behavior outside the fix.
- FR-05: Make critical-field benchmark evidence truthful and identity-safe.
- FR-06: Produce an honest external six-PDF smoke result when inputs exist.

### FR-01 — Contextual issue-date selection (P0)

1. The parser **MUST** evaluate all plausible issue-date candidates in the page-one
   administrative heading area before selecting a value; document order alone must
   not decide the winner.
2. A place-and-date carrier whose leading place matches the issuing administrative
   context **MUST** outrank an earlier date in a reference, body, validity, or deadline
   expression.
3. Explicit deadline expressions **MUST NOT** be selected as `issue_date`.
4. A date outside the page-one administrative heading area **MUST NOT** become the
   issue date merely because no better candidate was found.
5. Invalid calendar dates **MUST NOT** be emitted or coerced.
6. Given the same canonical blocks, selection and output ordering **MUST** be
   deterministic.

### FR-02 — Bounded OCR-tolerant Vietnamese administrative matching (P0)

1. Matching **MUST** tolerate Unicode composition differences, case, Vietnamese
   diacritics, compact/repeated whitespace, and non-semantic punctuation differences.
2. Date parsing **MUST** recognize valid compact OCR spacing represented by the
   approved synthetic forms `ngày31tháng03năm2026` and
   `ngày 31 tháng03 năm 2026`, while preserving the matched raw expression.
3. Document-number matching **MUST** support the existing `Số:` form and the observed
   bounded OCR forms `SO:` and `S:`. Subject matching **MUST** support the existing
   `V/v`/`Về việc` forms and the observed unaccented `Ve viec:` form.
4. Issuer matching **MUST** continue to recognize documented authority prefixes when
   diacritics are absent, including the synthetic `BO GIAO DUC VA DAO TAO` case.
5. Hierarchy matching **MAY** add only reviewed, explicit OCR aliases backed by
   synthetic tests, including `Điu` for `Điều`, `khon` for `Khoản`, and unaccented
   `Diem` for `Điểm` when the ordinal syntax is otherwise valid.
6. Matching **MUST NOT** use unconstrained edit distance, repair arbitrary prose,
   alter canonical block text, alter provenance, or silently rewrite an extracted
   raw value.

### FR-03 — Ambiguity, review state, and provenance (P0)

1. The parser **MUST NOT** publish a high-confidence or `unreviewed` critical value
   when conflicting issue-date or document-number candidates remain unresolved.
2. If a deterministic candidate is retained for review, it **MUST** have confidence
   below the existing `0.75` review threshold, `review_status: needs_review`, and
   block/page provenance pointing only to the source that supports the retained raw
   and normalized value. Returning no field is also acceptable when no candidate can
   be defended; returning an ordinary high-confidence value is not.
3. The quality report **MUST** identify the affected field as low-confidence or
   ambiguous without copying candidate source text, and ambiguity **MUST** set
   `quality_report.requires_user_review` to `true`.
4. For one clear issue date, `raw_value` **MUST** be the matched source expression,
   `normalized_value` **MUST** be its ISO date, and provenance **MUST** point only to
   the block and page that support that value.
5. If no defensible candidate exists, the existing `issue_date: not found` behavior
   **MUST** remain; the parser must not manufacture a placeholder date.
6. The result **MUST** contain at most one field for each extracted critical-field
   name. This increment applies the explicit conflict policy to issue date and document
   number; it does not redesign every other extractor or add candidate-list schema.

### FR-04 — Regression safety (P0)

1. Existing unambiguous `cong_van` and `quyet_dinh` golden outputs **MUST** retain
   their normalized issue dates and exact source provenance.
2. Document number, document type, title, signer, deadline, hierarchy, list, table,
   and recipient behavior **MUST NOT** regress.
3. The benchmark-only extractor in `tools/parser_bench/critical_fields.py` **MUST NOT**
   be treated as a substitute for the Phase 2 `run_ingestion`/administrative-parser
   path when proving this fix.

### FR-05 — Critical-field benchmark integrity (P0)

1. Real-PDF scoring **MUST** enrich canonical output through the same Phase 2
   administrative path as `run_ingestion`, or share one conservative critical-field
   implementation with that path. The divergent benchmark-only extractor must not be
   the sole oracle for issue date, document number, or provenance.
2. Benchmark critical-field behavior **MUST** be case-insensitive for approved number
   labels, select issue dates contextually rather than by first occurrence, recognize
   `chậm nhất là ngày` as a deadline marker, and reject invalid calendar dates.
3. Private-manifest validation **MUST** reject a PDF or ground-truth path located
   inside the repository even when the path is absolute.
4. The runner **MUST** reject ground truth whose `document_id` differs from the
   manifest entry before scoring.
5. Missing ground-truth layers **MUST** remain unavailable rather than zero, and no
   parser output may be copied into expected truth.

The research also found weak diacritic-preservation and page-attribution metrics.
Those broader metric redesigns are not required to accept this bounded critical-field
fix, but Gate E must disclose them and ADR-001 must remain pending until they are
resolved or explicitly waived in a later strategy.

### FR-06 — Honest six-PDF evidence (P1, currently blocked)

1. The external manifest **MUST** contain exactly six unique official-PDF cases and
   pass the existing manifest/file validator before execution.
2. Expected issue-date, issuer/admin-match, ambiguity, and provenance judgments
   **MUST** be authored by a human from each source before parser output is inspected.
   Missing labels are `BLOCKED`, never inferred from parser output.
3. Every case **MUST** execute live through a runner satisfying FR-05 and therefore
   through the Phase 2 administrative enrichment semantics. A divergent benchmark-
   only regex result, contract recording, mock, or generated PDF is not real-PDF
   evidence.
4. The evidence **MUST** record the parser name, installed provider version,
   configuration hash, route, run timestamp, source SHA-256, and whether the run was
   live or replayed. A replayed or unavailable provider cannot count as a live pass.
5. A scanned or garbled case without a live OCR-capable provider **MUST** be reported
   `BLOCKED`; it must not fall back to a text-layer result and be called successful.
6. `docs/eval/real-pdf-batch-01-results.md` **MUST** report each case and every gate as
   `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN`. It must not contain source paths, excerpts,
   personal names, or unapproved private values.
7. Six passing cases **MUST NOT** change ADR-001 from `PENDING EVIDENCE` or claim that
   the at-least-30-document parser-selection requirement is met.

## Non-Functional Requirements

### NFR-01 — Determinism

Two runs over identical canonical input and configuration must produce byte-equivalent
critical-field values, review states, warnings, and provenance ordering.

### NFR-02 — Privacy and evidence hygiene

Official/private source PDFs and local manifests remain outside Git. Published
evidence uses opaque case IDs and hashes and contains no source excerpt or private
filesystem path. Repository hygiene and secret scans must remain green.

### NFR-03 — Compatibility

No endpoint, database table, route ownership, parser strategy, or provider selection
changes are part of this increment. Existing consumers must continue to parse the
current canonical schema.

### NFR-04 — Performance

No new latency threshold is invented in this strategy because the repository has no
real-batch baseline for this matcher. The results artifact should record elapsed time
for observation only; performance is not a pass/fail gate for this correctness fix.

## Acceptance Criteria

### AC-01: Correct carrier beats first date (FR-01, FR-04)

**Given** a synthetic page-one heading where an earlier block contains another valid
date and a later place-and-date line matches the issuing authority, **when** the
administrative parser runs, **then** it emits the place-and-date value as `issue_date`
with only that carrier's block/page provenance.

### AC-02: Deadline/body dates do not leak (FR-01)

**Given** page-one or later text containing deadline, effective, review, or reference
dates but no defensible issue-date carrier, **when** parsing completes, **then** none of
those dates is emitted as `issue_date`; the field is unavailable and review is
required through the existing missing-field warning.

### AC-03: OCR-tolerant positive matrix (FR-02)

**Given** the approved invented compact-date, number-label, subject-label, unaccented
issuer, and hierarchy variants in FR-02, **when** administrative enrichment runs,
**then** the intended signal is recognized, source text remains byte-for-byte
unchanged, and extracted fields/nodes retain exact block/page provenance.

### AC-04: OCR-tolerant negative matrix (FR-02)

**Given** arbitrary misspellings or unapproved OCR variants outside the explicit
allow-list, **when** matching runs, **then** they are not repaired through general
fuzzy matching and cannot silently create a high-confidence critical fact or hierarchy
node.

### AC-05: Ambiguity is explicit (FR-03)

**Given** two conflicting page-one issue-date or document-number candidates that the
evidence cannot clearly separate, **when** parsing completes, **then** no ordinary
high-confidence value is published. Any retained candidate is below `0.75`, marked
`needs_review`, points exactly to its supporting block/page, produces a field-specific
warning, and sets `requires_user_review: true`; omission is acceptable when no
candidate is defensible.

### AC-06: Clear and absent states remain honest (FR-03, FR-04)

**Given** one clear candidate, **when** parsing completes, **then** its exact ISO value
and source provenance are emitted; **given** no valid candidate, **when** parsing
completes, **then** no plausible date is invented and the existing not-found warning
remains.

### AC-07: Existing golden behavior does not regress (FR-04)

**Given** all committed unit, contract, benchmark-smoke, ingestion, and golden
fixtures, **when** the focused and full gates run, **then** all pass without changing
unrelated field, hierarchy, or API behavior.

### AC-08: Benchmark integrity rejects false evidence (FR-05, NFR-02)

**Given** a private manifest whose absolute PDF or ground-truth path is inside the
repository, **then** validation fails; **given** ground truth with a mismatched
`document_id`, **then** scoring fails before metrics are written; **given** uppercase
or abbreviated number labels, deadline-before-issue ordering, `chậm nhất là ngày`, or
an invalid date, **then** the benchmark's critical-field result follows the same
conservative semantics as the Phase 2 path.

### AC-09: Real-PDF evidence is complete and honest (FR-06, NFR-02)

**Given** the six external PDFs, valid manifest, independent labels, and applicable
live providers, **when** the private smoke runs, **then** all six rows are recorded and:

- every expected clear issue date is an exact normalized match;
- every expected ambiguous case is review-required and contains all reviewed source
  locations without an asserted normalized date;
- every expected issuer/place contextual match passes;
- every emitted clear date has human-verified supporting block/page provenance;
- there are zero unreviewed wrong issue dates; and
- any provider/input/runtime failure remains `FAIL` or `BLOCKED`, not `PASS`.

Until those inputs exist and the run is observed, AC-09 is `BLOCKED`.

## 8. Required test matrix

The implementation must add deterministic tests for at least these cases:

| ID | Synthetic condition | Required result |
|---|---|---|
| T01 | Existing clear full-diacritic place-and-date line | Existing value/provenance unchanged |
| T02 | Earlier reference date, later matched place-and-date carrier | Carrier selected |
| T03 | Deadline appears before carrier | Carrier selected; deadline remains deadline |
| T04 | Only body/effective/reference dates | `issue_date` unavailable; review required |
| T05 | Invalid calendar date plus valid carrier | Invalid candidate ignored; carrier selected |
| T06 | Numeric date on a matched administrative carrier | Valid ISO date selected |
| T07 | Compact date spacing forms from FR-02 | Valid ISO date; raw expression/provenance preserved |
| T08 | `Số:` / `SO:` / `S:` number labels | Same normalized number; exact source provenance |
| T09 | `V/v` / `Về việc` / `Ve viec:` subject labels | Same intended title; raw source unchanged |
| T10 | Unaccented documented issuer prefix | Issuer recognized; source text not rewritten |
| T11 | Approved `Điu` / `khon` / `Diem` hierarchy aliases | Correct node/parent/source provenance |
| T12 | Unapproved arbitrary OCR misspelling | No fuzzy repair or high-confidence invented signal |
| T13 | Conflicting date and number candidates | Omitted or below-threshold `needs_review`; exact retained provenance |
| T14 | Same candidates in repeated execution | Byte-equivalent field/warning output |
| T15 | Private absolute path inside repository | Manifest validation rejects it |
| T16 | Manifest/ground-truth document ID mismatch | Runner rejects before scoring |
| T17 | Benchmark deadline before issue date and `chậm nhất là ngày` | Issue/deadline remain distinct |
| T18 | Benchmark uppercase/abbreviated number and invalid date | Number recognized; invalid date unavailable |
| T19 | Existing non-date fields and structure | No regression |

All text in this matrix must remain invented/synthetic. The official six PDFs are not
used to author committed expected fixtures.

## 9. Exact gates and evidence

### Gate A — Focused deterministic correctness

```bash
UV_CACHE_DIR=.uv-cache uv run pytest \
  tests/unit/test_admin_parser_ocr.py \
  tests/unit/test_benchmark_harness.py \
  tests/unit/test_metrics.py \
  tests/golden/test_admin_parser_golden.py -q
```

Pass condition: T01-T19 pass; no skipped or xfailed acceptance case.

### Gate B — Phase 1/2 regression suite

```bash
make admin-parser-golden-tests parser-contract-tests ingestion-integration \
  backend-format-check backend-lint backend-typecheck
```

Pass condition: every command exits zero. Report actual test counts; do not copy old
counts from phase status.

### Gate C — Repository-wide gate

```bash
make check
```

Pass condition: exits zero after the final implementation diff. A partial target pass
does not replace this gate.

### Gate D — External six-PDF preflight and smoke

The manifest and output paths are supplied at runtime. The manifest, PDFs, and ground
truth remain outside Git; the raw artifact directory must not be committed:

```bash
REAL_PDF_BATCH_01_MANIFEST=/absolute/path/to/manifest.jsonl
REAL_PDF_BATCH_01_OUTPUT=artifacts/parser-bench/real-pdf-batch-01

PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  UV_CACHE_DIR=.uv-cache uv run python -m tools.parser_bench validate \
  --manifest "$REAL_PDF_BATCH_01_MANIFEST"

PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  UV_CACHE_DIR=.uv-cache uv run python -m tools.parser_bench run \
  --manifest "$REAL_PDF_BATCH_01_MANIFEST" \
  --parsers pymupdf,mineru,marker,docling,ppstructure \
  --output "$REAL_PDF_BATCH_01_OUTPUT"
```

The benchmark implementation used here must already satisfy FR-05; an unchanged
divergent benchmark-only regex is not an acceptable oracle. Pass condition is AC-09 on
all six cases. If the manifest, PDFs, labels, or live applicable provider is absent,
Gate D is `BLOCKED`.

### Gate E — Evidence artifact audit

`docs/eval/real-pdf-batch-01-results.md` must include:

1. run timestamp, commit SHA, command, environment, and overall status;
2. manifest checksum and exactly six opaque case IDs/source SHA-256 values;
3. parser/provider version, configuration hash, route, live/replayed status, and
   per-case `PASS`/`FAIL`/`BLOCKED`/`NOT RUN`;
4. issue-date exact-match/ambiguity result, admin-context match result, provenance
   result, review state, and warning category without source excerpts;
5. actual Gate A-D command results from the same final code state;
6. explicit statements that the batch is six documents, ADR-001 remains pending, and
   no production parser or real-document readiness is claimed.

The file must not be created as a success report before Gate D runs. A blocker-only
artifact may be written later if the implementation stage needs to record an attempted
run, but it must say `BLOCKED` and contain no fabricated rows or values.

## Edge Cases

- EC-01: Date regex matches an impossible calendar date — ignore it; do not coerce.
- EC-02: OCR damage affects `ngày/tháng/năm` itself — do not invent a date unless
  the bounded date parser can establish a valid expression.
- EC-03: Matched place and issuer are on different page-one blocks — matching may
  use their context, but emitted field provenance belongs to the date carrier.
- EC-04: Multiple candidates normalize to the same ISO date — they are corroborating,
  not conflicting; emit the value with deterministic supporting provenance and do not
  raise a false ambiguity warning.
- EC-05: Multiple candidates normalize to different ISO dates and no candidate has
  stronger evidence — apply AC-05.
- EC-06: An approved OCR alias conflicts with a different exact administrative
  signal — exact evidence wins; the alias cannot create an unreviewed tie.
- EC-07: Parser/provider is unavailable on a real case — record `BLOCKED`; do not
  substitute a recording or generated fixture.
- EC-08: Ground truth is absent or was derived from parser output — the case is
  `BLOCKED` and cannot count toward AC-09.
- EC-09: Source provenance points to a block whose text does not contain the raw
  date expression — fail the case even if the normalized date is correct.

## API Contracts

No new endpoint is required. The existing canonical read surface remains unchanged:

```text
GET /api/v1/documents/{document_id}/canonical
GET /api/v1/documents/{document_id}/canonical?version={n}
```

The response continues to expose the current `CanonicalDocument`; this strategy adds
no request field, response field, status code, or route.

## Data Models

No new database entity or migration is required. The intended behavior remains within
the existing canonical model:

```text
interface ExtractedField {
  name: "issue_date"
  raw_value: string | null
  normalized_value: string | null
  value_type: "date"
  confidence: number
  review_status: "unreviewed" | "needs_review"
  source_block_ids: string[]
  source_page_numbers: number[]
  extractor: { name: string, version: string }
}
```

| Field | Type | Constraint in this increment |
|---|---|---|
| `name` | string | At most one `issue_date` and one `document_number` field |
| `raw_value` | string or null | Exact matched source expression; never OCR-rewritten |
| `normalized_value` | string or null | Valid ISO date or normalized number; never guessed |
| `confidence` | number | Below `0.75` when a conflicting retained candidate needs review |
| `review_status` | enum | `needs_review` for unresolved retained candidates |
| `source_block_ids` | string array | Only blocks supporting the retained value |
| `source_page_numbers` | integer array | Exact pages for the supporting blocks |

If technical design finds that candidate-level provenance cannot be represented
truthfully in this existing shape, that is a contract blocker requiring an additive
spec revision before implementation. It is not permission to overload unrelated
fields or add a migration silently.

## 12. Success criteria

The increment is software-accepted when Gates A-C pass and all deterministic
acceptance criteria AC-01 through AC-08 are satisfied. It is real-PDF-verified only
when Gates D-E satisfy AC-09.

Success means:

- zero Severity 3 wrong issue dates in the committed matrix;
- zero false-positive administrative matches in the negative matrix;
- 100% exact block/page provenance for emitted clear issue dates;
- 100% of expected ambiguous cases visibly require review, with any retained value
  below the review threshold and tied to its exact source;
- all six real cases reported honestly once available; and
- no change to ADR-001, parser promotion, or later-phase scope.

Passing Gates A-C while Gate D is blocked is valid evidence of software correctness,
but it is not evidence of real-PDF correctness or production readiness.

## 13. Remaining blockers

1. `docs/eval/real-pdf-batch-01-results.md` and its parent `docs/eval/` directory are
   absent.
2. The six official PDFs are absent from the checkout and no external paths were
   supplied.
3. The six-case manifest is absent.
4. Independently authored expected issue-date, issuer/admin-match, ambiguity, and
   provenance labels are absent; expected values must not be reconstructed from parser
   output.
5. At the inspected baseline, critical-field benchmark scoring diverges from the Phase
   2 admin path, private-path containment is incomplete, and ground-truth identity is
   unchecked. Concurrent uncommitted changes are not accepted evidence that these
   defects are closed.
6. The live provider needed by each scanned/garbled route has not been demonstrated in
   this checkout. Contract recordings do not satisfy that evidence gate.
7. ADR-001 remains `PENDING EVIDENCE`; even a successful six-file smoke is below the
   required at-least-30-document private benchmark and cannot close it.

## Out of Scope

- OS-01: Accepting or rewriting ADR-001, choosing a production parser, changing parser
  routing, or promoting PyMuPDF.
- OS-02: Phase 4 single-document Q&A, RAG, retrieval, embeddings, reranking, LLM inference,
  chat, assistant UI, or citation generation.
- OS-03: Phase 5 cross-document search/chat or Phase 6 training/fine-tuning.
- OS-04: OCR model training, OCR provider integration beyond what is already implemented,
  or correction of arbitrary OCR text.
- OS-05: Broad redesign of CER/WER, diacritic-preservation, or page-attribution metrics. Their
  known limitations must remain disclosed and cannot be used to accept ADR-001.
- OS-06: New endpoints, migrations, archive/filter behavior, feedback semantics, or UI
  redesign.
- OS-07: Committing official/private PDFs, private manifests, local paths, personal data, or
  source excerpts.
- OS-08: Fabricating missing expected values, provider runs, test results, or real-document
  readiness claims.
