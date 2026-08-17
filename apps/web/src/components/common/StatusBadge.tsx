import { AlertTriangle, CheckCircle2, Clock, XCircle } from "lucide-react";

import { cn } from "../../lib/cn";

export type StatusTone = "neutral" | "progress" | "success" | "warning" | "danger";

const TONE_STYLES: Record<StatusTone, string> = {
  neutral: "bg-mg-surface-2 text-mg-text-muted",
  progress: "bg-mg-accent-soft text-mg-accent",
  success: "bg-mg-success/15 text-mg-success",
  warning: "bg-mg-warning/15 text-mg-warning",
  danger: "bg-mg-danger/15 text-mg-danger",
};

const TONE_ICON: Record<StatusTone, typeof Clock> = {
  neutral: Clock,
  progress: Clock,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
};

/** Status is never color-only: an icon and text label always ship together (docs/10 section 15). */
export function StatusBadge({ tone, label }: { tone: StatusTone; label: string }) {
  const Icon = TONE_ICON[tone];
  return (
    <span
      role="status"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-medium",
        TONE_STYLES[tone],
      )}
    >
      <Icon aria-hidden="true" size={14} />
      {label}
    </span>
  );
}
