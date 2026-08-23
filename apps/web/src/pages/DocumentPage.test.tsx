import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { DocumentPage } from "./DocumentPage";
import { server } from "../test/server";
import { API_BASE_URL } from "../api/client";
import { makeDocumentSummary } from "../test/fixtures";

function statusHandler(status: string, extra: Record<string, unknown> = {}) {
  return http.get(`${API_BASE_URL}/api/v1/documents/doc_1/status`, () =>
    HttpResponse.json({
      document: makeDocumentSummary({ status: status as never, ...extra }),
      latest_job: null,
      current_parse_run: null,
    }),
  );
}

function renderDocumentPage() {
  return render(
    <MemoryRouter initialEntries={["/van-ban/doc_1"]}>
      <Routes>
        <Route path="/van-ban/:documentId" element={<DocumentPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DocumentPage (API integration)", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { value: 1280, configurable: true });
  });

  it("shows the failed-processing UI for a terminal parse failure", async () => {
    server.use(statusHandler("PARSE_FAILED"));
    renderDocumentPage();

    expect(await screen.findByText("Trạng thái: Không đọc được văn bản")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it("retries a failed document through the reprocess endpoint (retry path)", async () => {
    const user = userEvent.setup();
    let reprocessCalled = false;
    server.use(
      statusHandler("PARSE_FAILED"),
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/reprocess`, () => {
        reprocessCalled = true;
        return HttpResponse.json(
          {
            document: makeDocumentSummary({ status: "QUEUED_FOR_PARSE" }),
            job: { id: "job_2", status: "QUEUED" },
          },
          { status: 202 },
        );
      }),
    );
    renderDocumentPage();

    await screen.findByRole("button", { name: "Thử lại" });
    await user.click(screen.getByRole("button", { name: "Thử lại" }));

    await waitFor(() => expect(reprocessCalled).toBe(true));
  });

  it("shows a document-not-found error with retry", async () => {
    server.use(
      http.get(`${API_BASE_URL}/api/v1/documents/doc_1/status`, () =>
        HttpResponse.json(
          {
            error: {
              code: "not_found",
              message: "document not found",
              retryable: false,
              request_id: "req_1",
              details: {},
            },
          },
          { status: 404 },
        ),
      ),
    );
    renderDocumentPage();

    expect(await screen.findByText("Không tìm thấy văn bản.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it("mounts the workspace with the assistant entry point for a READY document", async () => {
    server.use(
      statusHandler("READY"),
      http.get(`${API_BASE_URL}/api/v1/documents`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
      http.get(`${API_BASE_URL}/api/v1/documents/doc_1/canonical`, () =>
        HttpResponse.json({
          parse_run: {
            id: "prun_1",
            document_id: "doc_1",
            version: 1,
            is_current: true,
            parser_name: "pymupdf",
            parser_version: "1.0",
            configuration_hash: "hash",
            strategy_decided: false,
            degraded: true,
            route: "born_digital",
            schema_version: "1.0",
            quality_report: {},
            started_at: "2026-08-14T00:00:00Z",
            finished_at: "2026-08-14T00:00:01Z",
          },
          canonical: {
            schema_version: "1.0",
            document_id: "doc_1",
            parser_run: { id: "prun_1", started_at: "", finished_at: "" },
            metadata: {},
            pages: [{ page_number: 1, width: 595, height: 842, rotation: 0, blocks: [] }],
            hierarchy: [],
            tables: [],
            extracted_fields: [],
            quality_report: {},
          },
        }),
      ),
    );
    renderDocumentPage();

    expect(await screen.findByRole("tab", { name: "Trợ lý" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Chi tiết" })).toBeInTheDocument();
  });

  it("mounts the workspace without the assistant entry point for a READY_FOR_REVIEW document", async () => {
    server.use(
      statusHandler("READY_FOR_REVIEW"),
      http.get(`${API_BASE_URL}/api/v1/documents`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
      http.get(`${API_BASE_URL}/api/v1/documents/doc_1/canonical`, () =>
        HttpResponse.json({
          parse_run: {
            id: "prun_1",
            document_id: "doc_1",
            version: 1,
            is_current: true,
            parser_name: "pymupdf",
            parser_version: "1.0",
            configuration_hash: "hash",
            strategy_decided: false,
            degraded: true,
            route: "born_digital",
            schema_version: "1.0",
            quality_report: {},
            started_at: "2026-08-14T00:00:00Z",
            finished_at: "2026-08-14T00:00:01Z",
          },
          canonical: {
            schema_version: "1.0",
            document_id: "doc_1",
            parser_run: { id: "prun_1", started_at: "", finished_at: "" },
            metadata: {},
            pages: [{ page_number: 1, width: 595, height: 842, rotation: 0, blocks: [] }],
            hierarchy: [],
            tables: [],
            extracted_fields: [],
            quality_report: {},
          },
        }),
      ),
    );
    renderDocumentPage();

    expect(await screen.findByText("Trang 1 / 1")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Trợ lý" })).not.toBeInTheDocument();
  });
});
