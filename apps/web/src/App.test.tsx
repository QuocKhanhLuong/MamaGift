import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { App } from "./App";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", service: "api", version: "0.1.0" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders the API health result", async () => {
  render(<App />);

  expect(await screen.findByRole("status")).toHaveTextContent("API hoạt động · phiên bản 0.1.0");
});

it("renders a recoverable API error state", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(new Response("service unavailable", { status: 503 }));

  render(<App />);

  expect(await screen.findByRole("status")).toHaveTextContent("Không thể kết nối API.");
});
