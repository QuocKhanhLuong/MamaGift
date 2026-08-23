import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "../../api/client";
import type { QaCitation, QaResponse, QaStatus } from "../../api/types";
import { makeCanonicalDocument, makeDocumentSummary } from "../../test/fixtures";
import { server } from "../../test/server";
import { AssistantPanel } from "./AssistantPanel";

function qaResponse(
  status: QaStatus,
  answer = "Nhà trường cần thực hiện theo văn bản.",
  citations: QaCitation[] = [],
): QaResponse {
  return {
    answer,
    status,
    citations,
    retrieval: { query_id: "qry_1" },
    model: { provider: "fake", model: "fake-model", version: "1" },
  };
}

const citation1: QaCitation = {
  citation_id: "c1",
  document_id: "doc_1",
  page_number: 2,
  block_ids: ["b_2_0007"],
  quote: "Hạn hoàn thành trước ngày 25 tháng 8 năm 2026",
};

function renderPanel(
  status: string = "READY",
  props: Partial<Parameters<typeof AssistantPanel>[0]> = {},
) {
  return render(
    <AssistantPanel
      document={makeDocumentSummary({ status: status as never })}
      sourcePages={makeCanonicalDocument().pages}
      {...props}
    />,
  );
}

describe("AssistantPanel", () => {
  beforeEach(() => {
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, async () =>
        HttpResponse.json(qaResponse("answered")),
      ),
    );
  });

  it("keeps the entry point unavailable with a plain-language reason for a non-ready document", () => {
    renderPanel("PARSING");

    expect(screen.getByRole("heading", { name: "Trợ lý chưa sẵn sàng" })).toBeInTheDocument();
    expect(screen.getByText(/Hiện tại: Đang đọc văn bản/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Trợ lý" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("textbox", { name: "Câu hỏi" })).not.toBeInTheDocument();
  });

  it("enables the composer for a READY document", () => {
    renderPanel();

    expect(screen.getByPlaceholderText("Hỏi về văn bản…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tóm tắt" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Trợ lý" })).toHaveAttribute(
      "aria-disabled",
      "false",
    );
  });

  it("submits a question through the document QA endpoint and renders the answer via AnswerView", async () => {
    const user = userEvent.setup();
    let requestBody: unknown;
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, async ({ request }) => {
        requestBody = await request.json();
        return HttpResponse.json(
          qaResponse("answered", "Câu trả lời có căn cứ. [c1]", [citation1]),
        );
      }),
    );
    renderPanel();

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Văn bản yêu cầu gì?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByText(/Câu trả lời có căn cứ./)).toBeInTheDocument();
    expect(screen.getByTestId("citation-chip-c1")).toBeInTheDocument();
    expect(requestBody).toEqual({ question: "Văn bản yêu cầu gì?" });
  });

  it("invokes onCitationNavigate when a citation chip in the answer is clicked", async () => {
    const user = userEvent.setup();
    const onCitationNavigate = vi.fn();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json(qaResponse("answered", "Căn cứ theo [c1]", [citation1])),
      ),
    );
    renderPanel("READY", { onCitationNavigate });

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Hạn nộp?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(
      await screen.findByRole("button", { name: "Đi tới nguồn · Trang 2" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Đi tới nguồn · Trang 2" }));

    expect(onCitationNavigate).toHaveBeenCalledWith(2, ["b_2_0007"], citation1);
  });

  it("renders the answered response through AnswerView", async () => {
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json(qaResponse("answered", "Nội dung trả lời chính xác.")),
      ),
    );
    renderPanel();
    await userEvent.setup().click(screen.getByRole("button", { name: "Tóm tắt" }));

    expect(await screen.findByText("Nội dung trả lời chính xác.")).toBeInTheDocument();
    expect(document.querySelector("[data-answer-view]")).toBeInTheDocument();
  });

  it("renders the insufficient_evidence response state through AssistantStates", async () => {
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json(qaResponse("insufficient_evidence", "")),
      ),
    );
    renderPanel();
    await userEvent.setup().click(screen.getByRole("button", { name: "Tóm tắt" }));

    expect(await screen.findByTestId("assistant-insufficient-evidence")).toBeInTheDocument();
    expect(screen.getByText("Chưa tìm thấy câu trả lời trong văn bản này")).toBeInTheDocument();
  });

  it("renders the ai_worker_unavailable response state through AssistantStates", async () => {
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json(qaResponse("ai_worker_unavailable", "")),
      ),
    );
    renderPanel();
    await userEvent.setup().click(screen.getByRole("button", { name: "Tóm tắt" }));

    expect(await screen.findByTestId("assistant-ai-worker-unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Trợ lý đang tạm thời không kết nối được/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it("renders the failed response state through AssistantStates", async () => {
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json(qaResponse("failed", "")),
      ),
    );
    renderPanel();
    await userEvent.setup().click(screen.getByRole("button", { name: "Tóm tắt" }));

    expect(await screen.findByTestId("assistant-failed")).toBeInTheDocument();
    expect(screen.getByText(/Trợ lý chưa thể hoàn thành câu trả lời lúc này/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it.each([
    ["Tóm tắt", "Tóm tắt văn bản này."],
    ["Tôi cần làm gì?", "Tôi cần làm gì theo văn bản này?"],
    ["Có deadline nào?", "Văn bản này có deadline nào?"],
    ["Đối tượng áp dụng?", "Đối tượng nào áp dụng theo văn bản này?"],
  ] as const)("submits the expected question for %s", async (label, expectedQuestion) => {
    const user = userEvent.setup();
    const questions: string[] = [];
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, async ({ request }) => {
        questions.push(((await request.json()) as { question: string }).question);
        return HttpResponse.json(qaResponse("answered"));
      }),
    );
    renderPanel();

    await user.click(screen.getByRole("button", { name: label }));

    await waitFor(() => expect(questions).toEqual([expectedQuestion]));
  });
});
