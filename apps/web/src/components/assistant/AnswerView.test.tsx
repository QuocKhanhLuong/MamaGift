import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { QaResponse } from "../../api/types";
import { makeCanonicalDocument } from "../../test/fixtures";
import { AnswerView } from "./AnswerView";

function response(answer: string, citations: QaResponse["citations"]): QaResponse {
  return {
    answer,
    status: "answered",
    citations,
    retrieval: { query_id: "query_1" },
    model: { provider: "fake", model: "fake-model", version: "1" },
  };
}

const citation1 = {
  citation_id: "c1",
  document_id: "doc_1",
  page_number: 2,
  block_ids: ["b_2_0007"],
  quote: "Hạn hoàn thành trước ngày 25 tháng 8 năm 2026",
};
const citation2 = {
  citation_id: "c2",
  document_id: "doc_1",
  page_number: 2,
  block_ids: ["b_2_0008"],
  quote: "Nhà trường thực hiện thông báo",
};

describe("AnswerView", () => {
  it("renders one source chip for each returned citation", () => {
    render(
      <AnswerView
        response={response("Nhà trường cần thực hiện [c1] và thông báo [c2].", [
          citation1,
          citation2,
        ])}
      />,
    );

    expect(screen.getByTestId("citation-chip-c1")).toBeInTheDocument();
    expect(screen.getByTestId("citation-chip-c2")).toBeInTheDocument();
  });

  it("passes the exact page and block IDs when a citation is activated", async () => {
    const user = userEvent.setup();
    const onCitationNavigate = vi.fn();
    render(
      <AnswerView
        response={response("Căn cứ [c1].", [citation1])}
        sourcePages={makeCanonicalDocument().pages}
        onCitationNavigate={onCitationNavigate}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Đi tới nguồn · Trang 2" }));

    expect(onCitationNavigate).toHaveBeenCalledWith(2, ["b_2_0007"], citation1);
  });

  it("shows an explicit unavailable state when the page or source block cannot be resolved", () => {
    render(
      <AnswerView
        response={response("Không xác định được [c1].", [citation1])}
        sourcePages={makeCanonicalDocument().pages.map((page) => ({ ...page, blocks: [] }))}
      />,
    );

    expect(screen.getByText("Không thể định vị nguồn · Trang 2")).toBeInTheDocument();
    expect(screen.getByTestId("citation-chip-c1")).toHaveAttribute(
      "data-citation-unresolvable",
      "true",
    );
    expect(screen.queryByRole("button", { name: /Đi tới nguồn/ })).not.toBeInTheDocument();
  });

  it("renders grounded prose without a source row when there are no citations", () => {
    render(<AnswerView response={response("Không có nguồn phù hợp.", [])} />);

    expect(screen.getByText("Không có nguồn phù hợp.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Nguồn tham khảo")).not.toBeInTheDocument();
  });

  it("keeps hostile answer and quote text as text, never HTML", () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    render(<AnswerView response={response(hostile, [{ ...citation1, quote: hostile }])} />);

    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });
});
