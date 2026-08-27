import { AlertTriangle, ArrowUp, Sparkles } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import type { ArchiveFilterInput, ArchiveQaResponse } from "../../api/archive";
import type { QaCitation } from "../../api/types";
import { archiveQaErrorMessage, useArchiveQa } from "../../hooks/useArchiveQa";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";
import { Textarea } from "../ui/Input";
import { ArchiveAssistantStates } from "./ArchiveAssistantStates";
import { DocumentCitationGroup } from "./DocumentCitationGroup";

export const ARCHIVE_QUICK_QUESTIONS = [
  {
    label: "Deadline tháng này",
    question: "Trong các văn bản tháng này có deadline nào?",
  },
  {
    label: "Tuyển sinh mới nhất",
    question: "Văn bản mới nhất liên quan tới tuyển sinh?",
  },
  {
    label: "Việc cần làm",
    question: "Những việc cần làm trong tuần này?",
  },
] as const;

// Not exported: nothing outside this file uses it, and exporting a non-component from a
// component module trips react-refresh/only-export-components.
const RELATION_TYPE_LABEL: Record<string, string> = {
  replaces: "Thay thế",
  supersedes: "Bãi bỏ",
  amends: "Sửa đổi, bổ sung",
  references: "Viện dẫn",
};

export interface ArchiveAssistantPanelProps {
  className?: string;
  onCitationNavigate?: (
    documentId: string,
    page: number,
    blockIds: string[],
    citation: QaCitation,
  ) => void;
  filters?: ArchiveFilterInput;
  renderAnswer?: (response: ArchiveQaResponse, question: string) => ReactNode;
  renderResponseState?: (response: ArchiveQaResponse, question: string) => ReactNode;
}

export function ArchiveAssistantPanel({
  className,
  onCitationNavigate,
  filters,
  renderAnswer,
  renderResponseState,
}: ArchiveAssistantPanelProps) {
  const { state, ask } = useArchiveQa(true);
  const [draft, setDraft] = useState("");

  const submit = (overrideQuestion?: string) => {
    const question = (overrideQuestion ?? draft).trim();
    if (!question || state.kind === "loading") return;
    setDraft("");
    void ask(question, filters);
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

  return (
    <section
      aria-label="Trợ lý kho văn bản"
      className={cn("flex h-full min-h-0 flex-col bg-mg-canvas px-4 py-5 desktop:px-5", className)}
    >
      <header className="flex shrink-0 items-start gap-3 border-b border-mg-border pb-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-mg-md bg-mg-accent-soft text-mg-accent">
          <Sparkles aria-hidden="true" size={18} />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-mg-text">Trợ lý kho văn bản</h2>
          <p className="truncate text-sm text-mg-text-muted">
            Tìm kiếm và tổng hợp có căn cứ từ toàn bộ kho tài liệu
          </p>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto py-5">
        {state.kind === "idle" ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <ArchiveAssistantStates state="empty" />
          </div>
        ) : null}

        {state.kind === "loading" ? (
          <div className="flex flex-col gap-4" data-qa-status="loading">
            <div className="self-end rounded-mg-lg bg-mg-surface-2 px-4 py-3 text-mg-text max-w-[85%]">
              {state.question}
            </div>
            <p className="text-mg-text-muted" role="status">
              Đang tìm trong kho văn bản…
            </p>
          </div>
        ) : null}

        {state.kind === "error" ? (
          <div className="flex flex-col gap-3" data-qa-status="error" role="alert">
            <div className="self-end rounded-mg-lg bg-mg-surface-2 px-4 py-3 text-mg-text max-w-[85%]">
              {state.question}
            </div>
            <p className="text-mg-danger">{archiveQaErrorMessage(state.error)}</p>
            <Button
              variant="secondary"
              size="sm"
              className="self-start"
              onClick={() => void ask(state.question, filters)}
            >
              Thử lại
            </Button>
          </div>
        ) : null}

        {state.kind === "success" ? (
          <div className="flex flex-col gap-5" data-qa-status={state.response.status}>
            <div className="self-end rounded-mg-lg bg-mg-surface-2 px-4 py-3 text-mg-text max-w-[85%]">
              {state.question}
            </div>

            {renderResponseState ? (
              renderResponseState(state.response, state.question)
            ) : state.response.status !== "answered" ? (
              <ArchiveAssistantStates
                status={state.response.status}
                onRetry={() => void ask(state.question, filters)}
              />
            ) : null}

            {state.response.status === "answered" ? (
              <>
                {renderAnswer ? (
                  renderAnswer(state.response, state.question)
                ) : (
                  <div
                    className="whitespace-pre-wrap text-[16px] leading-relaxed text-mg-text"
                    data-answer-slot
                    data-answer-text
                  >
                    {state.response.answer}
                  </div>
                )}

                {state.response.freshness_caveat ? (
                  <div
                    role="note"
                    data-testid="freshness-caveat"
                    className="flex items-start gap-2.5 rounded-mg-md border border-mg-warning/40 bg-mg-warning/10 p-3 text-sm text-mg-text"
                  >
                    <AlertTriangle
                      aria-hidden="true"
                      className="shrink-0 text-mg-warning mt-0.5"
                      size={16}
                    />
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium text-mg-text">Lưu ý về tính cập nhật</span>
                      <p className="text-sm text-mg-text-muted">
                        {state.response.freshness_caveat}
                      </p>
                    </div>
                  </div>
                ) : null}

                {state.response.document_groups && state.response.document_groups.length > 0 ? (
                  <div className="flex flex-col gap-3" aria-label="Nguồn tham khảo theo văn bản">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-mg-text-muted">
                      Văn bản tham khảo ({state.response.document_groups.length})
                    </h3>
                    <div className="flex flex-col gap-3">
                      {state.response.document_groups.map((group) => (
                        <DocumentCitationGroup
                          key={group.document_id}
                          group={group}
                          citations={state.response.citations}
                          onCitationNavigate={onCitationNavigate}
                        />
                      ))}
                    </div>
                  </div>
                ) : null}

                {state.response.relations && state.response.relations.length > 0 ? (
                  <div
                    className="flex flex-col gap-3"
                    aria-label="Quan hệ giữa các văn bản"
                    data-testid="relations-section"
                  >
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-mg-text-muted">
                      Quan hệ giữa các văn bản ({state.response.relations.length})
                    </h3>
                    <div className="flex flex-col gap-2.5">
                      {state.response.relations.map((relation, index) => {
                        const isUnverified = relation.review_state === "unverified";
                        return (
                          <div
                            key={`relation-${index}-${relation.source_document_id}-${relation.relation_type}`}
                            className="flex flex-col gap-1.5 rounded-mg-md border border-mg-border bg-mg-surface p-3 text-sm"
                            data-testid="relation-item"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex items-center gap-2">
                                <span className="font-medium text-mg-text">
                                  {RELATION_TYPE_LABEL[relation.relation_type] ??
                                    relation.relation_type}
                                </span>
                                {relation.target_document_number || relation.target_document_id ? (
                                  <span className="text-mg-text-muted">
                                    →{" "}
                                    {relation.target_document_number ?? relation.target_document_id}
                                  </span>
                                ) : null}
                              </div>
                              <span
                                className={cn(
                                  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                                  isUnverified
                                    ? "border border-mg-warning/40 bg-mg-warning/15 text-mg-warning"
                                    : relation.review_state === "confirmed"
                                      ? "bg-mg-success/15 text-mg-success"
                                      : "bg-mg-surface-2 text-mg-text-muted",
                                )}
                                data-review-state={relation.review_state}
                              >
                                {isUnverified
                                  ? "Chưa xác thực (unverified)"
                                  : relation.review_state === "confirmed"
                                    ? "Đã xác nhận"
                                    : relation.review_state}
                              </span>
                            </div>
                            {isUnverified ? (
                              <p className="text-xs text-mg-warning">
                                Quan hệ này được trích xuất tự động và chưa được xác thực
                                (unverified), không phải căn cứ pháp lý chính thức.
                              </p>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="flex shrink-0 flex-col gap-3">
        <div className="flex flex-wrap gap-2" aria-label="Câu hỏi gợi ý">
          {ARCHIVE_QUICK_QUESTIONS.map(({ label, question }) => (
            <Button
              key={label}
              type="button"
              variant="secondary"
              size="sm"
              disabled={state.kind === "loading"}
              onClick={() => submit(question)}
            >
              {label}
            </Button>
          ))}
        </div>

        <form
          aria-label="Hỏi về kho văn bản"
          className="rounded-mg-lg border border-mg-border bg-mg-surface p-3 shadow-sm"
          onSubmit={handleSubmit}
        >
          <Textarea
            aria-label="Câu hỏi"
            className="min-h-20 resize-none border-0 bg-transparent p-0 text-[16px] leading-relaxed shadow-none focus-visible:outline-none"
            disabled={state.kind === "loading"}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="Hỏi về kho văn bản…"
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
    </section>
  );
}
