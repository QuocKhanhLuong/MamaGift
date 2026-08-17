import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { LoginPage } from "./LoginPage";
import { SessionProvider } from "../state/SessionContext";
import { server } from "../test/server";
import { API_BASE_URL } from "../api/client";

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/dang-nhap"]}>
      <SessionProvider>
        <Routes>
          <Route path="/dang-nhap" element={<LoginPage />} />
          <Route path="/van-ban" element={<p>Văn bản shell</p>} />
        </Routes>
      </SessionProvider>
    </MemoryRouter>,
  );
}

describe("LoginPage (IA-00)", () => {
  it("enters the shell once connectivity is confirmed", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${API_BASE_URL}/health`, () =>
        HttpResponse.json({ status: "ok", service: "api", version: "0.1.0" }),
      ),
    );
    renderLogin();

    await user.type(screen.getByLabelText("Tên của bạn"), "Mẹ Lan");
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByText("Văn bản shell")).toBeInTheDocument();
  });

  it("shows an offline error without claiming invalid credentials", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${API_BASE_URL}/health`, () => HttpResponse.error()));
    renderLogin();

    await user.type(screen.getByLabelText("Tên của bạn"), "Mẹ Lan");
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(
      await screen.findByText("Không thể kết nối máy chủ. Kiểm tra kết nối mạng và thử lại."),
    ).toBeInTheDocument();
  });

  it("keeps the submit action disabled without a name", () => {
    renderLogin();
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeDisabled();
  });

  it("shows a loading label while submitting", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${API_BASE_URL}/health`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json({ status: "ok", service: "api", version: "0.1.0" });
      }),
    );
    renderLogin();

    await user.type(screen.getByLabelText("Tên của bạn"), "Mẹ Lan");
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(screen.getByRole("button", { name: "Đang đăng nhập…" })).toBeDisabled();
    await waitFor(() => expect(screen.getByText("Văn bản shell")).toBeInTheDocument());
  });
});
