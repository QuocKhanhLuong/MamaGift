import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { DocumentWorkspace } from "../components/workspace/DocumentWorkspace";
import { ProcessingStatus } from "../components/processing/ProcessingStatus";
import { ErrorState } from "../components/common/ErrorState";
import { StatusBadge } from "../components/common/StatusBadge";
import { ApiRequestError } from "../api/client";
import { reprocessDocument } from "../api/documents";
import { useDocumentStatus } from "../hooks/useDocumentStatus";
import { DOCUMENT_STATUS_LABEL, documentStatusTone, isOpenableDocument } from "../lib/status";

export function DocumentPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const { state, reload } = useDocumentStatus(documentId!);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  if (state.kind === "loading") {
    return <div className="p-8 text-mg-text-muted">Đang mở văn bản…</div>;
  }

  if (state.kind === "error") {
    return (
      <div className="p-6">
        <ErrorState message={state.message} onRetry={reload} />
      </div>
    );
  }

  const { document } = state.response;
  const title = document.document_number ?? document.title ?? document.filename;
  const ready = isOpenableDocument(document.status);

  async function handleRetry() {
    setRetrying(true);
    setRetryError(null);
    try {
      await reprocessDocument(documentId!);
      await reload();
    } catch (error) {
      setRetryError(
        error instanceof ApiRequestError && error.offline
          ? "Không thể thử lại khi đang ngoại tuyến."
          : "Không thể thử lại. Vui lòng thử lại sau.",
      );
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-mg-border px-3 py-2">
        <Link
          to="/van-ban"
          aria-label="Quay lại danh sách văn bản"
          className="flex h-11 w-11 items-center justify-center rounded-mg-sm text-mg-text hover:bg-mg-surface-2"
        >
          <ArrowLeft aria-hidden="true" size={18} />
        </Link>
        <span className="truncate font-medium text-mg-text">{title}</span>
        <span className="ml-auto">
          <StatusBadge
            tone={documentStatusTone(document.status)}
            label={DOCUMENT_STATUS_LABEL[document.status]}
          />
        </span>
      </div>

      <div className="min-h-0 flex-1">
        {ready ? (
          <DocumentWorkspace documentId={documentId!} document={document} />
        ) : (
          <>
            <ProcessingStatus
              title={title}
              status={document.status}
              onRetry={handleRetry}
              onChooseAnother={() => navigate("/van-ban")}
            />
            {retrying ? <p className="px-8 text-sm text-mg-text-muted">Đang thử lại…</p> : null}
            {retryError ? (
              <p role="alert" className="px-8 text-sm text-mg-danger">
                {retryError}
              </p>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
