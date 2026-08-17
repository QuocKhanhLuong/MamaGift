import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Button } from "../ui/Button";
import { getPagePreviewUrl } from "../../api/documents";
import type { CanonicalBlock, CanonicalPage } from "../../api/types";

function PreviewImage({
  documentId,
  page,
  focusedBlock,
}: {
  documentId: string;
  page: CanonicalPage;
  focusedBlock: CanonicalBlock | undefined;
}) {
  const [imageState, setImageState] = useState<"loading" | "ready" | "error">("loading");

  if (imageState === "error") {
    return (
      <p role="alert" className="mt-8 text-mg-danger">
        Không thể mở trang này.
      </p>
    );
  }

  return (
    <div className="relative inline-block shadow-sm" style={{ width: "min(100%, 720px)" }}>
      <img
        key={`${documentId}-${page.page_number}`}
        src={getPagePreviewUrl(documentId, page.page_number)}
        alt={`Trang ${page.page_number} của bản gốc`}
        className="block w-full"
        onLoad={() => setImageState("ready")}
        onError={() => setImageState("error")}
      />
      {focusedBlock?.bbox ? (
        <span
          aria-hidden="true"
          className="absolute rounded-mg-sm border-2 border-mg-accent bg-mg-accent-soft/50"
          style={{
            left: `${(focusedBlock.bbox.x0 / page.width) * 100}%`,
            top: `${(focusedBlock.bbox.y0 / page.height) * 100}%`,
            width: `${((focusedBlock.bbox.x1 - focusedBlock.bbox.x0) / page.width) * 100}%`,
            height: `${((focusedBlock.bbox.y1 - focusedBlock.bbox.y0) / page.height) * 100}%`,
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * D-04 source pane. The highlighted block is positioned as a percentage of the page's
 * point-space dimensions, so it stays correct regardless of the served PNG's actual
 * pixel size (`docs/10_DESIGN_SYSTEM.md` section 10).
 */
export function SourceViewer({
  documentId,
  page,
  pageCount,
  onPageChange,
  focusedBlockId,
}: {
  documentId: string;
  page: CanonicalPage | null;
  pageCount: number;
  onPageChange: (page: number) => void;
  focusedBlockId: string | null;
}) {
  if (!page) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-mg-text-muted">
        Đang mở bản gốc…
      </div>
    );
  }

  const focusedBlock: CanonicalBlock | undefined = focusedBlockId
    ? page.blocks.find((block) => block.id === focusedBlockId)
    : undefined;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-center gap-3 border-b border-mg-border p-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Trang trước"
          disabled={page.page_number <= 1}
          onClick={() => onPageChange(page.page_number - 1)}
        >
          <ChevronLeft aria-hidden="true" size={18} />
        </Button>
        <span className="text-sm text-mg-text-muted" aria-live="polite">
          Trang {page.page_number} / {pageCount}
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Trang sau"
          disabled={page.page_number >= pageCount}
          onClick={() => onPageChange(page.page_number + 1)}
        >
          <ChevronRight aria-hidden="true" size={18} />
        </Button>
      </div>

      <div className="flex flex-1 items-start justify-center overflow-auto bg-mg-surface-2 p-4">
        <PreviewImage
          key={`${documentId}-${page.page_number}`}
          documentId={documentId}
          page={page}
          focusedBlock={focusedBlock}
        />
      </div>

      {focusedBlock ? (
        <p className="sr-only" role="status">
          Đang xem đoạn nội dung được trích dẫn ở trang {focusedBlock.provenance.page_number}.
        </p>
      ) : null}
    </div>
  );
}
