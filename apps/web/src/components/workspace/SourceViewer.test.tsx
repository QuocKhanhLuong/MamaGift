import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceViewer } from "./SourceViewer";
import { makeCanonicalDocument } from "../../test/fixtures";

const canonical = makeCanonicalDocument();
const page2 = canonical.pages[1];

describe("SourceViewer (citation/source jump)", () => {
  it("shows a loading placeholder before a page is available", () => {
    render(
      <SourceViewer
        documentId="doc_1"
        page={null}
        pageCount={2}
        onPageChange={vi.fn()}
        focusedBlockId={null}
      />,
    );
    expect(screen.getByText("Đang mở bản gốc…")).toBeInTheDocument();
  });

  it("shows the current page and total page count", () => {
    render(
      <SourceViewer
        documentId="doc_1"
        page={page2}
        pageCount={2}
        onPageChange={vi.fn()}
        focusedBlockId={null}
      />,
    );
    expect(screen.getByText("Trang 2 / 2")).toBeInTheDocument();
  });

  it("renders a bounded highlight over the cited block, positioned proportionally to the page", () => {
    const { container } = render(
      <SourceViewer
        documentId="doc_1"
        page={page2}
        pageCount={2}
        onPageChange={vi.fn()}
        focusedBlockId="b_2_0007"
      />,
    );

    const highlight = container.querySelector('[aria-hidden="true"].border-mg-accent');
    expect(highlight).not.toBeNull();
    // bbox x0=72 over page width=595 -> 12.1%
    expect((highlight as HTMLElement).style.left).toBe(`${(72 / 595) * 100}%`);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Đang xem đoạn nội dung được trích dẫn ở trang 2.",
    );
  });

  it("renders no highlight when no block is focused", () => {
    const { container } = render(
      <SourceViewer
        documentId="doc_1"
        page={page2}
        pageCount={2}
        onPageChange={vi.fn()}
        focusedBlockId={null}
      />,
    );
    expect(container.querySelector('[aria-hidden="true"].border-mg-accent')).toBeNull();
  });

  it("calls onPageChange when navigating and disables out-of-range controls", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(
      <SourceViewer
        documentId="doc_1"
        page={page2}
        pageCount={2}
        onPageChange={onPageChange}
        focusedBlockId={null}
      />,
    );

    expect(screen.getByRole("button", { name: "Trang sau" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Trang trước" }));
    expect(onPageChange).toHaveBeenCalledWith(1);
  });
});
