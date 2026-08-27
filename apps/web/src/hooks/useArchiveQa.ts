import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError } from "../api/client";
import {
  askArchiveQuestion,
  type ArchiveFilterInput,
  type ArchiveQaResponse,
} from "../api/archive";

export type ArchiveQaState =
  | { kind: "idle" }
  | { kind: "loading"; question: string }
  | { kind: "success"; question: string; response: ArchiveQaResponse }
  | { kind: "error"; question: string; error: unknown };

export interface UseArchiveQaResult {
  state: ArchiveQaState;
  ask: (question: string, filters?: ArchiveFilterInput) => Promise<ArchiveQaResponse | null>;
  reset: () => void;
}

/**
 * Keeps one QA thread across the entire institutional archive. A new question cancels the
 * previous request so a slow response cannot overwrite a subsequent question.
 */
export function useArchiveQa(enabled = true): UseArchiveQaResult {
  const [state, setState] = useState<ArchiveQaState>({ kind: "idle" });
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, [enabled]);

  const reset = useCallback(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setState({ kind: "idle" });
  }, []);

  const ask = useCallback(
    async (question: string, filters?: ArchiveFilterInput): Promise<ArchiveQaResponse | null> => {
      const normalizedQuestion = question.trim();
      if (!enabled || !normalizedQuestion) return null;

      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      setState({ kind: "loading", question: normalizedQuestion });

      try {
        const response = await askArchiveQuestion(
          { question: normalizedQuestion, filters },
          controller.signal,
        );
        if (controller.signal.aborted || requestRef.current !== controller) return null;
        setState({ kind: "success", question: normalizedQuestion, response });
        return response;
      } catch (error) {
        if (controller.signal.aborted || requestRef.current !== controller) return null;
        setState({ kind: "error", question: normalizedQuestion, error });
        return null;
      } finally {
        if (requestRef.current === controller) requestRef.current = null;
      }
    },
    [enabled],
  );

  return { state, ask, reset };
}

export function archiveQaErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.code === "ai_worker_unavailable") {
      return "Trợ lý đang tạm thời không hoạt động. Vui lòng thử lại sau.";
    }
    if (error.code === "archive_not_indexed") {
      return "Kho tài liệu chưa sẵn sàng để tìm kiếm. Vui lòng thử lại sau.";
    }
    if (error.offline) return "Không thể kết nối tới Trợ lý. Vui lòng thử lại.";
  }
  return "Chưa thể hoàn thành câu trả lời. Vui lòng thử lại.";
}
