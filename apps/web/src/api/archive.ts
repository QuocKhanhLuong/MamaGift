import { apiRequest } from "./client";
import type { QaCitation } from "./types";

export interface ArchiveFilterInput {
  document_ids?: string[] | null;
  document_types?: string[] | null;
  document_numbers?: string[] | null;
  issuers?: string[] | null;
  issued_date_from?: string | null; // ISO date
  issued_date_to?: string | null;
  include_requires_review?: boolean;
}

export interface ArchiveDocumentGroup {
  document_id: string;
  document_number: string | null;
  title: string | null;
  document_type: string | null;
  issuer: string | null;
  issued_date: string | null;
  document_version: number;
  parse_run_id: string;
  citation_ids: string[];
}

export interface ArchiveRelationRef {
  relation_type: string;
  review_state: string;
  confidence: number;
  source_document_id: string;
  target_document_id: string | null;
  target_document_number: string | null;
  citation_ids: string[];
}

export type ArchiveQaStatus =
  "answered" | "insufficient_evidence" | "ai_worker_unavailable" | "failed";

export interface ArchiveQaResponse {
  answer: string;
  status: ArchiveQaStatus;
  citations: QaCitation[];
  document_groups: ArchiveDocumentGroup[];
  relations: ArchiveRelationRef[];
  freshness_caveat: string | null;
  retrieval: { query_id: string };
  model: { provider: string; model: string; version: string };
}

export interface ArchiveQaRequest {
  question: string;
  filters?: ArchiveFilterInput;
}

/**
 * Ask a grounded question across the institutional archive.
 * POST /api/v1/archive/qa
 */
export function askArchiveQuestion(
  input: ArchiveQaRequest,
  signal?: AbortSignal,
): Promise<ArchiveQaResponse> {
  return apiRequest<ArchiveQaResponse>("/api/v1/archive/qa", {
    method: "POST",
    body: input,
    signal,
  });
}
