import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError } from "../api/client";
import { listDocuments } from "../api/documents";
import type { DocumentListFilters } from "../api/documents";
import type { DocumentSummary } from "../api/types";

type ListState =
  | { kind: "loading" }
  | { kind: "error"; message: string; staleItems: DocumentSummary[] | null }
  | { kind: "ready"; items: DocumentSummary[]; total: number };

export function useDocumentList(filters: DocumentListFilters) {
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const staleRef = useRef<DocumentSummary[] | null>(null);
  const filterKey = JSON.stringify(filters);

  const load = useCallback(
    (signal?: AbortSignal) => {
      setState((previous) => {
        if (previous.kind === "ready") staleRef.current = previous.items;
        return { kind: "loading" };
      });
      listDocuments(filters, signal)
        .then((response) => {
          staleRef.current = response.items;
          setState({ kind: "ready", items: response.items, total: response.total });
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          const message =
            error instanceof ApiRequestError
              ? "Không tải được danh sách văn bản."
              : "Không tải được danh sách văn bản.";
          setState({ kind: "error", message, staleItems: staleRef.current });
        });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filterKey],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  return { state, reload: () => load() };
}
