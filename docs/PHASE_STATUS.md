# Phase Status

This file is the factual execution tracker for MamaGift. Update it at the end of each implementation phase.

## Current active phase

**Phase 3 — Document archive and verification-first web UX**

Status: `IN_PROGRESS`

Exact `/goal`:

> Let a non-technical family user upload, find, inspect, and verify parsed documents without using developer tools.

Phase 3's web flows, component/integration/E2E tests and CI gates are implemented and
green. The product is demonstrable entirely from the browser, but it inherits Phase
1/2's open item: every document shown was parsed by the undecided PyMuPDF baseline, so
the UI correctly displays every field/parse run as `degraded`/`Cần kiểm tra` rather
than implying a trustworthy production parse. Login is a screen/state handoff only
(`docs/design/01_INFORMATION_ARCHITECTURE.md` IA-00) with no real authentication
backend, as no such contract exists yet.

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
| 1 | PDF parser benchmark and parser decision | IN_PROGRESS | Harness, adapters, router, CanonicalDocument v1 and CI gates complete; ADR-001 `PENDING EVIDENCE` |
| 2 | Production ingestion and Vietnamese administrative structure | IN_PROGRESS | Ingestion pipeline, APIs, schema, admin parser and Phase 2 CI gates complete; production parser strategy still blocked on ADR-001 |
| 3 | Document archive and verification-first web UX | IN_PROGRESS | Web shell, archive, upload/status, verification workspace, correction UI and Phase 3 CI gates complete; inherits Phase 1/2's undecided parser strategy |
| 4 | Self-hosted LLM and grounded single-document Q&A | BLOCKED_BY_PHASE_3 | — |
| 5 | Cross-document institutional memory | BLOCKED_BY_PHASE_4 | — |
| 6 | Feedback dataset and offline continual OCR/domain adaptation | BLOCKED_BY_PHASE_5 | — |
| 7 | Production hardening and low-cost deployment | BLOCKED_BY_PHASE_6 | — |
| 8 | Meeting assistant | PARKED | document product must be stable/useful first |

## Status values

Use only:

```text
NOT_STARTED
IN_PROGRESS
BLOCKED
COMPLETE
BLOCKED_BY_PHASE_<N>
PARKED
```

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

- Commit/PR: pending (working tree).
- Test commands: `make parser-contract-tests`; `make parser-benchmark-smoke`;
  `make backend-format-check`; `make backend-lint`; `make backend-typecheck`;
  `make backend-test`; `make docs-check`; `make repository-hygiene`; `make secret-scan`.
- CI status: `parser-contract-tests` and `parser-benchmark-smoke` jobs added to
  `.github/workflows/ci.yml`; the manual heavy benchmark lives in
  `.github/workflows/parser-benchmark.yml`.
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

- Commit/PR: pending (working tree).
- Test commands: `make ingestion-integration`; `make admin-parser-golden-tests`;
  `make db-migration-test`; `make backend-format-check`; `make backend-lint`;
  `make backend-typecheck`; `make backend-test`; `make parser-contract-tests`;
  `make parser-benchmark-smoke`; `make docs-check`; `make repository-hygiene`;
  `make secret-scan`; `make compose-config`.
- CI status: `ingestion-integration`, `admin-parser-golden-tests` and
  `db-migration-test` jobs added to `.github/workflows/ci.yml`; the migration job runs
  against the PostgreSQL service, the rest are CPU-only with no private data.
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

- Commit/PR: pending (working tree).
- Test commands: `make web-component-tests`; `make web-e2e-smoke`; `make feedback-tests`;
  `make frontend-format-check`; `make frontend-lint`; `make frontend-typecheck`;
  `make frontend-build`; `make db-migration-test`; full `make check`.
- CI status: `feedback-tests` and `web-e2e-smoke` jobs added to
  `.github/workflows/ci.yml`; `web-e2e-smoke` runs the real API, worker and a headless
  Chromium browser against a scratch SQLite database, no mocks and no private data.
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
  low-confidence), `CorrectionControl`, `SourceViewer` (citation/source jump).
- API integration (mocked via MSW): upload happy path, failed-processing UI, retry
  path, document search/filter, correction reflected without a full refetch.
- Browser E2E (Playwright, real backend): `login -> upload -> processing -> open
  document -> verify metadata -> jump to cited page -> correct field -> reload ->
  correction persists`.
- Backend: `services/api/tests/test_feedback_api.py` (persistence, latest-correction-
  wins, unknown-document 404) and an extended
  `test_document_list_supports_metadata_search` in `test_ingestion_integration.py`.

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
