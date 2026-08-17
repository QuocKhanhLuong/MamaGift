import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_PDF = path.resolve(
  __dirname,
  "../../../benchmarks/parser/fixtures/quyet_dinh_dieu_khoan.pdf",
);

const INTERACTIVE_ROLES = [
  "button",
  "link",
  "tab",
  "textbox",
  "combobox",
  "menuitem",
  "searchbox",
] as const;

async function assertNoInteractiveAssistantControls(page: Page) {
  for (const role of INTERACTIVE_ROLES) {
    await expect(page.getByRole(role, { name: /Trợ lý/i })).toHaveCount(0);
  }
}

async function signInAndOpenArchive(page: Page) {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dang-nhap$/);

  await page.getByLabel("Tên của bạn").fill("Mẹ Lan");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page).toHaveURL(/\/van-ban$/);
  await expect(page.getByRole("heading", { name: "Văn bản" })).toBeVisible();
}

async function assertArchiveMenu(page: Page) {
  await page.getByRole("button", { name: "Mở menu" }).click();

  const navigation = page.getByRole("navigation", { name: "Điều hướng chính" });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Văn bản" })).toBeVisible();
  await assertNoInteractiveAssistantControls(page);

  await page.getByRole("button", { name: "Đóng menu" }).click();
  await expect(page.getByRole("button", { name: "Mở menu" })).toBeVisible();
  await assertNoInteractiveAssistantControls(page);
}

async function uploadReviewableDocument(page: Page) {
  await page.getByRole("button", { name: "Tải văn bản PDF" }).click();
  await page.setInputFiles("#upload-file-input", FIXTURE_PDF);
  await expect(page.getByText("quyet_dinh_dieu_khoan.pdf", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tải lên" })).toBeEnabled();
  await page.getByRole("button", { name: "Tải lên" }).click();

  await expect(page).toHaveURL(/\/van-ban\/doc_[^/?]+/);
  await expect(page.getByText("Cần kiểm tra", { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  });
}

async function assertSourcePageNavigation(page: Page) {
  const pageIndicator = page.getByText(/^Trang \d+ \/ \d+$/);
  await expect(pageIndicator).toHaveText("Trang 1 / 2");
  await assertNoInteractiveAssistantControls(page);

  await page.getByRole("button", { name: "Trang sau" }).click();
  await expect(pageIndicator).toHaveText("Trang 2 / 2");
  await assertNoInteractiveAssistantControls(page);

  await page.getByRole("button", { name: "Trang trước" }).click();
  await expect(pageIndicator).toHaveText("Trang 1 / 2");
}

test.describe("responsive workspace tablet smoke", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("covers archive, source navigation, and tablet details return", async ({ page }) => {
    await signInAndOpenArchive(page);
    await assertArchiveMenu(page);
    await uploadReviewableDocument(page);
    await assertSourcePageNavigation(page);

    await page.getByRole("tab", { name: "Nội dung đã đọc" }).click();
    await expect(page.getByRole("heading", { name: "Thông tin văn bản" })).toBeVisible();
    await assertNoInteractiveAssistantControls(page);

    await page.getByRole("tab", { name: "Nguồn" }).click();
    await expect(page.getByText("Trang 1 / 2", { exact: true })).toBeVisible();
    await assertNoInteractiveAssistantControls(page);
  });
});

test.describe("responsive workspace mobile smoke", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("covers archive, source navigation, and mobile details return", async ({ page }) => {
    await signInAndOpenArchive(page);
    await assertArchiveMenu(page);
    await uploadReviewableDocument(page);
    await assertSourcePageNavigation(page);

    await page.getByRole("button", { name: "Chi tiết", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Thông tin văn bản" })).toBeVisible();
    await assertNoInteractiveAssistantControls(page);

    await page.getByRole("button", { name: "Văn bản", exact: true }).click();
    await expect(page.getByText("Trang 1 / 2", { exact: true })).toBeVisible();
    await assertNoInteractiveAssistantControls(page);
  });
});
