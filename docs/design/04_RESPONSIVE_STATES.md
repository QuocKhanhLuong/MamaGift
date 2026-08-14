# MamaGift Responsive States

**Status:** Draft design handoff — requires user review before implementation authority.

**Scope:** Desktop, tablet, and mobile layout states for the information architecture, document flow, and Phase 4 single-document chat. This is a responsive behavior contract, not application code or a commitment to a native mobile app.

## 1. Responsive principles

1. Do not squeeze the desktop three-pane workspace onto a phone.
2. Keep the original source one clear action away from every answer or field.
3. Preserve selected document, page, block, draft, and back context across layout changes.
4. Use progressive disclosure for metadata and diagnostics; never hide provenance behind multiple menus.
5. Maintain readable Vietnamese text, generous spacing, and touch-safe controls.
6. Render unavailable/loading/error states as intentional layouts, not collapsed blank screens.
7. A breakpoint changes the arrangement, not the product truth: a citation remains the same document/page/block citation at every width.

This document refines the breakpoints and panel rules in `docs/10_DESIGN_SYSTEM.md`. It does not add routes, endpoints, or later-phase functionality.

## 2. Breakpoint contract

| Name | Viewport | Primary arrangement | Main use |
|---|---:|---|---|
| Desktop | `>= 1200px` | Full shell; three-pane document workspace when active | Compare source, structured text/details, and assistant at once |
| Tablet | `768–1199px` | Two active panes; rails/details become drawers or sheets | Read source and assistant without crowding |
| Mobile | `< 768px` | One active surface: `Văn bản`, `Trợ lý`, or `Chi tiết` | Focused reading and one-tap switching |

The exact CSS breakpoint may be tuned during implementation, but the three behavioral modes must remain intentional and testable.

## 3. Global shell states

### 3.1 Desktop shell

```text
+----------------------+-----------------------------------------------+
| MamaGift             | page context                         [profile] |
|----------------------|-----------------------------------------------|
| + Trợ lý             |                                               |
|   Văn bản            |              ACTIVE WORKSPACE                |
|   Gần đây            |                                               |
|                      |                                               |
| [thu gọn rail]       |                                               |
+----------------------+-----------------------------------------------+
```

- Rail: approximately 240–272px.
- Main workspace: centered content; no dashboard KPI cards.
- Selected navigation uses a warm subtle surface, not saturated color.
- On a document, title/number and status remain visible near the workspace header.

### 3.2 Tablet shell

```text
+--------------------------------------------------+
| [☰] MamaGift       Công văn 142        [⋯]       |
|--------------------------------------------------|
|                                                  |
|                  ACTIVE SURFACE                  |
|                                                  |
+--------------------------------------------------+
```

- Sidebar opens as a drawer from `☰`.
- Document rail is not simultaneously visible with the source and assistant panes.
- Drawer close returns to the exact active surface and scroll position.

### 3.3 Mobile shell

```text
+------------------------------------------+
| [←] Công văn 142                 [⋯]    |
|------------------------------------------|
|                                          |
|              ACTIVE SURFACE              |
|                                          |
|------------------------------------------|
| [Văn bản]       [Trợ lý]       [Chi tiết]|
+------------------------------------------+
```

- Use a single active surface; bottom/tab controls are direct, named, and touch-safe.
- The selected document title is shortened visually only; full title remains available as accessible text/details.
- System/browser back follows the context stack defined in `01_INFORMATION_ARCHITECTURE.md`.

## 4. Responsive state matrix

This table is the implementation index for the named flows. Each row points to a detailed behavior below.

| Flow | Desktop | Tablet | Mobile |
|---|---|---|---|
| D-01 Archive | Rail + library rows | Library surface + drawer rail | Full-width rows + filter sheet |
| D-02 Upload | Centered drawer/dialog | Sheet or centered dialog | Full-screen/bottom sheet |
| D-03 Processing | Status detail beside/list context | Status active surface | Vertical status timeline |
| D-04 Document workspace | Rail + source dominant + assistant | Source + assistant; rail/details drawers | `Văn bản` / `Trợ lý` / `Chi tiết` surfaces |
| D-05 Correction | Details beside source | Details sheet over source | Dedicated details form/tab |
| D-06 Retry/reprocess | Inline status action | Full-width status action | One primary retry CTA |
| C-01 Assistant entry | Centered thread or right pane | Assistant pane | `Trợ lý` surface |
| C-02 Question/composer | Sticky composer under thread | Composer spans assistant pane | Composer above keyboard |
| C-03 Quick actions | Compact chips | Wrapped chips | Stacked/two-column touch chips |
| C-04 Answer/citation | Prose + source pane | Prose + source switch/sheet | Prose + source surface |
| C-05 Insufficient evidence | Message + related sources | Message + source sheet | Full-width text + stacked source links |
| C-06 AI offline/error | Inline status; source remains | Status in assistant pane | Status above composer |
| C-07 Change document | Picker sheet/rail | Picker drawer | Full-screen picker |

## 5. R-01 — Archive and recent list (D-01)

### Desktop

```text
+----------------------+-----------------------------------------------+
| VĂN BẢN              | Văn bản                         [Tải văn bản] |
|                      | [Tìm...] [Lọc]                                  |
| Hôm nay              |                                               |
|  Công văn 142        | +-------------------------------------------+ |
|  Kế hoạch 18         | | Công văn 142/SGDĐT-GDTH                   | |
|                      | | 14/08/2026 · Sẵn sàng                     | |
| Tháng này            | +-------------------------------------------+ |
|  ...                 |                                               |
+----------------------+-----------------------------------------------+
```

- Rows are document-library rows, not dense table records.
- Search and filters remain at the top; filter controls may use a popover but must keep text labels.
- Empty archive has one obvious upload CTA. Empty filtered result has `Xóa bộ lọc`.
- Loading uses row skeletons; errors keep stale rows if available.

### Tablet

- The list takes the full active surface.
- The rail opens from the left as a drawer; filters open as a sheet from the bottom or side.
- Selecting a row closes the drawer/sheet and opens the document surface.
- Preserve typed query/filter when the user backs out.

### Mobile

- Rows stack as:

```text
 +--------------------------------------+
 | Công văn 142/SGDĐT-GDTH              |
 | Về việc ...                          |
 | 14/08/2026 · Sở Giáo dục             |
 | Sẵn sàng                         [>] |
 +--------------------------------------+
```

- A row is one large target; do not make only a tiny arrow clickable.
- Filters are a full-width sheet with `Áp dụng` and `Xóa bộ lọc`.
- Upload is visible in the header and/or a bottom-safe primary action; never cover list content.

### Required states at all widths

- `Đang tải danh sách văn bản` — skeletons, not an empty message.
- `Chưa có văn bản nào` — explanation + upload CTA.
- `Không tìm thấy văn bản phù hợp` — clear filter recovery.
- `Không tải được danh sách văn bản` — retry; stale rows remain labelled if available.

## 6. R-02 — Upload drawer/sheet (D-02)

### Desktop

```text
background: archive remains visible and dimmed
                +--------------------------+
                | Tải văn bản          [×] |
                | [Chọn tệp PDF]            |
                | selected file row         |
                | [Hủy]       [Tải lên]    |
                +--------------------------+
```

- Width approximately 420–520px.
- The original-preservation explanation is visible but secondary.
- `Tải lên` is the only primary action.

### Tablet

- Use a sheet/dialog with enough width for the filename and error message.
- Keep the selected file and error copy above the action row.
- Close returns to the archive without clearing archive filters.

### Mobile

- Use a full-screen or bottom sheet.
- Stack file picker, selected file, explanation, and actions.
- File errors wrap naturally; do not truncate the actionable part.
- Keep actions above the keyboard/safe area.

### Required states at all widths

| State | Layout behavior |
|---|---|
| Empty | No file row; submit disabled; clear PDF instruction |
| Selected | Filename, remove/replace, submit enabled |
| Uploading | Stable filename + `Đang tải lên…`; duplicate submit disabled |
| Accepted | Transition to D-03 status; do not return to a blank list |
| Invalid/unsupported | Inline error near file row + one recovery action |
| Control-plane offline | Preserve current selection, say it was not sent, offer retry |

## 7. R-03 — Processing status (D-03)

### Desktop/tablet

```text
Document: Công văn 142

✓ Đã nhận văn bản
✓ Đang kiểm tra văn bản
● Đang đọc văn bản
○ Cần kiểm tra
○ Sẵn sàng

Trạng thái: Đang chờ xử lý
Máy xử lý tạm thời không kết nối. Văn bản sẽ được thử lại.
```

- Desktop can show the status beside the archive or in a focused workspace.
- Tablet uses the status as the active surface; the archive is a drawer.
- A worker availability note is separate from document state; do not relabel the document as a terminal failure.

### Mobile

- Use a vertical, text-labelled timeline; no progress-only visual.
- Keep the document filename/title and back action in the header.
- Put retry/reprocess below the explanation and preserve the original file link when available.

### Required states

- Upload accepted: `Đã nhận văn bản`.
- Queued/waiting: `Đang chờ xử lý`.
- Parsing/normalizing/structuring: `Đang đọc văn bản`.
- Reviewable: `Cần kiểm tra`.
- Ready: `Sẵn sàng`.
- Parse failure: `Không đọc được văn bản`.
- Unsupported: `Định dạng chưa được hỗ trợ`.
- Worker offline: a separate retryable note, never a false `PARSE_FAILED`.

## 8. R-04 — Document workspace (D-04)

### Desktop: full evidence workspace

```text
+------------+-----------------------------------+---------------------+
| Document   | SOURCE / ORIGINAL PDF             | ASSISTANT (P4)      |
| rail       |                                   |                     |
|            | page controls                    | answer/thread       |
|            |                                   |                     |
|            | page image + source highlight    | citations           |
|            |                                   |                     |
|            | structured representation        | composer            |
+------------+-----------------------------------+---------------------+
```

- Source pane remains dominant and can expand when a rail collapses.
- Assistant is 360–440px and never overlays the source at normal desktop widths.
- Metadata/details may be a secondary column or contained drawer, but source remains one action away.
- Panel collapse changes width, not context; selected page/block remains focused.

### Tablet: two-pane comparison

```text
+--------------------------------------------------+
| [☰] Công văn 142                    [Chi tiết]   |
|--------------------------------------------------|
|                    SOURCE                        |
|                                                  |
| [Nguồn]                         [Trợ lý]         |
+--------------------------------------------------+
```

- Keep source and assistant as the two primary panes.
- Structured representation and metadata open as a sheet/drawer from `Chi tiết`.
- Citation activation focuses source; returning switches back to the previous assistant/field context.

### Mobile: one active surface

```text
+------------------------------------------+
| [←] Công văn 142                         |
|------------------------------------------|
|              SOURCE PAGE                 |
|        [highlighted block]               |
|------------------------------------------|
| [Văn bản]       [Trợ lý]       [Chi tiết]|
+------------------------------------------+
```

- `Văn bản` is the default after opening a document or citation.
- `Trợ lý` opens the single-document thread; the document title remains in context.
- `Chi tiết` opens metadata/confidence/correction; source link returns to the exact page/block.
- System back from a citation returns to the answer; back from the document returns to archive with list state preserved.

### Workspace states at all widths

| State | Desktop | Tablet | Mobile |
|---|---|---|---|
| Source loading | Source skeleton in dominant pane | Source active surface skeleton | Full-screen source skeleton |
| Structured loading | Secondary skeleton beside source | Details/structured sheet loading | `Chi tiết` loading tab |
| No blocks | Original remains visible; message in structured pane | Source + empty structured sheet | Source + `Chưa có nội dung cấu trúc` |
| Source unavailable | Error in source pane, structured text may remain | Error active surface + details/source text fallback | Error surface + back/details actions |
| Ready | Compare source/structure; citations focus source | Switch panes; preserve focus | Tabs preserve page/block context |
| AI offline | Assistant status only; source remains usable | Status in assistant pane | Status above composer; source tab remains available |

## 9. R-05 — Details and correction (D-05)

### Desktop

- Place metadata beside the source or in a right-side drawer.
- Field layout:

```text
Hạn
25/08/2026                         Cần kiểm tra
Nguồn: Trang 3                 [Đi tới nguồn]
                                  [Sửa]
```

- On edit, keep the source link within the same visual region.

### Tablet

- Details opens as a sheet over the source.
- The source can remain visible behind a non-blocking sheet only if text remains legible; otherwise use a full sheet with a prominent `Đi tới nguồn` action.

### Mobile

- Details is a dedicated tab; fields stack one per section.
- Correction form uses full-width input and sticky `Lưu thay đổi`/`Hủy` actions above the safe area.
- Unsaved input is preserved on a layout switch where possible; if not, warn before loss.

### Required states

- `Đang lưu thay đổi…` disables duplicate submit.
- `Đã sửa` appears only after the feedback response succeeds.
- `Chưa lưu được thay đổi` retains entered value and retry.
- Null source is labelled `Chưa có nguồn xác định`; no invented page number.
- Raw extraction is not presented as deleted or rewritten.

## 10. R-06 — Chat and composer (C-01–C-07)

### Desktop

```text
+------------------------------------------+
| Trợ lý · Công văn 142                    |
|                                          |
| assistant prose + citations              |
|                                          |
| +--------------------------------------+ |
| | Hỏi về văn bản…                     | |
| | [đính kèm/đổi]                 [Gửi]| |
| +--------------------------------------+ |
+------------------------------------------+
```

- Centered 760–860px thread when assistant-only.
- In the workspace, composer is inside the 360–440px assistant pane.
- Quick actions are compact chips, not cards.
- New answers should not forcibly scroll if the user has intentionally scrolled upward.

### Tablet

- Composer spans the assistant pane and stays near its bottom.
- Source remains the neighboring pane or one `Nguồn` switch away.
- Citation preview may open as a sheet but source page focus takes the user to the source pane.

### Mobile

```text
+------------------------------------------+
| [←] Trợ lý · Công văn 142                |
|------------------------------------------|
| answer prose                             |
| [Trang 3 · Đi tới nguồn]                 |
|                                          |
|------------------------------------------|
| Hỏi về văn bản…                 [Gửi ↑]  |
| [Đính kèm / đổi văn bản]                 |
|------------------------------------------|
| [Văn bản]       [Trợ lý]       [Chi tiết]|
+------------------------------------------+
```

- Composer sits above the virtual keyboard and safe area.
- Send/attachment/retry/citation controls are approximately 44px targets.
- Long answer prose remains at least 16px with comfortable line height.
- Source citation opens the `Văn bản` surface and shows `Quay lại câu trả lời`.

### Chat state variants

| State | Desktop/tablet | Mobile |
|---|---|---|
| Empty | Greeting + four quick chips + composer | Same, stacked chips + composer |
| Asking | User question + `Đang tìm trong văn bản…`; no duplicate send | Same above keyboard; preserve draft/request state |
| Answered | Prose + citation chips + source pane/sheet | Prose + wrapped citation links + source surface |
| Insufficient evidence | Explain abstention + related validated sources | Full-width explanation + stacked source links |
| AI unavailable | Inline status; document remains visible | Status block above composer; `Văn bản` remains one tap away |
| Failed | Retry same question; preserve selected document | Retry primary, source/document secondary |
| Change document | Picker sheet/rail | Full-screen picker; old thread not relabelled as new document |

## 11. R-07 — Citation and source return

Citation behavior must be invariant across widths:

```text
Citation activated
      |
      v
Open selected document
      |
      v
Navigate page_number
      |
      v
Focus block_ids / bbox
      |
      v
Return to originating answer/field
```

### Desktop

- Focus the source pane directly; keep assistant answer visible.
- Use a warm translucent outline/highlight; do not obscure document text.

### Tablet

- Switch to the source pane or open source sheet; retain the originating answer in navigation state.

### Mobile

- Open `Văn bản` as the active surface with page/block focus.
- Provide a prominent text action `Quay lại câu trả lời` or `Quay lại chi tiết`.
- Move accessible focus to the page/source heading and expose a text alternative for the highlighted block.

### Citation failure state

If `citation_id`, `document_id`, `page_number`, or known `block_ids` cannot resolve:

- do not render it as a valid source;
- show `Không mở được nguồn này` and retry/open-document recovery;
- retain the answer only with a clear source-validation error, never a guessed page/block.

## 12. R-08 — Loading, empty, error, and offline visual language

### Loading

- Use quiet skeletons/placeholders and plain Vietnamese status copy.
- Preserve title, back, and primary context controls.
- Avoid technical terms such as `OCR_WORKER_PENDING`, `canonicalization`, `embedding`, or provider names.
- Do not add decorative AI animation or token-by-token flourish.

### Empty

- Empty archive: explain value + one upload CTA.
- Empty filtered archive: clear filter.
- Empty assistant: greeting + selected-document explanation.
- Empty structured representation: original still visible; say that structured content is unavailable.
- Empty citation result: insufficient evidence, not a blank answer.

### Error/offline

- Pair status color with text and semantic icon.
- Keep stale/previously loaded content when safe and label freshness.
- Use `Thử lại` for retryable requests and do not show it for unsupported inputs unless reprocess is actually supported.
- Home AI offline affects Q&A, not ready-document browsing.
- Control-plane offline affects upload/list/QA requests; preserve local draft/selected file only as transient UI state, never as a browser processing fallback.

### Success

- `Sẵn sàng`, `Đã sửa`, and `Đã nhận văn bản` are text states with clear next actions.
- Success does not imply a later-phase capability: a document being `READY` does not automatically mean archive-wide search or Phase 4 Q&A is enabled.

## 13. Accessibility and interaction invariants

- Keyboard paths must work for shell nav, archive rows, upload, status/retry, page/source jump, tabs/drawers, composer, citation return, and correction.
- Focus is visible at every breakpoint and restored after sheets close or source jumps.
- Drawers/sheets have accessible names, escape/close behavior, and logical focus trapping where appropriate.
- Status is never color-only; include text and an icon/semantic role.
- Touch targets are approximately 44px for primary mobile actions.
- Text does not fall below the design-system minimum: body/chat prose around 16–17px desktop and at least 16px mobile.
- Reduced-motion preference removes transitions but preserves state/focus indicators.
- PDF/source content has accessible textual context; bounding-box highlight is supplemental, not the only way to understand a citation.
- Do not use horizontal scrolling as a substitute for responsive panel design on mobile.

## 14. Responsive implementation checklist

- [ ] User has reviewed and approved this draft.
- [ ] Desktop uses source-dominant three-pane behavior only at widths where it remains readable.
- [ ] Tablet uses two panes plus drawers/sheets, not three squeezed columns.
- [ ] Mobile uses one active surface with preserved document/page/citation context.
- [ ] Archive, upload, processing, workspace, correction, chat, and citation flows each have loading/empty/success/error/offline states.
- [ ] All state copy is Vietnamese-first and avoids internal provider terminology.
- [ ] AI unavailable does not hide or invalidate ready document browsing.
- [ ] No future Phase 5/6/8 surface is rendered as a working current feature.
- [ ] No application code is changed as part of this design handoff.
