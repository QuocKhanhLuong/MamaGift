import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError } from "../api/client";
import { getDocumentStatus } from "../api/documents";
import type { DocumentStatusResponse } from "../api/types";
import { PROCESSING_STATUSES } from "../lib/status";

type StatusState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; response: DocumentStatusResponse };

const POLL_INTERVAL_MS = 2000;

export function useDocumentStatus(documentId: string) {
  const [state, setState] = useState<StatusState>({ kind: "loading" });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchOnce = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await getDocumentStatus(documentId, signal);
        setState({ kind: "ready", response });
        return response;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return null;
        const message =
          error instanceof ApiRequestError && error.code === "not_found"
            ? "Không tìm thấy văn bản."
            : "Không tải được trạng thái văn bản.";
        setState({ kind: "error", message });
        return null;
      }
    },
    [documentId],
  );

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      const response = await fetchOnce(controller.signal);
      if (cancelled || !response) return;
      if (PROCESSING_STATUSES.has(response.document.status)) {
        timerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
      }
    }

    tick();

    return () => {
      cancelled = true;
      controller.abort();
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetchOnce]);

  return { state, reload: () => fetchOnce() };
}
