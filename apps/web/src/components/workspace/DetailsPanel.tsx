import { ConfidenceField } from "../fields/ConfidenceField";
import type { CanonicalDocument, ExtractedField, HierarchyNode } from "../../api/types";

const HIERARCHY_LABEL: Record<HierarchyNode["kind"], string> = {
  chapter: "Chương",
  section: "Mục",
  article: "Điều",
  clause: "Khoản",
  point: "Điểm",
  appendix: "Phụ lục",
  custom_heading: "",
};

/** D-04 third column: extracted fields/correction, then the parsed structured content. */
export function DetailsPanel({
  documentId,
  canonical,
  onGoToSource,
  onCorrected,
}: {
  documentId: string;
  canonical: CanonicalDocument;
  onGoToSource: (field: ExtractedField) => void;
  onCorrected: (fieldId: string, correctedValue: string) => void;
}) {
  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-4">
      <section aria-labelledby="fields-heading">
        <h2 id="fields-heading" className="text-base font-semibold text-mg-text">
          Thông tin văn bản
        </h2>
        {canonical.extracted_fields.length === 0 ? (
          <p className="mt-2 text-sm text-mg-text-muted">Chưa có trường thông tin để kiểm tra.</p>
        ) : (
          <div className="mt-1">
            {canonical.extracted_fields.map((field) => (
              <ConfidenceField
                key={field.id}
                documentId={documentId}
                field={field}
                onGoToSource={onGoToSource}
                onCorrected={onCorrected}
              />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="hierarchy-heading">
        <h2 id="hierarchy-heading" className="text-base font-semibold text-mg-text">
          Nội dung đã đọc
        </h2>
        {canonical.hierarchy.length === 0 ? (
          <p className="mt-2 text-sm text-mg-text-muted">Chưa có nội dung cấu trúc để hiển thị.</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {canonical.hierarchy.map((node) => (
              <li key={node.id}>
                <p className="text-sm font-medium text-mg-text">
                  {HIERARCHY_LABEL[node.kind]} {node.label}
                </p>
                {node.text ? (
                  <p className="text-sm text-mg-text-muted line-clamp-2">{node.text}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
