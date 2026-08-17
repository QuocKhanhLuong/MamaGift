import { useState } from "react";

import { ArchiveFilters } from "../components/archive/ArchiveFilters";
import { DocumentRow } from "../components/archive/DocumentRow";
import { UploadDrawer } from "../components/archive/UploadDrawer";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorState } from "../components/common/ErrorState";
import { DocumentRowSkeleton } from "../components/common/Skeleton";
import { Button } from "../components/ui/Button";
import { useDocumentList } from "../hooks/useDocumentList";
import type { DocumentListFilters } from "../api/documents";

/** D-01 — Open the archive (`docs/design/02_DOCUMENT_FLOW.md`). */
export function ArchivePage() {
  const [filters, setFilters] = useState<DocumentListFilters>({});
  const { state, reload } = useDocumentList(filters);

  const hasActiveFilters = Boolean(
    filters.query || filters.type || filters.issuer || filters.from || filters.to,
  );

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 p-4 desktop:p-8">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-mg-text desktop:text-[28px]">Văn bản</h1>
        <UploadDrawer onUploaded={reload} />
      </div>

      <ArchiveFilters filters={filters} onChange={setFilters} />

      {state.kind === "loading" && (
        <ul className="flex flex-col gap-3" aria-label="Đang tải danh sách văn bản">
          <li>
            <DocumentRowSkeleton />
          </li>
          <li>
            <DocumentRowSkeleton />
          </li>
          <li>
            <DocumentRowSkeleton />
          </li>
        </ul>
      )}

      {state.kind === "error" && (
        <>
          <ErrorState message={state.message} onRetry={reload} />
          {state.staleItems && state.staleItems.length > 0 ? (
            <>
              <p className="text-sm text-mg-text-muted">Danh sách bên dưới chưa được làm mới.</p>
              <ul className="flex flex-col gap-3">
                {state.staleItems.map((document) => (
                  <DocumentRow key={document.id} document={document} />
                ))}
              </ul>
            </>
          ) : null}
        </>
      )}

      {state.kind === "ready" && state.items.length === 0 && !hasActiveFilters && (
        <EmptyState
          title="Chưa có văn bản nào"
          description="Tải lên một tệp PDF để bắt đầu tìm kiếm và kiểm tra văn bản."
        />
      )}

      {state.kind === "ready" && state.items.length === 0 && hasActiveFilters && (
        <EmptyState
          title="Không tìm thấy văn bản phù hợp"
          action={
            <Button variant="secondary" size="sm" onClick={() => setFilters({})}>
              Xóa bộ lọc
            </Button>
          }
        />
      )}

      {state.kind === "ready" && state.items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {state.items.map((document) => (
            <DocumentRow key={document.id} document={document} />
          ))}
        </ul>
      )}
    </div>
  );
}
