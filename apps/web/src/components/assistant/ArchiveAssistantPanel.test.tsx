import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "../../api/client";
import type {
  ArchiveDocumentGroup,
  ArchiveQaResponse,
  ArchiveQaStatus,
  ArchiveRelationRef,
} from "../../api/archive";
import type { QaCitation } from "../../api/types";
import { server } from "../../test/server";
import { ArchiveAssistantPanel } from "./ArchiveAssistantPanel";

const citationDocA: QaCitation = {
  citation_id: "c_a1",
  document_id: "doc_A",
  page_number: 1,
  block_ids: ["b_a1"],
  quote: "Thông tư 19/2026/TT-BGDĐT quy định điều kiện tuyển sinh",
};

const citationDocB: QaCitation = {
  citation_id: "c_b1",
  document_id: "doc_B",
  page_number: 3,
  block_ids: ["b_b1"],
  quote: "Kế hoạch 57/KH-UBND triển khai công tác tuyển sinh",
};

const groupDocA: ArchiveDocumentGroup = {
  document_id: "doc_A",
  document_number: "19/2026/TT-BGDĐT",
  title: "Quy chế tuyển sinh",
  document_type: "Thông tư",
  issuer: "Bộ Giáo dục và Đào tạo",
  issued_date: "2026-03-31",
  document_version: 1,
  parse_run_id: "prun_a",
  citation_ids: ["c_a1"],
};

const groupDocB: ArchiveDocumentGroup = {
  document_id: "doc_B",
  document_number: "57/KH-UBND",
  title: "Kế hoạch tuyển sinh đầu cấp",
  document_type: "Kế hoạch",
  issuer: "Ủy ban nhân dân",
  issued_date: "2026-05-10",
  document_version: 1,
  parse_run_id: "prun_b",
  citation_ids: ["c_b1"],
};

function makeArchiveQaResponse({
  status = "answered" as ArchiveQaStatus,
  answer = "Căn cứ theo các văn bản tuyển sinh...",
  citations = [citationDocA, citationDocB],
  document_groups = [groupDocA, groupDocB],
  relations = [] as ArchiveRelationRef[],
  freshness_caveat = null as string | null,
}: Partial<ArchiveQaResponse> = {}): ArchiveQaResponse {
  return {
    answer,
    status,
    citations,
    document_groups,
    relations,
    freshness_caveat,
    retrieval: { query_id: "qry_archive_1" },
    model: { provider: "fake", model: "fake-model", version: "1" },
  };
}

describe("ArchiveAssistantPanel", () => {
  beforeEach(() => {
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(makeArchiveQaResponse()),
      ),
    );
  });

  it("1. Asking a question renders the answer and one group per document, each group naming its document number", async () => {
    const user = userEvent.setup();

    render(<ArchiveAssistantPanel />);

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Tuyển sinh mới nhất?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByText(/Căn cứ theo các văn bản tuyển sinh.../)).toBeInTheDocument();
    expect(screen.getByText("19/2026/TT-BGDĐT")).toBeInTheDocument();
    expect(screen.getByText("57/KH-UBND")).toBeInTheDocument();
    expect(screen.getByTestId("document-group-doc_A")).toBeInTheDocument();
    expect(screen.getByTestId("document-group-doc_B")).toBeInTheDocument();
  });

  it("2. Every rendered citation chip belongs to the group whose document it cites — assert a citation for doc B does NOT appear under doc A's group", async () => {
    const user = userEvent.setup();

    render(<ArchiveAssistantPanel />);

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Các trích dẫn?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    await screen.findByText(/Căn cứ theo các văn bản tuyển sinh.../);

    const groupA = screen.getByTestId("document-group-doc_A");
    const groupB = screen.getByTestId("document-group-doc_B");

    // Group A contains citation c_a1, but NOT c_b1
    expect(within(groupA).getByTestId("citation-chip-c_a1")).toBeInTheDocument();
    expect(within(groupA).queryByTestId("citation-chip-c_b1")).not.toBeInTheDocument();

    // Group B contains citation c_b1, but NOT c_a1
    expect(within(groupB).getByTestId("citation-chip-c_b1")).toBeInTheDocument();
    expect(within(groupB).queryByTestId("citation-chip-c_a1")).not.toBeInTheDocument();
  });

  it("3. Clicking a citation chip calls onCitationNavigate with that citation's document_id, page and block_ids", async () => {
    const user = userEvent.setup();
    const onCitationNavigate = vi.fn();

    render(<ArchiveAssistantPanel onCitationNavigate={onCitationNavigate} />);

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Tìm nguồn?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    const chipDocA = await screen.findByTestId("citation-chip-c_a1");
    await user.click(chipDocA);

    expect(onCitationNavigate).toHaveBeenCalledTimes(1);
    expect(onCitationNavigate).toHaveBeenCalledWith("doc_A", 1, ["b_a1"], citationDocA);
  });

  it("4. freshness_caveat is rendered when present and absent when null", async () => {
    const user = userEvent.setup();

    // Case A: freshness_caveat is present
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(
          makeArchiveQaResponse({
            freshness_caveat: "Có văn bản mới hơn đã ban hành ngày 15/08/2026.",
          }),
        ),
      ),
    );

    const { unmount } = render(<ArchiveAssistantPanel />);
    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Kiểm tra tính cập nhật");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByTestId("freshness-caveat")).toBeInTheDocument();
    expect(screen.getByText("Có văn bản mới hơn đã ban hành ngày 15/08/2026.")).toBeInTheDocument();

    unmount();

    // Case B: freshness_caveat is null
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(makeArchiveQaResponse({ freshness_caveat: null })),
      ),
    );

    render(<ArchiveAssistantPanel />);
    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Không có caveat");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    await screen.findByText(/Căn cứ theo các văn bản tuyển sinh.../);
    expect(screen.queryByTestId("freshness-caveat")).not.toBeInTheDocument();
  });

  it("5. An unverified relation is labelled unverified — assert the visible text", async () => {
    const user = userEvent.setup();
    const unverifiedRelation: ArchiveRelationRef = {
      relation_type: "replaces",
      review_state: "unverified",
      confidence: 0.85,
      source_document_id: "doc_B",
      target_document_id: "doc_A",
      target_document_number: "19/2026/TT-BGDĐT",
      citation_ids: ["c_b1"],
    };

    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(makeArchiveQaResponse({ relations: [unverifiedRelation] })),
      ),
    );

    render(<ArchiveAssistantPanel />);

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Quan hệ văn bản?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByTestId("relations-section")).toBeInTheDocument();
    const relationItem = screen.getByTestId("relation-item");

    // The badge is the load-bearing part: a machine-extracted relation must never read as an
    // established fact. Match the badge element itself rather than any text containing the
    // word, which also appears in the relation's own description.
    const badge = within(relationItem).getByText("Chưa xác thực (unverified)");
    expect(badge).toHaveAttribute("data-review-state", "unverified");
  });

  it("6. status: 'insufficient_evidence' renders the abstention state and NO citations", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(
          makeArchiveQaResponse({
            status: "insufficient_evidence",
            answer: "",
            citations: [citationDocA],
            document_groups: [groupDocA],
          }),
        ),
      ),
    );

    render(<ArchiveAssistantPanel />);

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Câu hỏi không có căn cứ?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByTestId("assistant-insufficient-evidence")).toBeInTheDocument();
    expect(screen.getByText("Chưa tìm thấy câu trả lời trong kho tài liệu")).toBeInTheDocument();
    expect(screen.queryByTestId("citation-chip-c_a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("document-group-doc_A")).not.toBeInTheDocument();
  });

  it("7. ai_worker_unavailable and archive_not_indexed errors render their specific messages", async () => {
    const user = userEvent.setup();

    // Subcase A: ai_worker_unavailable (503)
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(
          {
            error: {
              code: "ai_worker_unavailable",
              message: "AI service is unavailable",
              retryable: true,
              request_id: "req_503",
              details: {},
            },
          },
          { status: 503 },
        ),
      ),
    );

    const { unmount } = render(<ArchiveAssistantPanel />);
    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Hỏi khi worker hỏng");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(
      await screen.findByText("Trợ lý đang tạm thời không hoạt động. Vui lòng thử lại sau."),
    ).toBeInTheDocument();

    unmount();

    // Subcase B: archive_not_indexed (409)
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(
          {
            error: {
              code: "archive_not_indexed",
              message: "Archive not indexed",
              retryable: true,
              request_id: "req_409",
              details: {},
            },
          },
          { status: 409 },
        ),
      ),
    );

    render(<ArchiveAssistantPanel />);
    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Hỏi khi chưa index");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(
      await screen.findByText("Kho tài liệu chưa sẵn sàng để tìm kiếm. Vui lòng thử lại sau."),
    ).toBeInTheDocument();
  });

  it("8. Enter submits, Shift+Enter does not", async () => {
    const user = userEvent.setup();
    let requestCount = 0;
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () => {
        requestCount++;
        return HttpResponse.json(makeArchiveQaResponse());
      }),
    );

    render(<ArchiveAssistantPanel />);
    const textarea = screen.getByRole("textbox", { name: "Câu hỏi" });

    // Shift+Enter does not submit
    await user.type(textarea, "Dòng 1{Shift>}{Enter}{/Shift}Dòng 2");
    expect(requestCount).toBe(0);
    expect(textarea).toHaveValue("Dòng 1\nDòng 2");

    // Enter submits
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(requestCount).toBe(1);
    });
  });

  it("9. the composer is locked while a question is in flight, so answers cannot race", async () => {
    const user = userEvent.setup();
    // A holder object, not a bare `let`: TypeScript's control-flow analysis cannot see the
    // MSW callback run, so a plain variable narrows to `never` at the call site below.
    const deferred: { resolve: ((value: unknown) => void) | null } = { resolve: null };
    let requestCount = 0;

    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () => {
        requestCount += 1;
        await new Promise((resolve) => {
          deferred.resolve = resolve;
        });
        return HttpResponse.json(makeArchiveQaResponse({ answer: "Câu trả lời duy nhất" }));
      }),
    );

    render(<ArchiveAssistantPanel />);
    const textarea = screen.getByRole("textbox", { name: "Câu hỏi" });

    await user.type(textarea, "Câu hỏi 1");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(screen.getByText("Đang tìm trong kho văn bản…")).toBeInTheDocument();

    // While a question is in flight the composer and its controls are disabled. This -- not an
    // abort race -- is how the panel guarantees a stale answer can never appear under a newer
    // question: a second question cannot be started in the first place. The abort logic in
    // useArchiveQa remains as defence for programmatic callers.
    expect(textarea).toBeDisabled();
    expect(screen.getByRole("button", { name: "Gửi câu hỏi" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));
    expect(requestCount).toBe(1);

    deferred.resolve?.(null);
    expect(await screen.findByText("Câu trả lời duy nhất")).toBeInTheDocument();

    // Once the answer lands the composer is usable again.
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Câu hỏi" })).not.toBeDisabled();
    });
  });

  it("submits when a quick question button is clicked", async () => {
    const user = userEvent.setup();
    let submittedQuestion: string | null = null;
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async ({ request }) => {
        const body = (await request.json()) as { question: string };
        submittedQuestion = body.question;
        return HttpResponse.json(makeArchiveQaResponse());
      }),
    );

    render(<ArchiveAssistantPanel />);

    const quickButton = screen.getByRole("button", { name: "Tuyển sinh mới nhất" });
    await user.click(quickButton);

    await waitFor(() => {
      expect(submittedQuestion).toBe("Văn bản mới nhất liên quan tới tuyển sinh?");
    });
  });
});
