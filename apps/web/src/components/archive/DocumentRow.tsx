import { Link } from "react-router-dom";

import { StatusBadge } from "../common/StatusBadge";
import { DOCUMENT_STATUS_LABEL, documentStatusTone, formatVietnameseDate } from "../../lib/status";
import type { DocumentSummary } from "../../api/types";

export function DocumentRow({ document }: { document: DocumentSummary }) {
  const heading = document.document_number ?? document.title ?? document.filename;
  const showTitleLine = document.title && document.title !== heading;
  const issuedDate = formatVietnameseDate(document.issued_date);

  return (
    <li>
      <Link
        to={`/van-ban/${document.id}`}
        className="flex min-h-[44px] flex-col gap-1 rounded-mg-lg border border-mg-border bg-mg-surface p-4 hover:border-mg-border-strong"
      >
        <span className="text-[17px] font-medium text-mg-text">{heading}</span>
        {showTitleLine ? (
          <span className="text-sm text-mg-text-muted">{document.title}</span>
        ) : null}
        <span className="flex flex-wrap items-center gap-2 text-sm text-mg-text-muted">
          {issuedDate ? <span>{issuedDate}</span> : null}
          {issuedDate && document.issuer ? <span aria-hidden="true">·</span> : null}
          {document.issuer ? <span>{document.issuer}</span> : null}
          <StatusBadge
            tone={documentStatusTone(document.status)}
            label={DOCUMENT_STATUS_LABEL[document.status]}
          />
        </span>
      </Link>
    </li>
  );
}
