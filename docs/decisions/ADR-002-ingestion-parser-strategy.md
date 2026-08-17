# ADR-002 — Parser strategy is configuration, not code

- **Status:** ACCEPTED
- **Date:** 2026-08-17
- **Phase:** 2 — Production ingestion and Vietnamese administrative structure
- **Supersedes:** nothing
- **Depends on:** ADR-001, which is still `PENDING EVIDENCE`

## Context

Phase 2 requires a working ingestion pipeline with a "selected parser" step, while
ADR-001 deliberately selects no production parser: the evidence for that decision
needs ≥30 real Vietnamese administrative PDFs that are not in this repository.

Two failure modes had to be avoided:

1. **Blocking Phase 2 entirely** on a corpus nobody can commit here.
2. **Quietly hard-coding PyMuPDF** as the production parser because it happens to be
   the one installed in CI. ADR-001 measured it at `heading_hierarchy_f1 = 0.000`,
   `list_preservation = 0.000` and `table_structure_score = 0.000`, which disqualifies
   it for a product built on `Chương/Mục/Điều/Khoản/Điểm`.

## Decision

The parser choice is a **configuration object**, not a code path.

`mamagift_docpipe.strategy.ParserStrategy` maps each router route to a required
capability, an optional primary parser and an ordered fallback chain. It is loaded
from JSON via `PARSER_STRATEGY_PATH`, and the pipeline resolves it per document.

Three properties are enforced by validators and pinned by tests:

1. **The baseline can never be silently promoted.** Naming `pymupdf` as a route's
   primary is rejected unless the configuration also sets
   `baseline_promoted_by_benchmark: true` — which only a real benchmark result
   justifies.
2. **An undecided strategy refuses to run in production.** With no primary configured
   and `APP_ENV=production`, selection raises the structured error
   `parser_strategy_undecided` instead of guessing. Development and CI fall back to
   the baseline so the pipeline is testable.
3. **Every baseline fallback is marked degraded.** The parse run records
   `degraded = true` and `strategy_decided = false`, the quality report carries the
   warning, and the document is flagged `requires_user_review`. Nothing produced while
   ADR-001 is open can be mistaken for a trustworthy production parse.

Capability gaps are reported the same way rather than hidden: the baseline has no OCR,
so a `scanned` route resolves to a degraded run with `capability_gaps: ["ocr"]`.

## Consequences

- Closing ADR-001 means writing one JSON file and setting `PARSER_STRATEGY_PATH`; no
  ingestion code changes.
- Phase 2 can be built, tested and reviewed now, but **it cannot be declared
  production-complete**: its parser strategy still depends on the unresolved evidence
  in ADR-001. `docs/PHASE_STATUS.md` records that explicitly.
- The API, database schema, versioning and administrative parser are all parser-neutral
  and unaffected by the eventual decision.
- CI stays CPU-only: the baseline is the only parser mandatory CI ever executes.

## Alternatives considered

- **Pick a parser from reputation now.** Forbidden by
  `docs/09_CODEX_EXECUTION.md` section 4 for exactly this decision.
- **Block Phase 2 until the corpus exists.** Leaves the upload, storage, job, schema
  and administrative-structure work — none of which depends on the parser — unbuilt
  and unreviewed.
- **Hard-code the baseline and "swap it later".** The swap never stays cheap, and a
  degraded parse that looks normal is the failure this project is most exposed to.

## References

- `docs/decisions/ADR-001-parser-selection.md`
- `docs/03_DOCUMENT_PIPELINE.md`
- `docs/04_PHASE_PLAN.md` — Phase 2
- `packages/docpipe/python/mamagift_docpipe/strategy.py`
- `configs/parser-strategy.example.json`
