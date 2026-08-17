import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfidenceField } from "./ConfidenceField";
import { makeExtractedField } from "../../test/fixtures";

describe("ConfidenceField", () => {
  it("renders the field label, formatted value, and confidence/review status", () => {
    render(
      <ConfidenceField
        documentId="doc_1"
        field={makeExtractedField({ review_status: "confirmed" })}
        onGoToSource={vi.fn()}
        onCorrected={vi.fn()}
      />,
    );

    expect(screen.getByText("Hạn hoàn thành")).toBeInTheDocument();
    expect(screen.getByText("25/08/2026")).toBeInTheDocument();
    expect(screen.getByText("Đã xác nhận")).toBeInTheDocument();
  });

  it("flags an unreviewed low-confidence field as needing review, not by color alone", () => {
    render(
      <ConfidenceField
        documentId="doc_1"
        field={makeExtractedField({ confidence: 0.4, review_status: "unreviewed" })}
        onGoToSource={vi.fn()}
        onCorrected={vi.fn()}
      />,
    );

    expect(screen.getByText("Cần kiểm tra")).toBeInTheDocument();
  });

  it("does not flag a high-confidence unreviewed field", () => {
    render(
      <ConfidenceField
        documentId="doc_1"
        field={makeExtractedField({ confidence: 0.98, review_status: "unreviewed" })}
        onGoToSource={vi.fn()}
        onCorrected={vi.fn()}
      />,
    );

    expect(screen.queryByText("Cần kiểm tra")).not.toBeInTheDocument();
  });

  it("labels a field with no resolvable source instead of inventing a page", () => {
    render(
      <ConfidenceField
        documentId="doc_1"
        field={makeExtractedField({ source_block_ids: [], source_page_numbers: [] })}
        onGoToSource={vi.fn()}
        onCorrected={vi.fn()}
      />,
    );

    expect(screen.getByText("Chưa có nguồn xác định")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Đi tới nguồn/ })).not.toBeInTheDocument();
  });

  it("invokes onGoToSource with the field when the citation jump action is used", async () => {
    const user = userEvent.setup();
    const onGoToSource = vi.fn();
    const field = makeExtractedField();
    render(
      <ConfidenceField
        documentId="doc_1"
        field={field}
        onGoToSource={onGoToSource}
        onCorrected={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Đi tới nguồn · Trang 2/ }));
    expect(onGoToSource).toHaveBeenCalledWith(field);
  });
});
