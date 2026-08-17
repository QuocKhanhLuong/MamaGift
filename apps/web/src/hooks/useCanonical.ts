import { useCallback, useEffect, useState } from "react";

import { ApiRequestError } from "../api/client";
import { getCanonical } from "../api/documents";
import type { CanonicalDocument, ParseRunSummary } from "../api/types";

type CanonicalState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; canonical: CanonicalDocument; parseRun: ParseRunSummary };

export function useCanonical(documentId: string, ready: boolean) {
  const [state, setState] = useState<CanonicalState>({ kind: "loading" });

  const load = useCallback(
    (signal?: AbortSignal) => {
      setState({ kind: "loading" });
      getCanonical(documentId, undefined, signal)
        .then((response) => {
          setState({ kind: "ready", canonical: response.canonical, parseRun: response.parse_run });
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          const message =
            error instanceof ApiRequestError && error.code === "not_found"
              ? "Chưa có nội dung đã xử lý cho văn bản này."
              : "Không tải được nội dung đã trích xuất.";
          setState({ kind: "error", message });
        });
    },
    [documentId],
  );

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [ready, load]);

  return { state, reload: () => load() };
}
