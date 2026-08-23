import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantStates, type AssistantStateKind } from "./AssistantStates";

const STATE_COPY: Record<AssistantStateKind, string> = {
  empty: "Chào mẹ, hôm nay mẹ cần tìm gì?",
  indexing: "Văn bản đang được chuẩn bị",
  ai_worker_unavailable:
    "Văn bản của mẹ vẫn còn nguyên. Trợ lý đang tạm thời không kết nối được nên chưa thể trả lời. Mẹ thử lại sau nhé.",
  insufficient_evidence: "Chưa tìm thấy câu trả lời trong văn bản này",
  failed:
    "Trợ lý chưa thể hoàn thành câu trả lời lúc này. Văn bản của mẹ vẫn được giữ nguyên. Mẹ thử lại nhé.",
};

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  fireEvent.resize(window);
}

describe("AssistantStates", () => {
  beforeEach(() => {
    setViewport(1440);
  });

  afterEach(() => {
    setViewport(1440);
  });

  it.each(Object.entries(STATE_COPY) as [AssistantStateKind, string][])(
    "renders distinct Vietnamese copy for %s",
    (state, copy) => {
      render(<AssistantStates state={state} />);

      expect(screen.getByText(copy)).toBeInTheDocument();
      expect(screen.getByTestId(`assistant-${state.replaceAll("_", "-")}`)).toBeInTheDocument();
      expect(
        screen.getByTestId(`assistant-${state.replaceAll("_", "-")}`).closest("[data-breakpoint]"),
      ).toHaveAttribute("data-breakpoint", "desktop");
    },
  );

  it.each(["ai_worker_unavailable", "failed"] as const)("wires retry for %s", (state) => {
    const onRetry = vi.fn();
    render(<AssistantStates state={state} onRetry={onRetry} />);

    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("keeps indexing as a wait state without an error retry", () => {
    render(<AssistantStates state="indexing" onRetry={vi.fn()} />);

    expect(screen.getByRole("status", { name: "Đang chuẩn bị văn bản" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử lại" })).not.toBeInTheDocument();
  });

  it.each([
    [375, "mobile", "px-2"],
    [768, "tablet", "px-4"],
  ] as const)("uses the %dpx (%s) responsive layout", (width, breakpoint, className) => {
    setViewport(width);
    render(<AssistantStates state="empty" />);

    const frame = screen.getByTestId("assistant-empty").parentElement;
    expect(frame).toHaveAttribute("data-breakpoint", breakpoint);
    expect(frame).toHaveClass(className);
  });
});
