# MamaGift Information Architecture

**Status:** Draft design handoff — requires user review before implementation authority.

**Scope:** Product navigation, screen ownership, document-first context, and the relationship between the Phase 3 document workspace and the Phase 4 single-document assistant.

This document refines `docs/10_DESIGN_SYSTEM.md` without changing its global visual contract. It is based on `README.md`, `docs/00_PROJECT_CHARTER.md`, `docs/01_ARCHITECTURE.md`, `docs/04_PHASE_PLAN.md`, `docs/08_API_AND_DATA_CONTRACTS.md`, `docs/09_CODEX_EXECUTION.md`, and `docs/design/README.md`.

## 1. Product orientation

MamaGift is a family-only document assistant, not a general chatbot or analytics dashboard. The information architecture must make the following loop obvious:

```text
Find a document
      |
      v
Inspect the original and structured text
      |
      v
Verify metadata / correct a field when needed
      |
      v
Ask a grounded question about the selected document
      |
      v
Jump from every factual answer back to page/block evidence
```

The document remains the primary context. Chat is a secondary inspection tool attached to a selected document in Phase 4. Archive-wide chat and cross-document retrieval are Phase 5, not a hidden capability of the initial shell.

## 2. Phase map

| Product surface | Phase | Contract status | Design rule |
|---|---:|---|---|
| Login shell | 3 | UI flow required; auth contract is not specified here | Keep it simple and Vietnamese-first; do not invent account-management screens. |
| Document archive | 3 | `GET /api/v1/documents` with current filters | The archive is a document library, not a dense data table. |
| Upload and processing status | 3 | `POST /api/v1/documents`, job/document states | Show durable status and retryability plainly. |
| Original PDF + structured representation | 3 | document/canonical/file/page-preview APIs | Source is the dominant evidence surface. |
| Metadata review and correction | 3 | extracted fields + feedback API | Corrections append feedback; raw predictions remain preserved. |
| Single-document assistant | 4 | `POST /api/v1/documents/{document_id}/qa` | Only the selected document is in scope. Every factual answer uses resolvable citations. |
| Home AI availability | 4/7 operational concern | Q&A returns `ai_worker_unavailable`; document jobs have separate worker state | Render unavailable, retryable states; never disguise offline as an empty answer. |
| Archive-wide retrieval/chat | 5 | Later API surface | Show a labelled future placeholder only; do not expose it as working search/chat. |
| Offline OCR/parser learning loop | 6 | Later | A user correction is a product action now; training/export is not a user-facing Phase 3 feature. |
| Meeting assistant | 8 | Deferred | No meeting navigation, audio capture, transcript, or diarization in this IA. |

## 3. Navigation model

### 3.1 Desktop shell

The desktop shell uses a restrained Claude-inspired conversation layout and Granola-inspired warm/editorial surfaces. The left rail is navigation, not a dashboard.

```text
+----------------------+----------------------------------------------------------+
| MamaGift             |                                                  [User]  |
|                      |                                                          |
|  + Trợ lý            |                  ACTIVE WORKSPACE                       |
|                      |                                                          |
|  Văn bản             |  page title / context                                    |
|  Gần đây             |                                                          |
|                      |  content                                                |
|                      |                                                          |
|  [optional collapse] |                                                          |
+----------------------+----------------------------------------------------------+
```

Desktop shell rules:

- Sidebar target width: 240–272px.
- Use text-first rows and a subtle warm selected surface.
- Do not add Analytics, Admin, Activity, Integrations, Billing, Teams, or model/provider navigation.
- Keep the main workspace centered and readable; the shell should not feel like a KPI dashboard.
- A document context label may appear in the top bar when the active workspace is a document.

### 3.2 Primary destinations

| Destination | User intent | Initial/empty behavior | Current phase |
|---|---|---|---:|
| **Trợ lý** | Start a question or resume the selected document context | Greeting plus composer; if no document is selected, explain that grounded questions need a document | Visual shell in 3; working single-document Q&A in 4 |
| **Văn bản** | Find, upload, and inspect documents | Explain what a document library is and show the upload action | 3 |
| **Gần đây** | Reopen recently updated documents | Use only API-supported ordering over known document resources; no invented conversation-history endpoint | 3 |

`Gần đây` is a view over known document resources, not a promise of persisted chat history. If the list contract does not provide ordering, do not invent a separate recent-items endpoint; keep the view unavailable or visibly limited until it does.

### 3.3 Conceptual screen tree

Route names below are screen identifiers for handoff, not a commitment to unverified URL paths.

```text
MamaGift shell
├── Trợ lý [Phase 3 shell / Phase 4 working]
│   ├── No document selected
│   │   ├── Greeting + composer
│   │   ├── Suggested actions (disabled or explanatory until a document exists)
│   │   └── Attachment entry to upload flow
│   └── Document selected
│       ├── Current single-document thread
│       ├── Quick grounded questions
│       ├── Answer + citation chips
│       └── Source jump -> Document workspace
├── Văn bản [Phase 3]
│   ├── Archive list/search/filter
│   ├── Upload panel
│   ├── Processing status
│   └── Document workspace
│       ├── Original PDF/source pane
│       ├── Structured representation
│       ├── Metadata + confidence review
│       └── Correction feedback
└── Gần đây [Phase 3]
    └── Recent document list -> same Document workspace
```

### 3.4 Later-phase surfaces kept out of the current tree

The following may be named in planning material but must not appear as active navigation in Phase 3/4:

- **Archive-wide chat/search:** Phase 5; it needs cross-document retrieval, filters, reranking, freshness behavior, and multi-document citations.
- **External web/legal search:** not specified in the phase plan; do not imply it.
- **Meeting:** Phase 8; no audio/transcript UI now.
- **Training/admin/benchmark dashboards:** operational or later-phase surfaces, not family-user navigation.

If product wants to preview a later capability, use a non-interactive label such as `Sắp có ở giai đoạn 5 — hỏi trên toàn bộ kho văn bản`, never a live control that returns fabricated results.

## 4. Context ownership and back behavior

### 4.1 Context stack

The UI should preserve context as a stack rather than opening unrelated pages:

```text
Archive / Recent list
        |
        v
Selected document workspace
        |
        v
Single-document assistant thread
        |
        v
Citation source focus (same document, page/block)
```

Back behavior:

1. **Citation source focus:** return to the exact answer and scroll position in the assistant; keep the cited page/block selected in the source pane when the layout permits.
2. **Assistant -> document workspace:** return to the previous source page, panel state, and selected document.
3. **Document workspace -> archive/recent:** preserve the list query/filter and approximate scroll position.
4. **Upload drawer -> archive:** cancel closes the drawer without inventing a document; successful upload opens the newly created document status context.
5. **Mobile tab change:** back returns to the previously active surface, not to a reset document. A browser/system back from the document subview returns to the list.

Never use a citation or quick action to start a second unrelated global chat. The selected document remains the scope until the user explicitly changes it.

## 5. Information architecture flow contracts

The following contracts apply to every major IA flow. Each state is explicit so implementation does not collapse unavailable, empty, or loading into one generic screen.

### IA-00 — Enter the product / login shell

**Phase status:** Phase 3 visual flow. The supplied API/data contracts do not define authentication request fields or endpoints, so this is a screen/state handoff only. Do not invent account creation, password reset, roles, or identity-management behavior as part of this document.

**Entry:** User opens MamaGift without an active authenticated session.

**Actions:** Complete the authentication controls selected by the eventual auth contract; submit `Đăng nhập`; retry a failed attempt. The form must not expose infrastructure or model settings.

**States:**

| State | Required behavior |
|---|---|
| Loading | Show `Đang đăng nhập…`; prevent duplicate submit and keep the entered values according to the chosen auth implementation. |
| Empty | Initial form with Vietnamese labels and one obvious `Đăng nhập` action. No fabricated account list or onboarding claims. |
| Success | Enter the MamaGift shell at `Trợ lý` or `Văn bản` according to the approved product default; retain no sensitive value in visible UI. |
| Error/offline | Show `Không thể đăng nhập` with a retry action and a plain explanation when available. Do not turn network failure into invalid credentials without server evidence. |
| Navigation/back | Desktop/browser back follows the auth implementation; mobile back does not expose protected document content. After success, shell navigation owns back behavior. |
| Source/citation | No document source/citation exists before a document is opened. |

**Layouts:**

- Desktop: centered, calm form on the warm canvas; no marketing hero or dashboard cards.
- Tablet: same form with comfortable width and safe margins; shell rail is not shown before authentication.
- Mobile: full-width labelled controls with 44px-ish actions; keep the form above the keyboard and safe area.

### IA-01 — Open the assistant

**Entry:** User selects **Trợ lý** from the shell, or returns from a source citation.

**Actions:**

- If a document is selected, type a question or choose one of the four current quick actions.
- If no document is selected, attach/upload a PDF through the documented upload path or go to **Văn bản**.
- Choose a citation to open its source.

**States:**

| State | Required behavior |
|---|---|
| Loading | On first document-context load, show a quiet `Đang mở văn bản…` placeholder in the thread/source context. Do not show fake assistant text. |
| Empty | Greeting, one large composer, and a clear explanation: `Để trả lời có căn cứ, hãy chọn hoặc tải lên một văn bản.` |
| Success | Selected document name/metadata is visible near the thread; quick actions are enabled only when Phase 4 Q&A is available. |
| Error/offline | If the selected document cannot load, show a retry action and a link back to **Văn bản**. If AI is unavailable, retain the document and explain that browsing still works. |
| Navigation/back | Return from source preserves the answer and selected evidence. Go to **Văn bản** preserves the current document selection. |
| Source/citation | No factual assistant response without a citation object that resolves to document/page/block. |

**Layouts:**

- Desktop: centered thread at 760–860px; when a document is active, use the document workspace with source dominant and assistant at right.
- Tablet: source and assistant are the two active panes; archive rail is a drawer.
- Mobile: one active surface (`Văn bản`, `Trợ lý`, or `Chi tiết`); switch in one tap and preserve the selected document/page.

### IA-02 — Browse the archive

**Entry:** User selects **Văn bản** or **Gần đây**.

**Actions:** Search/filter using only current document-list capabilities; select a row; choose upload; retry a retryable processing item.

**States:**

| State | Required behavior |
|---|---|
| Loading | Show document-row skeletons and keep the page title/action stable. Do not claim that the archive is empty until the request resolves. |
| Empty | If no documents exist, explain the value of the archive and show one primary action: `Tải văn bản PDF`. If a filter has no matches, say `Không tìm thấy văn bản phù hợp` and offer `Xóa bộ lọc`. |
| Success | Render document rows with title/number, issued date, issuer when available, and user-facing processing/review status. Keep nullable fields absent or labelled unavailable, never guessed. |
| Error/offline | Show `Không tải được danh sách văn bản` with retry. Keep already loaded rows visible if stale data exists and label the list as not refreshed. |
| Navigation/back | Opening a row pushes the document workspace. Returning restores query/filter/scroll. |
| Source/citation | Archive rows do not need citations; any answer launched from a row must use the selected document's source contract. |

**Layouts:**

- Desktop: left rail plus comfortable library rows; avoid a dense table.
- Tablet: library occupies the active surface; source/assistant opens as the next surface or sheet.
- Mobile: full-width rows, 44px-ish touch target, filters in a sheet, one primary upload action.

### IA-03 — Work inside a selected document

**Entry:** User selects a document from the archive/recent view, opens a successful upload, or follows a citation.

**Actions:** Read original PDF, inspect structured representation, open metadata/details, move to a cited page/block, ask a Phase 4 question, or correct a supported field.

**States:**

| State | Required behavior |
|---|---|
| Loading | Source pane says `Đang mở bản gốc…`; structured pane says `Đang tải nội dung đã trích xuất…`. Keep the document title and back control visible. |
| Empty | A valid document with no readable structured blocks shows the original if available plus `Chưa có nội dung cấu trúc để hiển thị`; do not fabricate parsed text. |
| Success | Original and structured content can be compared; metadata has confidence/review semantics; source page/block focus works when provenance exists. |
| Error/offline | File/page preview failure has a retry and a text status. Home AI offline does not prevent viewing a ready document. Unsupported/parse-failed documents explain next action. |
| Navigation/back | Preserve current page, focused block, panel/tab, and selected document. Back from a citation returns to the originating answer. |
| Source/citation | Source page/block and bounding region are the canonical verification target. A citation that cannot resolve must not render as a valid citation. |

**Layouts:**

- Desktop: document rail 220–260px, source pane dominant, assistant 360–440px when Phase 4 is active.
- Tablet: two panes (`Nguồn` + `Trợ lý`) with metadata in a drawer; structured text can appear as a source subview.
- Mobile: tabs `Văn bản` / `Trợ lý` / `Chi tiết`; the selected page and citation focus survive tab changes.

### IA-04 — Review metadata and correct a field

**Entry:** User opens `Chi tiết` or a document shows `Cần kiểm tra`.

**Actions:** Inspect value and evidence, choose `Sửa`, submit a corrected value through feedback, cancel, or return to source.

**States:**

| State | Required behavior |
|---|---|
| Loading | Field control shows `Đang lưu thay đổi…`; prevent duplicate submission while preserving the source link. |
| Empty | If no extracted fields exist, say `Chưa có trường thông tin để kiểm tra`; retain original/source access. |
| Success | Show corrected view with `Đã sửa`; retain a source link and make clear that the raw extraction is preserved by the system. |
| Error/offline | Keep the user's entered value locally in the open form, show retry, and do not pretend correction persisted. Use structured error text when available. |
| Navigation/back | Cancel returns to the same metadata list. After success, back returns to the same field context, not to a new document. |
| Source/citation | Every field displays source page/block IDs through a human-readable `Trang X`/`Đi tới nguồn` action where available. |

**Layouts:**

- Desktop: metadata in the right/secondary column; source remains visible or opens alongside.
- Tablet: details drawer/sheet over the source; correction form has full-width controls.
- Mobile: `Chi tiết` is a dedicated tab/sheet; source link is a full-width action below the field.

## 6. Global state vocabulary

The product uses plain Vietnamese labels mapped from the API contracts:

| Internal capability | User-facing label | Meaning |
|---|---|---|
| `UPLOADED` / upload request accepted | `Đã nhận văn bản` | Original is accepted; processing has not necessarily started. |
| `INSPECTING` | `Đang kiểm tra văn bản` | PDF signals are being inspected. |
| `QUEUED_FOR_PARSE` | `Đang chờ xử lý` | Waiting for parser work; not a parse failure. |
| `PARSING` / `NORMALIZING` / `STRUCTURING` | `Đang đọc văn bản` | Processing is active; avoid technical provider names. |
| `READY_FOR_REVIEW` | `Cần kiểm tra` | Reviewable output exists; low-confidence fields may need attention. |
| `INDEXING` | `Đang chuẩn bị tìm kiếm` | Later/indexing step; in Phase 4 this may be visible only if contract exposes it. |
| `READY` | `Sẵn sàng` | Document can be browsed; Phase 4 Q&A depends on its separate capability. |
| `PARSE_FAILED` | `Không đọc được văn bản` | Terminal parse problem with retry/reprocess only when supported. |
| `UNSUPPORTED` | `Định dạng chưa được hỗ trợ` | User must choose another file or a later-supported path. |
| `ai_worker_unavailable` | `Trợ lý AI tạm thời không kết nối` | Q&A unavailable; document browsing remains usable. |
| `insufficient_evidence` | `Chưa tìm thấy đủ căn cứ` | Q&A abstains; show available evidence, never guess. |

## 7. Component ownership

Use the product-specific components named in `docs/10_DESIGN_SYSTEM.md` only when their flow requires them. The IA ownership map is:

| Area | Components |
|---|---|
| Shell/archive | `DocumentRail`, `DocumentRow`, `DocumentStatus` |
| Document workspace | `DocumentViewer`, `DocumentMetadata`, `SourceHighlight` |
| Provenance | `CitationChip`, `CitationPreview`, `SourceHighlight` |
| Review | `ConfidenceField`, `CorrectionControl`, `DeadlineCard`, `ActionItem` |
| Chat (Phase 4) | `AssistantThread`, `AssistantComposer`, `QuickQuestionActions`, `DocumentAttachment`, `HomeAINodeStatus` |

No component implies an endpoint. The implementation must map each visible action to an API contract or render it as an explicit unavailable/future state.

## 8. Accessibility and content rules

- Use semantic headings so a screen-reader user can distinguish archive, source, details, and assistant regions.
- Name every icon-only action, including citation jump, panel close, retry, attachment, send, and back.
- Do not communicate status through color alone; pair color with text and an icon/semantic state.
- Keep important touch targets around 44px on mobile.
- Never hide source/citation information behind more than one interaction layer.
- Use natural Vietnamese labels and preserve Vietnamese diacritics.
- If a field is null/unavailable, say so or omit it; do not render placeholder facts.

## 9. Implementation handoff checklist

Before implementation begins, confirm:

- [ ] User has reviewed and approved this draft.
- [ ] Phase 3 screens do not expose working Q&A controls before Phase 4.
- [ ] Phase 4 Q&A remains selected-document-only.
- [ ] Every answer citation resolves to known document/page/block data.
- [ ] Archive filters map only to available list/filter capabilities.
- [ ] No global chat history, archive-wide RAG, meeting, or admin surface is silently introduced.
- [ ] Desktop, tablet, and mobile shell transitions follow `04_RESPONSIVE_STATES.md`.
