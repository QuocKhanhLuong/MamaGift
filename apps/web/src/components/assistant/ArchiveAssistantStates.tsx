import type { ReactNode } from "react";

import { useBreakpoint, type Breakpoint } from "../../hooks/useBreakpoint";
import { cn } from "../../lib/cn";
import { EmptyState } from "../common/EmptyState";
import { ErrorState } from "../common/ErrorState";
import { Skeleton } from "../common/Skeleton";

export type ArchiveAssistantStateKind =
  | "empty"
  | "indexing"
  | "archive_not_indexed"
  | "ai_worker_unavailable"
  | "insufficient_evidence"
  | "failed"
  | "offline"
  | "error";

export interface ArchiveAssistantStatesProps {
  state?: ArchiveAssistantStateKind;
  status?: ArchiveAssistantStateKind;
  errorMessage?: string;
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
  state: ArchiveAssistantStateKind;
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

function EmptyArchiveState({
  breakpoint,
  className,
}: {
  breakpoint: Breakpoint;
  className?: string;
}) {
  return (
    <StateFrame state="empty" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-empty">
        <EmptyState
          title="Chào mẹ, hôm nay mẹ cần tra cứu gì?"
          description="Mẹ hãy đặt một câu hỏi về kho văn bản. Trợ lý sẽ tìm kiếm và tổng hợp thông tin có căn cứ từ các văn bản hiện có."
        />
      </div>
    </StateFrame>
  );
}

function IndexingArchiveState({
  breakpoint,
  className,
}: {
  breakpoint: Breakpoint;
  className?: string;
}) {
  return (
    <StateFrame state="archive_not_indexed" breakpoint={breakpoint} className={className}>
      <div
        aria-label="Kho tài liệu chưa sẵn sàng"
        className="flex flex-col gap-4 rounded-mg-lg border border-mg-border bg-mg-surface px-5 py-6"
        data-testid="assistant-archive-not-indexed"
        role="status"
      >
        <div className="flex flex-col gap-2" aria-hidden="true">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </div>
        <div>
          <p className="font-medium text-mg-text">Kho tài liệu chưa sẵn sàng để tìm kiếm</p>
          <p className="mt-1 text-sm leading-relaxed text-mg-text-muted">
            Kho tài liệu chưa sẵn sàng để tìm kiếm. Vui lòng thử lại sau.
          </p>
        </div>
      </div>
    </StateFrame>
  );
}

function WorkerUnavailableState({
  breakpoint,
  className,
  onRetry,
}: {
  breakpoint: Breakpoint;
  className?: string;
  onRetry?: () => void;
}) {
  return (
    <StateFrame state="ai_worker_unavailable" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-ai-worker-unavailable">
        <ErrorState
          message="Trợ lý đang tạm thời không hoạt động. Mẹ vẫn có thể tra cứu và xem văn bản gốc trong kho. Mẹ thử lại sau nhé."
          onRetry={onRetry}
        />
      </div>
    </StateFrame>
  );
}

function InsufficientEvidenceState({
  breakpoint,
  className,
}: {
  breakpoint: Breakpoint;
  className?: string;
}) {
  return (
    <StateFrame state="insufficient_evidence" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-insufficient-evidence">
        <EmptyState
          title="Chưa tìm thấy câu trả lời trong kho tài liệu"
          description="Mẹ có thể thử hỏi theo cách khác hoặc bổ sung thêm văn bản vào kho. Điều này không có nghĩa câu trả lời không tồn tại ở nơi khác."
        />
      </div>
    </StateFrame>
  );
}

function OfflineState({
  breakpoint,
  className,
  onRetry,
}: {
  breakpoint: Breakpoint;
  className?: string;
  onRetry?: () => void;
}) {
  return (
    <StateFrame state="offline" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-offline">
        <ErrorState
          message="Không thể kết nối tới Trợ lý. Mẹ vui lòng kiểm tra lại kết nối mạng."
          onRetry={onRetry}
        />
      </div>
    </StateFrame>
  );
}

function FailedState({
  breakpoint,
  className,
  errorMessage,
  onRetry,
}: {
  breakpoint: Breakpoint;
  className?: string;
  errorMessage?: string;
  onRetry?: () => void;
}) {
  return (
    <StateFrame state="failed" breakpoint={breakpoint} className={className}>
      <div data-testid="assistant-failed">
        <ErrorState
          message={
            errorMessage ??
            "Trợ lý chưa thể hoàn thành câu trả lời lúc này. Kho tài liệu của mẹ vẫn an toàn. Mẹ thử lại nhé."
          }
          onRetry={onRetry}
        />
      </div>
    </StateFrame>
  );
}

/**
 * Responsive, plain-Vietnamese states for the archive assistant thread.
 */
export function ArchiveAssistantStates({
  state,
  status,
  errorMessage,
  onRetry,
  className,
}: ArchiveAssistantStatesProps) {
  const breakpoint = useBreakpoint();
  const resolvedState = state ?? status ?? "empty";

  switch (resolvedState) {
    case "indexing":
    case "archive_not_indexed":
      return <IndexingArchiveState breakpoint={breakpoint} className={className} />;
    case "ai_worker_unavailable":
      return (
        <WorkerUnavailableState breakpoint={breakpoint} className={className} onRetry={onRetry} />
      );
    case "insufficient_evidence":
      return <InsufficientEvidenceState breakpoint={breakpoint} className={className} />;
    case "offline":
      return <OfflineState breakpoint={breakpoint} className={className} onRetry={onRetry} />;
    case "failed":
    case "error":
      return (
        <FailedState
          breakpoint={breakpoint}
          className={className}
          errorMessage={errorMessage}
          onRetry={onRetry}
        />
      );
    case "empty":
    default:
      return <EmptyArchiveState breakpoint={breakpoint} className={className} />;
  }
}
