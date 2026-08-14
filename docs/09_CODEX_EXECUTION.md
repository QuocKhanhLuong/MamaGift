# Codex Execution Contract

This file is the operating contract for Codex when implementing MamaGift.

## 1. Required reading before any implementation

Before changing code, read:

1. `README.md`
2. `docs/00_PROJECT_CHARTER.md`
3. `docs/01_ARCHITECTURE.md`
4. `docs/02_INFRASTRUCTURE.md`
5. `docs/03_DOCUMENT_PIPELINE.md`
6. `docs/04_PHASE_PLAN.md`
7. `docs/05_TEST_STRATEGY.md`
8. `docs/06_CICD.md`
9. `docs/07_DATA_AND_CONTINUAL_LEARNING.md`
10. `docs/08_API_AND_DATA_CONTRACTS.md`
11. `docs/PHASE_STATUS.md`

Then inspect the repository state. Repository code is authoritative when it conflicts with assumptions, but architectural changes require updating docs/ADR rather than silently diverging.

## 2. Phase execution rule

Implement exactly one phase at a time.

The active phase is defined in `docs/PHASE_STATUS.md` or explicitly supplied by the user.

For the active phase:

1. copy its `/goal` mentally as the primary objective;
2. enumerate existing code relevant to that goal;
3. identify missing acceptance criteria;
4. implement the smallest coherent design satisfying all criteria;
5. add all phase-required tests;
6. run applicable CI-equivalent commands locally;
7. update docs/config/examples;
8. report what is complete and any remaining blockers.

Do **not** begin the next phase automatically.

## 3. Scope discipline

Do not implement later-phase features merely because they seem easy.

Examples:

- During Phase 0, do not add RAG.
- During Phase 1, do not build chat UI.
- During Phase 2, do not fine-tune OCR.
- During Phase 3, do not integrate the real LLM.
- During Phase 4, do not implement archive-wide RAG.
- Before Phase 8, do not add meeting/audio dependencies.

A future-facing interface is allowed when required to prevent architectural coupling; a future feature implementation is not.

## 4. Decision discipline

### When docs already decide

Follow the documented decision.

### When docs intentionally leave a choice open

Examples: Vite vs Next.js in Phase 0, tunnel provider in Phase 7.

Choose the simplest option that satisfies current constraints and record the decision in an ADR if it materially affects architecture.

### When benchmark evidence is required

Do not guess. Build the benchmark seam and report results.

The parser decision in Phase 1 is explicitly benchmark-driven.

## 5. Implementation quality rules

- Prefer boring, typed, explicit code.
- Avoid framework abstractions with no current need.
- Keep parser/model providers behind interfaces.
- Keep API DTOs separate from DB models where practical.
- Keep model output validation strict.
- Preserve document provenance at every transformation.
- Make background operations idempotent.
- Treat PDFs/document text as untrusted input.
- Never commit secrets/private documents/model weights.
- Pin meaningful dependency versions through lockfiles.
- Use structured errors, not string matching across layers.

## 6. Testing rule

Every behavior added in the active phase must have the test category required by `docs/05_TEST_STRATEGY.md` and `docs/04_PHASE_PLAN.md`.

Model/GPU-dependent code must expose deterministic fakes/fixtures so mandatory CI stays CPU-only.

Do not “test” model behavior using assertions on nondeterministic prose in ordinary unit tests. Test contracts and evaluate model quality through eval sets.

## 7. Parser implementation rule

In Phase 1:

- implement all required candidates enough to benchmark their capabilities;
- never let provider output types leak into application business logic;
- persist/report exact versions/config;
- keep PyMuPDF as baseline/utility unless benchmark evidence promotes it;
- use real Vietnamese administrative/legal documents privately for final selection, but commit only sanitized/synthetic fixtures.

The outcome must be `docs/decisions/ADR-001-parser-selection.md`.

## 8. Data rule

Original document -> raw parse -> canonical document -> semantic extraction -> index are separate layers.

Never destructively replace upstream artifacts with corrected downstream data.

User corrections are append-only feedback events.

Knowledge from new documents is added by indexing, not LLM fine-tuning.

## 9. AI model rule

Application code talks to model interfaces.

LLM integration must support an OpenAI-compatible local endpoint configured via environment variables.

Do not hard-code Qwen/DeepSeek-specific request behavior into product services unless isolated in a provider adapter.

CI must not require the actual home LLM.

## 10. Database rule

Every schema change uses migrations.

For each migration:

- apply from empty DB in tests;
- test relevant constraints;
- update API/data docs if contract changes;
- avoid destructive production assumptions without a migration/backup plan.

## 11. Frontend rule

The target user is non-technical.

UI priorities:

1. Vietnamese-first clarity;
2. verification against original source;
3. obvious processing/error status;
4. few high-value actions;
5. mobile-friendly layout;
6. no prompt-engineering dependence for common tasks.

Do not optimize for flashy AI UI at the expense of provenance.

## 12. CI rule

When adding a subsystem, add its phase-required CI job in the same phase.

Never make mandatory CI depend on:

- home machine being online;
- private files;
- paid APIs;
- GPU runners;
- downloading huge weights for ordinary PR checks.

## 13. Completion report format

At the end of a Codex phase run, report:

```text
Phase: <n> — <name>
/goal: <exact phase goal>

Implemented:
- ...

Tests added:
- ...

Validation run:
- <command> -> PASS/FAIL

Docs/ADRs updated:
- ...

Acceptance criteria:
- [x] ...
- [ ] ... (only if genuinely blocked)

Known limitations:
- ...

Next phase:
- NOT STARTED
```

If something cannot be completed, leave the repository in a coherent tested state and explain the exact missing criterion. Do not quietly mark the phase complete.

## 14. Master prompt to start a phase

The user can give Codex this prompt:

```text
You are implementing MamaGift from the repository planning baseline.

Read README.md and every file under docs/ listed in docs/09_CODEX_EXECUTION.md before coding. Then inspect the current repository state and docs/PHASE_STATUS.md.

Implement ONLY Phase <N> from docs/04_PHASE_PLAN.md. Treat its exact /goal, deliverables, non-goals, required tests, CI gate, and exit criteria as binding requirements.

Preserve the architecture and contracts in docs/01_ARCHITECTURE.md and docs/08_API_AND_DATA_CONTRACTS.md. Follow docs/05_TEST_STRATEGY.md and docs/06_CICD.md. Do not implement later phases.

Make all code/config/docs changes needed to complete the phase. Add and run the required tests and CI-equivalent checks. If a documented choice is intentionally unresolved, choose the simplest valid option and record a concise ADR when the choice materially affects architecture.

Do not use real private school/family documents in the repository. Do not introduce paid API dependencies or require a GPU/home machine in mandatory CI.

Before finishing, update docs/PHASE_STATUS.md with factual completion status and return the completion report format specified in docs/09_CODEX_EXECUTION.md.
```

Replace `<N>` with the active phase number.

## 15. Phase 0 first invocation

For the first implementation run, use:

```text
Implement ONLY Phase 0.
```

Do not ask Codex to implement all phases in one mega-run. The phase boundaries exist specifically so tests and architectural choices can be reviewed before later work depends on them.
