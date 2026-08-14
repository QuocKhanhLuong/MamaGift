# MamaGift Document Flow

**Status:** Approved design handoff.

**Scope:** Upload, archive, processing, document inspection, source verification, metadata review, and supported corrections. Chat is referenced only where the document flow hands off to the feature-gated single-document assistant; its detailed interaction contract is in `03_CHAT_FLOW.md`.

**Internal phase note:** Phase labels below are implementation-scope annotations only. They must never appear in product navigation, controls, empty states, or other user-facing copy.

**Phase boundary:** The core user-facing document flow is Phase 3. Parser benchmark, ingestion, and canonical data work belong to Phases 1–2. Single-document Q&A is Phase 4. Archive-wide search/chat is Phase 5. This document defines visual states for later phases but does not authorize their implementation early.

## 1. Document-first principles

1. The original PDF is immutable and remains the primary verification surface.
2. Structured extraction is useful only when its page/block provenance is visible.
3. `NULL`, low confidence, parse failure, unsupported input, and worker downtime are distinct states.
4. A user correction creates feedback; it does not overwrite the raw prediction.
5. Every visible action maps to a documented API contract or is labelled unavailable/future.
6. The interface should feel like a calm document reader with an attached assistant, not an upload dashboard.

## 2. Supported contracts

| Flow need | Current conceptual contract |
|---|---|
| Upload | `POST /api/v1/documents`, multipart PDF, `202 Accepted` with document + queued job |
| List | `GET /api/v1/documents`, pagination and only current filters |
| Document | `GET /api/v1/documents/{document_id}` |
| Canonical content | `GET /api/v1/documents/{document_id}/canonical` |
| Original | `GET /api/v1/documents/{document_id}/file` |
| Page preview | `GET /api/v1/documents/{document_id}/pages/{page}/preview` |
| Reprocess | `POST /api/v1/documents/{document_id}/reprocess` |
| Correction | `POST /api/v1/documents/{document_id}/feedback` |
| Metadata search | Phase 3 query on document list, only for supported filters |
| Single-document Q&A | Phase 4 `POST /api/v1/documents/{document_id}/qa` |

No endpoint for deleting documents, editing arbitrary text, streaming chat, persistent conversation history, cross-document Q&A, external search, or model selection is assumed by this handoff.

## 3. End-to-end flow map

```text
Văn bản / empty archive
          |
          | Tải văn bản PDF
          v
Upload drawer
  | validate file locally / server accepts
  v
Đã nhận văn bản -> Đang chờ xử lý -> Đang đọc văn bản
                                      |
                   +------------------+-------------------+
                   |                                      |
                   v                                      v
            Cần kiểm tra / Sẵn sàng              Không đọc được /
                   |                             Định dạng chưa hỗ trợ
                   v                                      |
        Document workspace <---------------------- retry/reprocess
           |       |       |
           |       |       +--> Chi tiết / correction feedback
           |       +----------> source page/block focus
           +------------------> Assistant workspace (when enabled, selected doc only)
```

## 4. D-01 — Open the archive

### Entry and intent

**Entry:** User selects `Văn bản`, applies the recent grouping/filter inside the archive, or returns from a document workspace.

**Intent:** Find an existing document or start a new upload.

### Desktop wireframe

```text
+----------------------+-----------------------------------------------+
| MamaGift             | Văn bản                         [Tải văn bản] |
|                      |-----------------------------------------------|
|  Văn bản  *          | [Tìm theo tên, số văn bản...] [Lọc]            |
|    Gần đây (bộ lọc)  | HÔM NAY                                       |
|                      | +-------------------------------------------+ |
|                      | | Công văn 142/SGDĐT-GDTH                   | |
|                      | | Về việc ...                                | |
|                      | | 14/08/2026 · Sở Giáo dục · Sẵn sàng        | |
|                      | +-------------------------------------------+ |
|                      |                                               |
|                      | THÁNG NÀY                                    |
|                      | +-------------------------------------------+ |
|                      | | Kế hoạch ...                               | |
|                      | | Đang đọc văn bản                           | |
|                      | +-------------------------------------------+ |
+----------------------+-----------------------------------------------+
```

### Actions and states

| State/behavior | Handoff requirement |
|---|---|
| Entry | Keep page title, upload action, search field, and list context stable while data loads. |
| Primary actions | Select a row; search/filter using available list query parameters; choose `Tải văn bản PDF`; retry a retryable item. |
| Loading | Render 3–5 row skeletons with no false document facts. Search/filter controls remain available but should not submit duplicate requests. |
| Empty archive | Message: `Chưa có văn bản nào`. Explain that uploaded PDFs become searchable/inspectable after processing. Primary CTA: `Tải văn bản PDF`. |
| Empty filter | Message: `Không tìm thấy văn bản phù hợp`. Primary recovery: `Xóa bộ lọc`; preserve the typed query until cleared. |
| Success | Each row shows available filename/title/number, date/issuer when non-null, and a plain-language status. Do not expose parser/provider/model fields. |
| Error/offline | `Không tải được danh sách văn bản` plus `Thử lại`. If stale rows exist, keep them and label refresh unavailable; do not replace with an empty state. |
| Back/navigation | Row selection opens D-04. Back returns to the same query/filter and approximate scroll. Upload opens D-02 and can return without creating a document if cancelled. |
| Source/citation | Rows are source entry points, not citations. A later answer must cite the selected document/page/block. |

### Responsive behavior

- **Desktop (>=1200px):** sidebar plus library list; no dense admin table. Upload button in page header.
- **Tablet (768–1199px):** library is the main surface; sidebar becomes a drawer; filters use a sheet.
- **Mobile (<768px):** full-width rows with 44px-ish targets; upload is a sticky/visible primary action; filters open in a sheet and close back to the same list.

## 5. D-02 — Upload a PDF

### Entry and intent

**Entry:** `Tải văn bản PDF` from the archive, or `Chọn văn bản` from an enabled assistant workspace when the user needs a different document context.

**Intent:** Submit one Vietnamese administrative PDF and receive a durable document/job state.

### Wireframe

```text
+--------------------------------------------------+
| Tải văn bản                                  [×] |
|                                                  |
| Kéo thả tệp PDF vào đây                          |
| hoặc                                             |
| [Chọn tệp PDF]                                   |
|                                                  |
| Tệp đã chọn                                      |
|  📄 cong-van-142.pdf                 [Bỏ chọn]   |
|                                                  |
| Tệp được lưu nguyên bản để đối chiếu nguồn.     |
|                                                  |
|                              [Hủy] [Tải lên]     |
+--------------------------------------------------+
```

### Actions and states

| State/behavior | Handoff requirement |
|---|---|
| Entry | Focus the file chooser/drop area; explain PDF-only input and immutable source preservation. |
| Actions | Choose one PDF, remove/replace selection, cancel, submit. Do not expose parser choice or model settings. |
| Loading | On submit, disable duplicate submission and show `Đang tải lên…`; retain filename and progress only if transport exposes it. Do not invent percentage progress. |
| Empty | No selected file: primary submit disabled; show `Chọn một tệp PDF để tiếp tục`. |
| Success | On `202 Accepted`, show `Đã nhận văn bản` and `Đang chờ xử lý`; open the new document status context D-03. The UI may show the opaque document/job identifiers only in diagnostics, not to the family user. |
| Error | Map documented upload errors: unsupported media, too large, invalid PDF, encrypted PDF, storage failure. Keep the file choice when safe; give one next action. Never claim a document was created when acceptance failed. |
| Offline | If the browser cannot reach the control plane, show `Không thể tải lên khi đang ngoại tuyến`; keep the selected filename only for the current form and offer retry. No browser-side PDF processing or raw-camera fallback. |
| Back/navigation | Cancel closes without creating a document. After success, back returns to the status context, not a blank archive. |
| Source/citation | No citation exists at upload time. State explicitly that the original will be the source after processing. |

### Responsive behavior

- **Desktop:** centered 420–520px drawer/modal over the archive; no competing primary CTA behind it.
- **Tablet:** sheet from the side or centered dialog with full-width file control.
- **Mobile:** bottom sheet/full-screen upload view; file row and buttons stack; controls remain above the virtual keyboard.

## 6. D-03 — Processing and readiness

### Entry and intent

**Entry:** Upload accepted, archive row selected while processing, or a user returns to an in-progress document.

**Intent:** Understand what MamaGift is doing, whether the user must wait/review, and what can be done next.

### State timeline wireframe

```text
Đã nhận văn bản
      |
      v
Đang kiểm tra văn bản
      |
      v
Đang chờ xử lý  -- worker unavailable is shown as a separate note
      |
      v
Đang đọc văn bản
      |
      +--> Cần kiểm tra ---> Mở để kiểm tra
      |
      +--> Sẵn sàng -------> Mở văn bản
      |
      +--> Không đọc được -> Thử lại / Tải tệp khác
```

### Actions and states

| State/behavior | Handoff requirement |
|---|---|
| Entry | Show document title/filename, current plain-language status, and a back action to the list. |
| Actions | Wait/reload status, open workspace when available, retry/reprocess only when API capability supports it, choose another file for unsupported input. |
| Loading | Poll or refresh according to the implementation contract; show a calm progress label, not technical worker logs. Keep original file/download/view access only if available from the API state. |
| Empty | A status page is never empty: it always has the document identity and current state. If canonical content has zero blocks, show the original plus an explicit no-structured-content message. |
| Success | `Sẵn sàng` opens D-04. `Cần kiểm tra` opens D-04 with the metadata review emphasis. The UI does not imply assistant Q&A readiness unless that capability is enabled. |
| Retryable error/offline | A home worker being offline is not a terminal document failure. Show `Đang chờ máy xử lý` or equivalent separate availability note and keep the job retryable. |
| Terminal error | `Không đọc được văn bản` or `Định dạng chưa được hỗ trợ`, with the documented next action. Preserve original file and error context. |
| Back/navigation | Back preserves list context. Reopening the status returns to the same state; do not reset to upload. |
| Source/citation | Until parse output exists, no structured citations are available. Once output exists, all source actions resolve to page/block provenance. |

### Status mapping

| API state | User-facing copy | Action |
|---|---|---|
| `UPLOADED` | `Đã nhận văn bản` | Wait/open status |
| `INSPECTING` | `Đang kiểm tra văn bản` | Wait |
| `QUEUED_FOR_PARSE` | `Đang chờ xử lý` | Wait; if worker unavailable, show separate retryable note |
| `PARSING`, `NORMALIZING`, `STRUCTURING` | `Đang đọc văn bản` | Wait |
| `READY_FOR_REVIEW` | `Cần kiểm tra` | Open document and review fields |
| `INDEXING` | `Đang chuẩn bị tìm kiếm` | Wait; archive-wide retrieval is not implied |
| `READY` | `Sẵn sàng` | Open document; assistant access is separately feature-gated |
| `PARSE_FAILED` | `Không đọc được văn bản` | Retry/reprocess if supported; otherwise upload another file |
| `UNSUPPORTED` | `Định dạng chưa được hỗ trợ` | Choose a supported PDF |

### Responsive behavior

- **Desktop:** status is a focused center panel or document-row detail; source pane can open as soon as available.
- **Tablet:** status occupies the active surface; document list is a drawer.
- **Mobile:** use a vertical timeline/step list with text labels; never rely on a thin progress bar or color-only status.

## 7. D-04 — Inspect the document workspace

### Entry and intent

**Entry:** A document is `READY`/`READY_FOR_REVIEW`, or the user follows a source citation.

**Intent:** Compare the original PDF with the structured representation and verify critical fields.

### Desktop verification workspace

The default verification workspace is the Phase 3 source-first layout:

```text
+----------------+--------------------------------+----------------------+
| VĂN BẢN        | CÔNG VĂN 142/SGDĐT-GDTH        | CHI TIẾT             |
|                |                                |                      |
| Search         | [<] page 3 / 8   [zoom]       | Hạn: 25/08/2026      |
| [recent group]  |                                | Cần kiểm tra         |
| > Công văn...  |      ORIGINAL PDF             | [Đi tới nguồn]       |
|   Kế hoạch...  |   +----------------------+     | [Sửa]                |
|                |   | page image/text      |     |                      |
|                |   | [source highlight]   |     | Parsed content       |
|                |   +----------------------+     | Điều 5 → Khoản 2…   |
|                |                                |                      |
|                |                                |                      |
+----------------+--------------------------------+----------------------+
```

Implementation contract: `Document rail | Original PDF | Parsed content / metadata / correction`. The third column may be split between parsed content and metadata, but it remains the verification surface. No assistant nav/tab/control is rendered before the assistant capability is enabled.

### Desktop assistant workspace (feature-enabled)

When the assistant capability is enabled for the selected document, the workspace changes deliberately rather than mixing both products into one dense panel:

```text
+----------------+--------------------------------+----------------------+
| VĂN BẢN        | CÔNG VĂN 142/SGDĐT-GDTH        | TRỢ LÝ               |
|                |                                |                      |
| Search         | [<] page 3 / 8   [zoom]       | Tóm tắt              |
| [recent group]  |      ORIGINAL PDF             | Nguồn: Trang 3       |
| > Công văn...  |   +----------------------+     | [Đi tới nguồn]       |
|   Kế hoạch...  |   | page image/text      |     |                      |
|                |   | [source highlight]   |     | Hỏi về văn bản…     |
|                |   +----------------------+     | [Chọn văn bản] [gửi] |
|                |                                |                      |
+----------------+--------------------------------+----------------------+
```

Implementation contract: `Document rail | Original PDF | Assistant`. Parsed content and details become a secondary tab or drawer while the assistant is active. `Trợ lý` is a real product label only after the feature gate is on; it is never shown as a disabled placeholder.

### Actions and states

| State/behavior | Handoff requirement |
|---|---|
| Entry | Keep document title/number, back, status, and current source context visible. Default to the first useful page or the citation target, not an unexplained blank canvas. |
| Actions | Page navigation, source/parsed-content reading, open details, focus cited block, correct supported field, and open the assistant when enabled. PDF zoom/controls may use the chosen viewer but must preserve source page context. |
| Loading | Source: `Đang mở bản gốc…`; structured: `Đang tải nội dung đã trích xuất…`; metadata: field skeletons. Keep shell and back controls usable. |
| Empty | If source unavailable: `Không thể mở bản gốc`. If canonical blocks are empty: `Chưa có nội dung cấu trúc để hiển thị`; do not render invented headings/fields. |
| Success | Source and structured representation are visibly comparable. Fields show confidence/review status. `Đi tới nguồn` focuses page and block/bbox when known. |
| Error/offline | A page preview failure has retry and a fallback text status where available. Ready documents remain browseable when the home AI node is offline. Parse failure/unsupported states retain the original and explain limitation. |
| Back/navigation | Return to archive with query/filter preserved. From a citation, return to the originating answer while keeping page/block focus. Panel collapse preserves the selected page. |
| Source/citation | The source pane is always the evidence destination. Highlight must be subtle, accessible, and bounded to known block/bbox provenance. |

### Layout variants

- **Desktop verification:** document rail 220–260px; source pane dominant; parsed content/metadata/correction in the third column; no overlapping normal panels.
- **Desktop assistant:** document rail + source pane + assistant pane; parsed content/details move to a secondary tab or drawer.
- **Tablet verification:** `Original PDF + parsed content/details`; document rail is a drawer.
- **Tablet assistant:** `Original PDF + assistant`; parsed content/details are a drawer.
- **Mobile verification:** `Văn bản` + `Chi tiết`; citation navigation switches to `Văn bản` and stores page/block focus.
- **Mobile assistant:** add `Trợ lý` only when enabled and a document is selected; citation navigation still switches to `Văn bản` and exposes `Quay lại câu trả lời`.

## 8. D-05 — Review and correct critical fields

### Entry and intent

**Entry:** `Cần kiểm tra` status, a low-confidence field, or `Chi tiết` within D-04.

**Intent:** Verify a field against its source and submit a correction without destroying raw extraction.

### Wireframe

```text
+-------------------------------------+
| Chi tiết văn bản                    |
|-------------------------------------|
| Hạn                                  |
| 25/08/2026                 Cần kiểm tra |
| Nguồn: Trang 3 · Đoạn b_2_0007       |
| [Đi tới nguồn]                       |
|                                     |
| [Sửa]                                |
| +---------------------------------+ |
| | 25/08/2026                     | |
| +---------------------------------+ |
| [Hủy]                 [Lưu thay đổi]|
+-------------------------------------+
```

### Actions and states

| State/behavior | Handoff requirement |
|---|---|
| Entry | Show field label, normalized/current value, confidence/review label, and source link together. |
| Actions | Open source, edit supported value, cancel, submit correction once. Do not expose dataset/training terminology. |
| Loading | `Đang lưu thay đổi…`; disable duplicate submit; preserve entered value and source link. |
| Empty | If no extracted field is available, show `Chưa có trường thông tin để kiểm tra` and keep source access. |
| Success | Show `Đã sửa`/`Đã lưu`; display corrected value and source link. Make clear through supporting copy that the original extraction remains versioned by the system. |
| Error/offline | Keep the edit open, show `Chưa lưu được thay đổi`, and provide retry. Do not mark `Đã sửa` until the feedback response succeeds. |
| Back/navigation | Cancel returns to the same field list; after success return preserves field focus; browser/system back must warn only if unsaved input would be lost. |
| Source/citation | Source page/block is a required verification affordance when `source_block_ids` exist. If unavailable, label `Chưa có nguồn xác định` rather than inventing a page. |

### Responsive behavior

- **Desktop:** details column or drawer beside the source; correction input remains near evidence.
- **Tablet:** details sheet over source; source link is a full-width action.
- **Mobile:** dedicated `Chi tiết` tab; form controls stack; save/cancel actions are sticky but never cover the field value.

## 9. D-06 — Retry and reprocess

### Entry and intent

**Entry:** `PARSE_FAILED`, retryable job state, or an explicit `POST .../reprocess` capability in the current phase.

**Intent:** Recover from a processing failure without losing the original or overwriting prior parse runs.

### Actions and states

| State/behavior | Handoff requirement |
|---|---|
| Entry | Explain why the document is blocked in plain language and distinguish retryable worker unavailability from terminal unsupported input. |
| Actions | `Thử lại`/reprocess only if the API capability is enabled; `Tải tệp khác`; return to archive. No parser/model selector. |
| Loading | `Đang thử lại…`; lock duplicate retry; keep prior error details collapsed but available. |
| Empty | Not applicable as a blank state; retain document identity and original-file access. |
| Success | New job status is shown; if reprocess creates a new parse run, present the latest current version without deleting history. |
| Error/offline | Explain retry failure, preserve original/error, and keep retry available when `retryable: true`. |
| Back/navigation | Return to the document status or archive with filter context intact. |
| Source/citation | Prior citations remain tied to their specific parse version; do not silently retarget them to a new run. |

### Responsive behavior

- **Desktop/tablet:** retry action stays near status and error explanation.
- **Mobile:** one full-width retry CTA followed by secondary `Tải tệp khác`; no destructive-looking reset.

## 10. Source verification contract

Whenever the UI presents a field source or assistant answer citation, the interaction is:

```text
User activates Trang 3 / Đi tới nguồn
          |
          v
Open selected document if not already open
          |
          v
Navigate to page_number
          |
          v
Focus block_ids / bbox when present
          |
          v
Keep bounded context visible
          |
          v
Back returns to originating field/answer
```

Citation/source rules:

- A source chip must contain enough information to resolve `document_id`, `page_number`, and known `block_ids`.
- A bounded quote is optional; the source page/block is authoritative.
- Never show a source chip for an unknown citation ID or unresolved block.
- Use a warm, translucent focus treatment that does not obscure text.
- On mobile, source focus is a full-screen document surface with a clear `Quay lại câu trả lời` action.

## 11. Phase implementation gates

### Phase 3 must include

- archive/list, upload, durable processing states, document detail;
- original PDF and structured representation;
- metadata and confidence rendering;
- source page/block jump;
- supported correction feedback;
- browser-accessible desktop/tablet/mobile states.

### Phase 3 must not include

- real Q&A or an ungrounded global assistant;
- cross-document retrieval;
- parser/model/provider settings for family users;
- meeting/audio features;
- training-data/admin interfaces.

### Phase 4 may add

- the assistant pane/composer for one selected document;
- four quick grounded actions;
- citations and insufficient-evidence behavior;
- explicit `Trợ lý AI tạm thời không kết nối` state.

### Later phases

- Phase 5: archive-wide retrieval/chat, metadata filters, reranking, freshness-aware behavior, and multi-document citations.
- Phase 6: offline feedback dataset/model promotion tooling; not part of the correction UI.
- Phase 7: production backup/recovery/monitoring surfaces.
- Phase 8: meeting assistant, explicitly parked.

## 12. Accessibility checklist

- [x] Reviewed UX corrections are applied; this is an approved design handoff.
- [ ] Before assistant enablement, no `Trợ lý` navigation, tab, or dead control is rendered.
- [ ] Recent documents remain a grouping/filter inside `Văn bản`, not a top-level destination.
- [ ] Verification workspace is `Document rail | Original PDF | Parsed content / metadata / correction`.
- [ ] Assistant workspace is `Document rail | Original PDF | Assistant`, with parsed/details secondary when active.
- [ ] Context changes use `Chọn văn bản` rather than ambiguous attachment wording.

- [ ] File input has a visible label and keyboard path.
- [ ] Upload/status/error text is announced semantically, not only by color.
- [ ] Page navigation, zoom, panel toggles, citation jump, retry, and correction controls have accessible names.
- [ ] Keyboard users can reach source evidence and return to the originating context.
- [ ] Mobile controls meet the approximate 44px touch-target rule.
- [ ] Reduced-motion behavior does not hide processing or source focus.
- [ ] Null/unavailable values are readable as text.
