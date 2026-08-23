import type { CanonicalPage, QaCitation } from "../../api/types";
import { Button } from "../ui/Button";

export interface CitationChipProps {
  citation: QaCitation;
  /** Called with the exact page and every source block in the citation. */
  onNavigate?: (page: number, blockIds: string[]) => void;
  /** Optional hook for keeping the answer/thread focus when opening a source. */
  onCitationClick?: (citation: QaCitation) => void;
  /** When supplied, the citation is checked against the canonical source before activation. */
  sourcePages?: readonly CanonicalPage[];
  /** Allows a parent source resolver to report a failed lookup explicitly. */
  resolvable?: boolean;
}

/**
 * Check the complete citation target, not just its page. A page without all of
 * the cited blocks cannot support a verifiable source jump.
 */
function isCitationResolvable(
  citation: QaCitation,
  sourcePages?: readonly CanonicalPage[],
): boolean {
  if (citation.page_number < 1 || citation.block_ids.length === 0) return false;
  if (!sourcePages) return true;

  const page = sourcePages.find((candidate) => candidate.page_number === citation.page_number);
  if (!page) return false;

  return citation.block_ids.every((blockId) => {
    const block = page.blocks.find((candidate) => candidate.id === blockId);
    return block?.provenance.page_number === page.page_number;
  });
}

function defaultSourceHref(citation: QaCitation): string {
  const params = new URLSearchParams({
    page: String(citation.page_number),
    block: citation.block_ids[0] ?? "",
  });
  return `?${params.toString()}`;
}

/** A compact, touch-friendly source action for grounded answers. */
export function CitationChip({
  citation,
  onNavigate,
  onCitationClick,
  sourcePages,
  resolvable,
}: CitationChipProps) {
  const canNavigate = resolvable ?? isCitationResolvable(citation, sourcePages);
  const pageLabel = citation.page_number > 0 ? `Trang ${citation.page_number}` : "Không rõ trang";

  function navigate() {
    if (!canNavigate) return;
    onNavigate?.(citation.page_number, citation.block_ids);
    onCitationClick?.(citation);

    // The callback is the normal integration seam. The URL fallback keeps a
    // standalone chip useful in the existing document workspace as well.
    if (!onNavigate && typeof window !== "undefined") {
      window.history.pushState({}, "", defaultSourceHref(citation));
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  }

  if (!canNavigate) {
    return (
      <span
        aria-label={`Không thể định vị nguồn · ${pageLabel}`}
        className="inline-flex min-h-9 items-center rounded-mg-md border border-mg-border bg-mg-surface-2 px-3 text-sm text-mg-text-muted"
        data-citation-id={citation.citation_id}
        data-citation-unresolvable="true"
        data-testid={`citation-chip-${citation.citation_id}`}
        title="Không thể định vị đầy đủ trang hoặc đoạn nguồn này."
      >
        Không thể định vị nguồn · {pageLabel}
      </span>
    );
  }

  return (
    <Button
      aria-label={`Đi tới nguồn · ${pageLabel}`}
      className="max-w-full"
      data-citation-id={citation.citation_id}
      data-testid={`citation-chip-${citation.citation_id}`}
      onClick={navigate}
      size="sm"
      title={citation.quote ?? undefined}
      type="button"
      variant="link"
    >
      <span className="truncate">Nguồn · {pageLabel}</span>
    </Button>
  );
}
