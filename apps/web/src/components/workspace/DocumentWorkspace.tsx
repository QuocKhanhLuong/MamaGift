import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { AssistantPanel } from "../assistant/AssistantPanel";
import { DetailsPanel } from "./DetailsPanel";
import { DocumentRail } from "./DocumentRail";
import { SourceViewer } from "./SourceViewer";
import { ErrorState } from "../common/ErrorState";
import { Skeleton } from "../common/Skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../ui/Tabs";
import { useBreakpoint } from "../../hooks/useBreakpoint";
import { useCanonical } from "../../hooks/useCanonical";
import type { CanonicalDocument, DocumentSummary, ExtractedField } from "../../api/types";

export interface DocumentWorkspaceProps {
  documentId: string;
  document?: DocumentSummary | null;
}

/** D-04 — Inspect the document workspace (`docs/design/02_DOCUMENT_FLOW.md`). */
export function DocumentWorkspace({ documentId, document }: DocumentWorkspaceProps) {
  const { state, reload } = useCanonical(documentId, true);
  const breakpoint = useBreakpoint();
  const [searchParams, setSearchParams] = useSearchParams();
  const [canonical, setCanonical] = useState<CanonicalDocument | null>(null);
  const [mobileSurface, setMobileSurface] = useState<"van-ban" | "tro-ly" | "chi-tiet">("van-ban");
  const [tabletTab, setTabletTab] = useState<string>("nguon");

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

  const isReady = document ? document.status === "READY" : true;

  const pageNumber = Number(searchParams.get("page") ?? "1");
  const focusedBlockId = searchParams.get("block");
  const focusedBlocksParam = searchParams.get("blocks");
  const focusedBlockIds = focusedBlocksParam
    ? focusedBlocksParam.split(",").filter(Boolean)
    : focusedBlockId
      ? [focusedBlockId]
      : undefined;

  const currentPage =
    canonical.pages.find((page) => page.page_number === pageNumber) ?? canonical.pages[0] ?? null;

  function goToPage(page: number) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("page", String(page));
      next.delete("block");
      next.delete("blocks");
      return next;
    });
  }

  function goToSource(field: ExtractedField) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("page", String(field.source_page_numbers[0]));
      next.set("block", field.source_block_ids[0]);
      next.delete("blocks");
      return next;
    });
    setMobileSurface("van-ban");
    setTabletTab("nguon");
  }

  function handleCitationNavigate(page: number, blockIds: string[]) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("page", String(page));
      if (blockIds.length > 0) {
        next.set("block", blockIds[0]);
        next.set("blocks", blockIds.join(","));
      } else {
        next.delete("block");
        next.delete("blocks");
      }
      return next;
    });
    setMobileSurface("van-ban");
    setTabletTab("nguon");
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

  const documentSummary: DocumentSummary = document ?? {
    id: documentId,
    filename: canonical.document_id,
    checksum_sha256: "",
    byte_size: 0,
    status: "READY",
    document_type: null,
    document_number: null,
    title: null,
    issuer: null,
    issued_date: null,
    signer: null,
    deadline: null,
    requires_user_review: false,
    current_parse_run_id: canonical.parser_run.id,
    error_code: null,
    created_at: canonical.parser_run.started_at,
    updated_at: canonical.parser_run.finished_at,
  };

  const source = (
    <SourceViewer
      documentId={documentId}
      page={currentPage}
      pageCount={canonical.pages.length}
      onPageChange={goToPage}
      focusedBlockId={focusedBlockId}
      focusedBlockIds={focusedBlockIds}
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

  const assistant = (
    <AssistantPanel
      document={documentSummary}
      sourcePages={canonical.pages}
      onCitationNavigate={handleCitationNavigate}
    />
  );

  if (breakpoint === "desktop") {
    return (
      <div className="grid h-full grid-cols-[220px_1fr_380px] divide-x divide-mg-border">
        <DocumentRail activeDocumentId={documentId} />
        <div className="min-w-0">{source}</div>
        <div className="min-w-0">
          {isReady ? (
            <Tabs defaultValue="chi-tiet" className="flex h-full flex-col">
              <TabsList className="m-2 self-center">
                <TabsTrigger value="tro-ly">Trợ lý</TabsTrigger>
                <TabsTrigger value="chi-tiet">Chi tiết</TabsTrigger>
              </TabsList>
              <TabsContent value="tro-ly" className="min-h-0 flex-1">
                {assistant}
              </TabsContent>
              <TabsContent value="chi-tiet" className="min-h-0 flex-1 overflow-y-auto">
                {details}
              </TabsContent>
            </Tabs>
          ) : (
            details
          )}
        </div>
      </div>
    );
  }

  if (breakpoint === "tablet") {
    return (
      <Tabs value={tabletTab} onValueChange={setTabletTab} className="flex h-full flex-col">
        <TabsList className="m-2 self-center">
          <TabsTrigger value="nguon">Nguồn</TabsTrigger>
          {isReady ? <TabsTrigger value="tro-ly">Trợ lý</TabsTrigger> : null}
          <TabsTrigger value="chi-tiet">Nội dung đã đọc</TabsTrigger>
        </TabsList>
        <TabsContent value="nguon" className="min-h-0 flex-1">
          {source}
        </TabsContent>
        {isReady ? (
          <TabsContent value="tro-ly" className="min-h-0 flex-1">
            {assistant}
          </TabsContent>
        ) : null}
        <TabsContent value="chi-tiet" className="min-h-0 flex-1 overflow-y-auto">
          {details}
        </TabsContent>
      </Tabs>
    );
  }

  const currentMobileContent = () => {
    if (mobileSurface === "van-ban") return source;
    if (mobileSurface === "tro-ly" && isReady) return assistant;
    return details;
  };

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">{currentMobileContent()}</div>
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
        {isReady ? (
          <button
            type="button"
            onClick={() => setMobileSurface("tro-ly")}
            aria-current={mobileSurface === "tro-ly"}
            className={`flex min-h-[44px] flex-1 items-center justify-center text-sm font-medium ${
              mobileSurface === "tro-ly" ? "text-mg-accent" : "text-mg-text-muted"
            }`}
          >
            Trợ lý
          </button>
        ) : null}
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
