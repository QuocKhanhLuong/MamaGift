import { useState } from "react";
import type { FormEvent } from "react";

import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { ApiRequestError } from "../../api/client";
import { submitFeedback } from "../../api/documents";

/** D-05 — Review and correct a field (`docs/design/02_DOCUMENT_FLOW.md`). */
export function CorrectionControl({
  documentId,
  fieldId,
  currentValue,
  onCancel,
  onSaved,
}: {
  documentId: string;
  fieldId: string;
  currentValue: string;
  onCancel: () => void;
  onSaved: (correctedValue: string) => void;
}) {
  const [value, setValue] = useState(currentValue);
  const [status, setStatus] = useState<"idle" | "saving" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "saving") return;
    setStatus("saving");
    setError(null);
    try {
      await submitFeedback(documentId, {
        feedback_type: "critical_field_correction",
        field_id: fieldId,
        corrected_value: value,
      });
      onSaved(value);
    } catch (cause) {
      setStatus("error");
      setError(
        cause instanceof ApiRequestError && cause.offline
          ? "Chưa lưu được thay đổi. Kiểm tra kết nối mạng."
          : "Chưa lưu được thay đổi.",
      );
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 flex flex-col gap-2" aria-label="Sửa giá trị">
      <label htmlFor={`correction-${fieldId}`} className="sr-only">
        Giá trị mới
      </label>
      <Input
        id={`correction-${fieldId}`}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        disabled={status === "saving"}
        autoFocus
      />
      {status === "error" && error ? (
        <p role="alert" className="text-sm text-mg-danger">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={onCancel}
          disabled={status === "saving"}
        >
          Hủy
        </Button>
        <Button type="submit" size="sm" disabled={status === "saving" || !value.trim()}>
          {status === "saving" ? "Đang lưu thay đổi…" : "Lưu thay đổi"}
        </Button>
      </div>
    </form>
  );
}
