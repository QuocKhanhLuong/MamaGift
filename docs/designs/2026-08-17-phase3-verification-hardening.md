# Design: Phase 3 verification hardening

Run: `20260817T100005Z`
Stage: `design`
Role: `Architect`
Date: `2026-08-17`

This is a design-only handoff. It authorizes no application, test, or phase-status
edits in this stage. The implementation boundary is the completed Phase 3 browser
verification workflow; Phase 4, RAG, LLM, chat, parser changes, UI redesign, and
parse-run-aware correction migration remain out of scope.

## 1. Current facts and binding contracts

The current checkout was inspected at `main`/`origin/main`:

- `d8edafe9724a3cca3004c5ecb4708c9da6bd6928` — current Phase 3 implementation.
- `4659fab647078b75015761857fd4baf317b5f64e` — Phase 1 implementation.
- `fc71f8b0178fbde82ffa2eebbffa43b9057e3699` — Phase 2 implementation.
- Existing untracked `.agenteam/events/`, `.agenteam/state/`, `docs/research/`, and
  `docs/strategies/` work is unrelated and must remain untouched.

The binding execution rules are:

- `docs/09_CODEX_EXECUTION.md:24-56,90-96` — one active phase, no later-phase
  implementation, and tests for every active-phase behavior.
- `docs/09_CODEX_EXECUTION.md:110-118` — raw parse/canonical data remain separate;
  corrections are append-only feedback events.
- `docs/04_PHASE_PLAN.md:361-406` — component/API/browser/responsive coverage is
  required for Phase 3; the existing full browser journey remains the exit path.
- `docs/PHASE_STATUS.md:7-21,38-50,197-212,271-283` — Phases 1, 2, and 3 remain
  `IN_PROGRESS` while private parser evidence and ADR-001 remain unresolved.

### Existing seams

| Concern | Current source-backed seam | Design implication |
|---|---|---|
| Preview identity | `SourceViewer` receives `documentId` and `page`; the `<img>` key is `${documentId}-${page.page_number}` at `apps/web/src/components/workspace/SourceViewer.tsx:73-79`. | Move or bind the error/loading state to the same identity; changing only the image key is insufficient while the parent state survives. |
| Page ownership | `DocumentWorkspace` derives `page` from URL search params at `apps/web/src/components/workspace/DocumentWorkspace.tsx:43-55`. | Do not add local page ownership, remount the workspace, or change URL/query behavior. |
| Current canonical | `Document.current_parse_run_id` is `services/api/app/models.py:31-69`; `ParseRun.canonical` is `models.py:106-139`; current lookup is `services/api/app/routers/documents.py:195-224`. | Validate submitted field IDs against the pointed-to run's raw `canonical.extracted_fields`, not a mirrored document column or an overlaid response. |
| Feedback persistence | `record_feedback` adds and commits `FeedbackEvent` at `services/api/app/feedback.py:21-41`; `FeedbackEvent` is document-scoped and append-only at `models.py:142-163`. | All critical-correction checks must complete before `session.add`, commit, or `record_feedback`; no migration is needed. |
| Error envelope | `ApiError`, `ErrorBody`, and `api_error_handler` are at `services/api/app/errors.py:28-81`; request IDs already echo `X-Request-ID`. | Use `ApiError` for field validation so responses remain `{error:{code,message,retryable,request_id,details}}`, not FastAPI's default validation body. |
| Responsive workspace | Breakpoints are `<768` mobile, `768-1199` tablet, `>=1200` desktop at `apps/web/src/hooks/useBreakpoint.ts:3-23`; tablet tabs and mobile controls are in `DocumentWorkspace.tsx:100-155`. | Smoke only the existing surfaces at `1024x768` and `390x844`; do not change breakpoints or copy. |
| Assistant restriction | `Sidebar.tsx:6-32` has only `Văn bản`; the login paragraph includes the approved tagline `Trợ lý tài liệu gia đình` at `LoginPage.tsx:40-42`. | Assert absence of interactive assistant controls by role/name, never absence of all visible `Trợ lý` text. |

## 2. Approaches considered

### Approach A — Minimal effect reset, router-local validation, config projects

- Add a `useEffect` in `SourceViewer` keyed by `documentId` and
  `page?.page_number` to call `setImageState("loading")`.
- Validate critical corrections inline in `routers/feedback.py` before calling
  `record_feedback`.
- Add tablet/mobile Playwright projects to `playwright.config.ts`.

Advantages: smallest apparent diff and few new symbols. Risks: an effect runs after
the first render of a new identity, so a previous error can be visible for one render;
late image events still share parent state. Router-only validation also makes the data
integrity rule dependent on this one endpoint. Additional Playwright projects can
make the full desktop spec run at every viewport unless project selection is carefully
filtered.

### Approach B — Identity/state pair, shared validation helper, spec-local scopes

- Keep state in `SourceViewer` as `{identity, status}` and render `loading` whenever
  the state identity does not equal `(documentId, page.page_number)`.
- Add a validation helper in `feedback.py`; call it from the router before the
  persistence function.
- Add one responsive spec with `test.use({ viewport })` scopes and leave the
  Playwright config and existing desktop spec unchanged.

Advantages: loading is computed synchronously for a new identity and the desktop
project is preserved. Risks: event identity guards are subtle; a future change that
forgets to guard an image event can reintroduce cross-page state coupling. The helper
also needs a clear service-call contract so no caller can persist an unvalidated event.

### Approach C — Keyed preview boundary, service orchestration, spec-local scopes
*(recommended)*

- Keep `SourceViewer` responsible for page controls, URL-owned selection, the
  null-page placeholder, and the focus overlay. Extract only the preview image/error
  branch into an internal `PreviewImage` boundary rendered with a key derived from
  `(documentId, page.page_number)`. The child owns its `loading/ready/error` state.
- Add a service-level `validate_feedback` plus `submit_feedback` orchestration in
  `feedback.py`; the router calls `submit_feedback`, which validates and only then
  calls `record_feedback`.
- Add `responsive-workspace.spec.ts` with spec-local tablet/mobile viewport scopes;
  leave the existing Chromium desktop project and full journey unchanged.

Advantages: React remounts the state owner before the new preview renders, so a failed
page cannot suppress a later page and stale events cannot cross the keyed boundary.
The validation seam is explicit and reusable while guaranteeing that the current
router path validates before persistence. Spec-local scopes exercise the existing
real-server contract without multiplying the full desktop journey. The small internal
preview extraction does not change visible UI or page ownership.

Recommendation: implement Approach C. It is the smallest design that gives both
SourceViewer and feedback validation an explicit identity/ownership boundary, while
keeping all current Phase 3 contracts intact.

## 3. Recommended implementation design

### 3.1 SourceViewer identity-keyed recovery

Targets:

- `apps/web/src/components/workspace/SourceViewer.tsx`
  - existing `SourceViewer` function, currently lines `13-104`;
  - new file-local `PreviewImage` (or equivalently named) component for the image,
    error branch, and proportional focus overlay.
- `apps/web/src/components/workspace/SourceViewer.test.tsx`
  - retain the existing five behaviors and add event/recovery cases.

Execution contract:

1. Define the preview identity as the exact tuple
   `(documentId, page.page_number)`. The key must include both values.
2. Keep the `SourceViewer` hook ordering valid by keeping all hooks before the
   `if (!page)` placeholder return. The parent continues to render the page controls
   and the existing `Đang mở bản gốc…` placeholder when no canonical page exists.
3. Render the preview boundary with the identity key. Its initial state is
   `loading`; its `onLoad` transition is `ready`; its `onError` transition is `error`.
   A failed child may render the existing `Không thể mở trang này.` alert.
4. Keep the existing `<img>` key, `getPagePreviewUrl(documentId, page.page_number)`,
   Vietnamese alt text, page indicator, page buttons, and bbox percentage math. The
   inner key is harmlessly redundant but preserves the current identity contract.
5. On a page change after an error, React must discard the old error state and mount
   a new image immediately. On a document change with the same page number, it must
   do the same. No retry button, URL change, scroll change, or workspace remount is
   part of this fix.
6. Do not add a competing loading animation or change the visual language. The
   current component has no distinct loading markup; the test contract is image
   presence/error recovery, not a new loading design.

Component test contract in `SourceViewer.test.tsx`:

- Render page 1 for `doc_1`, fire `error` on its image, and assert the existing
  `role="alert"`.
- Rerender page 2 for `doc_1`; assert the page-2 image is present with the page-2
  preview URL, the old alert is absent, then fire `load` and assert the image remains
  available without an alert.
- Repeat the failure/recovery sequence with page 1 and a changed document ID. Assert
  the new document URL is used and the old alert is absent after rerender/load.
- Preserve assertions for the null placeholder, `Trang 2 / 2`, navigation button
  behavior, proportional highlight placement, and no-highlight behavior.
- Drive recovery through rendered `img` load/error events using Testing Library;
  never inspect component state or implementation-only variables.

Risk controls:

- Key the state owner, not only the `<img>` node; this is the defect in the current
  implementation where the parent `imageState` outlives the keyed image.
- Keep the focus overlay in the keyed preview boundary only if its inputs remain the
  same `page` and `focusedBlock`; otherwise leave the overlay in `SourceViewer` and
  key only the image/error child. Either shape must preserve the existing highlight
  contract; the preferred shape keeps the current overlay markup in the child with
  no calculation changes.
- Do not alter `DocumentWorkspace`, `useBreakpoint`, or search-parameter ownership.

### 3.2 Feedback validation before persistence

Targets:

- `services/api/app/errors.py`
  - add stable constants next to the existing API codes:
    `FEEDBACK_FIELD_REQUIRED = "feedback_field_required"` and
    `FEEDBACK_FIELD_INVALID = "feedback_field_invalid"`.
- `services/api/app/feedback.py`
  - add `validate_feedback` (or the equivalent file-local service helper);
  - add `submit_feedback` as the validated service orchestration;
  - leave `record_feedback` as the append-only persistence seam;
  - leave `_latest_corrections_by_field` and `apply_corrections` behavior unchanged.
- `services/api/app/routers/feedback.py`
  - preserve document lookup and structured `not_found` 404;
  - call the service orchestration instead of persisting directly.
- `services/api/app/schemas.py`
  - inspect only; keep `FeedbackRequest.field_id` and
    `FeedbackRequest.corrected_value` optional because `general_comment` is allowed
    to omit them. Do not move this conditional rule into a schema validator that
    would produce FastAPI's unrelated validation envelope.
- `services/api/tests/test_feedback_api.py`
  - extend the existing integration tests at lines `22-123`.
- `services/api/tests/test_migrations.py` and
  `services/api/alembic/versions/0003_phase3_feedback.py`
  - no schema change; run the migration regression only.

Validation algorithm:

1. The router loads `Document` exactly as today. For non-
   `critical_field_correction` types, preserve existing behavior, including
   `general_comment` without `field_id`.
2. For `critical_field_correction`, evaluate required values in stable order:
   `field_id`, then `corrected_value`. Treat `None`, `""`, and whitespace-only
   strings as missing. Do not trim and rewrite the submitted value before storage.
3. If either value is missing, raise:

   ```text
   HTTP 422
   error.code = feedback_field_required
   error.retryable = false
   error.details.missing_fields = [field names in field_id, corrected_value order]
   ```

   The message is human-readable but not a test contract; tests assert the stable
   code and details.

4. Resolve the current run only through
   `document.current_parse_run_id`, using `session.get(ParseRun, ...)`. Confirm the
   pointed run belongs to the same document. If the pointer is null, dangling, or
   points to a run for another document, raise the existing structured conflict
   contract (`errors.CONFLICT`, HTTP 409) with details including `document_id`,
   `current_parse_run_id`, and `reason: "current_canonical_unavailable"`.
5. Read only `run.canonical["extracted_fields"]` for field identity. Compare the
   submitted `field_id` exactly against the current raw extracted-field IDs. Do not
   consult an overlaid canonical response, document mirrors, field names, or an
   older parse run.
6. If the ID is absent, raise:

   ```text
   HTTP 422
   error.code = feedback_field_invalid
   error.retryable = false
   error.details.document_id = current document ID
   error.details.field_id = submitted field ID
   error.details.reason = not_in_current_canonical
   ```

7. Only after all checks pass does `submit_feedback` call `record_feedback`. No
   invalid request may reach `session.add`, `session.commit`, or the append-only event
   constructor. Keep the incoming `X-Request-ID` behavior unchanged so tests can
   assert request correlation in the error envelope.
8. `record_feedback`, `FeedbackEvent`, `_latest_corrections_by_field`, and
   `apply_corrections` retain their current append-only/latest-wins behavior. A valid
   correction creates a new event; it never edits or replaces `ParseRun.canonical`.
   The raw `raw_value` and `normalized_value` remain unchanged.

API test contract:

- Parameterize missing, empty, and whitespace-only `field_id` and
  `corrected_value` cases. Assert 422, `feedback_field_required`, `retryable == false`,
  stable `missing_fields`, an echoed request ID, and zero `FeedbackEvent` rows.
- Submit an unknown ID and assert 422, `feedback_field_invalid`,
  `reason == "not_in_current_canonical"`, document/field details, and zero rows.
- Build a stale-ID scenario from the existing versioning fixture: process a document,
  capture the first run's field ID, advance `Document.current_parse_run_id` to a new
  current `ParseRun` through the existing reprocess path or a test-only equivalent
  fixture, and ensure the new raw canonical uses a different field ID. Submit the old
  ID and assert the same structured 422/no-row contract. The fixture must not add a
  `parse_run_id` column or change parser code.
- Extend the valid correction test to snapshot `ParseRun.canonical` directly before
  and after the request, assert equality of the raw artifact, then assert the fresh
  canonical GET has the read-time corrected overlay.
- Retain latest-correction-wins, unknown-document structured 404, and
  `general_comment` without `field_id` coverage.
- Add a no-current-canonical case if the helper can construct it without changing
  production schema; assert structured 409/no row. This protects the dangling-pointer
  branch without broadening the API.

Concurrency and future boundary:

- The validation and insert occur in one request/session, but this increment does not
  bind an event to a parse run. A reprocess can advance the current pointer after
  validation; that race and historical overlay semantics remain the known future
  migration concern.
- Do not add `parse_run_id` to `FeedbackEvent`, alter migration `0003`, rewrite old
  events, or change historical `GET /canonical?version=...` overlay behavior.

### 3.3 Responsive browser smoke coverage

Target:

- New file: `apps/web/e2e/responsive-workspace.spec.ts`.
- No required change to `apps/web/playwright.config.ts`; its existing `testDir` picks
  up the new spec, and its `chromium` Desktop Chrome project remains the full-journey
  project.
- No change to `apps/web/e2e/upload-verify-correct.spec.ts`; preserve its full
  login/upload/process/verify/source/correct/reload journey.

Use two spec-local scopes:

```text
tablet: { width: 1024, height: 768 }
mobile: { width: 390, height: 844 }
```

Each smoke test may use the existing deterministic fixture and real Playwright
servers. The API duplicate-upload contract returns the existing document, so the
second viewport test must still wait on the explicit reviewable status rather than
assuming a fresh document. Do not add mocks, fixed sleeps, coordinate clicks, or a
second correction-persistence journey.

Required path for each viewport:

1. Navigate to `/`, assert `/dang-nhap`, perform the existing name handoff, and reach
   `/van-ban` with the `Văn bản` heading.
2. At the responsive shell, open `Mở menu`, assert the named `Điều hướng chính`
   contains the `Văn bản` link, then close/use the drawer. This covers archive/menu
   navigation without relying on a particular drawer animation.
3. Upload the existing reviewable fixture, wait for `/van-ban/doc_...`, and wait for
   the exact `Cần kiểm tra` status. Use explicit URL, role, and status assertions.
4. Assert `Trang <n> / <count>`, click `Trang sau` and assert `Trang 2 / 2` for the
   known two-page fixture, then click `Trang trước` and return to page 1. If the
   fixture contract changes page count, retain a page transition assertion based on
   the rendered indicator rather than a sleep.
5. Tablet only: click the `Nội dung đã đọc` tab, assert the details surface (for
   example `Thông tin văn bản`), click `Nguồn`, and assert the source indicator.
6. Mobile only: click the `Chi tiết` control, assert the details surface, click
   `Văn bản`, and assert the source indicator.
7. At archive/menu and each workspace surface, assert no interactive control has an
   accessible name containing `Trợ lý`. Check the relevant `button`, `link`, `tab`,
   `textbox`, `combobox`, `menuitem`, and other applicable interactive roles. Do not
   assert `page.getByText(/Trợ lý/)` has zero matches: the approved login paragraph
   contains `Trợ lý tài liệu gia đình` and is not interactive UI.

Keep the existing real API/worker/scratch SQLite setup from `playwright.config.ts:47-70`.
The new smoke suite proves responsive navigation and source/details reachability; the
existing desktop test remains the only full correction journey.

Smoke risks and controls:

- Radix tabs expose role/name state; assert the tab/control names rather than CSS
  classes or coordinates.
- The source image is a real page-preview request; wait on the page indicator and
  status, not on arbitrary time. A preview-specific failure is covered by the
  component tests in this increment, not hidden with an E2E retry.
- The login tagline is intentionally excluded from the assistant restriction because
  the Phase 3 contract forbids assistant controls, not the approved login copy.

### 3.4 Factual Phase Status evidence update

Target: `docs/PHASE_STATUS.md`, only in the later implementation/documentation stage;
it must not be edited during this design stage.

Update the stale `Commit/PR: pending (working tree)` entries at the current lines
`120`, `165`, and `216` as follows:

- Phase 1: record observed commit
  `4659fab647078b75015761857fd4baf317b5f64e` and its actual publication state.
- Phase 2: record observed commit
  `fc71f8b0178fbde82ffa2eebbffa43b9057e3699` and its actual publication state.
- Phase 3: record the observed baseline
  `d8edafe9724a3cca3004c5ecb4708c9da6bd6928` plus the actual hardening commit once
  implementation is complete and committed. Do not use a placeholder or claim a
  commit that does not exist.

For each phase, distinguish:

- local commands actually run from commands merely planned;
- CI jobs defined in `.github/workflows/ci.yml` from a confirmed GitHub run;
- unavailable live CI from PASS. The research stage observed `gh run list` failing
  with `error connecting to api.github.com`, so no run ID may be invented.

The final Phase 3 evidence should name the preserved desktop E2E plus the tablet and
mobile smoke coverage only after those tests pass. It must keep the phase table and
progress statuses `IN_PROGRESS`, retain the ADR-001/private-corpus limitations, and
make no claim of real-document or production parser readiness. Do not turn this
design artifact's proposed command list into evidence.

## 4. Execution and verification contract

Implementation order:

1. Dev implements the keyed preview boundary and feedback validation seam.
2. QA adds component/API/migration assertions and the responsive smoke spec.
3. Dev/QA run focused gates, then the complete repository gate.
4. PM updates `docs/PHASE_STATUS.md` from observed hashes, command results, and
   observable CI only.
5. Reviewer confirms the diff contains only the SourceViewer recovery, feedback
   validation, responsive smoke coverage, and factual evidence update.

Focused local gate set:

```text
make web-component-tests feedback-tests web-e2e-smoke \
  frontend-format-check frontend-lint frontend-typecheck frontend-build \
  db-migration-test
make check
```

The implementation report must mark every command `PASS`, `FAIL`, or `unavailable`,
including the exact reason for an unavailable live/browser/credential/runtime check.
`make check` already includes docs, repository hygiene, secret scan, backend gates,
parser gates, migration/feedback tests, frontend gates, Compose validation, and the
desktop-plus-responsive E2E suite.

## 5. Explicit non-goals and future-only concern

This design does not authorize:

- Phase 4 Q&A, RAG, LLM, chat, assistant navigation, assistant UI, or a chat composer;
- parser/provider strategy changes, private benchmark execution, or PyMuPDF promotion;
- breakpoint, typography, palette, copy, layout, or interaction redesign;
- URL/page ownership, provenance, bbox math, or desktop full-E2E changes;
- raw canonical rewrites, feedback update/delete behavior, or a new migration;
- `parse_run_id` on feedback or run-aware historical correction semantics.

The current hardening intentionally validates IDs against the document's current raw
canonical parse while `FeedbackEvent` remains document-scoped. A future migration may
bind correction events to a specific `parse_run_id`, define historical overlay and
backfill semantics, and update the API/data contract. That is recorded as a future
concern only and is not part of this Phase 3 design.
