import { Link } from "react-router-dom";

import { Input } from "../ui/Input";
import { DOCUMENT_STATUS_LABEL } from "../../lib/status";
import { useDocumentList } from "../../hooks/useDocumentList";
import { cn } from "../../lib/cn";

/** The document-scoped rail: search plus recent documents (`docs/10_DESIGN_SYSTEM.md` section 9). */
export function DocumentRail({ activeDocumentId }: { activeDocumentId: string }) {
  const { state } = useDocumentList({ limit: 20 });

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <Link to="/van-ban" className="text-sm font-medium text-mg-accent">
        ← Văn bản
      </Link>
      <Input aria-label="Tìm văn bản" placeholder="Tìm kiếm..." disabled className="opacity-70" />
      {state.kind === "ready" ? (
        <ul className="flex flex-col gap-1 overflow-y-auto">
          {state.items.map((document) => {
            const active = document.id === activeDocumentId;
            return (
              <li key={document.id}>
                <Link
                  to={`/van-ban/${document.id}`}
                  className={cn(
                    "flex min-h-[44px] flex-col justify-center rounded-mg-sm px-2 py-1.5 text-sm",
                    active
                      ? "bg-mg-accent-soft text-mg-accent"
                      : "text-mg-text hover:bg-mg-surface-2",
                  )}
                >
                  <span className="truncate font-medium">
                    {document.document_number ?? document.title ?? document.filename}
                  </span>
                  <span className="truncate text-xs text-mg-text-muted">
                    {DOCUMENT_STATUS_LABEL[document.status]}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
