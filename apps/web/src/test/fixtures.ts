import type { CanonicalDocument, DocumentSummary, ExtractedField } from "../api/types";

export function makeExtractedField(overrides: Partial<ExtractedField> = {}): ExtractedField {
  return {
    id: "field_deadline_1",
    name: "deadline",
    raw_value: "trước ngày 25 tháng 8 năm 2026",
    normalized_value: "2026-08-25",
    value_type: "date",
    confidence: 0.93,
    review_status: "unreviewed",
    source_block_ids: ["b_2_0007"],
    source_page_numbers: [2],
    extractor: { name: "admin-rule-date-v1", version: "1.0" },
    ...overrides,
  };
}

export function makeDocumentSummary(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: "doc_1",
    filename: "cong-van.pdf",
    checksum_sha256: "abc",
    byte_size: 1024,
    status: "READY",
    document_type: "cong_van",
    document_number: "142/SGDĐT-GDTH",
    title: "Về việc hướng dẫn tuyển sinh",
    issuer: "Sở Giáo dục và Đào tạo",
    issued_date: "2026-08-14",
    signer: null,
    deadline: "2026-08-25",
    requires_user_review: false,
    current_parse_run_id: "prun_1",
    error_code: null,
    created_at: "2026-08-14T00:00:00Z",
    updated_at: "2026-08-14T00:00:00Z",
    ...overrides,
  };
}

export function makeCanonicalDocument(
  overrides: Partial<CanonicalDocument> = {},
): CanonicalDocument {
  return {
    schema_version: "1.0",
    document_id: "doc_1",
    parser_run: {
      id: "prun_1",
      parser_name: "pymupdf",
      parser_version: "1.0",
      configuration_hash: "hash",
      started_at: "2026-08-14T00:00:00Z",
      finished_at: "2026-08-14T00:00:01Z",
      device: "cpu",
    },
    metadata: {},
    pages: [
      { page_number: 1, width: 595, height: 842, rotation: 0, blocks: [] },
      {
        page_number: 2,
        width: 595,
        height: 842,
        rotation: 0,
        blocks: [
          {
            id: "b_2_0007",
            type: "paragraph",
            text: "Hạn hoàn thành trước ngày 25 tháng 8 năm 2026",
            reading_order: 0,
            bbox: { x0: 72, y0: 100, x1: 500, y1: 130 },
            confidence: 0.93,
            parent_id: null,
            attributes: {},
            provenance: { page_number: 2, provider_block_id: null },
          },
        ],
      },
    ],
    hierarchy: [],
    tables: [],
    extracted_fields: [makeExtractedField()],
    quality_report: {
      route: "born_digital",
      route_confidence: 0.99,
      text_quality_score: 1,
      structure_quality_score: 0.9,
      critical_field_warnings: [],
      warnings: [],
      requires_user_review: false,
    },
    ...overrides,
  };
}
