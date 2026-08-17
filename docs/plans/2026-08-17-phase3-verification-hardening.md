# Implementation plan: Phase 3 verification hardening

Run: 20260817T100005Z
Stage: plan
Role: Dev
Date: 2026-08-17

## Objective and boundary

Harden the completed Phase 3 browser verification workflow before real-document
testing. Stay within the existing document archive, source-preview, feedback, and
responsive workspace contracts.

This plan authorizes no Phase 4 work: no RAG, LLM, Q&A/chat, assistant route or
control, parser/provider changes, UI redesign, feedback migration, or parse-run-aware
correction semantics. FeedbackEvent remains document-scoped; parse-run-aware
correction migration is a documented future concern only.

This plan-stage turn changes only this file. Do not modify application code, tests,
docs/PHASE_STATUS.md, generated metadata, or existing untracked handoffs. Do not run
git add or git commit.

## Source-backed baseline

- Current main and origin/main are d8edafe9724a3cca3004c5ecb4708c9da6bd6928.
- Phase 1 baseline: 4659fab647078b75015761857fd4baf317b5f64e.
- Phase 2 baseline: fc71f8b0178fbde82ffa2eebbffa43b9057e3699.
- Preserve pre-existing untracked .agenteam/events/, .agenteam/state/,
  docs/research/, and docs/strategies/ work.
- SourceViewer currently owns one parent imageState while keying only the img;
  a failed page therefore leaves the parent in the error branch.
- The feedback router calls record_feedback directly, and that function inserts
  and commits without current-canonical field validation.
- The existing Playwright project is Chromium/Desktop Chrome and
  upload-verify-correct.spec.ts is the full desktop correction journey.
- Phase 1, 2, and 3 status entries still say Commit/PR: pending (working tree);
  their actual hashes and observable local/CI evidence must be recorded later,
  without changing their IN_PROGRESS status.

## Planned file scope

| Area | Later implementation targets | Explicitly unchanged |
|---|---|---|
| Preview recovery | apps/web/src/components/workspace/SourceViewer.tsx; apps/web/src/components/workspace/SourceViewer.test.tsx | DocumentWorkspace.tsx, URL/search-param page ownership, useBreakpoint, preview URL, page controls, bbox math, copy and layout |
| Feedback validation | services/api/app/errors.py, services/api/app/feedback.py, services/api/app/routers/feedback.py, services/api/tests/test_feedback_api.py | schemas.py optional fields, models.py schema, migration 0003_phase3_feedback, parser code, raw canonical JSON, existing overlay behavior |
| Responsive smoke | new apps/web/e2e/responsive-workspace.spec.ts | apps/web/e2e/upload-verify-correct.spec.ts and apps/web/playwright.config.ts unless a discovery issue is proven |
| Evidence | docs/PHASE_STATUS.md in the later implementation/documentation stage | Phase statuses, ADR-001/private-corpus limitation, and real-document readiness boundary |

## 1. SourceViewer recovery

### Implementation

Target SourceViewer in apps/web/src/components/workspace/SourceViewer.tsx,
currently the component at line 13 and imageState at line 26.

1. Define preview identity as the exact pair (documentId, page.page_number).
2. Extract the image/error branch into a file-local PreviewImage boundary, or an
   equivalent state-owning child, rendered with a key derived from both identity
   components. Its initial state is loading; onLoad becomes ready; onError becomes
   error and retains the existing role=alert copy.
3. Keep the parent hooks before the !page early return. Keep the existing null
   placeholder, page indicator, previous/next controls, image src/alt, inner image
   key, focus overlay, proportional bbox calculations, and citation status.
4. The keyed state owner must mount a fresh loading image synchronously when either
   page number or document ID changes. A failed page must not remove the image for
   a later page or for the same page number from another document. Do not add a
   retry button, change the URL, remount DocumentWorkspace, or introduce new
   loading animation/copy.

### Component tests

Extend apps/web/src/components/workspace/SourceViewer.test.tsx using rendered img
events, not component state or implementation-only variables:

- Render doc_1 page 1, fire error, and assert the existing alert.
- Rerender doc_1 page 2; assert the page-2 preview URL/image is present and the old
  alert is absent; fire load and assert the image remains available without an
  alert.
- Repeat with page 1 and a changed document ID, asserting the new document URL and
  recovery after the prior document error.
- Retain the current null placeholder, page-count, navigation-button,
  proportional-highlight, and no-highlight assertions.

## 2. Current-canonical feedback validation

### Application implementation

Target services/api/app/errors.py by adding stable codes adjacent to the existing
codes:

- FEEDBACK_FIELD_REQUIRED = feedback_field_required
- FEEDBACK_FIELD_INVALID = feedback_field_invalid

Target services/api/app/feedback.py with a validation/orchestration seam:

1. Add validate_feedback, or an equivalently named service helper, receiving the
   session, document, and payload values.
2. Add submit_feedback as the service orchestration used by the router. It must
   validate completely before calling the existing record_feedback persistence seam.
3. Leave record_feedback, FeedbackEvent, _latest_corrections_by_field, and
   apply_corrections append-only/latest-wins behavior unchanged.

Target services/api/app/routers/feedback.py so document lookup and the structured
unknown-document 404 remain intact, then call the validated service orchestration
instead of record_feedback directly.

Keep services/api/app/schemas.py as an inspection-only target: field_id and
corrected_value stay optional because general_comment may omit them. Do not move
the conditional rule into a Pydantic validator that would produce the wrong
framework error envelope.

### Validation contract and ordering

Apply checks only when feedback_type is exactly critical_field_correction:

1. Treat None, empty, and whitespace-only field_id or corrected_value as missing,
   in stable order field_id, then corrected_value.
2. Raise ApiError with HTTP 422, code feedback_field_required, retryable=false,
   and details.missing_fields containing missing names in that order. Do not trim
   and rewrite a non-empty submitted value before storing.
3. Resolve only document.current_parse_run_id with session.get(ParseRun, ...).
   Require the pointed run to exist and belong to the same document. A null,
   dangling, or cross-document pointer uses the existing structured CONFLICT
   contract (HTTP 409) with document_id, current_parse_run_id, and
   reason=current_canonical_unavailable details.
4. Read only the pointed run's raw canonical.extracted_fields IDs. Compare the
   submitted field_id exactly; do not consult document mirrors, an overlaid
   response, field names, or an older parse run.
5. For an absent or old ID, raise ApiError with HTTP 422, code
   feedback_field_invalid, retryable=false, and details containing current
   document_id, submitted field_id, and reason=not_in_current_canonical.
6. Only after all checks pass may the service construct, add, or commit a feedback
   event. Rejected requests must not reach record_feedback, session.add, or
   session.commit for a FeedbackEvent.
7. For non-critical feedback, preserve current behavior, including a general_comment
   without a field ID. Preserve request-ID echoing through the existing ApiError
   handler.

No valid correction may mutate ParseRun.canonical; it remains a new event and is
overlaid only on a fresh canonical read. Do not add parse_run_id to feedback, rewrite
old events, or alter historical canonical overlay behavior.

### API tests

Extend services/api/tests/test_feedback_api.py and keep existing tests for valid
persistence, latest-correction-wins, unknown-document 404, and general comments.
Add:

- parameterized missing, empty, and whitespace-only field_id cases;
- parameterized missing, empty, and whitespace-only corrected_value cases;
- assertions for HTTP 422, stable error code, retryable=false, echoed X-Request-ID,
  stable details.missing_fields, and zero new FeedbackEvent rows for every rejected
  request;
- an unknown current-canonical ID case with structured invalid-ID details and zero
  event rows;
- a stale-ID case that captures an ID from an earlier parse, advances the document's
  current_parse_run_id through the existing reprocess path or a test-only equivalent
  fixture, and rejects the old ID against the new raw canonical; do not add a
  schema column or parser behavior;
- a no-current-canonical case, if constructible with existing schema, asserting the
  structured 409 and no event;
- a valid correction test that snapshots raw ParseRun.canonical before and after
  submission, asserts equivalent JSON equality, then verifies the fresh API canonical
  response contains the read-time overlay;
- preservation of latest-correction-wins and general_comment without field_id.

Run services/api/tests/test_migrations.py through the existing migration target; do
not modify 0003_phase3_feedback.

## 3. Responsive browser smoke coverage

Add only apps/web/e2e/responsive-workspace.spec.ts. Use spec-local Playwright
viewport scopes so the existing Chromium Desktop Chrome project does not execute
the full journey at additional sizes:

- tablet: 1024 x 768;
- mobile: 390 x 844.

Reuse the current real API/worker/scratch-SQLite setup from
apps/web/playwright.config.ts and the existing deterministic fixture
benchmarks/parser/fixtures/quyet_dinh_dieu_khoan.pdf. Do not add mocks, fixed
sleeps, coordinate clicks, or a second correction-persistence journey.

Each viewport smoke path must:

1. Navigate to /, assert /dang-nhap, complete the current name handoff, and reach
   /van-ban with the Văn bản heading.
2. Open Mở menu, assert the Điều hướng chính navigation contains the Văn bản link,
   then close/use the drawer. Repeat the assistant-control absence check at the
   archive/menu surface.
3. Upload the fixture, wait for /van-ban/doc_... and exact Cần kiểm tra reviewable
   status. Because the second viewport can hit the duplicate-upload contract, wait
   on URL/status rather than assuming a fresh ID.
4. Assert Trang <n> / <count>, perform a page-next transition and page-previous
   transition (the current fixture is Trang 2 / 2), using role/state assertions.
5. At tablet width, switch Nguồn -> Nội dung đã đọc, assert the details surface
   such as Thông tin văn bản, then return to Nguồn and assert the source indicator.
6. At mobile width, switch Văn bản -> Chi tiết, assert the details surface, then
   return to Văn bản and assert the source indicator.
7. At the archive/menu and each workspace surface, inspect applicable interactive
   roles (button, link, tab, textbox, combobox, menuitem, and other relevant
   controls) and assert no accessible name contains Trợ lý.

Do not assert that the entire page has no Trợ lý text: the approved login tagline
Trợ lý tài liệu gia đình is non-interactive and must remain unchanged. Do not
modify upload-verify-correct.spec.ts or add a second full desktop journey.

## 4. Factual Phase Status evidence update

In the later implementation/documentation stage only, update stale entries in
docs/PHASE_STATUS.md:

- Phase 1: record observed commit
  4659fab647078b75015761857fd4baf317b5f64e and actual publication state.
- Phase 2: record observed commit
  fc71f8b0178fbde82ffa2eebbffa43b9057e3699 and actual publication state.
- Phase 3: record baseline
  d8edafe9724a3cca3004c5ecb4708c9da6bd6928 and, only after a real later
  implementation commit exists, the actual hardening commit.

For each phase, distinguish:

- commands actually run from commands merely planned;
- CI job definitions in .github/workflows/ci.yml from a confirmed GitHub run;
- unavailable live CI from PASS. Do not invent a run ID when GitHub is unreachable.

Keep Phases 1, 2, and 3 IN_PROGRESS; retain the ADR-001/private-corpus
limitation, degraded/parser-strategy boundary, and lack of real-document or
production-readiness claims. Name the preserved desktop E2E plus new tablet/mobile
smoke paths only after they actually pass.

## 5. Verification and scope gates

After implementation, run and report each result as PASS, FAIL, or unavailable with
the reason.

### Focused behavior checks

    npm --prefix apps/web exec vitest run src/components/workspace/SourceViewer.test.tsx
    uv run pytest services/api/tests/test_feedback_api.py -q
    make db-migration-test
    npm run test:e2e --prefix apps/web

The E2E command must include the unchanged full desktop journey and new responsive
smoke file.

### Focused CI-equivalent gate set

    make web-component-tests feedback-tests web-e2e-smoke \
      frontend-format-check frontend-lint frontend-typecheck frontend-build \
      db-migration-test

### Full repository gate

    make check

### Documentation and scope checks

    make docs-check
    git diff --check
    git status --short --branch
    git diff --name-only

The final scope audit must show only approved implementation/test/evidence paths plus
intentionally preserved pre-existing untracked work. It must show no Phase 4,
RAG/LLM/chat, parser, UI-redesign, or migration files. The plan-stage audit for
this turn must show only this new file, with no staging or commit.

## Acceptance checklist for the later implementation stage

- [ ] A failed page N preview recovers to a loadable page N+1.
- [ ] A failed preview for document A does not poison the same page for document B.
- [ ] Critical corrections reject all required-value missing/blank forms before
      persistence with the agreed structured envelope.
- [ ] Unknown and stale IDs are checked against the current raw canonical and
      rejected with no event.
- [ ] Valid corrections preserve raw canonical data, overlay at read time, and
      retain latest-correction-wins behavior.
- [ ] general_comment without a field ID remains valid.
- [ ] Desktop full E2E remains intact and passes.
- [ ] Tablet 1024px and mobile 390px smoke paths cover menu/archive,
      source/page navigation, details, and return navigation.
- [ ] No responsive smoke path exposes interactive Trợ lý UI.
- [ ] Phase evidence is factual, statuses remain IN_PROGRESS, and future-only
      parse-run-aware migration remains unimplemented.
