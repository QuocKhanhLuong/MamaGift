# Research: Phase 3 verification hardening

Run: `20260817T100005Z` · stage: `research` · role: `Researcher`

This is a read-only implementation handoff. Only this report was written; application
code, tests, and `docs/PHASE_STATUS.md` were not modified.

## Checkout and boundary

- `HEAD`, `main`, `origin/main`, and `origin/HEAD` all point to
  `d8edafe9724a3cca3004c5ecb4708c9da6bd6928` (`feat(phase-3): implement document
  archive and verification-first web UX`); `git rev-list --left-right --count
  main...origin/main` is `0 0`.
- The phase commits in the current history are `4659fab647078b75015761857fd4baf317b5f64e`
  (Phase 1), `fc71f8b0178fbde82ffa2eebbffa43b9057e3699` (Phase 2), and the Phase 3
  commit above.
- Pre-existing untracked `.agenteam/events/` and `.agenteam/state/` were preserved.

The binding boundary is Phase 3's goal in `docs/PHASE_STATUS.md:5-21` and the
Phase 3 deliverables/tests/non-goals in `docs/04_PHASE_PLAN.md:325-406`.
`docs/09_CODEX_EXECUTION.md:24-56` requires one active phase and explicitly excludes
real LLM/chat/RAG work; `docs/09_CODEX_EXECUTION.md:90-96` requires tests for every
active-phase behavior. The data rule requires append-only feedback and non-destructive
upstream artifacts (`docs/09_CODEX_EXECUTION.md:110-118`).

## Findings

### 1. SourceViewer page-state recovery

Current implementation:

- `apps/web/src/components/workspace/SourceViewer.tsx:13-26` keeps one local
  `imageState`, initialized to `"loading"`; there is no effect or other transition
  keyed by `documentId` or page number.
- The image is keyed by document/page at `SourceViewer.tsx:73-79`, but that only
  remounts the `<img>`. `onError` sets the parent state to `"error"`, and the error
  branch at `SourceViewer.tsx:66-80` removes the image entirely.
- `DocumentWorkspace` derives the selected page from the URL at
  `apps/web/src/components/workspace/DocumentWorkspace.tsx:43-55` and passes the
  document/page to `SourceViewer` at `:81-89`.

Therefore, after page N fails, the parent remains in `"error"`; changing to page N+1
or changing `documentId` still renders the error branch and no new image can load.
Changing from a ready page also does not explicitly return the state to `"loading"`.

Existing coverage in `apps/web/src/components/workspace/SourceViewer.test.tsx:11-87`
covers the null placeholder, page count, highlight, no-highlight, and navigation
button behavior. It does not fire an image error/load event or rerender with a new
page/document after failure.

Required test additions:

1. Render a page, fire its image error, rerender with the next page, and assert the
   new preview URL/image is present and the old alert is gone; fire load to confirm the
   recovered page reaches its normal state.
2. Repeat the failure/recovery assertion for a changed `documentId` (same page is
   sufficient), so document changes cannot inherit the old error.
3. Keep the test tied to the `documentId` + `page.page_number` identity; do not alter
   URL/page ownership or the proportional highlight contract.

### 2. Feedback validation and canonical field identity

Current request and write path:

- `services/api/app/schemas.py:178-184` requires only a non-empty
  `feedback_type`; both `field_id` and `corrected_value` are optional strings for all
  feedback types.
- `services/api/app/routers/feedback.py:24-45` checks only that the document exists,
  then forwards the payload directly to the service.
- `services/api/app/feedback.py:21-41` creates and commits a `FeedbackEvent` without
  checking feedback type, field presence, corrected-value content, or canonical field
  identity.
- The browser form disables an empty trimmed value at
  `apps/web/src/components/fields/CorrectionControl.tsx:27-37,49-77`, but the API is
  the authority and can be called without that UI. `apps/web/src/api/documents.ts:93-107`
  also models both fields as optional.

Current canonical lookup and overlay:

- `Document.current_parse_run_id` is the current-run pointer at
  `services/api/app/models.py:31-69`; `ParseRun.canonical` is immutable JSON at
  `models.py:106-139`.
- The canonical endpoint resolves the current run (or an explicitly requested
  historical version) at `services/api/app/routers/documents.py:195-220`, then applies
  the document's feedback overlay at `:221-224`.
- `apply_corrections` deep-copies only when corrections exist and overlays matching
  `extracted_fields[].id` at `services/api/app/feedback.py:62-80`; an unknown stored
  ID is silently ignored. That makes accepting an invalid/stale ID an invisible,
  orphaned correction.
- Existing tests prove valid persistence and raw-value preservation at
  `services/api/tests/test_feedback_api.py:22-61`, latest-correction-wins at `:63-97`,
  structured unknown-document 404 at `:99-105`, and that `general_comment` may omit a
  field at `:108-123`. There is no test for critical-correction field/value presence,
  invalid IDs, stale IDs, or “no event stored on rejection.”

The required validation seam is the document's current `ParseRun.canonical`, reached
through `Document.current_parse_run_id`; compare the submitted ID with the current
canonical `extracted_fields[].id` before calling `record_feedback`. A missing/blank
`field_id` or `corrected_value` must be rejected only for
`critical_field_correction`; the existing general-comment behavior must remain
allowed. Invalid/stale IDs must go through the documented `ApiError` envelope:
`services/api/app/errors.py:16-25` currently has no field-validation code, while the
structured envelope is defined at `errors.py:28-80`. The implementation should add a
stable named error code and assert its `code`, `request_id`, `retryable`, and useful
`details` in API tests rather than relying on string matching or an unstructured
framework error.

Append-only and raw-data constraints remain satisfied by the existing design: the
`FeedbackEvent` model is append-only at `services/api/app/models.py:142-163`, and the
overlay must continue to leave `ParseRun.canonical` unchanged. No
`parse_run_id` exists on `FeedbackEvent` (`models.py:152-163` and migration
`services/api/alembic/versions/0003_phase3_feedback.py:16-35`). Parse-run-aware
correction binding is a future migration/contract concern only. This task should
validate against the current parse without adding that migration or changing parser
strategy. In particular, historical canonical reads currently still use the
document-scoped overlay (`documents.py:204-224`); do not broaden this hardening task
into run-scoped correction migration.

Required API tests in `services/api/tests/test_feedback_api.py` (or a focused adjacent
API test) should cover:

- critical correction with missing, empty, and whitespace-only `field_id`;
- critical correction with missing, empty, and whitespace-only `corrected_value`;
- an unknown field ID and an ID absent from the current canonical after a current-run
  change, each returning the structured error and creating no feedback row;
- a valid current field ID still returning 201, overlaying the latest correction, and
  preserving the stored raw canonical value;
- `general_comment` without `field_id` remaining valid;
- migration-from-empty regression via `make db-migration-test` because the feedback
  table remains part of the shipped schema.

### 3. Responsive browser smoke coverage and Phase 3 assistant restriction

Current browser coverage:

- `apps/web/e2e/upload-verify-correct.spec.ts:16-57` is the required full journey:
  login, upload, processing, open, metadata verification, source jump, correction,
  reload, and persistence.
- `apps/web/playwright.config.ts:35-46` defines one Chromium project using
  `devices["Desktop Chrome"]`; there are no tablet/mobile projects or viewport
  overrides. The real API/worker/web servers are configured at `playwright.config.ts:47-70`.
- No source or test currently references a viewport smoke suite (`rg` found no
  `viewport`, `setViewportSize`, or `test.use` in `apps/web/e2e`).

The responsive implementation already exposes the intended surfaces:

- Breakpoints are mobile `<768`, tablet `768–1199`, desktop `>=1200` at
  `apps/web/src/hooks/useBreakpoint.ts:3-10`.
- Tablet renders `Nguồn` and `Nội dung đã đọc` tabs at
  `apps/web/src/components/workspace/DocumentWorkspace.tsx:110-124`.
- Mobile renders `Văn bản` and `Chi tiết` bottom controls at
  `DocumentWorkspace.tsx:127-154`.
- Desktop uses the rail/source/details layout at `DocumentWorkspace.tsx:100-107`.
- The responsive shell opens the menu drawer below desktop at
  `apps/web/src/components/shell/AppShell.tsx:19-52`; `Sidebar.tsx:13-32` contains
  only the `Văn bản` destination.

Keep the existing full desktop spec/project unchanged. Add a lightweight smoke spec
or viewport-scoped projects at approximately 1024x768 and 390x844 (the requested
~1024px/~390px widths) that reaches a reviewable document and verifies:

- archive/navigation and the mobile/tablet menu behavior;
- source page indicator and page navigation;
- tablet details tab and mobile `Chi tiết` surface, then return to the source surface;
- no assistant navigation item, tab, button, composer, or other interactive control.

The Phase 3 restriction is explicit in `docs/PHASE_STATUS.md:227-231` and
`docs/design/02_DOCUMENT_FLOW.md:250,399-421`: no `Trợ lý` navigation/tab/control before
the Phase 4 capability gate. The live app routes only to login/archive/document at
`apps/web/src/App.tsx:10-27`, and the workspace has no assistant surface. One nuance
must be preserved in the smoke assertion: `apps/web/src/pages/LoginPage.tsx:35-42`
does display the tagline `Trợ lý tài liệu gia đình`. That is not a navigation, tab, or
control under the current design contract. A blanket assertion that no visible text
contains `Trợ lý` would fail on the login screen; assert absence of assistant
interactive UI (or explicitly resolve the copy requirement before changing it).

The smoke tests should use explicit states and role/name assertions, not fixed sleeps,
matching `docs/05_TEST_STRATEGY.md:253-267,362-369` and the Phase 3 responsive test
requirement in `docs/04_PHASE_PLAN.md:380-402`.

## Stale Phase 1/2/3 evidence in `docs/PHASE_STATUS.md`

The following entries are stale against the current checkout:

- Phase 1 `docs/PHASE_STATUS.md:118-126` says `Commit/PR: pending (working tree)`,
  while the implementation is committed as `4659fab` and is an ancestor of current
  `main`. Its local CI jobs are defined in `.github/workflows/ci.yml:169-191` and
  `:355-380`.
- Phase 2 `docs/PHASE_STATUS.md:163-173` says `Commit/PR: pending (working tree)`,
  while the implementation is committed as `fc71f8b` and is an ancestor of current
  `main`. Its local CI jobs are defined in `.github/workflows/ci.yml:193-245` and
  `:247-283`.
- Phase 3 `docs/PHASE_STATUS.md:214-222` says `Commit/PR: pending (working tree)`,
  while the implementation is committed as `d8edafe` and is exactly current
  `main`/`origin/main`. Its feedback and E2E jobs are defined in
  `.github/workflows/ci.yml:285-353`.

The Phase table still has only a concrete commit/CI reference for Phase 0 at
`docs/PHASE_STATUS.md:52-60`; the Phase 1/2/3 rows remain descriptive. The Phase 1
and Phase 2 statuses must remain `IN_PROGRESS` because the private benchmark/ADR
evidence is still explicitly missing (`PHASE_STATUS.md:38-50,146-161,197-212`). Phase
3 also inherits that limitation (`PHASE_STATUS.md:271-283`); updating commit/CI
evidence must not mark any of those phases complete or claim real-document readiness.

Live CI status was not established in this research pass: `gh run list --repo
QuocKhanhLuong/MamaGift --branch main` failed with `error connecting to
api.github.com`. Therefore, replace the three pending commit entries with the exact
commit IDs above, but do not invent PASS/run IDs. After the hardening changes land,
record a confirmed CI run ID and job results for the modified main commit. The
CI-equivalent command set is already enumerated at `docs/PHASE_STATUS.md:216-219` and
in `Makefile:115-119`; the focused gates are `make web-component-tests
feedback-tests web-e2e-smoke frontend-format-check frontend-lint
frontend-typecheck frontend-build db-migration-test`, followed by full `make check`.

## Handoff and non-goals

Implement only the three hardening areas above. Do not add Phase 4 Q&A/RAG/LLM/chat,
change parser/provider strategy, redesign the UI, or add parse-run-aware feedback
migrations. Preserve the existing source-of-truth URL page selection, current
canonical raw JSON, append-only feedback rows, and desktop full E2E journey.
