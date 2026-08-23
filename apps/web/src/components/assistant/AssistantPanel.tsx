import { ArrowUp, FileText } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import type { DocumentSummary, QaResponse, QaStatus } from "../../api/types";
import { Button } from "../ui/Button";
import { Textarea } from "../ui/Input";
import { cn } from "../../lib/cn";
import { DOCUMENT_STATUS_LABEL } from "../../lib/status";
import { qaErrorMessage, useQa } from "../../hooks/useQa";

export const QUICK_QUESTIONS = [
  { label: "Tóm tắt", question: "Tóm tắt văn bản này." },
  { label: "Tôi cần làm gì?", question: "Tôi cần làm gì theo văn bản này?" },
  { label: "Có deadline nào?", question: "Văn bản này có deadline nào?" },
  { label: "Đối tượng áp dụng?", question: "Đối tượng nào áp dụng theo văn bản này?" },
] as const;

const QA_STATUS_COPY: Record<QaStatus, { label: string; description: string }> = {
  answered: {
    label: "Đã có câu trả lời",
    description: "Câu trả lời được tìm trong văn bản đã chọn.",
  },
  insufficient_evidence: {
    label: "Chưa đủ căn cứ",
    description: "Chưa tìm thấy đủ căn cứ trong văn bản để trả lời chắc chắn câu hỏi này.",
  },
  ai_worker_unavailable: {
    label: "Trợ lý tạm thời không hoạt động",
    description: "Bạn vẫn có thể xem văn bản gốc và thử lại sau.",
  },
  failed: {
    label: "Chưa hoàn thành",
    description: "Chưa thể hoàn thành câu trả lời. Vui lòng thử lại.",
  },
};

export interface AssistantPanelProps {
  document: DocumentSummary | null;
  className?: string;
  onChooseDocument?: () => void;
  /** G2 can replace the default prose view with answer and citation rendering. */
  renderAnswer?: (response: QaResponse, question: string) => ReactNode;
  /** G3 can replace the minimal status fallback with its dedicated state view. */
  renderResponseState?: (response: QaResponse, question: string) => ReactNode;
}

function documentLabel(document: DocumentSummary): string {
  return document.document_number ?? document.title ?? document.filename;
}

function statusFallback(response: QaResponse): ReactNode {
  const copy = QA_STATUS_COPY[response.status];
  return (
    <div className="flex flex-col gap-1" data-qa-status={response.status} role="status">
      <p className="font-medium text-mg-text">{copy.label}</p>
      <p className="text-sm text-mg-text-muted">{copy.description}</p>
    </div>
  );
}

/** G1 — document-gated assistant shell; answer/citation and failure views remain slots for G2/G3. */
export function AssistantPanel({
  document,
  className,
  onChooseDocument,
  renderAnswer,
  renderResponseState,
}: AssistantPanelProps) {
  const ready = document?.status === "READY";
  const documentId = document?.id ?? null;
  const { state, ask } = useQa(documentId, ready);
  const [draft, setDraft] = useState("");

  const submit = () => {
    const question = draft.trim();
    if (!ready || !question || state.kind === "loading") return;
    setDraft("");
    void ask(question);
  };

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  const title = document ? documentLabel(document) : "Chưa chọn văn bản";
  const unavailableReason = document
    ? `Trợ lý chỉ hoạt động khi văn bản đã sẵn sàng. Hiện tại: ${DOCUMENT_STATUS_LABEL[document.status]}.`
    : "Hãy chọn một văn bản đã sẵn sàng để hỏi có căn cứ.";

  return (
    <section
      aria-label="Trợ lý"
      aria-disabled={!ready}
      className={cn("flex h-full min-h-0 flex-col bg-mg-canvas px-4 py-5 desktop:px-5", className)}
    >
      <header className="flex shrink-0 items-start gap-3 border-b border-mg-border pb-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-mg-md bg-mg-accent-soft text-mg-accent">
          <FileText aria-hidden="true" size={18} />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-mg-text">Trợ lý</h2>
          <p className="truncate text-sm text-mg-text-muted" title={title}>
            {title}
          </p>
        </div>
      </header>

      {!ready ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-8 text-center">
          <h3 className="text-lg font-medium text-mg-text">Trợ lý chưa sẵn sàng</h3>
          <p className="max-w-sm text-mg-text-muted">{unavailableReason}</p>
          {onChooseDocument ? (
            <Button variant="secondary" size="sm" onClick={onChooseDocument}>
              Chọn văn bản khác
            </Button>
          ) : null}
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto py-5">
            {state.kind === "idle" ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                <p className="text-lg font-medium text-mg-text">Chào mẹ,</p>
                <p className="text-mg-text-muted">Hôm nay mẹ cần tìm gì trong văn bản này?</p>
              </div>
            ) : null}
            {state.kind === "loading" ? (
              <div className="flex flex-col gap-4" data-qa-status="loading">
                <div className="self-end rounded-mg-lg bg-mg-surface-2 px-4 py-3 text-mg-text">
                  {state.question}
                </div>
                <p className="text-mg-text-muted" role="status">
                  Đang tìm trong văn bản…
                </p>
              </div>
            ) : null}
            {state.kind === "error" ? (
              <div className="flex flex-col gap-3" data-qa-status="error" role="alert">
                <div className="self-end rounded-mg-lg bg-mg-surface-2 px-4 py-3 text-mg-text">
                  {state.question}
                </div>
                <p className="text-mg-danger">{qaErrorMessage(state.error)}</p>
                <Button
                  variant="secondary"
                  size="sm"
                  className="self-start"
                  onClick={() => void ask(state.question)}
                >
                  Thử lại
                </Button>
              </div>
            ) : null}
            {state.kind === "success" ? (
              <div className="flex flex-col gap-4">
                <div className="self-end rounded-mg-lg bg-mg-surface-2 px-4 py-3 text-mg-text">
                  {state.question}
                </div>
                {renderResponseState
                  ? renderResponseState(state.response, state.question)
                  : statusFallback(state.response)}
                {state.response.status === "answered" && state.response.answer ? (
                  <div
                    className="whitespace-pre-wrap text-[16px] leading-relaxed text-mg-text"
                    data-answer-slot
                  >
                    {renderAnswer
                      ? renderAnswer(state.response, state.question)
                      : state.response.answer}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="flex shrink-0 flex-col gap-3">
            <div className="flex flex-wrap gap-2" aria-label="Câu hỏi gợi ý">
              {QUICK_QUESTIONS.map(({ label, question }) => (
                <Button
                  key={label}
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={state.kind === "loading"}
                  onClick={() => {
                    setDraft("");
                    void ask(question);
                  }}
                >
                  {label}
                </Button>
              ))}
            </div>
            <form
              aria-label="Hỏi về văn bản"
              className="rounded-mg-lg border border-mg-border bg-mg-surface p-3 shadow-sm"
              onSubmit={handleSubmit}
            >
              <Textarea
                aria-label="Câu hỏi"
                className="min-h-20 resize-none border-0 bg-transparent p-0 text-[16px] leading-relaxed shadow-none focus-visible:outline-none"
                disabled={state.kind === "loading"}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder="Hỏi về văn bản…"
                value={draft}
              />
              <div className="mt-2 flex justify-end">
                <Button
                  aria-label="Gửi câu hỏi"
                  disabled={!draft.trim() || state.kind === "loading"}
                  size="icon"
                  type="submit"
                >
                  <ArrowUp aria-hidden="true" size={18} />
                </Button>
              </div>
            </form>
          </div>
        </>
      )}
    </section>
  );
}
