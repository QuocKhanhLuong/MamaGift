import { useState } from "react";

import { CorrectionControl } from "./CorrectionControl";
import { StatusBadge } from "../common/StatusBadge";
import {
  fieldLabel,
  formatFieldValue,
  isLowConfidence,
  REVIEW_STATUS_LABEL,
} from "../../lib/status";
import type { ExtractedField } from "../../api/types";

function reviewTone(status: ExtractedField["review_status"]): "neutral" | "warning" | "success" {
  if (status === "corrected" || status === "confirmed") return "success";
  if (status === "needs_review") return "warning";
  return "neutral";
}

/** D-05 field row: value, confidence/review status, source jump, and correction entry. */
export function ConfidenceField({
  documentId,
  field,
  onGoToSource,
  onCorrected,
}: {
  documentId: string;
  field: ExtractedField;
  onGoToSource: (field: ExtractedField) => void;
  onCorrected: (fieldId: string, correctedValue: string) => void;
}) {
  const [editing, setEditing] = useState(false);

  const rawDisplayValue = field.corrected_value ?? field.normalized_value ?? field.raw_value;
  const displayValue = formatFieldValue(rawDisplayValue, field.value_type);
  const lowConfidence = isLowConfidence(field.confidence) && field.review_status === "unreviewed";
  const hasSource = field.source_block_ids.length > 0 && field.source_page_numbers.length > 0;
  const reviewLabel = REVIEW_STATUS_LABEL[field.review_status];

  return (
    <div
      data-field-name={field.name}
      className="flex flex-col gap-1.5 border-b border-mg-border py-3 last:border-0"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-mg-text-muted">{fieldLabel(field.name)}</span>
        {reviewLabel ? (
          <StatusBadge tone={reviewTone(field.review_status)} label={reviewLabel} />
        ) : lowConfidence ? (
          <StatusBadge tone="warning" label="Cần kiểm tra" />
        ) : null}
      </div>

      <p className="text-[15px] text-mg-text">
        {displayValue || <span className="text-mg-text-muted">Chưa có dữ liệu</span>}
      </p>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        {hasSource ? (
          <button
            type="button"
            onClick={() => onGoToSource(field)}
            className="font-medium text-mg-accent hover:underline"
          >
            Đi tới nguồn · Trang {field.source_page_numbers[0]}
          </button>
        ) : (
          <span className="text-mg-text-muted">Chưa có nguồn xác định</span>
        )}
        {!editing ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="font-medium text-mg-text hover:underline"
          >
            Sửa
          </button>
        ) : null}
      </div>

      {editing ? (
        <CorrectionControl
          documentId={documentId}
          fieldId={field.id}
          currentValue={displayValue ?? ""}
          onCancel={() => setEditing(false)}
          onSaved={(correctedValue) => {
            setEditing(false);
            onCorrected(field.id, correctedValue);
          }}
        />
      ) : null}
    </div>
  );
}
