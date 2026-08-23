import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../..");
const FIXTURE_PDF = path.resolve(
  __dirname,
  "../../../benchmarks/parser/fixtures/quyet_dinh_dieu_khoan.pdf",
);
const SYNTHETIC_FIXTURES_DIR = path.join(REPO_ROOT, "var", "test_fixtures");

function prepareUniquePdf(basePath: string, tag: string): string {
  fs.mkdirSync(SYNTHETIC_FIXTURES_DIR, { recursive: true });
  const targetPath = path.join(
    SYNTHETIC_FIXTURES_DIR,
    `${tag}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}.pdf`,
  );
  const content = fs.readFileSync(basePath);
  const trailerComment = Buffer.from(`\n% unique_test_fixture_${tag}_${Date.now()}\n`);
  fs.writeFileSync(targetPath, Buffer.concat([content, trailerComment]));
  return targetPath;
}

/**
 * Required Phase 3 browser E2E flow (`docs/04_PHASE_PLAN.md` Phase 3):
 * login -> upload -> processing -> open document -> verify metadata -> jump to
 * cited page -> correct field -> reload -> correction persists.
 */
test("upload, verify, correct, and reload keeps the correction", async ({ page }) => {
  const fixturePath = prepareUniquePdf(FIXTURE_PDF, "upload_verify_correct");
  const fileName = path.basename(fixturePath);

  await page.goto("/");
  await expect(page).toHaveURL(/\/dang-nhap$/);

  await page.getByLabel("Tên của bạn").fill("Mẹ Lan");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page).toHaveURL(/\/van-ban$/);
  await expect(page.getByRole("heading", { name: "Văn bản" })).toBeVisible();

  await page.getByRole("button", { name: "Tải văn bản PDF" }).click();
  await page.setInputFiles("#upload-file-input", fixturePath);
  await expect(page.getByText(fileName, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Tải lên" }).click();

  await expect(page).toHaveURL(/\/van-ban\/doc_/);

  // Processing: the worker (poll interval 1s) moves this to a reviewable state.
  await expect(page.getByText("Cần kiểm tra", { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  });

  // Verify metadata: the deadline field is extracted with page/block provenance.
  const deadlineRow = page.locator('[data-field-name="deadline"]');
  await expect(deadlineRow.getByText("30/04/2026")).toBeVisible();

  // Jump to source: the page indicator should move to the field's cited page.
  await deadlineRow.getByRole("button", { name: /Đi tới nguồn/ }).click();
  await expect(page.getByText(/^Trang \d+ \/ \d+$/)).toBeVisible();

  // Correct the field.
  await deadlineRow.getByRole("button", { name: "Sửa" }).click();
  await deadlineRow.locator('input[id^="correction-"]').fill("25/08/2026");
  await deadlineRow.getByRole("button", { name: "Lưu thay đổi" }).click();
  await expect(deadlineRow.getByText("Đã sửa")).toBeVisible();
  await expect(deadlineRow.getByText("25/08/2026")).toBeVisible();

  // Reload: the correction must come back from the server, not client state.
  await page.reload();
  const reloadedRow = page.locator('[data-field-name="deadline"]');
  await expect(reloadedRow.getByText("Đã sửa")).toBeVisible();
  await expect(reloadedRow.getByText("25/08/2026")).toBeVisible();
});
