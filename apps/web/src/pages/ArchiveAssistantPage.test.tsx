import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import type { ArchiveDocumentGroup, ArchiveQaResponse } from "../api/archive";
import { API_BASE_URL } from "../api/client";
import type { QaCitation } from "../api/types";
import { Sidebar } from "../components/shell/Sidebar";
import { makeDocumentSummary } from "../test/fixtures";
import { server } from "../test/server";
import { ArchiveAssistantPage } from "./ArchiveAssistantPage";
import { DocumentPage } from "./DocumentPage";

const testCitationSingleBlock: QaCitation = {
  citation_id: "c_single",
  document_id: "doc_1",
  page_number: 2,
  block_ids: ["b_2_0001"],
  quote: "Quy định điều kiện tuyển sinh",
};

const testCitationMultiBlock: QaCitation = {
  citation_id: "c_multi",
  document_id: "doc_2",
  page_number: 3,
  block_ids: ["b_3_0001", "b_3_0002"],
  quote: "Kế hoạch triển khai công tác tuyển sinh",
};

const testGroupDoc1: ArchiveDocumentGroup = {
  document_id: "doc_1",
  document_number: "01/QD-UBND",
  title: "Quyết định ban hành quy chế",
  document_type: "Quyết định",
  issuer: "Ủy ban nhân dân",
  issued_date: "2026-01-01",
  document_version: 1,
  parse_run_id: "prun_1",
  citation_ids: ["c_single"],
};

const testGroupDoc2: ArchiveDocumentGroup = {
  document_id: "doc_2",
  document_number: "02/KH-UBND",
  title: "Kế hoạch tuyển sinh đầu cấp",
  document_type: "Kế hoạch",
  issuer: "Ủy ban nhân dân",
  issued_date: "2026-02-01",
  document_version: 1,
  parse_run_id: "prun_2",
  citation_ids: ["c_multi"],
};

function makeArchiveQaResponse(overrides: Partial<ArchiveQaResponse> = {}): ArchiveQaResponse {
  return {
    answer: "Căn cứ theo tài liệu lưu trữ...",
    status: "answered",
    citations: [testCitationSingleBlock],
    document_groups: [testGroupDoc1],
    relations: [],
    freshness_caveat: null,
    retrieval: { query_id: "qry_test_1" },
    model: { provider: "fake", model: "fake-model", version: "1" },
    ...overrides,
  };
}

let currentLocation: { pathname: string; search: string } = { pathname: "", search: "" };
function LocationTracker() {
  const location = useLocation();
  currentLocation = { pathname: location.pathname, search: location.search };
  return null;
}

function mockDocumentPageApis() {
  server.use(
    http.get(`${API_BASE_URL}/api/v1/documents/doc_1/status`, () =>
      HttpResponse.json({
        document: makeDocumentSummary({ id: "doc_1", status: "READY" }),
        latest_job: null,
        current_parse_run: null,
      }),
    ),
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
          pages: [
            {
              page_number: 1,
              width: 595,
              height: 842,
              rotation: 0,
              blocks: [
                {
                  id: "b_1_0001",
                  page_number: 1,
                  block_index: 0,
                  text: "Nội dung trang 1",
                  bbox: { x0: 10, y0: 10, x1: 100, y1: 50 },
                  kind: "paragraph",
                  confidence: 0.9,
                  provenance: { page_number: 1, parser: "pymupdf" },
                },
              ],
            },
            {
              page_number: 2,
              width: 595,
              height: 842,
              rotation: 0,
              blocks: [
                {
                  id: "b_2_0005",
                  page_number: 2,
                  block_index: 0,
                  text: "Nội dung trang 2 đoạn 5",
                  bbox: { x0: 20, y0: 20, x1: 200, y1: 80 },
                  kind: "paragraph",
                  confidence: 0.95,
                  provenance: { page_number: 2, parser: "pymupdf" },
                },
              ],
            },
          ],
          hierarchy: [],
          tables: [],
          extracted_fields: [],
          quality_report: {},
        },
      }),
    ),
  );
}

describe("ArchiveAssistantPage & Routing & Citation Deep-links", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { value: 1280, configurable: true });
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(makeArchiveQaResponse()),
      ),
    );
  });

  it("1. /tro-ly renders the page heading and subtitle", async () => {
    render(
      <MemoryRouter initialEntries={["/tro-ly"]}>
        <ArchiveAssistantPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "Trợ lý kho tài liệu", level: 1 }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Hỏi đáp và tra cứu thông tin tổng hợp từ toàn bộ kho tài liệu"),
    ).toBeInTheDocument();
  });

  it("2. Clicking a citation navigates to /van-ban/<id>?trang=<n>&khoi=<b> — assert location and params", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(
          makeArchiveQaResponse({
            citations: [testCitationSingleBlock],
            document_groups: [testGroupDoc1],
          }),
        ),
      ),
    );

    render(
      <MemoryRouter initialEntries={["/tro-ly"]}>
        <LocationTracker />
        <Routes>
          <Route path="/tro-ly" element={<ArchiveAssistantPage />} />
          <Route path="/van-ban/:documentId" element={<div>Trang xem văn bản</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Hỏi điều kiện tuyển sinh?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    const chip = await screen.findByTestId("citation-chip-c_single");
    await user.click(chip);

    await waitFor(() => {
      expect(currentLocation.pathname).toBe("/van-ban/doc_1");
    });

    const searchParams = new URLSearchParams(currentLocation.search);
    expect(searchParams.get("trang")).toBe("2");
    expect(searchParams.getAll("khoi")).toEqual(["b_2_0001"]);
  });

  it("3. Multiple block ids produce multiple khoi params, not one comma-joined value", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/archive/qa`, async () =>
        HttpResponse.json(
          makeArchiveQaResponse({
            citations: [testCitationMultiBlock],
            document_groups: [testGroupDoc2],
          }),
        ),
      ),
    );

    render(
      <MemoryRouter initialEntries={["/tro-ly"]}>
        <LocationTracker />
        <Routes>
          <Route path="/tro-ly" element={<ArchiveAssistantPage />} />
          <Route path="/van-ban/:documentId" element={<div>Trang xem văn bản</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.type(screen.getByRole("textbox", { name: "Câu hỏi" }), "Hỏi kế hoạch tuyển sinh?");
    await user.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    const chip = await screen.findByTestId("citation-chip-c_multi");
    await user.click(chip);

    await waitFor(() => {
      expect(currentLocation.pathname).toBe("/van-ban/doc_2");
    });

    const searchParams = new URLSearchParams(currentLocation.search);
    expect(searchParams.get("trang")).toBe("3");
    // Must produce multiple distinct khoi parameters: ?trang=3&khoi=b_3_0001&khoi=b_3_0002
    expect(searchParams.getAll("khoi")).toEqual(["b_3_0001", "b_3_0002"]);
    expect(searchParams.get("khoi")).not.toContain(",");
    expect(currentLocation.search).toContain("khoi=b_3_0001&khoi=b_3_0002");
  });

  it("4. The Sidebar shows Trợ lý and it links to /tro-ly", async () => {
    render(
      <MemoryRouter initialEntries={["/van-ban"]}>
        <Sidebar />
      </MemoryRouter>,
    );

    const assistantLink = screen.getByRole("link", { name: /Trợ lý/ });
    expect(assistantLink).toBeInTheDocument();
    expect(assistantLink).toHaveAttribute("href", "/tro-ly");
  });

  it("5. ?trang=2&khoi=b_2_0005 drives the viewer to page 2 with that block highlighted", async () => {
    mockDocumentPageApis();

    const { container } = render(
      <MemoryRouter initialEntries={["/van-ban/doc_1?trang=2&khoi=b_2_0005"]}>
        <Routes>
          <Route path="/van-ban/:documentId" element={<DocumentPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // Page indicator displays page 2
    expect(await screen.findByText("Trang 2 / 2")).toBeInTheDocument();

    // Block highlight is rendered for b_2_0005
    await waitFor(() => {
      const highlight = container.querySelector('[data-source-block-id="b_2_0005"]');
      expect(highlight).toBeInTheDocument();
    });
  });

  it("6. ?trang=abc and ?trang=-1 and ?trang=999 are ignored without crashing", async () => {
    mockDocumentPageApis();

    // 6a: ?trang=abc is ignored and defaults to page 1
    const { unmount: unmountAbc } = render(
      <MemoryRouter initialEntries={["/van-ban/doc_1?trang=abc"]}>
        <Routes>
          <Route path="/van-ban/:documentId" element={<DocumentPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Trang 1 / 2")).toBeInTheDocument();
    unmountAbc();

    // 6b: ?trang=-1 is ignored and defaults to page 1
    const { unmount: unmountNeg } = render(
      <MemoryRouter initialEntries={["/van-ban/doc_1?trang=-1"]}>
        <Routes>
          <Route path="/van-ban/:documentId" element={<DocumentPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Trang 1 / 2")).toBeInTheDocument();
    unmountNeg();

    // 6c: ?trang=999 is out of range and falls back to page 1 without crashing
    const { unmount: unmountOver } = render(
      <MemoryRouter initialEntries={["/van-ban/doc_1?trang=999"]}>
        <Routes>
          <Route path="/van-ban/:documentId" element={<DocumentPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Trang 1 / 2")).toBeInTheDocument();
    unmountOver();
  });
});
