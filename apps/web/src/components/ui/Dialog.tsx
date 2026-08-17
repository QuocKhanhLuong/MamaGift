import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;

interface DialogContentProps {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}

/**
 * A responsive overlay: full-screen/bottom sheet on mobile, a centered 420–520px
 * drawer on desktop (`docs/design/02_DOCUMENT_FLOW.md` D-02, `docs/design/04_RESPONSIVE_STATES.md` R-02).
 */
export function DialogContent({ title, description, children, className }: DialogContentProps) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-40 bg-mg-text/30" />
      <RadixDialog.Content
        aria-describedby={description ? "dialog-description" : undefined}
        className={cn(
          "fixed z-50 flex flex-col bg-mg-surface shadow-xl focus:outline-none",
          "inset-x-0 bottom-0 max-h-[92vh] rounded-t-mg-xl p-5",
          "sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-1/2 sm:max-h-[85vh] sm:w-[min(92vw,480px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-mg-lg",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <RadixDialog.Title className="text-xl font-semibold text-mg-text">
            {title}
          </RadixDialog.Title>
          <RadixDialog.Close
            aria-label="Đóng"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-mg-sm text-mg-text-muted hover:bg-mg-surface-2"
          >
            <X aria-hidden="true" size={20} />
          </RadixDialog.Close>
        </div>
        {description ? (
          <p id="dialog-description" className="mt-1 text-sm text-mg-text-muted">
            {description}
          </p>
        ) : null}
        <div className="mt-4 overflow-y-auto">{children}</div>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}
