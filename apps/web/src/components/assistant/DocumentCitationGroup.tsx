import { FileText } from "lucide-react";

import type { ArchiveDocumentGroup } from "../../api/archive";
import type { QaCitation } from "../../api/types";
import { Button } from "../ui/Button";
import { formatVietnameseDate } from "../../lib/status";
import { cn } from "../../lib/cn";

export interface DocumentCitationGroupProps {
  group: ArchiveDocumentGroup;
  citations: readonly QaCitation[];
  onCitationNavigate?: (
    documentId: string,
    page: number,
    blockIds: string[],
    citation: QaCitation,
  ) => void;
  className?: string;
}

export function DocumentCitationGroup({
  group,
  citations,
  onCitationNavigate,
  className,
}: DocumentCitationGroupProps) {
  const citationMap = new Map(citations.map((c) => [c.citation_id, c]));
  const matchingCitations = group.citation_ids
    .map((id) => citationMap.get(id))
    .filter((c): c is QaCitation => Boolean(c));

  const docNumber = group.document_number;
  const docTitle = group.title;
  const docDisplayName = docNumber ?? docTitle ?? group.document_id;
  const formattedDate = formatVietnameseDate(group.issued_date);

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-mg-lg border border-mg-border bg-mg-surface p-4 transition-colors",
        className,
      )}
      data-testid={`document-group-${group.document_id}`}
      data-document-id={group.document_id}
    >
      <div className="flex items-start gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-mg-md bg-mg-accent-soft text-mg-accent mt-0.5">
          <FileText aria-hidden="true" size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            {docNumber ? (
              <span className="font-semibold text-mg-text text-[15px]" data-testid="doc-number">
                {docNumber}
              </span>
            ) : null}
            {docTitle && docTitle !== docNumber ? (
              <span
                className="text-sm text-mg-text-muted line-clamp-1"
                title={docTitle}
                data-testid="doc-title"
              >
                {docTitle}
              </span>
            ) : !docNumber ? (
              <span className="font-semibold text-mg-text text-[15px]">{group.document_id}</span>
            ) : null}
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-mg-text-muted">
            {group.document_type ? (
              <span className="rounded bg-mg-surface-2 px-1.5 py-0.5 font-medium text-mg-text">
                {group.document_type}
              </span>
            ) : null}
            {group.issuer ? <span>{group.issuer}</span> : null}
            {group.issuer && formattedDate ? <span aria-hidden="true">·</span> : null}
            {formattedDate ? <span>{formattedDate}</span> : null}
          </div>
        </div>
      </div>

      {matchingCitations.length > 0 ? (
        <div
          className="flex flex-wrap items-center gap-2 pt-1 border-t border-mg-border/50"
          aria-label={`Trích dẫn từ ${docDisplayName}`}
        >
          {matchingCitations.map((citation) => {
            const accessibleName = `Văn bản ${docDisplayName} · Trang ${citation.page_number}`;
            return (
              <Button
                key={citation.citation_id}
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 max-w-full truncate px-3 text-xs"
                aria-label={accessibleName}
                title={citation.quote ?? undefined}
                data-testid={`citation-chip-${citation.citation_id}`}
                data-citation-id={citation.citation_id}
                onClick={() =>
                  onCitationNavigate?.(
                    group.document_id,
                    citation.page_number,
                    citation.block_ids,
                    citation,
                  )
                }
              >
                <span>Trang {citation.page_number}</span>
                {citation.quote ? (
                  <span className="hidden sm:inline max-w-[160px] truncate text-mg-text-muted">
                    · {citation.quote}
                  </span>
                ) : null}
              </Button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
