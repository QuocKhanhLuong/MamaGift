# MamaGift Chat Flow

**Status:** Draft design handoff — requires user review before implementation authority.

**Scope:** Claude-inspired single-document assistant interaction for Phase 4, attached to the document-first workspace. This document does not authorize archive-wide chat, external search, autonomous actions, or a general-purpose chatbot.

## 1. Chat contract

MamaGift chat is a grounded inspection surface. The user asks about one selected document; the API retrieves bounded source blocks and returns an answer plus validated citations.

```text
Selected document
      |
      v
Question / quick action
      |
      v
POST /api/v1/documents/{document_id}/qa
      |
      +--> answered + citations
      +--> insufficient_evidence + available citations
      +--> ai_worker_unavailable
      +--> failed
```

The current request body contains only:

```json
{
  "question": "Văn bản này yêu cầu trường làm gì?"
}
```

The response contains `answer`, `status`, `citations`, and retrieval/model metadata. The UI must consume application DTOs and must not depend on database rows, provider-specific fields, or invented citation formats.

### 1.1 Current and later capability boundaries

| Capability | Phase | Chat behavior |
|---|---:|---|
| Composer shell and document context | 3/4 | Phase 3 may show the shell/placeholder; it must not pretend to answer. |
| Grounded Q&A over one selected document | 4 | Working interaction defined here. |
| Quick actions: summary, tasks, deadlines, applicability | 4 | Each is a normal grounded question through the same path. |
| Citation page/block jump | 4 | Required for every factual answer. |
| Insufficient evidence / AI unavailable | 4 | Explicit result states, not generic blank/errors. |
| Streaming tokens | Not in current API contract | Do not require it. If later adopted, preserve stable scroll and source behavior. |
| Persistent conversation history | Not specified | Keep current thread local to the selected document until a contract exists. |
| Cross-document chat, recency/freshness, reranking | 5 | Label as later; do not route a Phase 4 question across the archive. |
| Legal conclusion/autonomous action | Non-goal | Never present as a chat feature. |

## 2. Chat shell

### 2.1 Empty assistant state

```text
+--------------------------------------------------+
| Trợ lý                              Công văn 142  |
|                                                  |
|                    Chào mẹ,                      |
|              Hôm nay mẹ cần tìm gì?              |
|                                                  |
|       [Tóm tắt văn bản] [Tìm deadline]           |
|       [Tôi cần làm gì?] [Đối tượng áp dụng?]     |
|                                                  |
| +----------------------------------------------+ |
| | Hỏi về văn bản…                              | |
| |                                              | |
| | [Đính kèm / đổi văn bản]              [Gửi ↑]| |
| +----------------------------------------------+ |
+--------------------------------------------------+
```

Interaction/layout rules:

- Normal conversation content is centered around 760–860px in an assistant-only view.
- In the document workspace, the source pane remains dominant and the assistant pane is approximately 360–440px on desktop.
- Assistant messages are prose-first; do not wrap every paragraph in a card or create messenger-style giant bubbles.
- Use warm surfaces, restrained borders, generous spacing, and typography hierarchy from `docs/10_DESIGN_SYSTEM.md`.
- The composer is multiline, sticky near the bottom, and usable above the mobile virtual keyboard.
- Do not expose model/provider selectors, prompt instructions, or technical retrieval controls to the family user.

## 3. C-01 — Enter a document-scoped assistant

### Entry

The user selects `Trợ lý` with a ready document selected, opens the assistant pane from D-04, or returns to a previous answer after viewing a citation.

### Actions

- Read the selected document context label.
- Choose one of the four quick actions.
- Type a question and send it.
- Select `Đính kèm / đổi văn bản` to choose a known document or enter the upload flow; this is a context-selection action, not an invented binary field in the Q&A request.
- Select a citation to open the source.

### State contract

| State | Behavior |
|---|---|
| Loading | On opening, show the document title and a restrained `Đang mở trợ lý…` placeholder. Do not fabricate a prior thread or answer. |
| Empty | Show greeting, composer, and quick actions. If no document is selected, replace enabled quick actions with `Chọn một văn bản để hỏi có căn cứ` and link to `Văn bản`. |
| Success | Selected document identity is visible above the thread; the question scope is obvious. The user can ask only about that document in Phase 4. |
| Error/offline | If the document context cannot load, show retry plus `Mở Văn bản`. If the AI worker is unavailable, keep source browsing available and show the explicit unavailable state when a question is sent. |
| Navigation/back | Return from source keeps the thread, answer, question, and selected document. Switching documents starts a clearly labelled new context and must not silently reuse old citations. |
| Source/citation | No answer is shown without resolvable source citations when the answer contains document facts. |

### Responsive layouts

- **Desktop:** assistant-only centered thread or right pane in D-04.
- **Tablet:** assistant and source are two panes; archive/document rail opens as a drawer.
- **Mobile:** assistant is the `Trợ lý` surface; `Văn bản` and `Chi tiết` are sibling surfaces with a one-tap switch.

## 4. C-02 — Ask a question

### Entry and actions

**Entry:** Empty composer or an existing thread with a selected document.

**Actions:** Type Vietnamese question, submit with send/keyboard action, edit before send, cancel/clear only before a request is accepted. Suggested actions must populate the same question path.

### Composer contract

```text
+--------------------------------------------------+
| Hỏi về văn bản…                                  |
|                                                  |
| [paperclip]                              [Gửi ↑] |
+--------------------------------------------------+
```

- Enter submits only when it does not conflict with the documented multiline keyboard behavior; Shift+Enter creates a newline if that behavior is chosen.
- The send button is disabled for blank/whitespace-only input.
- Submit the selected opaque `document_id` through the path and the question in the documented body.
- An attachment icon may open document selection/upload; it must not imply that the Q&A endpoint accepts arbitrary raw files.

### State contract

| State | Behavior |
|---|---|
| Loading | After submit, render the user question immediately and add an assistant `Đang tìm trong văn bản…` status. Disable duplicate send for the same request. Do not show token-by-token fake prose. |
| Empty | Blank composer is an idle state, not a conversation response; show the placeholder and optional quick actions. |
| Success | The answer is appended to the same selected-document thread with citation chips and lightweight follow-up actions. |
| Error/offline | Keep the typed question recoverable when request fails. Show structured `Thử lại`/`Chọn văn bản khác` actions; never turn a network error into `Chưa tìm thấy thông tin`. |
| Navigation/back | Leaving the chat preserves the drafted text only if the implementation can do so reliably; otherwise warn before losing non-empty draft. Returning preserves the submitted thread. |
| Source/citation | The question itself has no citation; its answer must render only citations returned and validated by the API. |

### Responsive layouts

- **Desktop:** composer max width matches thread, floating/sticky near bottom with 14px radius and restrained elevation.
- **Tablet:** composer spans assistant pane; source remains one switch away.
- **Mobile:** composer is fixed above the virtual keyboard/safe area; send and attachment touch targets are at least approximately 44px.

## 5. C-03 — Quick grounded actions

The four visible quick actions are shortcuts to ordinary grounded questions. They do not create separate summarization endpoints or bypass retrieval/citation validation.

| Label | Question intent | Minimum success content |
|---|---|---|
| `Tóm tắt văn bản` | Summarize the selected document | Concise summary with citations for factual claims |
| `Tôi cần làm gì?` | Identify obligations/actions | Action list with responsible party/deadline only when supported |
| `Có deadline nào?` | Find explicit deadlines | Dates/requirements with source page/block; say none found when evidence supports that |
| `Đối tượng áp dụng?` | Identify recipients/affected parties | Named audience/recipients with citations |

### State contract

| State | Behavior |
|---|---|
| Entry | Quick actions are visible only when a document is selected; otherwise they are disabled with an explanation, not dead buttons. |
| Actions | Clicking fills/submits the canonical question path; show the selected intent in the user message so the thread remains legible. |
| Loading | Same `Đang tìm trong văn bản…` state as manual Q&A. |
| Empty | If a quick action has no evidence, use the insufficient-evidence state rather than an empty card. |
| Success | Render a prose answer, structured list when useful, and citations; do not show unsupported legal conclusions. |
| Error/offline | Retry the same canonical question; preserve selected document and do not silently switch to archive-wide search. |
| Navigation/back | Source jump returns to the quick-action answer and keeps the intent visible. |
| Source/citation | Every factual bullet links to a source citation; no “summary” is exempt from provenance. |

### Responsive layouts

- **Desktop:** up to four compact chips below the greeting or latest answer; no feature-card grid.
- **Tablet:** wrap chips within the assistant pane; keep labels readable.
- **Mobile:** two-column or stacked chips with 44px-ish targets; do not let chips obscure the composer.

## 6. C-04 — Render an answered response

### Response wireframe

```text
User                                                   |
Văn bản này yêu cầu trường làm gì?                     |
                                                       |
Assistant                                               |
Nhà trường cần thực hiện:                              |
1. ...                                                  |
2. ...                                                  |
                                                       |
Nguồn: [Công văn 142 · Trang 3] [Đi tới nguồn]         |
                                                       |
        [Tôi cần làm gì?] [Có deadline nào?]            |
```

### State contract

| State | Behavior |
|---|---|
| Entry | Receive a response with `status: answered`. Validate citation IDs against the returned citation objects before rendering. |
| Actions | Read, activate citation, ask a follow-up within the same document, choose a quick action, return to source. |
| Loading | The completed answer is not shown until response validation finishes; a short `Đang hoàn thiện câu trả lời…` may be used only for real client processing. |
| Empty | Never render an empty assistant bubble as success. If `answer` is empty or invalid, show `Không nhận được câu trả lời hoàn chỉnh` with retry. |
| Success | Prose-first answer; headings/lists/tables only when they improve comprehension. Factual bullets have visible citation chips. Bounded quotes are optional and must remain short. |
| Error/offline | If citation validation fails client-side, hide the invalid citation as a valid source and show a retry/error notice; do not repair by guessing. |
| Navigation/back | Citation jump goes to D-04 and back returns to this answer plus prior thread scroll position. |
| Source/citation | Chip text includes document title/number when available and `Trang X`; activation resolves page and block IDs, highlights source, and preserves context. |

### Responsive layouts

- **Desktop:** assistant prose sits on the warm canvas with citations inline/below claims; source remains visible in the adjacent pane.
- **Tablet:** answer spans the assistant pane; citation preview can open as a sheet but source navigation switches to the source pane.
- **Mobile:** answer uses full-width prose; chips wrap, remain tap-friendly, and source opens as a dedicated `Văn bản` surface with `Quay lại câu trả lời`.

## 7. C-05 — Insufficient evidence

### Entry

The API returns `status: insufficient_evidence` because the retrieved evidence is not enough to support the question.

### Wireframe

```text
Trợ lý
Chưa tìm thấy đủ căn cứ trong văn bản để trả lời chắc chắn câu hỏi này.

Tôi tìm thấy các đoạn có liên quan:
[Trang 2 · Đoạn ...] [Đi tới nguồn]

Bạn có thể thử:
[Hỏi rõ hơn] [Mở văn bản] [Đổi câu hỏi]
```

### State contract

| State | Behavior |
|---|---|
| Entry | Preserve the exact user question and selected document. |
| Actions | Open available source citations, edit/rephrase question, ask a narrower follow-up, return to document. |
| Loading | Same request loading state; no speculative answer while retrieval is pending. |
| Empty | If no citations are returned, say `Chưa tìm thấy đoạn phù hợp trong văn bản` and do not fabricate a source. |
| Success | Treat abstention as a successful safety outcome: explain that evidence is insufficient and show any bounded, validated related sources. |
| Error/offline | A transport failure is not insufficient evidence; render the separate retryable error/offline state. |
| Navigation/back | Source return goes back to the abstention message, not a new answer. |
| Source/citation | Only returned/resolvable related citations are shown. Never label a weak/unknown result as proof. |

### Responsive layouts

- **Desktop/tablet:** keep the abstention message near the composer and sources in the assistant pane/sheet.
- **Mobile:** use readable full-width text, not a warning banner that relies on color; source links are stacked actions.

## 8. C-06 — AI worker unavailable / request failure

### Entry

The API returns `ai_worker_unavailable` or `failed`, or the browser cannot reach the control plane.

### State contract

| State | Behavior |
|---|---|
| Entry | Keep the selected document, user question, and prior thread visible. |
| Actions | `Thử lại`, `Mở văn bản`, and, where appropriate, `Đổi văn bản`. Do not offer a model selector or unsupported local fallback. |
| Loading | On retry, show `Đang thử lại…` and lock duplicate requests. |
| Empty | Not an empty conversation; prior answers/source remain visible. |
| Success | On retry success, append one answer and avoid duplicate user messages if the first request was accepted. |
| Error/offline | Copy: `Trợ lý AI tạm thời không kết nối. Văn bản vẫn có thể được xem và kiểm tra.` If the control plane itself is offline, say the question was not sent and keep the draft recoverable. |
| Navigation/back | User can return to source/archive without losing document context. |
| Source/citation | No new citation is rendered for a failed request. Existing citations remain valid and tied to their original answer/parse version. |

### Responsive layouts

- **Desktop:** compact inline status below the failed question; preserve the source pane.
- **Tablet:** status stays in assistant pane with a full-width retry.
- **Mobile:** status is a readable block above the composer; retry is primary and source navigation is secondary.

## 9. C-07 — Change document context

### Entry and intent

User chooses `Đính kèm / đổi văn bản`, a different row from the archive, or the document context selector in the assistant header.

### Contract

| State | Behavior |
|---|---|
| Entry | Show current document identity and explain that a new context changes what can be cited. |
| Actions | Pick a known document from the archive/recent list or start D-02 upload. Cancel leaves the current thread untouched. |
| Loading | `Đang mở văn bản…`; do not clear the old thread until the new document is confirmed. |
| Empty | If no other document exists, offer `Tải văn bản PDF`; do not show a fake picker. |
| Success | New document title replaces the active context; prior thread is not presented as if it belongs to the new document. Start a new empty thread or an explicitly labelled new context. |
| Error/offline | Keep old document/thread active and show retry; do not switch to a partially loaded document. |
| Navigation/back | Cancel/back returns to the existing thread and composer draft. Source back returns to the prior answer. |
| Source/citation | Existing citations remain associated with the old document; they must never retarget after context change. |

### Responsive layouts

- **Desktop:** document picker opens from the left rail or a contained sheet, not a full-screen dashboard.
- **Tablet:** picker is a drawer; source/assistant context remains visible behind it where possible.
- **Mobile:** picker is a full-screen list with a clear `Quay lại trợ lý`; selecting a document returns to a fresh selected context.

## 10. Scroll, focus, and keyboard rules

- Keep the composer near the viewport bottom but do not force-scroll when a user has intentionally scrolled upward.
- On a new answer, scroll to the answer only if the user was already near the bottom; otherwise show a non-invasive `Có câu trả lời mới` affordance.
- Citation activation moves focus to the source heading/page region and exposes a text alternative for the highlighted block.
- Returning from source restores focus to the citation control or originating answer.
- `Escape` closes a picker/sheet/dialog before leaving the document context.
- Preserve reduced motion: source focus may use a static outline instead of animation.

## 11. Phase gates and prohibited shortcuts

### Must be true for Phase 4

- Q&A is scoped by the selected `document_id`.
- The request/response follows the documented conceptual API contract.
- `answered`, `insufficient_evidence`, `ai_worker_unavailable`, and `failed` are distinct UI states.
- Factual answer bullets have resolvable page/block citations.
- The source can be opened and highlighted without hiding provenance.
- Home AI downtime does not make ready documents disappear.

### Must not be silently introduced

- Global/archive-wide chat or multi-document answers (Phase 5).
- External web search or uncited legal advice.
- Persistent conversation history without a contract.
- Streaming as a required backend behavior when the current API returns a complete response.
- Binary attachments sent directly through the Q&A body when the contract only accepts `question`.
- Raw camera data or browser parsing as a fallback.
- Automatic actions on behalf of the school.

## 12. Accessibility checklist

- [ ] Composer has a visible label and accessible name.
- [ ] Send, attach/change document, retry, citation, source back, and quick actions are keyboard accessible.
- [ ] Loading/errors/insufficient evidence are announced as status text and are not color-only.
- [ ] Citation controls identify their destination, including page number where available.
- [ ] Focus returns to the originating answer after a source jump.
- [ ] Touch targets are approximately 44px on mobile.
- [ ] Long answers remain readable at 16–17px body size with comfortable line height.
- [ ] Reduced-motion behavior does not remove the source focus cue.
