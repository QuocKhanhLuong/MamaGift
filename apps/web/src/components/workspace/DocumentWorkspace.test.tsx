import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { DocumentWorkspace } from "./DocumentWorkspace";
import { server } from "../../test/server";
import { API_BASE_URL } from "../../api/client";
import { makeCanonicalDocument, makeDocumentSummary } from "../../test/fixtures";

function renderWorkspace() {
  return render(
    <MemoryRouter>
      <DocumentWorkspace documentId="doc_1" />
    </MemoryRouter>,
  );
}

describe("DocumentWorkspace (correction persistence + citation jump)", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { value: 1280, configurable: true });
    server.use(
      http.get(`${API_BASE_URL}/api/v1/documents`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
      http.get(`${API_BASE_URL}/api/v1/documents/doc_1/canonical`, () =>
        HttpResponse.json({
          parse_run: {
            id: "prun_1",
            document_id: "doc_1",
            version: 1,
            is_current: true,
            parser_name: "pymupdf",
            parser_version: "1.0",
            configuration_hash: "hash",
            strategy_decided: false,
            degraded: true,
            route: "born_digital",
            schema_version: "1.0",
            quality_report: makeCanonicalDocument().quality_report,
            started_at: "2026-08-14T00:00:00Z",
            finished_at: "2026-08-14T00:00:01Z",
          },
          canonical: makeCanonicalDocument(),
        }),
      ),
    );
  });

  it("jumps to the cited page when 'Đi tới nguồn' is used", async () => {
    const user = userEvent.setup();
    renderWorkspace();

    expect(await screen.findByText("Trang 1 / 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Đi tới nguồn · Trang 2/ }));

    expect(await screen.findByText("Trang 2 / 2")).toBeInTheDocument();
  });

  it("reflects a correction immediately without re-fetching the canonical document", async () => {
    const user = userEvent.setup();
    let feedbackCalls = 0;
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/feedback`, async ({ request }) => {
        feedbackCalls += 1;
        const body = (await request.json()) as { corrected_value: string; field_id: string };
        return HttpResponse.json(
          {
            id: "fb_1",
            document_id: "doc_1",
            feedback_type: "critical_field_correction",
            field_id: body.field_id,
            corrected_value: body.corrected_value,
            comment: null,
            created_at: "2026-08-14T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );
    renderWorkspace();

    await screen.findByText("Hạn hoàn thành");
    await user.click(screen.getByRole("button", { name: "Sửa" }));
    const input = screen.getByLabelText("Giá trị mới");
    await user.clear(input);
    await user.type(input, "30/08/2026");
    await user.click(screen.getByRole("button", { name: "Lưu thay đổi" }));

    await waitFor(() => expect(screen.getByText("Đã sửa")).toBeInTheDocument());
    expect(screen.getByText("30/08/2026")).toBeInTheDocument();
    expect(feedbackCalls).toBe(1);
  });

  it("renders the assistant entry point for a READY document and does not for a non-ready one", async () => {
    const { unmount } = render(
      <MemoryRouter>
        <DocumentWorkspace documentId="doc_1" document={makeDocumentSummary({ status: "READY" })} />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("tab", { name: "Trợ lý" })).toBeInTheDocument();
    unmount();

    render(
      <MemoryRouter>
        <DocumentWorkspace
          documentId="doc_1"
          document={makeDocumentSummary({ status: "READY_FOR_REVIEW" })}
        />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Hạn hoàn thành")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Trợ lý" })).not.toBeInTheDocument();
  });

  it("asking a question renders the answer through AnswerView with its citation chips", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json({
          answer: "Theo quy định [c1], nhà trường cần báo cáo.",
          status: "answered",
          citations: [
            {
              citation_id: "c1",
              document_id: "doc_1",
              page_number: 2,
              block_ids: ["b_2_0007"],
              quote: "Hạn hoàn thành trước ngày 25 tháng 8 năm 2026",
            },
          ],
          retrieval: { query_id: "qry_1" },
          model: { provider: "fake", model: "fake-model", version: "1" },
        }),
      ),
    );

    renderWorkspace();
    await screen.findByText("Hạn hoàn thành");

    await user.click(screen.getByRole("tab", { name: "Trợ lý" }));
    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Khi nào phải nộp?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByText(/Theo quy định/)).toBeInTheDocument();
    expect(screen.getByTestId("citation-chip-c1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đi tới nguồn · Trang 2" })).toBeInTheDocument();
  });

  it("clicking a citation chip navigates the SourceViewer to the expected page and highlights the source block", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json({
          answer: "Hạn hoàn thành [c1].",
          status: "answered",
          citations: [
            {
              citation_id: "c1",
              document_id: "doc_1",
              page_number: 2,
              block_ids: ["b_2_0007"],
              quote: "Hạn hoàn thành trước ngày 25 tháng 8 năm 2026",
            },
          ],
          retrieval: { query_id: "qry_1" },
          model: { provider: "fake", model: "fake-model", version: "1" },
        }),
      ),
    );

    renderWorkspace();
    expect(await screen.findByText("Trang 1 / 2")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Trợ lý" }));
    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Hạn hoàn thành?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    const chip = await screen.findByRole("button", { name: "Đi tới nguồn · Trang 2" });
    await user.click(chip);

    expect(await screen.findByText("Trang 2 / 2")).toBeInTheDocument();
    expect(document.querySelector('[data-source-block-id="b_2_0007"]')).toBeInTheDocument();
  });

  it.each([
    ["answered", "data-answer-view"],
    ["insufficient_evidence", "assistant-insufficient-evidence"],
    ["ai_worker_unavailable", "assistant-ai-worker-unavailable"],
    ["failed", "assistant-failed"],
  ] as const)(
    "renders the %s QA status with its intended component",
    async (status, identifier) => {
      const user = userEvent.setup();
      server.use(
        http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
          HttpResponse.json({
            answer: status === "answered" ? "Câu trả lời hoàn chỉnh." : "",
            status,
            citations: [],
            retrieval: { query_id: "qry_1" },
            model: { provider: "fake", model: "fake-model", version: "1" },
          }),
        ),
      );

      renderWorkspace();
      await screen.findByText("Trang 1 / 2");

      await user.click(screen.getByRole("tab", { name: "Trợ lý" }));
      await user.click(screen.getByRole("button", { name: "Tóm tắt" }));

      if (status === "answered") {
        await waitFor(() => expect(document.querySelector(`[${identifier}]`)).toBeInTheDocument());
      } else {
        expect(await screen.findByTestId(identifier)).toBeInTheDocument();
      }
    },
  );
});
