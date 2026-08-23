import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { API_BASE_URL } from "../../api/client";
import type { QaStatus } from "../../api/types";
import { makeDocumentSummary } from "../../test/fixtures";
import { server } from "../../test/server";
import { AssistantPanel } from "./AssistantPanel";

function qaResponse(status: QaStatus, answer = "Nhà trường cần thực hiện theo văn bản.") {
  return {
    answer,
    status,
    citations: [],
    retrieval: { query_id: "qry_1" },
    model: { provider: "fake", model: "fake-model", version: "1" },
  };
}

function renderPanel(status: string = "READY") {
  return render(<AssistantPanel document={makeDocumentSummary({ status: status as never })} />);
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

  it("submits a question through the document QA endpoint and renders the answer", async () => {
    const user = userEvent.setup();
    let requestBody: unknown;
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, async ({ request }) => {
        requestBody = await request.json();
        return HttpResponse.json(qaResponse("answered", "Câu trả lời có căn cứ."));
      }),
    );
    renderPanel();

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Văn bản yêu cầu gì?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByText("Câu trả lời có căn cứ.")).toBeInTheDocument();
    expect(requestBody).toEqual({ question: "Văn bản yêu cầu gì?" });
  });

  it.each([
    ["answered", "Đã có câu trả lời"],
    ["insufficient_evidence", "Chưa đủ căn cứ"],
    ["ai_worker_unavailable", "Trợ lý tạm thời không hoạt động"],
    ["failed", "Chưa hoàn thành"],
  ] as const)("renders the %s response state", async (status, label) => {
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/qa`, () =>
        HttpResponse.json(qaResponse(status)),
      ),
    );
    renderPanel();
    await userEvent.setup().click(screen.getByRole("button", { name: "Tóm tắt" }));

    expect(await screen.findByText(label)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(label)).toBeInTheDocument());
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
