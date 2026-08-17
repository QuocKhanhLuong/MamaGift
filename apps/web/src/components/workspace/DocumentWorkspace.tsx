import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { DetailsPanel } from "./DetailsPanel";
import { DocumentRail } from "./DocumentRail";
import { SourceViewer } from "./SourceViewer";
import { ErrorState } from "../common/ErrorState";
import { Skeleton } from "../common/Skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../ui/Tabs";
import { useBreakpoint } from "../../hooks/useBreakpoint";
import { useCanonical } from "../../hooks/useCanonical";
import type { CanonicalDocument, ExtractedField } from "../../api/types";

/** D-04 — Inspect the document workspace (`docs/design/02_DOCUMENT_FLOW.md`). */
export function DocumentWorkspace({ documentId }: { documentId: string }) {
  const { state, reload } = useCanonical(documentId, true);
  const breakpoint = useBreakpoint();
  const [searchParams, setSearchParams] = useSearchParams();
  const [canonical, setCanonical] = useState<CanonicalDocument | null>(null);
  const [mobileSurface, setMobileSurface] = useState<"van-ban" | "chi-tiet">("van-ban");

  useEffect(() => {
    if (state.kind === "ready") setCanonical(state.canonical);
  }, [state]);

  if (state.kind === "loading" || !canonical) {
    return (
      <div className="flex flex-col gap-3 p-6">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="p-6">
        <ErrorState message={state.message} onRetry={reload} />
      </div>
    );
  }

  const pageNumber = Number(searchParams.get("page") ?? "1");
  const focusedBlockId = searchParams.get("block");
  const currentPage =
    canonical.pages.find((page) => page.page_number === pageNumber) ?? canonical.pages[0] ?? null;

  function goToPage(page: number) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("page", String(page));
      next.delete("block");
      return next;
    });
  }

  function goToSource(field: ExtractedField) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("page", String(field.source_page_numbers[0]));
      next.set("block", field.source_block_ids[0]);
      return next;
    });
    setMobileSurface("van-ban");
  }

  function applyCorrection(fieldId: string, correctedValue: string) {
    setCanonical((previous) => {
      if (!previous) return previous;
      return {
        ...previous,
        extracted_fields: previous.extracted_fields.map((field) =>
          field.id === fieldId
            ? { ...field, corrected_value: correctedValue, review_status: "corrected" }
            : field,
        ),
      };
    });
  }

  const source = (
    <SourceViewer
      documentId={documentId}
      page={currentPage}
      pageCount={canonical.pages.length}
      onPageChange={goToPage}
      focusedBlockId={focusedBlockId}
    />
  );

  const details = (
    <DetailsPanel
      documentId={documentId}
      canonical={canonical}
      onGoToSource={goToSource}
      onCorrected={applyCorrection}
    />
  );

  if (breakpoint === "desktop") {
    return (
      <div className="grid h-full grid-cols-[220px_1fr_380px] divide-x divide-mg-border">
        <DocumentRail activeDocumentId={documentId} />
        <div className="min-w-0">{source}</div>
        <div className="min-w-0">{details}</div>
      </div>
    );
  }

  if (breakpoint === "tablet") {
    return (
      <Tabs defaultValue="nguon" className="flex h-full flex-col">
        <TabsList className="m-2 self-center">
          <TabsTrigger value="nguon">Nguồn</TabsTrigger>
          <TabsTrigger value="chi-tiet">Nội dung đã đọc</TabsTrigger>
        </TabsList>
        <TabsContent value="nguon" className="min-h-0 flex-1">
          {source}
        </TabsContent>
        <TabsContent value="chi-tiet" className="min-h-0 flex-1 overflow-y-auto">
          {details}
        </TabsContent>
      </Tabs>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">{mobileSurface === "van-ban" ? source : details}</div>
      <nav
        aria-label="Chuyển đổi khu vực"
        className="flex shrink-0 border-t border-mg-border bg-mg-surface"
      >
        <button
          type="button"
          onClick={() => setMobileSurface("van-ban")}
          aria-current={mobileSurface === "van-ban"}
          className={`flex min-h-[44px] flex-1 items-center justify-center text-sm font-medium ${
            mobileSurface === "van-ban" ? "text-mg-accent" : "text-mg-text-muted"
          }`}
        >
          Văn bản
        </button>
        <button
          type="button"
          onClick={() => setMobileSurface("chi-tiet")}
          aria-current={mobileSurface === "chi-tiet"}
          className={`flex min-h-[44px] flex-1 items-center justify-center text-sm font-medium ${
            mobileSurface === "chi-tiet" ? "text-mg-accent" : "text-mg-text-muted"
          }`}
        >
          Chi tiết
        </button>
      </nav>
    </div>
  );
}
