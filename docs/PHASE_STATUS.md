# Phase Status

This file is the factual execution tracker for MamaGift. Update it at the end of each implementation phase.

## Current active phase

**Phase 4 — Self-hosted LLM and grounded single-document Q&A**

Status: `COMPLETE`

Known blocker: real scanned-document production evidence — ADR-001 `PENDING EVIDENCE`

Every Phase 4 exit criterion passed and every gate is green, so the execution status is
`COMPLETE` (see the exit-evidence entry at the end of this file). That is deliberately
separated from the limitation it carries: every fixture proving Phase 4 is born-digital or
synthetic, because the PP-StructureV3/OCR blocker means a real scanned Vietnamese document
still yields no critical fields. Phase 4 is therefore complete as specified and **not**
production-ready for scanned input. Phases 1, 2 and 3 stay `IN_PROGRESS` because that
blocker sits inside their own exit criteria, not merely alongside them.

### Previously active phase

**Phase 3 — Document archive and verification-first web UX**

Status: `IN_PROGRESS`

Exact `/goal`:

> Let a non-technical family user upload, find, inspect, and verify parsed documents without using developer tools.

Phase 3's web flows, component/integration/E2E tests and CI gates are implemented and
the local CI-equivalent gate is green on final hardening commit `c75c489`. The product is
demonstrable entirely from the browser, but it inherits Phase 1/2's open item: every
document shown was parsed by the undecided PyMuPDF baseline, so the UI correctly
displays every field/parse run as `degraded`/`Cần kiểm tra` rather than implying a
trustworthy production parse. Login is a screen/state handoff only
(`docs/design/01_INFORMATION_ARCHITECTURE.md` IA-00) with no real authentication
backend, as no such contract exists yet.

### Verification evidence snapshot — 2026-08-17

- Current publication: Phase 1 commit `4659fab647078b75015761857fd4baf317b5f64e`,
  Phase 2 commit `fc71f8b0178fbde82ffa2eebbffa43b9057e3699`, Phase 3 baseline
  `d8edafe9724a3cca3004c5ecb4708c9da6bd6928`, and Phase 3 hardening commit
  `e7cc7a8`, and final test/evidence commit `c75c489` are present on `main` and
  pushed to `origin/main`.
- Local CI-equivalent: `make check` **PASS** on `c75c489` — 411 Python tests passed
  with 1 provider-contract skip, parser/ingestion/migration/feedback gates passed,
  38 frontend tests passed, and the preserved desktop plus tablet/mobile Playwright
  suite passed 3/3. Frontend lint retained one existing `react-refresh` warning.
- GitHub CI: job definitions are present in `.github/workflows/ci.yml`, but live run
  status was unavailable on this date because `gh run list --repo
  QuocKhanhLuong/MamaGift --branch main` returned `error connecting to
  api.github.com`; no run ID or remote PASS is claimed here.

### Phase 2 progress carried forward

Phase 2's deliverables, tests and CI gates are implemented and green, but the phase is
**not production-complete**: its "selected parser strategy from ADR-001" deliverable
still depends on evidence that does not exist yet. Per
`docs/decisions/ADR-002-ingestion-parser-strategy.md` the strategy is configuration,
the baseline can never be silently promoted to production, and every run made while
ADR-001 is open is recorded as `degraded` and flagged for user review. Phase 3 also
completed two Phase 2 API-contract gaps that its own required tests exposed: the
`POST /api/v1/documents/{id}/feedback` correction endpoint (`docs/08_API_AND_DATA_CONTRACTS.md`
section 13, previously undocumented as implemented) and the `query`/`type`/`issuer`/
`from`/`to` filters on `GET /api/v1/documents` (section 14). Both are additive to the
existing schema (migration `0003_phase3_feedback`) and do not change any Phase 2
behavior.

### Phase 1 is still incomplete

Status: `IN_PROGRESS`

Exact `/goal`:

> Choose the document parsing foundation using evidence from Vietnamese administrative/legal PDF fixtures, not assumptions.

Every Phase 1 deliverable, test and CI gate is implemented and green, but the exit
criteria require benchmark evidence from at least 30 representative real Vietnamese
administrative documents. That corpus is private and is not in this repository, so
`docs/decisions/ADR-001-parser-selection.md` stays `PENDING EVIDENCE` and names no
production parser. Running the private benchmark is what closes both phases.

## Phase table

| Phase | Name | Status | Exit evidence |
|---|---|---|---|
| 0 | Repository and deterministic development foundation | COMPLETE | `941a5c4`; CI run `31787161450` |
| 1 | PDF parser benchmark and parser decision | IN_PROGRESS | Commit `4659fab`; harness, adapters, router, CanonicalDocument v1 and local CI gates complete; ADR-001 `PENDING EVIDENCE` |
| 2 | Production ingestion and Vietnamese administrative structure | IN_PROGRESS | Commit `fc71f8b`; ingestion pipeline, APIs, schema, admin parser and local Phase 2 gates complete; production parser strategy still blocked on ADR-001 |
| 3 | Document archive and verification-first web UX | IN_PROGRESS | Baseline `d8edafe` plus hardening `e7cc7a8`/`c75c489`; local Phase 3 gates complete, including desktop E2E and tablet/mobile smoke; inherits Phase 1/2's undecided parser strategy |
| 3.5 | Evaluation + Retrieval Foundation | COMPLETE | see entry below; deterministic foundation only — no embeddings, vector store, reranker, memory backend or LLM |
| 4 | Self-hosted LLM and grounded single-document Q&A | COMPLETE | see entry below; grounded QA green end to end on born-digital/synthetic fixtures only. Known blocker: real scanned-document evidence (ADR-001) |
| 5 | Cross-document institutional memory | IN_PROGRESS | Phase 4 is COMPLETE, so Phase 5 is unblocked; see the Phase 5 plan in `docs/superpowers/plans/` |
| 6 | Feedback dataset and offline continual OCR/domain adaptation | BLOCKED_BY_PHASE_5 | — |
| 7 | Production hardening and low-cost deployment | BLOCKED_BY_PHASE_6 | — |
| 8 | Meeting assistant | PARKED | document product must be stable/useful first |

## Status values

A phase's `Status:` is drawn from this closed set and nothing else. `tools/ci/check_docs.py`
enforces it, so a status outside this list fails CI rather than accumulating as drift.

```text
NOT_STARTED
IN_PROGRESS
BLOCKED
COMPLETE
BLOCKED_BY_PHASE_<N>
PARKED
```

### Execution status and carried limitations are separate

A phase that met every exit criterion is `COMPLETE`, even when it inherits a limitation that
is out of its scope to solve. The limitation is recorded on its own line instead of being
welded into the status value:

```text
Status: COMPLETE
Known blocker: <one line naming the limitation and the ADR or evidence that tracks it>
```

This exists because the tracker previously carried
`COMPLETE_WITH_EXTERNAL_OCR_BLOCKER`, which was not in the allowed set — a status that no
tool could validate and that conflated "did the phase finish?" with "what is still missing?".
Those are different questions and both deserve an honest answer. A `Known blocker:` line is
NOT a softer `COMPLETE`: if the blocker sits inside the phase's own exit criteria, the phase
is `IN_PROGRESS` or `BLOCKED`, not complete. Phases 1, 2 and 3 are the worked example —
they stay `IN_PROGRESS` for the same OCR blocker that Phase 4 merely carries.

## Update rules

When starting a phase:

1. set that phase to `IN_PROGRESS`;
2. keep later phases blocked;
3. do not mark previous phase complete unless its exit criteria really passed.

When completing a phase:

1. set it to `COMPLETE`;
2. add exit evidence below;
3. set the next phase to `NOT_STARTED`;
4. update “Current active phase” to the next phase only if instructed to proceed.

## Exit evidence log

Append entries in this format:

```text
### Phase N completed — YYYY-MM-DD

- Commit/PR: ...
- Test commands: ...
- CI status: ...
- ADR/benchmark artifacts: ...
- Known limitations carried forward: ...
```

Do not use this file for speculative progress or future plans; those belong in `04_PHASE_PLAN.md`.

### Phase 0 completed — 2026-08-14

- Commit/PR: `941a5c4` pushed to `main`.
- Test commands: `make check`; `uv lock --check`; `uv sync --locked`; `npm ci --prefix apps/web`; `docker compose -f infra/compose/docker-compose.yml config --quiet`.
- CI status: PASS — GitHub Actions run `31787161450` passed `docs-check`, `repository-hygiene`, `secret-scan`, backend lint/typecheck, PostgreSQL-backed backend tests, frontend checks/build, and Compose validation.
- ADR/benchmark artifacts: `docs/decisions/ADR-0001-phase0-stack.md`; documented repository placeholders only, with no parser benchmark implementation.
- Known limitations carried forward: Phase 0 intentionally has no document ingestion, OCR, parser, RAG, real LLM, or product UI. The local Docker daemon was unavailable during validation; the remote CI PostgreSQL service and Compose configuration checks passed.

### Phase 1 progress — 2026-08-16

- Commit/PR: `4659fab647078b75015761857fd4baf317b5f64e` is pushed to `main`; no
  separate PR reference was observable from this checkout.
- Test commands: the Phase 1 gate set is covered by the **PASS** `make check` in the
  verification snapshot above. The individual commands remain
  `make parser-contract-tests`; `make parser-benchmark-smoke`;
  `make backend-format-check`; `make backend-lint`; `make backend-typecheck`;
  `make backend-test`; `make docs-check`; `make repository-hygiene`; and
  `make secret-scan`.
- CI status: `parser-contract-tests` and `parser-benchmark-smoke` jobs are defined in
  `.github/workflows/ci.yml`; the manual heavy benchmark lives in
  `.github/workflows/parser-benchmark.yml`. Live GitHub status is unavailable; see
  the verification snapshot and no run ID is claimed.
- ADR/benchmark artifacts: `docs/decisions/ADR-001-parser-selection.md`
  (status `PENDING EVIDENCE`); eight synthetic fixtures with authored ground truth in
  `benchmarks/parser/`.

#### Delivered

- Provider-neutral `DocumentParser` interface with a shared structured error schema.
- Adapters for PyMuPDF (real, CI-executed), MinerU, Marker, Docling and
  PaddleOCR/PP-StructureV3 (implemented, contract-tested via recorded output, never
  executed against a real provider).
- PDF inspection/router covering good text layer, scanned, garbled text layer, mixed,
  rotated pages and encrypted/unsupported input; 8 of 8 fixtures routed correctly.
- `CanonicalDocument` v1 normalization with page/block provenance and deterministic
  block IDs.
- Benchmark manifest format, CLI, metrics beyond CER, weighted scoring with hard gates,
  and report generation.
- 148 passing tests across router, adapter contracts, canonical schema, metrics,
  harness and an end-to-end lightweight smoke path.

#### Blocking the phase exit

- **No real Vietnamese corpus is available in this repository.** Fewer than 30
  documents have been evaluated, and only synthetic ones. Exit criterion
  "at least 30 representative real PDFs have been evaluated" is unmet.
- **No heavy parser has ever been executed.** MinerU, Marker, Docling and
  PP-StructureV3 have zero measured results; their adapters are unverified against a
  real provider install.
- Consequently no winning parser strategy exists to check against the hard
  provenance/reading-order requirements.

#### To close Phase 1

Run the benchmark locally against the private corpus with the heavy providers
installed, commit only the derived `summary.json` / `summary.md`, then rewrite the
ADR-001 Decision section and set it to `ACCEPTED`.

### Phase 2 progress — 2026-08-17

- Commit/PR: `fc71f8b0178fbde82ffa2eebbffa43b9057e3699` is pushed to `main`; no
  separate PR reference was observable from this checkout.
- Test commands: the Phase 2 gate set is covered by the **PASS** `make check` in the
  verification snapshot above. The individual commands remain
  `make ingestion-integration`; `make admin-parser-golden-tests`;
  `make db-migration-test`; `make backend-format-check`; `make backend-lint`;
  `make backend-typecheck`; `make backend-test`; `make parser-contract-tests`;
  `make parser-benchmark-smoke`; `make docs-check`; `make repository-hygiene`;
  `make secret-scan`; and `make compose-config`.
- CI status: `ingestion-integration`, `admin-parser-golden-tests` and
  `db-migration-test` jobs are defined in `.github/workflows/ci.yml`; the migration
  job runs against the PostgreSQL service, the rest are CPU-only with no private
  data. Live GitHub status is unavailable; see the verification snapshot and no run
  ID is claimed.
- ADR/benchmark artifacts: `docs/decisions/ADR-002-ingestion-parser-strategy.md`
  (ACCEPTED); golden administrative fixtures in `tests/fixtures/admin/`.

#### Delivered

- Upload API with PDF/MIME, size, malformed and encrypted validation, content-addressed
  write-once original storage, and durable bytes before any job exists.
- `documents` / `jobs` / `parse_runs` tables and migration `0002_phase2_ingestion`,
  applied from empty and rolled back in tests on both SQLite and PostgreSQL.
- Document and job state machines with every legal transition tested and every illegal
  one rejected; worker availability is never encoded in document status.
- Job leases with expiry requeue, idempotency keys, bounded retries with backoff, and
  reprocess that adds a new parse-run version while keeping every earlier run intact.
- Configurable parser strategy (ADR-002): route to capability to parser, baseline
  usable only for development/CI, production refuses to parse while ADR-001 is open.
- Vietnamese administrative parser: `Chương/Mục/Điều/Khoản/Điểm`, `Phụ lục`, numbered,
  lettered and bulleted lists, `Nơi nhận`, title blocks, signature blocks and
  pipe-delimited tables preserved without ordering corruption.
- Critical fields (`Số`, document type, issuer, issue date, title, signer, deadline)
  with normalized values, confidence, review status and page/block provenance.
- APIs: upload, list, detail, status, canonical (current or a specific version),
  original file, page preview and reprocess, all on the documented error envelope.

#### Blocking the phase exit

- **The parser strategy is still undecided.** ADR-001 has no evidence, so every parse
  run in this repository uses the PyMuPDF baseline, is marked `degraded` and
  `strategy_decided = false`, and flags the document for user review. Structure and
  table extraction are consequently as weak as ADR-001 measured them.
- Phase 2's exit criterion — deterministic canonical output *that can be trusted* —
  is met mechanically but not evidentially until a real parser is selected.

#### To close Phase 2

1. Close Phase 1 by running the private benchmark and setting ADR-001 to `ACCEPTED`.
2. Write the resulting route table to a parser strategy JSON file, set
   `decided: true`, and point `PARSER_STRATEGY_PATH` at it.
3. Re-run `make check`, confirm parse runs report `degraded = false`, and record the
   exit evidence here.

### Phase 3 progress — 2026-08-17

- Commit/PR: baseline `d8edafe9724a3cca3004c5ecb4708c9da6bd6928`, implementation
  hardening `e7cc7a8`, and final test/evidence repair `c75c489` are pushed to `main`;
  no separate PR reference was observable from this checkout.
- Test commands: **PASS** — `make web-component-tests` (38 tests), `make feedback-tests`
  (13 tests), `make web-e2e-smoke` (desktop 1/1 plus tablet/mobile 2/2),
  `make frontend-format-check`, `make frontend-lint`, `make frontend-typecheck`,
  `make frontend-build`, `make db-migration-test` (7 tests), and full `make check`.
  The direct focused command `npm run test:run --prefix apps/web --
  src/components/workspace/SourceViewer.test.tsx` also passed 7/7; an initial
  root-context `npm --prefix apps/web exec vitest ...` invocation failed before
  collection because it did not load the configured DOM environment.
- CI status: `feedback-tests` and `web-e2e-smoke` jobs added to
  `.github/workflows/ci.yml`; `web-e2e-smoke` runs the real API, worker and a headless
  Chromium browser against a scratch SQLite database, no mocks and no private data.
  The browser job now discovers the preserved desktop journey plus the tablet/mobile
  smoke spec. Live GitHub status is unavailable; see the verification snapshot and
  no run ID is claimed.
- ADR/benchmark artifacts: none required — the frontend stack (React/TypeScript, Vite,
  Tailwind, Radix primitives styled to the shadcn/ui contract) was already decided by
  `docs/decisions/ADR-0001-phase0-stack.md` and `docs/10_DESIGN_SYSTEM.md`.

#### Delivered

- Application shell: warm/editorial `Văn bản` archive as the only primary
  destination; no `Trợ lý` navigation, tab or control anywhere (feature-gated to
  Phase 4).
- Login shell (IA-00): a screen/state handoff gated on real `/health` connectivity
  evidence, never fabricating "invalid credentials" from a network failure.
- Archive: document library rows with plain-language status, search (`query`) and
  filters (`type`/`issuer`/date range), loading/empty/empty-filtered/error-with-stale-
  data states.
- Upload: drawer with local + server-side validation, all documented upload error
  codes mapped to Vietnamese copy, offline state.
- Processing: durable status timeline using the exact `docs/design/02_DOCUMENT_FLOW.md`
  status vocabulary, terminal failure with retry/reprocess, unsupported-format state.
- Verification workspace (`Document rail | Original PDF | Parsed content / metadata /
  correction`): responsive at the documented desktop (>=1200px) / tablet (768–1199px)
  / mobile (<768px) breakpoints, using the page-preview PNG endpoint with a bbox
  highlight positioned proportionally to page dimensions (correct regardless of
  render DPI).
- `Đi tới nguồn`: resolves a field's citation to page + block, focuses the source
  pane, and never renders a citation for an unresolved block (`Chưa có nguồn xác định`
  instead).
- Correction UI + backend: `ConfidenceField`/`CorrectionControl` submit to the new
  append-only `POST .../feedback` endpoint; corrections are never written into
  `parse_runs.canonical` — a read-time overlay in `app/feedback.py` layers
  `review_status`/`corrected_value` onto the served canonical document, so the raw
  prediction is provably preserved.
- Accessibility: every icon-only control has an accessible name, status is never
  color-only (icon + text pairing), 44px-ish touch targets, visible focus ring,
  reduced-motion respected.

#### Required tests added

- Component: `UploadDrawer`, `ProcessingStatus`, `ConfidenceField` (metadata +
  low-confidence), `CorrectionControl`, `SourceViewer` (citation/source jump plus
  page/document preview recovery).
- API integration (mocked via MSW): upload happy path, failed-processing UI, retry
  path, document search/filter, correction reflected without a full refetch.
- Browser E2E (Playwright, real backend): `login -> upload -> processing -> open
  document -> verify metadata -> jump to cited page -> correct field -> reload ->
  correction persists`.
- Backend: `services/api/tests/test_feedback_api.py` (persistence, latest-correction-
  wins, unknown-document 404, required-field validation, current-canonical ID
  validation and stale-ID rejection) and an extended
  `test_document_list_supports_metadata_search` in `test_ingestion_integration.py`.
- Responsive browser smoke: `apps/web/e2e/responsive-workspace.spec.ts` covers
  1024px tablet and 390px mobile archive/menu, source/page navigation, details
  surfaces and return navigation; it asserts no interactive `Trợ lý` control while
  preserving the approved login tagline.

#### Blocking the phase exit

- Inherits Phase 1/2: every field/parse run a family user sees is `degraded` and
  `Cần kiểm tra` until ADR-001 closes; the UI is honest about this but cannot make it
  untrue.
- No real authentication contract exists, so login cannot be more than the approved
  screen/state handoff described in IA-00.

#### To close Phase 3

Phase 3 itself has no unmet exit criterion — the family workflow is demonstrable
entirely from the browser. What remains is Phase 1/2's parser evidence (see above),
which is a prerequisite for calling the *product*, not this phase, production-ready.

### Phase 3.5 completed — 2026-08-22

- Commit/PR: merged locally into `main` as the range `b61ef32..d6cfc4d` (50 commits,
  34 files, +6891/-4). **Not pushed to `origin/main`.** No PR was opened.
- Test commands: `make check` — **EXIT 0**. Component results inside that run:
  backend `pytest -q` 657 passed / 1 skipped; the new `make retrieval-eval-tests`
  gate 229 passed; parser-contract 408 passed / 1 skipped; benchmark smoke 12
  passed; ingestion-integration 220 passed; admin golden 15 passed; migration 7
  passed; feedback 14 passed; frontend 38 passed across 9 files; `vite build`
  succeeded; Compose config validated; Playwright 3/3 passed. `mypy` clean across
  63 source files, `ruff check` and `ruff format --check` clean, `git diff --check`
  clean.
- CI status: **not verified remotely.** The `retrieval-eval-tests` job was added to
  the `Makefile` and to the `check` target only; it was **not** wired into
  `.github/workflows/ci.yml`. Do not read this entry as remote CI coverage. Wiring
  it is carried as a Phase 4 task.
- ADR/benchmark artifacts: none. No parser or retrieval strategy decision was made.

#### Delivered

- `mamagift_retrieval`: `EvidenceScope` with the fixed authority order, the `Chunk`
  contract with `validate_chunk_tree`, legal / `Kế hoạch` / fallback chunk builders
  plus the `build_chunks` orchestrator, a naive lexical baseline seam, and the
  context/evidence budget contract.
- `mamagift_eval`: `ParserSemanticCase` / `RetrievalQACase` schemas, the
  failure-analysis taxonomy, document-type slicing, and per-type/plan metrics.
- A synthetic nested `Kế hoạch` golden fixture with two tasks carrying distinct
  owners, coordinating units and deadlines, proven not to cross-associate.

#### How it was verified

Each of the 13 tasks was implemented by one worker and then reviewed by an
independent agent that read the diff, ran the gates, and mutation-tested the
guards. **Every one of the 13 per-task reviews returned CHANGES_REQUIRED**, in two
recurring classes: incomplete version/scope isolation, and tests that passed
against a deliberately broken implementation. 13 fix commits closed them.

A final whole-diff integration review then found three further BLOCKING defects
that per-task review structurally could not see, because each was a disagreement
*between* branches rather than a fault within one:

1. the legal chunker's hardened ID scheme (version-bearing, separator-escaped) was
   never propagated to the plan and fallback chunkers, which were in flight on
   their own branches — allowing cross-version ID collisions;
2. the fallback chunker still built parent IDs in the superseded format, so mixed
   documents produced unresolvable parent references;
3. eval metrics inferred the identity to score against from the first input item,
   so foreign or stale evidence could be credited and inflate every metric.

All three are closed. Chunk-ID construction is now a single shared helper in
`chunking/_shared.py` that every builder calls, so a future chunker cannot invent
its own format.

#### Blocking further phases

- Phase 4 has not started and stays `BLOCKED_BY_PHASE_3.5` until deliberately
  picked up. Nothing in this phase retrieves against a real index, embeds anything,
  or calls a model.
- The PP-StructureV3/OCR blocker in `docs/eval/real-pdf-batch-01-results.md` and
  ADR-001's `PENDING EVIDENCE` status are both unchanged. Phase 3.5 operates only
  on already-produced `CanonicalDocument`/`ExtractedField` structure and never
  touches OCR or parsing.
- Phases 1 and 2 remain `IN_PROGRESS` for that same reason; Phase 3.5 does not
  close them.

#### Carried into Phase 4

1. Wire `retrieval-eval-tests` into `.github/workflows/ci.yml`.
2. Resolve the OCR blocker before any claim about real scanned documents; until
   then every Phase 4 fixture is born-digital or synthetic.

### Phase 4 completed (with external OCR blocker) — 2026-08-24

- Commit/PR: merged locally into `main` as `274bf50..715412c` (74 commits, 105 files,
  +19987/-122). **Not pushed to `origin/main`.** No PR was opened.
- Test commands: `make check` — **EXIT 0**. Inside that run: backend `pytest -q`
  **1033 passed / 1 skipped**; the four Phase 3.5+4 gates `retrieval-eval-tests` 229,
  `ai-worker-contract` 130, `rag-unit-tests` 78, `rag-eval-mini` 54; parser-contract
  702, benchmark smoke 12, ingestion 220, admin golden 15, migrations 20, feedback 14;
  frontend **78 passed** across 13 files; `vite build` succeeded; Compose validated;
  Playwright **12/12 passed**. `mypy` clean across 103 source files; `ruff check`,
  `ruff format --check` and `git diff --check` clean.
- CI status: **not verified remotely.** Four jobs were added to
  `.github/workflows/ci.yml` — `retrieval-eval-tests` (the carried-forward Phase 3.5
  follow-up), `ai-worker-contract`, `rag-unit-tests` and `rag-eval-mini` — bringing the
  workflow to 18 jobs. Their definitions are present and each passes locally; no remote
  run ID is claimed.
- ADR/benchmark artifacts: none. ADR-001 remains `PENDING EVIDENCE` and was not touched.

#### Delivered

- `services/ai-worker`: an authenticated worker service with `/internal/v1/health`
  that reports honestly — a worker with no backing model advertises `offline` with all
  capabilities false, so acceptance CASE 7 is meaningful.
- `mamagift_contracts`: LLM, embedding and rerank DTOs plus a structured worker-error
  contract.
- `mamagift_retrieval` (Phase 4 additions): OpenAI-compatible chat adapter and BGE-M3
  embedding adapter, each with a deterministic fake; a single-document, version-keyed
  `DocumentIndex`; Vietnamese BM25 lexical retrieval; dense retrieval; rank-only
  Reciprocal Rank Fusion (k=60); a provider-neutral reranker seam; ancestor-only
  evidence expansion; and bounded evidence assembly.
- `mamagift_rag`: the grounded prompt contract, the answer schema, citation allow-list
  validation, abstention, prompt-injection defences, and `QaService`.
- `services/api`: the `document_chunks` table and migration `0004`, the runtime
  indexing pipeline (`READY_FOR_REVIEW -> INDEXING -> READY`), and
  `POST /api/v1/documents/{id}/qa`.
- `apps/web`: the Trợ lý assistant panel with the four quick questions, answer
  rendering with citation chips that navigate to the exact source page and block, and
  the full set of offline/indexing/insufficient-evidence/failure states.
- `mamagift_eval` (Phase 4 additions): the single-document retrieval harness
  (Recall@1/3/5/10, MRR, nDCG, exact document-number, latency), MamaGift
  answer-quality metrics, per-question failure analysis, and the offline RAGAS adapter.

#### Architectural decision recorded here

**No vector database.** Retrieval is scoped to one document version, which produces
10^1–10^2 chunks, so exact brute-force cosine is both correct and cheaper than any ANN
index, with no extra service and no migration risk. pgvector is an explicit Phase 5
deliverable and was deliberately not pulled forward. The `DocumentIndex` Protocol is
the seam Phase 5 swaps.

#### E2E acceptance cases (all seven executing the real pipeline)

Fake LLM and fake embeddings only; chunking, retrieval, fusion, reranking, evidence
assembly and citation validation are all real.

| Case | Proves | Status |
|---|---|---|
| 1 | Exact fact; citation resolves to the correct block; clicking it opens that source | PASS (API + browser) |
| 2 | `Kế hoạch` task-local owner/deadline, with cross-association asserted absent | PASS |
| 3 | Điều/Khoản/Điểm hierarchy retrieval | PASS |
| 4 | Absent fact abstains with zero citations | PASS (API + browser) |
| 5 | Prompt injection treated as source text only | PASS (API + browser) |
| 6 | Current-version query cannot reach stale parse-run evidence | PASS (API + browser) |
| 7 | Worker offline: document intact, understandable retry state | PASS (API + browser) |

#### How it was verified, and the honest limits of that

Each of the 24 tasks was implemented by one worker and reviewed by an independent
agent that read the diff, ran the gates and mutation-tested the guards. Seven per-task
reviews ran (A1, A2, B1, B2, C1, D1, F2) and **every one returned CHANGES_REQUIRED**,
overwhelmingly for two recurring classes: incomplete version/scope isolation, and tests
that passed against a deliberately broken implementation.

Integration then found defects no per-task review could see, because they were
disagreements *between* branches:

1. Task C2 and D1 called a `search_dense` signature that Task B2's review had just
   restored to its frozen form.
2. Tasks C1 and C2 each defined their own structurally-identical `ScoredChunk`; two
   such Pydantic models are still different runtime types across the fusion boundary.
   Collapsed to one definition.
3. `AssistantPanel`, `AnswerView` and `AssistantStates` all existed with passing unit
   tests, and none were wired together or mounted — the feature was unreachable in the
   product until a dedicated integration task.
4. `services/api/app/db.py` never issued `PRAGMA foreign_keys=ON`, so every foreign key
   in the schema — including the composite key binding a chunk to its parse run, and
   the pre-existing Phase 2/3 cascades — was unenforced on SQLite.
5. The background indexing worker raised out of its loop and `exit(1)` on a document
   with no matching parse run, which would stop processing for every other document.
6. A worker, told not to add a `family_id` column, instead created a shadow table at
   runtime via `create_all` — schema outside Alembic. Reverted; the family guard is now
   a constant check with no persistence.

The final whole-diff integration review returned **PASS** with one warning (an
untested archive-scope guard), which was then covered by a test.

**Reviewer-strength caveat, stated plainly:** every review that found a blocking defect
was run by `codex` at `gpt-5.6-luna` with `model_reasoning_effort=max`. That account hit
its usage limit before the final integration review, so the final review — the single
most important one — ran on the weaker worker-tier model (`agy`, Gemini 3.7 Flash,
high) and returned PASS. A PASS from the weaker reviewer is weaker evidence than the
CHANGES_REQUIRED verdicts that preceded it. Re-running the final review on
`gpt-5.6-luna max` when that quota resets is recommended before treating this phase as
independently validated.

#### Known limitations carried forward

- **OCR / ADR-001 is unchanged and still blocking.** PP-StructureV3 is unavailable and
  real scanned documents still produce no critical fields. Every Phase 4 fixture is
  born-digital or synthetic. Nothing here makes a real scanned document answerable, and
  the phase must not be read as production-ready for scanned input.
- Phases 1, 2 and 3 remain `IN_PROGRESS` for that same reason.
- Login remains the Phase 3 screen/state handoff; there is no authentication backend,
  so there is no real tenancy. `family_id` is therefore enforced as a single
  authoritative constant rather than persisted — multi-family support needs a real
  tenancy source and is Phase 5+ work.
- CI job definitions are present but no remote GitHub Actions run was observed.
- The real self-hosted model and a real RAGAS run are offline operator evidence only;
  neither has been executed, and neither is required by CI.
