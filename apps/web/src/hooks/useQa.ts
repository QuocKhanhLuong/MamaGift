import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError } from "../api/client";
import { askDocumentQuestion } from "../api/documents";
import type { QaResponse } from "../api/types";

export type QaState =
  | { kind: "idle" }
  | { kind: "loading"; question: string }
  | { kind: "success"; question: string; response: QaResponse }
  | { kind: "error"; question: string; error: unknown };

export interface UseQaResult {
  state: QaState;
  ask: (question: string) => Promise<QaResponse | null>;
  reset: () => void;
}

/**
 * Keeps one QA thread scoped to the selected document. A new question cancels the
 * previous request so a slow response cannot appear in a different document's thread.
 */
export function useQa(documentId: string | null, enabled = true): UseQaResult {
  const [state, setState] = useState<QaState>({ kind: "idle" });
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setState({ kind: "idle" });

    return () => {
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, [documentId, enabled]);

  const reset = useCallback(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setState({ kind: "idle" });
  }, []);

  const ask = useCallback(
    async (question: string): Promise<QaResponse | null> => {
      const normalizedQuestion = question.trim();
      if (!documentId || !enabled || !normalizedQuestion) return null;

      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      setState({ kind: "loading", question: normalizedQuestion });

      try {
        const response = await askDocumentQuestion(
          documentId,
          { question: normalizedQuestion },
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
    [documentId, enabled],
  );

  return { state, ask, reset };
}

export function qaErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.code === "ai_worker_unavailable") {
      return "Trợ lý đang tạm thời không hoạt động. Bạn vẫn có thể xem văn bản gốc.";
    }
    if (error.code === "document_not_indexed") {
      return "Văn bản chưa được chuẩn bị để tìm kiếm. Vui lòng thử lại sau.";
    }
    if (error.offline) return "Không thể kết nối tới Trợ lý. Vui lòng thử lại.";
  }
  return "Chưa thể hoàn thành câu trả lời. Vui lòng thử lại.";
}
