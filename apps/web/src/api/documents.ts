import { apiRequest, API_BASE_URL } from "./client";
import type {
  CanonicalResponse,
  DocumentDetailResponse,
  DocumentListResponse,
  DocumentStatus,
  DocumentStatusResponse,
  FeedbackResponse,
  QaResponse,
  ReprocessResponse,
  UploadResponse,
} from "./types";

export interface DocumentListFilters {
  query?: string;
  type?: string;
  issuer?: string;
  from?: string;
  to?: string;
  status?: DocumentStatus;
  limit?: number;
  offset?: number;
}

function buildQuery(filters: DocumentListFilters): string {
  const params = new URLSearchParams();
  if (filters.query) params.set("query", filters.query);
  if (filters.type) params.set("type", filters.type);
  if (filters.issuer) params.set("issuer", filters.issuer);
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.status) params.set("status", filters.status);
  params.set("limit", String(filters.limit ?? 20));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

export function listDocuments(
  filters: DocumentListFilters = {},
  signal?: AbortSignal,
): Promise<DocumentListResponse> {
  return apiRequest<DocumentListResponse>(`/api/v1/documents?${buildQuery(filters)}`, { signal });
}

export function getDocument(
  documentId: string,
  signal?: AbortSignal,
): Promise<DocumentDetailResponse> {
  return apiRequest<DocumentDetailResponse>(`/api/v1/documents/${documentId}`, { signal });
}

export function getDocumentStatus(
  documentId: string,
  signal?: AbortSignal,
): Promise<DocumentStatusResponse> {
  return apiRequest<DocumentStatusResponse>(`/api/v1/documents/${documentId}/status`, { signal });
}

export function getCanonical(
  documentId: string,
  version?: number,
  signal?: AbortSignal,
): Promise<CanonicalResponse> {
  const suffix = version ? `?version=${version}` : "";
  return apiRequest<CanonicalResponse>(`/api/v1/documents/${documentId}/canonical${suffix}`, {
    signal,
  });
}

export function getOriginalFileUrl(documentId: string): string {
  return `${API_BASE_URL}/api/v1/documents/${documentId}/file`;
}

export function getPagePreviewUrl(documentId: string, page: number): string {
  return `${API_BASE_URL}/api/v1/documents/${documentId}/pages/${page}/preview`;
}

export function uploadDocument(file: File, signal?: AbortSignal): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<UploadResponse>("/api/v1/documents", {
    method: "POST",
    body: formData,
    signal,
  });
}

export function reprocessDocument(documentId: string): Promise<ReprocessResponse> {
  return apiRequest<ReprocessResponse>(`/api/v1/documents/${documentId}/reprocess`, {
    method: "POST",
  });
}

export interface SubmitFeedbackInput {
  feedback_type: "critical_field_correction" | "general_comment";
  field_id?: string;
  corrected_value?: string;
  comment?: string;
}

export function submitFeedback(
  documentId: string,
  input: SubmitFeedbackInput,
): Promise<FeedbackResponse> {
  return apiRequest<FeedbackResponse>(`/api/v1/documents/${documentId}/feedback`, {
    method: "POST",
    body: input,
  });
}

export interface QaRequest {
  question: string;
}

/** Ask a grounded question about this document only. */
export function askDocumentQuestion(
  documentId: string,
  input: QaRequest,
  signal?: AbortSignal,
): Promise<QaResponse> {
  return apiRequest<QaResponse>(`/api/v1/documents/${documentId}/qa`, {
    method: "POST",
    body: input,
    signal,
  });
}
