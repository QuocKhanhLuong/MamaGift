import { FileText, Upload as UploadIcon, X } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Dialog, DialogContent, DialogTrigger } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { ApiRequestError } from "../../api/client";
import { uploadDocument } from "../../api/documents";

type UploadState =
  | { kind: "empty" }
  | { kind: "selected"; file: File }
  | { kind: "uploading"; file: File }
  | { kind: "error"; file: File | null; message: string };

const MAX_LOCAL_CHECK_BYTES = 50 * 1024 * 1024;

function validateLocally(file: File): string | null {
  if (file.type && file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    return "Chỉ hỗ trợ tệp PDF.";
  }
  if (file.size > MAX_LOCAL_CHECK_BYTES) {
    return "Tệp vượt quá dung lượng cho phép.";
  }
  return null;
}

/** D-02 — Upload a PDF (`docs/design/02_DOCUMENT_FLOW.md`). */
export function UploadDrawer({ onUploaded }: { onUploaded: () => void }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<UploadState>({ kind: "empty" });
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  function reset() {
    setState({ kind: "empty" });
    if (inputRef.current) inputRef.current.value = "";
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) reset();
  }

  function handleFileChosen(file: File) {
    const problem = validateLocally(file);
    setState(problem ? { kind: "error", file, message: problem } : { kind: "selected", file });
  }

  async function handleSubmit() {
    if (state.kind !== "selected") return;
    const { file } = state;
    setState({ kind: "uploading", file });
    try {
      const response = await uploadDocument(file);
      onUploaded();
      setOpen(false);
      reset();
      navigate(`/van-ban/${response.document.id}`);
    } catch (error) {
      const message =
        error instanceof ApiRequestError
          ? error.offline
            ? "Không thể tải lên khi đang ngoại tuyến."
            : mapUploadError(error.code)
          : "Không thể tải lên. Vui lòng thử lại.";
      setState({ kind: "error", file, message });
    }
  }

  const selectedFile = state.kind === "empty" ? null : state.file;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <UploadIcon aria-hidden="true" size={16} />
          Tải văn bản PDF
        </Button>
      </DialogTrigger>
      <DialogContent title="Tải văn bản">
        <div className="flex flex-col gap-4">
          <label
            htmlFor="upload-file-input"
            className="flex cursor-pointer flex-col items-center gap-2 rounded-mg-lg border border-dashed border-mg-border-strong bg-mg-surface-2 px-4 py-8 text-center"
          >
            <UploadIcon aria-hidden="true" className="text-mg-text-muted" size={22} />
            <span className="text-sm text-mg-text">Kéo thả tệp PDF vào đây hoặc</span>
            <span className="text-sm font-medium text-mg-accent">Chọn tệp PDF</span>
          </label>
          <input
            ref={inputRef}
            id="upload-file-input"
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            disabled={state.kind === "uploading"}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleFileChosen(file);
            }}
          />

          {selectedFile ? (
            <div className="flex items-center justify-between gap-2 rounded-mg-md border border-mg-border bg-mg-surface px-3 py-2">
              <span className="flex items-center gap-2 text-sm text-mg-text">
                <FileText aria-hidden="true" size={16} />
                {selectedFile.name}
              </span>
              {state.kind !== "uploading" ? (
                <button
                  type="button"
                  aria-label="Bỏ chọn tệp"
                  onClick={reset}
                  className="flex h-9 w-9 items-center justify-center rounded-mg-sm text-mg-text-muted hover:bg-mg-surface-2"
                >
                  <X aria-hidden="true" size={16} />
                </button>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-mg-text-muted">Chọn một tệp PDF để tiếp tục.</p>
          )}

          {state.kind === "error" ? (
            <p role="alert" className="text-sm text-mg-danger">
              {state.message}
            </p>
          ) : null}

          <p className="text-sm text-mg-text-muted">Tệp được lưu nguyên bản để đối chiếu nguồn.</p>

          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => handleOpenChange(false)}>
              Hủy
            </Button>
            <Button onClick={handleSubmit} disabled={state.kind !== "selected"}>
              {state.kind === "uploading" ? "Đang tải lên…" : "Tải lên"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function mapUploadError(code: string): string {
  switch (code) {
    case "unsupported_media_type":
      return "Định dạng tệp không được hỗ trợ.";
    case "file_too_large":
      return "Tệp vượt quá dung lượng cho phép.";
    case "invalid_pdf":
      return "Tệp PDF không hợp lệ.";
    case "encrypted_pdf":
      return "Tệp PDF có mật khẩu, vui lòng gỡ mật khẩu trước khi tải lên.";
    case "storage_failure":
      return "Không thể lưu tệp. Vui lòng thử lại.";
    default:
      return "Không thể tải lên. Vui lòng thử lại.";
  }
}
