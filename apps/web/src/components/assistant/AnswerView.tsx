import type { CanonicalPage, QaCitation, QaResponse } from "../../api/types";
import { cn } from "../../lib/cn";
import { CitationChip } from "./CitationChip";

export interface AnswerViewProps {
  /** Use `response` when rendering directly from the QA DTO. */
  response?: QaResponse;
  /** These two props also support the AssistantPanel answer slot. */
  answer?: string;
  citations?: readonly QaCitation[];
  sourcePages?: readonly CanonicalPage[];
  onCitationNavigate?: (page: number, blockIds: string[], citation: QaCitation) => void;
  onCitationClick?: (citation: QaCitation) => void;
  className?: string;
}

function markerId(marker: string): string {
  return marker.slice(1, -1).trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Render grounded prose without parsing it as HTML. Citation markers emitted
 * by a model may be `[c1]`, `(c1)`, or `【c1】`; citations not mentioned in the
 * prose are rendered in the source row below so none silently disappear.
 */
export function AnswerView({
  response,
  answer,
  citations,
  sourcePages,
  onCitationNavigate,
  onCitationClick,
  className,
}: AnswerViewProps) {
  const text = response?.answer ?? answer ?? "";
  const responseCitations = response?.citations ?? citations ?? [];
  const citationById = new Map(
    responseCitations.map((citation) => [citation.citation_id, citation]),
  );
  const renderedCitationIds = new Set<string>();
  const citationMarkers = responseCitations.map((citation) => escapeRegExp(citation.citation_id));
  const markerPattern = citationMarkers.length
    ? new RegExp(
        `(\\[(?:${citationMarkers.join("|")})\\]|【(?:${citationMarkers.join("|")})】|\\((?:${citationMarkers.join("|")})\\))`,
        "g",
      )
    : null;
  const parts = markerPattern ? text.split(markerPattern) : [text];

  function renderCitation(citation: QaCitation) {
    renderedCitationIds.add(citation.citation_id);
    return (
      <CitationChip
        key={`inline-${citation.citation_id}-${renderedCitationIds.size}`}
        citation={citation}
        onCitationClick={onCitationClick}
        onNavigate={
          onCitationNavigate
            ? (page, blockIds) => onCitationNavigate(page, blockIds, citation)
            : undefined
        }
        sourcePages={sourcePages}
      />
    );
  }

  const prose = parts.map((part, index) => {
    const citation = citationById.get(markerId(part));
    if (!citation) {
      // React text nodes escape hostile document/model text by construction.
      return <span key={`text-${index}`}>{part}</span>;
    }
    return (
      <span key={`marker-${index}`} className="inline-flex align-baseline">
        {renderCitation(citation)}
      </span>
    );
  });

  const unmentionedCitations = responseCitations.filter(
    (citation) => !renderedCitationIds.has(citation.citation_id),
  );

  return (
    <div
      className={cn(
        "flex flex-col gap-3 whitespace-pre-wrap text-[16px] leading-relaxed text-mg-text",
        className,
      )}
      data-answer-view
    >
      <div data-answer-text>{prose}</div>
      {unmentionedCitations.length > 0 ? (
        <div aria-label="Nguồn tham khảo" className="flex flex-wrap items-center gap-2">
          {unmentionedCitations.map((citation) => (
            <CitationChip
              key={citation.citation_id}
              citation={citation}
              onCitationClick={onCitationClick}
              onNavigate={
                onCitationNavigate
                  ? (page, blockIds) => onCitationNavigate(page, blockIds, citation)
                  : undefined
              }
              sourcePages={sourcePages}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
