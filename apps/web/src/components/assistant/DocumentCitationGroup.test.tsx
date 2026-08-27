import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ArchiveDocumentGroup } from "../../api/archive";
import type { QaCitation } from "../../api/types";
import { DocumentCitationGroup } from "./DocumentCitationGroup";

const citation1: QaCitation = {
  citation_id: "c1",
  document_id: "doc_1",
  page_number: 2,
  block_ids: ["b_2_0001", "b_2_0002"],
  quote: "Quy định về thời hạn tuyển sinh năm học 2026-2027",
};

const citation2: QaCitation = {
  citation_id: "c2",
  document_id: "doc_1",
  page_number: 5,
  block_ids: ["b_5_0010"],
  quote: "Hạn chót nộp hồ sơ ngày 15/08/2026",
};

const group1: ArchiveDocumentGroup = {
  document_id: "doc_1",
  document_number: "142/SGDĐT-GDTH",
  title: "Về việc hướng dẫn tuyển sinh",
  document_type: "Công văn",
  issuer: "Sở Giáo dục và Đào tạo",
  issued_date: "2026-08-14",
  document_version: 1,
  parse_run_id: "prun_1",
  citation_ids: ["c1", "c2"],
};

describe("DocumentCitationGroup", () => {
  it("renders document metadata: number, title, type, issuer, and formatted date", () => {
    render(<DocumentCitationGroup group={group1} citations={[citation1, citation2]} />);

    expect(screen.getByText("142/SGDĐT-GDTH")).toBeInTheDocument();
    expect(screen.getByText("Về việc hướng dẫn tuyển sinh")).toBeInTheDocument();
    expect(screen.getByText("Công văn")).toBeInTheDocument();
    expect(screen.getByText("Sở Giáo dục và Đào tạo")).toBeInTheDocument();
    expect(screen.getByText("14/08/2026")).toBeInTheDocument();
  });

  it("skips citation_id with no matching citation without crashing or rendering a blank chip (Test 10)", () => {
    const groupWithMissingCitation: ArchiveDocumentGroup = {
      ...group1,
      citation_ids: ["c1", "c_missing_999", "c2"],
    };

    render(
      <DocumentCitationGroup group={groupWithMissingCitation} citations={[citation1, citation2]} />,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(screen.getByTestId("citation-chip-c1")).toBeInTheDocument();
    expect(screen.getByTestId("citation-chip-c2")).toBeInTheDocument();
    expect(screen.queryByTestId("citation-chip-c_missing_999")).not.toBeInTheDocument();
  });

  it("renders chips as <button> elements with accessible names naming document and page (Test 11)", () => {
    render(<DocumentCitationGroup group={group1} citations={[citation1, citation2]} />);

    const button1 = screen.getByRole("button", {
      name: "Văn bản 142/SGDĐT-GDTH · Trang 2",
    });
    const button2 = screen.getByRole("button", {
      name: "Văn bản 142/SGDĐT-GDTH · Trang 5",
    });

    expect(button1).toBeInTheDocument();
    expect(button1.tagName).toBe("BUTTON");
    expect(button2).toBeInTheDocument();
    expect(button2.tagName).toBe("BUTTON");
  });

  it("calls onCitationNavigate with document_id, page, blockIds, and citation when clicked", async () => {
    const user = userEvent.setup();
    const onCitationNavigate = vi.fn();

    render(
      <DocumentCitationGroup
        group={group1}
        citations={[citation1, citation2]}
        onCitationNavigate={onCitationNavigate}
      />,
    );

    const button1 = screen.getByRole("button", {
      name: "Văn bản 142/SGDĐT-GDTH · Trang 2",
    });
    await user.click(button1);

    expect(onCitationNavigate).toHaveBeenCalledTimes(1);
    expect(onCitationNavigate).toHaveBeenCalledWith(
      "doc_1",
      2,
      ["b_2_0001", "b_2_0002"],
      citation1,
    );
  });
});
