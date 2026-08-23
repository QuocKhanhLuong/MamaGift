import { cn } from "../../lib/cn";
import { useBreakpoint, type Breakpoint } from "../../hooks/useBreakpoint";
import { EmptyState } from "../common/EmptyState";
import { ErrorState } from "../common/ErrorState";
import { Skeleton } from "../common/Skeleton";
import type { ReactNode } from "react";

/** The assistant outcomes that do not contain an answer. */
export type AssistantStateKind =
  "empty" | "indexing" | "ai_worker_unavailable" | "insufficient_evidence" | "failed";

export interface AssistantStatesProps {
  /** The preferred prop name for the state slot in AssistantPanel. */
  state?: AssistantStateKind;
  /** Alias that maps naturally from the QA response status. */
  status?: AssistantStateKind;
  onRetry?: () => void;
  className?: string;
}

const RESPONSIVE_CLASSES: Record<Breakpoint, string> = {
  mobile: "max-w-full px-2 py-6",
  tablet: "max-w-xl px-4 py-8",
  desktop: "max-w-2xl px-6 py-10",
};

function StateFrame({
  state,
  breakpoint,
  className,
  children,
}: {
  state: AssistantStateKind;
  breakpoint: Breakpoint;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn("mx-auto flex w-full flex-col", RESPONSIVE_CLASSES[breakpoint], className)}
      data-assistant-state={state}
      data-breakpoint={breakpoint}
    >
      {children}
    </div>
  );
}

function IndexingState({
  breakpoint,
  className,
}: Omit<AssistantStatesProps, "state" | "status"> & { breakpoint: Breakpoint }) {
  return (
    <StateFrame state="indexing" breakpoint={breakpoint} className={className}>
      <div
        aria-label="Đang chuẩn bị văn bản"
        className="flex flex-col gap-4 rounded-mg-lg border border-mg-border bg-mg-surface px-5 py-6"
        data-testid="assistant-indexing"
        role="status"
      >
        <div className="flex flex-col gap-2" aria-hidden="true">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </div>
        <div>
          <p className="font-medium text-mg-text">Văn bản đang được chuẩn bị</p>
          <p className="mt-1 text-sm leading-relaxed text-mg-text-muted">
            Mẹ đợi một chút nhé. Khi chuẩn bị xong, mẹ có thể hỏi Trợ lý về văn bản này.
          </p>
        </div>
      </div>
    </StateFrame>
  );
}

function EmptyAssistantState({
  breakpoint,
  className,
}: Omit<AssistantStatesProps, "state" | "status"> & { breakpoint: Breakpoint }) {
  return (
    <StateFrame state="empty" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-empty">
        <EmptyState
          title="Chào mẹ, hôm nay mẹ cần tìm gì?"
          description="Mẹ hãy đặt một câu hỏi về văn bản đang mở. Trợ lý sẽ tìm thông tin trong chính văn bản đó."
        />
      </div>
    </StateFrame>
  );
}

function WorkerUnavailableState({
  breakpoint,
  className,
  onRetry,
}: Omit<AssistantStatesProps, "state" | "status"> & { breakpoint: Breakpoint }) {
  return (
    <StateFrame state="ai_worker_unavailable" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-ai-worker-unavailable">
        <ErrorState
          message="Văn bản của mẹ vẫn còn nguyên. Trợ lý đang tạm thời không kết nối được nên chưa thể trả lời. Mẹ thử lại sau nhé."
          onRetry={onRetry}
        />
      </div>
    </StateFrame>
  );
}

function InsufficientEvidenceState({
  breakpoint,
  className,
}: Omit<AssistantStatesProps, "state" | "status"> & { breakpoint: Breakpoint }) {
  return (
    <StateFrame state="insufficient_evidence" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-insufficient-evidence">
        <EmptyState
          title="Chưa tìm thấy câu trả lời trong văn bản này"
          description="Mẹ có thể thử hỏi theo cách khác hoặc xem lại văn bản gốc. Điều này không có nghĩa câu trả lời không tồn tại ở nơi khác."
        />
      </div>
    </StateFrame>
  );
}

function FailedState({
  breakpoint,
  className,
  onRetry,
}: Omit<AssistantStatesProps, "state" | "status"> & { breakpoint: Breakpoint }) {
  return (
    <StateFrame state="failed" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-failed">
        <ErrorState
          message="Trợ lý chưa thể hoàn thành câu trả lời lúc này. Văn bản của mẹ vẫn được giữ nguyên. Mẹ thử lại nhé."
          onRetry={onRetry}
        />
      </div>
    </StateFrame>
  );
}

/**
 * Responsive, plain-language states for the assistant thread.
 *
 * Each visual is deliberately delegated to a shared common state component:
 * EmptyState for intentional no-result views, ErrorState for retryable failures,
 * and Skeleton for the non-error indexing wait state.
 */
export function AssistantStates({ state, status, onRetry, className }: AssistantStatesProps) {
  const breakpoint = useBreakpoint();
  const resolvedState = state ?? status ?? "empty";

  switch (resolvedState) {
    case "indexing":
      return <IndexingState breakpoint={breakpoint} className={className} onRetry={onRetry} />;
    case "ai_worker_unavailable":
      return (
        <WorkerUnavailableState breakpoint={breakpoint} className={className} onRetry={onRetry} />
      );
    case "insufficient_evidence":
      return (
        <InsufficientEvidenceState
          breakpoint={breakpoint}
          className={className}
          onRetry={onRetry}
        />
      );
    case "failed":
      return <FailedState breakpoint={breakpoint} className={className} onRetry={onRetry} />;
    case "empty":
      return (
        <EmptyAssistantState breakpoint={breakpoint} className={className} onRetry={onRetry} />
      );
  }
}
