# Phase Status

This file is the factual execution tracker for MamaGift. Update it at the end of each implementation phase.

## Current active phase

**Phase 0 — Repository and deterministic development foundation**

Status: `COMPLETE`

Exact `/goal`:

> Make MamaGift reproducibly buildable and testable on a fresh machine before implementing document intelligence.

## Phase table

| Phase | Name | Status | Exit evidence |
|---|---|---|---|
| 0 | Repository and deterministic development foundation | COMPLETE | `941a5c4`; CI run `31787161450` |
| 1 | PDF parser benchmark and parser decision | NOT_STARTED | — |
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
