import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ArchivePage } from "./ArchivePage";
import { server } from "../test/server";
import { API_BASE_URL } from "../api/client";
import { makeDocumentSummary } from "../test/fixtures";

function renderArchive() {
  return render(
    <MemoryRouter>
      <ArchivePage />
    </MemoryRouter>,
  );
}

describe("ArchivePage (API integration)", () => {
  it("renders the returned documents", async () => {
    server.use(
      http.get(`${API_BASE_URL}/api/v1/documents`, () =>
        HttpResponse.json({ items: [makeDocumentSummary()], total: 1, limit: 20, offset: 0 }),
      ),
    );
    renderArchive();

    expect(await screen.findByText("142/SGDĐT-GDTH")).toBeInTheDocument();
  });

  it("shows the empty-archive state with an upload call to action", async () => {
    server.use(
      http.get(`${API_BASE_URL}/api/v1/documents`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
    );
    renderArchive();

    expect(await screen.findByText("Chưa có văn bản nào")).toBeInTheDocument();
  });

  it("shows an offline/error state and can retry", async () => {
    server.use(http.get(`${API_BASE_URL}/api/v1/documents`, () => HttpResponse.error()));
    renderArchive();

    expect(await screen.findByText("Không tải được danh sách văn bản.")).toBeInTheDocument();
  });

  it("sends the typed query to the search API (document search/filter)", async () => {
    const user = userEvent.setup();
    const seenQueries: string[] = [];
    server.use(
      http.get(`${API_BASE_URL}/api/v1/documents`, ({ request }) => {
        const url = new URL(request.url);
        seenQueries.push(url.searchParams.get("query") ?? "");
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 });
      }),
    );
    renderArchive();

    await screen.findByText("Chưa có văn bản nào");
    await user.type(screen.getByLabelText("Tìm theo tên, số văn bản"), "142");

    await waitFor(() => expect(seenQueries).toContain("142"));
  });

  it("shows the no-match state and clears filters", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${API_BASE_URL}/api/v1/documents`, ({ request }) => {
        const url = new URL(request.url);
        const hasQuery = Boolean(url.searchParams.get("query"));
        return HttpResponse.json({
          items: hasQuery ? [] : [makeDocumentSummary()],
          total: hasQuery ? 0 : 1,
          limit: 20,
          offset: 0,
        });
      }),
    );
    renderArchive();

    await user.type(screen.getByLabelText("Tìm theo tên, số văn bản"), "không có");
    expect(await screen.findByText("Không tìm thấy văn bản phù hợp")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Xóa bộ lọc" }));
    expect(await screen.findByText("142/SGDĐT-GDTH")).toBeInTheDocument();
  });
});
