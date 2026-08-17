import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

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
});
