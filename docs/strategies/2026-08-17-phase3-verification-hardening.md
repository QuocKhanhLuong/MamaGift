# Phase 3 Verification Hardening Strategy

Run: `20260817T100005Z`
Stage: `strategy`
Role: `PM`
Date: `2026-08-17`

## Decision

Treat this as one bounded Phase 3 hardening increment. The objective remains:

> Let a non-technical family user upload, find, inspect, and verify parsed documents without using developer tools.

The current `main`, `origin/main`, and `origin/HEAD` are aligned at
`d8edafe9724a3cca3004c5ecb4708c9da6bd6928`. Existing untracked
`.agenteam/events/`, `.agenteam/state/`, and `docs/research/` work is preserved. This
strategy is the only artifact produced by the strategy stage; it does not authorize
application, test, or phase-status edits in this stage.

## Priority order

| Priority | Outcome | Why it comes first | Implementation surface |
|---|---|---|---|
| P0 | Reject invalid critical corrections before persistence | Prevents orphaned or stale feedback from entering the append-only event stream | `services/api/app/{schemas.py,routers/feedback.py,feedback.py,errors.py}` |
| P0 | Recover SourceViewer after a failed page preview | A single failed page must not strand the verification workflow | `apps/web/src/components/workspace/SourceViewer.tsx` |
| P1 | Prove tablet and mobile workspace navigation | Exercises the already-implemented responsive surfaces without duplicating the full journey | `apps/web/e2e/responsive-workspace.spec.ts` |
| P1 | Replace stale phase evidence factually | Keeps commit provenance and CI claims auditable | `docs/PHASE_STATUS.md` in the later implementation/documentation stage |

Implementation order may place the SourceViewer fix first for fast feedback, but the
API validation is the data-integrity gate: no invalid or stale correction may reach
`record_feedback`.

## 1. Feedback validation and canonical identity

### Required behavior

Apply validation only when `feedback_type` is exactly
`critical_field_correction`.

1. `field_id` must be present and non-empty after a whitespace check.
2. `corrected_value` must be present and non-empty after a whitespace check.
3. Resolve the document's `current_parse_run_id`, load that `ParseRun.canonical`,
   and compare the submitted ID with the current canonical
   `extracted_fields[].id` values.
4. Perform all validation before `record_feedback`, `session.add`, or commit.
5. If the ID is absent from the current canonical, reject it as invalid/stale. Do
   not silently accept it because it might exist in an older parse run.
6. A `general_comment` without `field_id` or `corrected_value` remains valid.
7. A valid correction remains an append-only `FeedbackEvent`; the latest correction
   continues to win at read time, and `ParseRun.canonical` remains byte-for-byte
   unchanged.

Whitespace-only values are invalid. The validation check must not turn the raw
canonical value into a corrected value or silently rewrite the stored canonical
artifact. Do not introduce a new parser normalization rule as part of this work.

### Structured error contract

Use the existing `ApiError` envelope rather than a framework validation response or
string matching. Freeze stable codes in the implementation and API contract as:

- `feedback_field_required` — HTTP `422`, `retryable: false`, with
  `details.missing_fields` containing the missing field names in stable order.
- `feedback_field_invalid` — HTTP `422`, `retryable: false`, for an unknown or
  stale field ID, with details including `document_id`, the submitted `field_id`,
  and `reason: "not_in_current_canonical"`.

Every rejection must contain `error.code`, a non-empty `error.request_id`,
`error.retryable`, and useful `error.details`. An incoming `X-Request-ID` should
continue to be reflected by the existing error handler so the API test can assert
the request correlation value. If a document has no current canonical parse, reject
without writing an event through the repository's structured not-ready/conflict
contract; do not fall through to `record_feedback`.

The unknown-document 404 remains structured and must not regress. No migration is
needed: `FeedbackEvent` stays append-only and document-scoped for this hardening
increment.

### Required API tests

Extend `services/api/tests/test_feedback_api.py` or a focused adjacent API test to
cover all of the following:

- missing, empty, and whitespace-only `field_id` for a critical correction;
- missing, empty, and whitespace-only `corrected_value` for a critical correction;
- an unknown field ID;
- an ID captured from an earlier current parse, followed by a current-run change,
  proving that a stale ID is rejected against the new current canonical;
- structured rejection assertions for status, `error.code`, `request_id`,
  `retryable`, and relevant `details`;
- no `FeedbackEvent` row is created for any rejected request;
- a valid current field ID returns `201`, overlays the correction on a fresh
  canonical read, and preserves the raw canonical value;
- two valid corrections for one field retain latest-correction-wins behavior;
- `general_comment` without a field ID remains `201`;
- the existing unknown-document structured `404` remains covered;
- `make db-migration-test` still applies the shipped schema from an empty database.

The test must inspect the raw/current parse before and after a valid correction, not
only the overlaid API response. The stale-ID setup may use the existing reprocess
path or an equivalent test fixture that advances `Document.current_parse_run_id`;
it must not add a `parse_run_id` column to feedback.

## 2. SourceViewer page recovery

### Required behavior

Treat `(documentId, page.page_number)` as the preview identity. Whenever either
identity component changes, reset the preview state to `loading` before rendering the
new image. The reset must also work when the previous preview was already `ready` or
ended in `error`.

Keep the existing `<img>` key, source URL construction, URL-owned page selection,
page controls, proportional bounding-box highlight, null-page placeholder, and
accessible page indicator. A failed page may show its current error, but it must not
remove the ability of a later page or document to mount and load its own image.

The simplest acceptable implementation is identity-keyed state reset/effect placed
with the other hooks before the nullable-page early return. If state is represented
as an identity/state pair instead, stale events from an old image must not overwrite
the new identity's state.

### Required component tests

Extend `apps/web/src/components/workspace/SourceViewer.test.tsx` to:

1. render page 1, fire its image error, rerender with page 2, and assert that the
   page-2 preview URL/image is present, the old alert is gone, and a subsequent load
   event reaches the normal state;
2. repeat the failure/recovery assertion with a different `documentId` and the same
   page number;
3. retain existing coverage for null pages, page count, highlight positioning,
   navigation buttons, and no-highlight behavior.

The tests must prove recovery through the rendered image/event contract, not by
reaching into component state.

## 3. Responsive browser smoke coverage

### Preserve the desktop contract

Keep the existing full desktop Playwright journey and Chromium project unchanged in
meaning: login, upload, processing, open, metadata verification, source jump,
correction, reload, and persistence. The responsive suite is a smoke suite, not a
second full correction journey.

### Add two lightweight viewport paths

Add a focused `apps/web/e2e/responsive-workspace.spec.ts` using explicit viewport
scopes at approximately:

- tablet: `1024 x 768`;
- mobile: `390 x 844`.

Prefer spec-local Playwright `test.use` scopes so the existing desktop project does
not run the full journey at every responsive size. Use the existing real API,
worker, and scratch SQLite setup; do not introduce mocks or fixed sleeps.

Each viewport smoke path must:

1. complete the existing login handoff and reach the archive;
2. open the responsive menu, verify the `Văn bản` navigation item, close or use the
   drawer, and open a reviewable document using the existing deterministic fixture;
3. wait on explicit URL, role, and status assertions until the document is reviewable;
4. verify the source page indicator and at least one page-navigation transition;
5. at tablet width, switch between `Nguồn` and `Nội dung đã đọc`, verify details,
   and return to `Nguồn`;
6. at mobile width, switch between `Văn bản` and `Chi tiết`, verify details, and
   return to `Văn bản`;
7. verify that no assistant navigation item, tab, button, composer, textbox, or
   other interactive control has an accessible name containing `Trợ lý`.

The assistant assertion is intentionally scoped to interactive UI. The current login
screen contains the approved tagline `Trợ lý tài liệu gia đình`; a blanket assertion
that the entire page contains no `Trợ lý` text would test the wrong contract.

Use role/name and state assertions rather than pixel coordinates or time-based
waiting. The test should not assert a redesign, remove the login tagline, or add any
assistant surface.

## 4. Phase status evidence update

This strategy stage does not edit `docs/PHASE_STATUS.md`. The later implementation
stage must replace the stale `Commit/PR: pending (working tree)` entries with factual
evidence:

- Phase 1 baseline commit: `4659fab647078b75015761857fd4baf317b5f64e`;
- Phase 2 baseline commit: `fc71f8b0178fbde82ffa2eebbffa43b9057e3699`;
- Phase 3 baseline commit: `d8edafe9724a3cca3004c5ecb4708c9da6bd6928`, then the
  actual hardening commit once implementation is complete.

The documentation update must also:

- identify the existing Phase 1, Phase 2, and Phase 3 CI jobs and the local
  CI-equivalent commands that were actually run;
- record a confirmed GitHub run ID and job results only when they are observable;
- explicitly say live CI is unavailable rather than inventing a PASS or run ID;
- keep Phases 1, 2, and 3 `IN_PROGRESS` while private parser evidence and the
  `PENDING EVIDENCE` ADR remain unresolved;
- avoid claiming real-document readiness or promoting the baseline parser;
- mention that Phase 3 browser coverage now includes the preserved desktop journey
  plus the tablet/mobile smoke paths after those tests actually land.

The focused local gate set is:

```text
make web-component-tests feedback-tests web-e2e-smoke \
  frontend-format-check frontend-lint frontend-typecheck frontend-build \
  db-migration-test
make check
```

Report each command as `PASS`, `FAIL`, or unavailable; do not convert a planned or
unrun check into evidence.

## Acceptance criteria

The implementation handoff is complete only when all of these are true:

- [ ] A SourceViewer error on page N recovers to a loadable page N+1.
- [ ] A SourceViewer error for document A does not poison the same page for document B.
- [ ] Critical corrections reject missing, empty, and whitespace-only required
      values before persistence.
- [ ] Critical corrections accept only IDs in the document's current raw canonical
      parse; unknown and stale IDs return the agreed structured error.
- [ ] Rejected feedback creates no append-only event.
- [ ] Valid feedback preserves raw canonical data, overlays at read time, and keeps
      latest-correction-wins behavior.
- [ ] `general_comment` without a field ID remains valid.
- [ ] The existing desktop full E2E continues to pass.
- [ ] Tablet `1024px` and mobile `390px` smoke paths cover archive/menu,
      source/page navigation, details, and return navigation.
- [ ] No Phase 3 responsive smoke path exposes interactive `Trợ lý` UI.
- [ ] Focused gates and full `make check` are run and reported factually.
- [ ] Phase status evidence uses actual hashes/results and does not change phase
      status or claim production parser/real-document readiness.

## Explicit non-goals

This increment must not:

- implement Phase 4 Q&A, RAG, LLM, chat, assistant navigation, or assistant UI;
- change parser/provider strategy, run the private benchmark, or promote PyMuPDF;
- redesign the interface, change the approved copy/typography, or alter responsive
  breakpoints;
- change URL-owned page selection, provenance/highlight math, or the desktop E2E
  journey;
- rewrite `ParseRun.canonical`, replace raw values, update/delete feedback events, or
  add a migration solely for this validation;
- add real private school/family documents, paid API dependencies, or GPU-only CI;
- claim authentication, live CI, or real-document readiness that was not observed.

## Future-only correction migration concern

The current hardening validates a feedback ID against the document's current parse,
but it does not make a correction run-aware. `FeedbackEvent` remains document-scoped
and historical canonical reads retain the existing document-scoped overlay behavior.

A future migration may bind correction events to a specific `parse_run_id`, define
historical-version overlay semantics, decide how existing events are backfilled or
left unbound, and update the API/data contract and tests. That migration is recorded
here as a future concern only; it is not part of Phase 3 verification hardening.

## Handoff sequence

1. Dev implements the two P0 fixes without changing parser or schema strategy.
2. QA adds the SourceViewer, API, migration, and responsive smoke coverage listed
   above.
3. Dev/QA run the focused gates and then `make check`.
4. PM updates `docs/PHASE_STATUS.md` only from observed commit/CI evidence.
5. Reviewer verifies that the diff is limited to the three hardening areas and the
   factual evidence update; Phase 4 remains not started.
