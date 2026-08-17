import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { UploadDrawer } from "./UploadDrawer";
import { server } from "../../test/server";
import { API_BASE_URL } from "../../api/client";

function renderDrawer(onUploaded = vi.fn()) {
  return render(
    <MemoryRouter initialEntries={["/van-ban"]}>
      <Routes>
        <Route path="/van-ban" element={<UploadDrawer onUploaded={onUploaded} />} />
        <Route path="/van-ban/:documentId" element={<p>Đã mở văn bản</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function pdfFile(name = "cong-van.pdf") {
  return new File(["%PDF-1.7 nội dung"], name, { type: "application/pdf" });
}

describe("UploadDrawer", () => {
  it("keeps the submit action disabled until a file is selected", async () => {
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByRole("button", { name: "Tải văn bản PDF" }));
    expect(screen.getByText("Chọn một tệp PDF để tiếp tục.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tải lên" })).toBeDisabled();
  });

  it("rejects a non-PDF file locally without contacting the server", async () => {
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByRole("button", { name: "Tải văn bản PDF" }));
    const input = document.getElementById("upload-file-input") as HTMLInputElement;
    const badFile = new File(["hello"], "note.txt", { type: "text/plain" });
    // The input's `accept` attribute would make userEvent.upload() filter this file
    // out client-side (as a real browser file picker would); fire the change event
    // directly to exercise the component's own defense-in-depth validation instead,
    // covering drag-and-drop or an "all files" picker selection.
    fireEvent.change(input, { target: { files: [badFile] } });

    expect(await screen.findByText("Chỉ hỗ trợ tệp PDF.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tải lên" })).toBeDisabled();
  });

  it("uploads a selected PDF and opens the new document (upload happy path)", async () => {
    const user = userEvent.setup();
    const onUploaded = vi.fn();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents`, () =>
        HttpResponse.json(
          {
            document: { id: "doc_new", status: "UPLOADED" },
            job: { id: "job_1", status: "QUEUED" },
            duplicate_of_existing: false,
          },
          { status: 202 },
        ),
      ),
    );
    renderDrawer(onUploaded);

    await user.click(screen.getByRole("button", { name: "Tải văn bản PDF" }));
    const input = document.getElementById("upload-file-input") as HTMLInputElement;
    await user.upload(input, pdfFile());
    await user.click(screen.getByRole("button", { name: "Tải lên" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(await screen.findByText("Đã mở văn bản")).toBeInTheDocument();
  });

  it("maps a structured upload error to Vietnamese copy", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents`, () =>
        HttpResponse.json(
          {
            error: {
              code: "encrypted_pdf",
              message: "encrypted",
              retryable: false,
              request_id: "req_1",
              details: {},
            },
          },
          { status: 400 },
        ),
      ),
    );
    renderDrawer();

    await user.click(screen.getByRole("button", { name: "Tải văn bản PDF" }));
    const input = document.getElementById("upload-file-input") as HTMLInputElement;
    await user.upload(input, pdfFile());
    await user.click(screen.getByRole("button", { name: "Tải lên" }));

    expect(
      await screen.findByText("Tệp PDF có mật khẩu, vui lòng gỡ mật khẩu trước khi tải lên."),
    ).toBeInTheDocument();
  });
});
