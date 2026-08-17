import { Check } from "lucide-react";

import { Button } from "../ui/Button";
import { DOCUMENT_STATUS_LABEL } from "../../lib/status";
import type { DocumentStatus } from "../../api/types";

const TIMELINE_STEPS: DocumentStatus[] = [
  "UPLOADED",
  "INSPECTING",
  "QUEUED_FOR_PARSE",
  "PARSING",
  "READY_FOR_REVIEW",
];

const STEP_LABEL: Record<string, string> = {
  UPLOADED: DOCUMENT_STATUS_LABEL.UPLOADED,
  INSPECTING: DOCUMENT_STATUS_LABEL.INSPECTING,
  QUEUED_FOR_PARSE: DOCUMENT_STATUS_LABEL.QUEUED_FOR_PARSE,
  PARSING: DOCUMENT_STATUS_LABEL.PARSING,
  READY_FOR_REVIEW: "Cần kiểm tra / Sẵn sàng",
};

function stepIndex(status: DocumentStatus): number {
  if (status === "NORMALIZING" || status === "STRUCTURING")
    return TIMELINE_STEPS.indexOf("PARSING");
  if (status === "READY" || status === "INDEXING") return TIMELINE_STEPS.length - 1;
  const index = TIMELINE_STEPS.indexOf(status);
  return index === -1 ? 0 : index;
}

/** D-03 — Processing and readiness (`docs/design/02_DOCUMENT_FLOW.md`). */
export function ProcessingStatus({
  title,
  status,
  onRetry,
  onChooseAnother,
}: {
  title: string;
  status: DocumentStatus;
  onRetry?: () => void;
  onChooseAnother?: () => void;
}) {
  const isFailed = status === "PARSE_FAILED" || status === "UNSUPPORTED";
  const currentIndex = stepIndex(status);

  return (
    <div className="flex max-w-xl flex-col gap-6 p-4 desktop:p-8">
      <h1 className="text-xl font-semibold text-mg-text">{title}</h1>

      {!isFailed && (
        <ol className="flex flex-col gap-3" aria-label="Tiến trình xử lý văn bản">
          {TIMELINE_STEPS.map((step, index) => {
            const done = index < currentIndex;
            const current = index === currentIndex;
            return (
              <li key={step} className="flex items-center gap-3 text-[15px]">
                <span
                  aria-hidden="true"
                  className={
                    done
                      ? "flex h-6 w-6 items-center justify-center rounded-full bg-mg-success text-white"
                      : current
                        ? "flex h-6 w-6 items-center justify-center rounded-full border-2 border-mg-accent"
                        : "flex h-6 w-6 items-center justify-center rounded-full border border-mg-border"
                  }
                >
                  {done ? <Check size={14} /> : null}
                </span>
                <span className={done || current ? "text-mg-text" : "text-mg-text-muted"}>
                  {STEP_LABEL[step]}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      <p role="status" className="text-mg-text">
        Trạng thái: {DOCUMENT_STATUS_LABEL[status]}
      </p>

      {isFailed && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-mg-text-muted">
            {status === "PARSE_FAILED"
              ? "Không thể đọc nội dung văn bản này."
              : "Định dạng tệp này chưa được hỗ trợ."}
          </p>
          <div className="flex gap-2">
            {status === "PARSE_FAILED" && onRetry ? (
              <Button onClick={onRetry}>Thử lại</Button>
            ) : null}
            {onChooseAnother ? (
              <Button variant="secondary" onClick={onChooseAnother}>
                Tải tệp khác
              </Button>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
