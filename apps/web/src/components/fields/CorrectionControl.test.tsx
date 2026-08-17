import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, delay } from "msw";
import { describe, expect, it, vi } from "vitest";

import { CorrectionControl } from "./CorrectionControl";
import { server } from "../../test/server";
import { API_BASE_URL } from "../../api/client";

describe("CorrectionControl (correction interaction)", () => {
  it("submits the corrected value and reports success", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/feedback`, async ({ request }) => {
        const body = (await request.json()) as { corrected_value: string; field_id: string };
        expect(body.field_id).toBe("field_deadline_1");
        return HttpResponse.json(
          {
            id: "fb_1",
            document_id: "doc_1",
            feedback_type: "critical_field_correction",
            field_id: body.field_id,
            corrected_value: body.corrected_value,
            comment: null,
            created_at: "2026-08-14T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );

    render(
      <CorrectionControl
        documentId="doc_1"
        fieldId="field_deadline_1"
        currentValue="25/08/2026"
        onCancel={vi.fn()}
        onSaved={onSaved}
      />,
    );

    const input = screen.getByLabelText("Giá trị mới");
    await user.clear(input);
    await user.type(input, "30/08/2026");
    await user.click(screen.getByRole("button", { name: "Lưu thay đổi" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("30/08/2026"));
  });

  it("shows a saving state and disables duplicate submission", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/feedback`, async () => {
        await delay(50);
        return HttpResponse.json(
          {
            id: "fb_1",
            document_id: "doc_1",
            feedback_type: "critical_field_correction",
            field_id: "field_deadline_1",
            corrected_value: "30/08/2026",
            comment: null,
            created_at: "2026-08-14T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );

    render(
      <CorrectionControl
        documentId="doc_1"
        fieldId="field_deadline_1"
        currentValue="25/08/2026"
        onCancel={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Lưu thay đổi" }));
    expect(screen.getByRole("button", { name: "Đang lưu thay đổi…" })).toBeDisabled();
  });

  it("keeps the entered value and offers retry when saving fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API_BASE_URL}/api/v1/documents/doc_1/feedback`, () =>
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

    render(
      <CorrectionControl
        documentId="doc_1"
        fieldId="field_deadline_1"
        currentValue="25/08/2026"
        onCancel={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Lưu thay đổi" }));

    expect(await screen.findByText("Chưa lưu được thay đổi.")).toBeInTheDocument();
    expect(screen.getByLabelText("Giá trị mới")).toHaveValue("25/08/2026");
    expect(screen.getByRole("button", { name: "Lưu thay đổi" })).toBeEnabled();
  });

  it("cancels without submitting", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <CorrectionControl
        documentId="doc_1"
        fieldId="field_deadline_1"
        currentValue="25/08/2026"
        onCancel={onCancel}
        onSaved={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Hủy" }));
    expect(onCancel).toHaveBeenCalled();
  });
});
