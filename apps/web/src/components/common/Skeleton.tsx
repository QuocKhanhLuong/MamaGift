import { cn } from "../../lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-mg-sm bg-mg-border/60", className)}
    />
  );
}

export function DocumentRowSkeleton() {
  return (
    <div className="flex flex-col gap-2 rounded-mg-lg border border-mg-border bg-mg-surface p-4">
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-4 w-1/3" />
    </div>
  );
}
