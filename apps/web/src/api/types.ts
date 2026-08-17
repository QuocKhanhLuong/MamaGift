/**
 * DTO shapes mirrored from `docs/08_API_AND_DATA_CONTRACTS.md` and
 * `packages/docpipe/python/mamagift_docpipe/canonical.py`. The frontend must consume
 * these application DTOs, never invent fields the API does not return.
 */

export type DocumentStatus =
  | "UPLOADED"
  | "INSPECTING"
  | "QUEUED_FOR_PARSE"
  | "PARSING"
  | "NORMALIZING"
  | "STRUCTURING"
  | "READY_FOR_REVIEW"
  | "INDEXING"
  | "READY"
  | "PARSE_FAILED"
  | "UNSUPPORTED";

export type JobStatus =
  "QUEUED" | "LEASED" | "RUNNING" | "SUCCEEDED" | "FAILED_RETRYABLE" | "FAILED_TERMINAL";

export interface DocumentSummary {
  id: string;
  filename: string;
  checksum_sha256: string;
  byte_size: number;
  status: DocumentStatus;
  document_type: string | null;
  document_number: string | null;
  title: string | null;
  issuer: string | null;
  issued_date: string | null;
  signer: string | null;
  deadline: string | null;
  requires_user_review: boolean;
  current_parse_run_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobSummary {
  id: string;
  document_id: string;
  kind: string;
  status: JobStatus;
  attempt: number;
  idempotency_key: string;
  leased_by: string | null;
  lease_expires_at: string | null;
  error: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ParseRunSummary {
  id: string;
  document_id: string;
  version: number;
  is_current: boolean;
  parser_name: string;
  parser_version: string;
  configuration_hash: string;
  strategy_decided: boolean;
  degraded: boolean;
  route: string;
  schema_version: string;
  quality_report: QualityReport;
  started_at: string;
  finished_at: string;
}

export interface UploadResponse {
  document: DocumentSummary;
  job: JobSummary;
  duplicate_of_existing: boolean;
}

export interface DocumentListResponse {
  items: DocumentSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentStatusResponse {
  document: DocumentSummary;
  latest_job: JobSummary | null;
  current_parse_run: ParseRunSummary | null;
}

export interface DocumentDetailResponse {
  document: DocumentSummary;
  parse_runs: ParseRunSummary[];
}

export interface CanonicalResponse {
  parse_run: ParseRunSummary;
  canonical: CanonicalDocument;
}

export interface ReprocessResponse {
  document: DocumentSummary;
  job: JobSummary;
}

export interface FeedbackResponse {
  id: string;
  document_id: string;
  feedback_type: string;
  field_id: string | null;
  corrected_value: string | null;
  comment: string | null;
  created_at: string;
}

// --- CanonicalDocument v1 ---------------------------------------------------

export type BlockType =
  | "title"
  | "heading"
  | "paragraph"
  | "list_item"
  | "table"
  | "table_cell"
  | "caption"
  | "header"
  | "footer"
  | "page_number"
  | "signature"
  | "stamp_region"
  | "image"
  | "formula"
  | "unknown";

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface BlockProvenance {
  page_number: number;
  provider_block_id: string | null;
}

export interface CanonicalBlock {
  id: string;
  type: BlockType;
  text: string;
  reading_order: number;
  bbox: BBox | null;
  confidence: number | null;
  parent_id: string | null;
  attributes: Record<string, unknown>;
  provenance: BlockProvenance;
}

export interface CanonicalPage {
  page_number: number;
  width: number;
  height: number;
  rotation: number;
  blocks: CanonicalBlock[];
}

export type HierarchyKind =
  "chapter" | "section" | "article" | "clause" | "point" | "appendix" | "custom_heading";

export interface HierarchyNode {
  id: string;
  kind: HierarchyKind;
  label: string;
  text: string;
  parent_id: string | null;
  source_block_ids: string[];
  ordinal: number | null;
}

export interface CanonicalTable {
  id: string;
  page_number: number;
  block_id: string;
  n_rows: number;
  n_cols: number;
  cells: string[][];
  caption: string | null;
}

export type ReviewStatus = "unreviewed" | "needs_review" | "confirmed" | "corrected" | "rejected";

export interface ExtractedField {
  id: string;
  name: string;
  raw_value: string | null;
  normalized_value: string | null;
  /** Present only after a correction has been applied server-side; never rewritten in place. */
  corrected_value?: string | null;
  value_type: string;
  confidence: number | null;
  review_status: ReviewStatus;
  source_block_ids: string[];
  source_page_numbers: number[];
  extractor: { name: string; version: string };
}

export interface QualityReport {
  route: string;
  route_confidence: number;
  text_quality_score: number | null;
  structure_quality_score: number | null;
  critical_field_warnings: string[];
  warnings: string[];
  requires_user_review: boolean;
}

export interface ParserRunMeta {
  id: string;
  parser_name: string;
  parser_version: string;
  configuration_hash: string;
  started_at: string;
  finished_at: string;
  device: string;
}

export interface CanonicalDocument {
  schema_version: string;
  document_id: string;
  parser_run: ParserRunMeta;
  metadata: Record<string, unknown>;
  pages: CanonicalPage[];
  hierarchy: HierarchyNode[];
  tables: CanonicalTable[];
  extracted_fields: ExtractedField[];
  quality_report: QualityReport;
}

// --- Error envelope ---------------------------------------------------------

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  request_id: string;
  details: Record<string, unknown>;
}
