import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-mg-lg border border-dashed border-mg-border bg-mg-surface px-6 py-12 text-center">
      <p className="text-lg font-medium text-mg-text">{title}</p>
      {description ? <p className="max-w-sm text-sm text-mg-text-muted">{description}</p> : null}
      {action}
    </div>
  );
}
