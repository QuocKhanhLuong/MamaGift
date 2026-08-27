import { useNavigate } from "react-router-dom";

import { ArchiveAssistantPanel } from "../components/assistant/ArchiveAssistantPanel";

export function ArchiveAssistantPage() {
  const navigate = useNavigate();

  function handleCitationNavigate(documentId: string, page: number, blockIds: string[]) {
    const params = new URLSearchParams();
    if (page !== undefined && page !== null) {
      params.set("trang", String(page));
    }
    if (blockIds && blockIds.length > 0) {
      for (const blockId of blockIds) {
        params.append("khoi", blockId);
      }
    }
    const queryString = params.toString();
    navigate(queryString ? `/van-ban/${documentId}?${queryString}` : `/van-ban/${documentId}`);
  }

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col p-4 desktop:p-8">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-mg-text desktop:text-[28px]">
          Trợ lý kho tài liệu
        </h1>
        <p className="mt-1 text-sm text-mg-text-muted">
          Hỏi đáp và tra cứu thông tin tổng hợp từ toàn bộ kho tài liệu
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-mg-lg border border-mg-border bg-mg-surface">
        <ArchiveAssistantPanel onCitationNavigate={handleCitationNavigate} />
      </div>
    </div>
  );
}
