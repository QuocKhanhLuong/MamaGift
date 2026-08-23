import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { makeCanonicalDocument } from "../../test/fixtures";
import { CitationChip } from "./CitationChip";

const citation = {
  citation_id: "c1",
  document_id: "doc_1",
  page_number: 2,
  block_ids: ["b_2_0007"],
  quote: "Hạn hoàn thành trước ngày 25 tháng 8 năm 2026",
};

describe("CitationChip", () => {
  it("navigates to the citation page and every cited block", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(
      <CitationChip
        citation={citation}
        onNavigate={onNavigate}
        sourcePages={makeCanonicalDocument().pages}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Đi tới nguồn · Trang 2" }));

    expect(onNavigate).toHaveBeenCalledWith(2, ["b_2_0007"]);
  });

  it("degrades visibly and does not activate when the citation cannot be resolved", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(
      <CitationChip
        citation={citation}
        onNavigate={onNavigate}
        sourcePages={makeCanonicalDocument().pages.map((page) => ({ ...page, blocks: [] }))}
      />,
    );

    expect(screen.getByText("Không thể định vị nguồn · Trang 2")).toBeInTheDocument();
    expect(screen.getByTestId("citation-chip-c1")).toHaveAttribute(
      "data-citation-unresolvable",
      "true",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("citation-chip-c1"));
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("requires at least one source block even when the page exists", () => {
    render(
      <CitationChip
        citation={{ ...citation, block_ids: [] }}
        sourcePages={makeCanonicalDocument().pages}
      />,
    );

    expect(screen.getByText("Không thể định vị nguồn · Trang 2")).toBeInTheDocument();
  });

  it("does not claim a block whose recorded page disagrees with the citation page", () => {
    const pages = makeCanonicalDocument().pages.map((page) =>
      page.page_number === 2
        ? {
            ...page,
            blocks: page.blocks.map((block) => ({
              ...block,
              provenance: { ...block.provenance, page_number: 1 },
            })),
          }
        : page,
    );
    render(<CitationChip citation={citation} sourcePages={pages} />);

    expect(screen.getByText("Không thể định vị nguồn · Trang 2")).toBeInTheDocument();
  });
});
