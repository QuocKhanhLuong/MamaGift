import { AlertTriangle } from "lucide-react";

import { Button } from "../ui/Button";

export function ErrorState({
  message,
  onRetry,
  retryLabel = "Thử lại",
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-mg-lg border border-mg-danger/30 bg-mg-danger/5 px-6 py-8 text-center"
    >
      <AlertTriangle aria-hidden="true" className="text-mg-danger" size={22} />
      <p className="text-mg-text">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}
