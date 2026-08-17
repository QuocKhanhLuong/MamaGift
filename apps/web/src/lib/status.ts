import type { DocumentStatus } from "../api/types";

/**
 * Plain-Vietnamese status vocabulary
 * (`docs/design/01_INFORMATION_ARCHITECTURE.md` section 6,
 * `docs/design/02_DOCUMENT_FLOW.md` section 6 status mapping).
 * Internal provider/technical terms must never reach the user.
 */
export const DOCUMENT_STATUS_LABEL: Record<DocumentStatus, string> = {
  UPLOADED: "Đã nhận văn bản",
  INSPECTING: "Đang kiểm tra văn bản",
  QUEUED_FOR_PARSE: "Đang chờ xử lý",
  PARSING: "Đang đọc văn bản",
  NORMALIZING: "Đang đọc văn bản",
  STRUCTURING: "Đang đọc văn bản",
  READY_FOR_REVIEW: "Cần kiểm tra",
  INDEXING: "Đang chuẩn bị tìm kiếm",
  READY: "Sẵn sàng",
  PARSE_FAILED: "Không đọc được văn bản",
  UNSUPPORTED: "Định dạng chưa được hỗ trợ",
};

export const TERMINAL_STATUSES: ReadonlySet<DocumentStatus> = new Set([
  "READY",
  "READY_FOR_REVIEW",
  "PARSE_FAILED",
  "UNSUPPORTED",
]);

export const PROCESSING_STATUSES: ReadonlySet<DocumentStatus> = new Set([
  "UPLOADED",
  "INSPECTING",
  "QUEUED_FOR_PARSE",
  "PARSING",
  "NORMALIZING",
  "STRUCTURING",
  "INDEXING",
]);

export function isOpenableDocument(status: DocumentStatus): boolean {
  return status === "READY" || status === "READY_FOR_REVIEW";
}

export function isRetryableDocument(status: DocumentStatus): boolean {
  return status === "PARSE_FAILED";
}

export const REVIEW_STATUS_LABEL: Record<string, string> = {
  unreviewed: "",
  needs_review: "Cần kiểm tra",
  confirmed: "Đã xác nhận",
  corrected: "Đã sửa",
  rejected: "Đã từ chối",
};

export const FIELD_NAME_LABEL: Record<string, string> = {
  document_number: "Số văn bản",
  document_type: "Loại văn bản",
  issuer: "Cơ quan ban hành",
  issue_date: "Ngày ban hành",
  title: "Trích yếu",
  signer: "Người ký",
  deadline: "Hạn hoàn thành",
};

export function fieldLabel(name: string): string {
  return FIELD_NAME_LABEL[name] ?? name;
}

/** Low confidence is the same visible threshold `docs/10_DESIGN_SYSTEM.md` section 12 implies by example. */
export const LOW_CONFIDENCE_THRESHOLD = 0.75;

export function isLowConfidence(confidence: number | null): boolean {
  return confidence !== null && confidence < LOW_CONFIDENCE_THRESHOLD;
}

export type StatusTone = "neutral" | "progress" | "success" | "warning" | "danger";

export function documentStatusTone(status: DocumentStatus): StatusTone {
  if (status === "READY") return "success";
  if (status === "READY_FOR_REVIEW") return "warning";
  if (status === "PARSE_FAILED" || status === "UNSUPPORTED") return "danger";
  return "progress";
}

export function formatVietnameseDate(value: string | null): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}

/** Displays ISO dates as dd/mm/yyyy for date-typed fields; other values are shown as-is. */
export function formatFieldValue(value: string | null, valueType: string): string | null {
  if (value === null) return null;
  return valueType === "date" ? (formatVietnameseDate(value) ?? value) : value;
}
