import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProcessingStatus } from "./ProcessingStatus";

describe("ProcessingStatus", () => {
  it("shows the plain-Vietnamese status and progress timeline while queued", () => {
    render(<ProcessingStatus title="Công văn 142" status="QUEUED_FOR_PARSE" />);

    expect(screen.getByText("Trạng thái: Đang chờ xử lý")).toBeInTheDocument();
    expect(screen.getByText("Đã nhận văn bản")).toBeInTheDocument();
  });

  it("shows the reviewable status once parsing finishes", () => {
    render(<ProcessingStatus title="Công văn 142" status="READY_FOR_REVIEW" />);
    expect(screen.getByText("Trạng thái: Cần kiểm tra")).toBeInTheDocument();
  });

  it("shows a terminal failure state with retry and choose-another actions", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const onChooseAnother = vi.fn();
    render(
      <ProcessingStatus
        title="Công văn 142"
        status="PARSE_FAILED"
        onRetry={onRetry}
        onChooseAnother={onChooseAnother}
      />,
    );

    expect(screen.getByText("Trạng thái: Không đọc được văn bản")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(onRetry).toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Tải tệp khác" }));
    expect(onChooseAnother).toHaveBeenCalled();
  });

  it("shows the unsupported-format state without a retry action", () => {
    render(
      <ProcessingStatus title="Công văn 142" status="UNSUPPORTED" onChooseAnother={vi.fn()} />,
    );
    expect(screen.getByText("Trạng thái: Định dạng chưa được hỗ trợ")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử lại" })).not.toBeInTheDocument();
  });
});
