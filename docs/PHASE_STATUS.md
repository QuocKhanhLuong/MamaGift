# Phase Status

This file is the factual execution tracker for MamaGift. Update it at the end of each implementation phase.

## Current active phase

**Phase 1 — PDF parser benchmark and parser decision**

Status: `IN_PROGRESS`

Exact `/goal`:

> Choose the document parsing foundation using evidence from Vietnamese administrative/legal PDF fixtures, not assumptions.

Phase 1 is **not complete**. Every deliverable, test and CI gate is implemented and
green, but the exit criteria require benchmark evidence from at least 30 representative
real Vietnamese administrative documents. That corpus is private and is not in this
repository, so `docs/decisions/ADR-001-parser-selection.md` is committed with status
`PENDING EVIDENCE` and names no production parser.

Phase 2 stays blocked until that ADR is decided.

## Phase table

| Phase | Name | Status | Exit evidence |
|---|---|---|---|
| 0 | Repository and deterministic development foundation | COMPLETE | `941a5c4`; CI run `31787161450` |
| 1 | PDF parser benchmark and parser decision | IN_PROGRESS | Harness, adapters, router, CanonicalDocument v1 and CI gates complete; ADR-001 `PENDING EVIDENCE` |
| 2 | Production ingestion and Vietnamese administrative structure | BLOCKED_BY_PHASE_1 | — |
| 3 | Document archive and verification-first web UX | BLOCKED_BY_PHASE_2 | — |
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
