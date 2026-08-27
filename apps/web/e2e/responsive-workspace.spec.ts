import { expect, test, type Page } from "@playwright/test";
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

const INTERACTIVE_ROLES = [
  "button",
  "link",
  "tab",
  "textbox",
  "combobox",
  "menuitem",
  "searchbox",
] as const;

/**
 * On the document workspace at tablet and mobile widths the assistant is still not offered:
 * the screen is for reading and verifying the source. The Phase 5 sidebar link lives in a
 * closed drawer here, so nothing assistant-related should be reachable.
 */
async function assertNoInteractiveAssistantControls(page: Page) {
  for (const role of INTERACTIVE_ROLES) {
    await expect(page.getByRole(role, { name: /Trợ lý/i })).toHaveCount(0);
  }
}

/**
 * Phase 3 asserted that no `Trợ lý` control existed anywhere, because the assistant was
 * feature-gated and unbuilt. Phase 5 deliberately promotes it to a primary destination, so
 * the assertion is now the opposite: exactly one navigation link, and no OTHER interactive
 * assistant control loose on the archive screen. Simply deleting the check would have lost
 * the guarantee that the archive screen stays uncluttered on small viewports.
 */
async function assertAssistantIsANavigationDestinationOnly(page: Page) {
  const navigation = page.getByRole("navigation", { name: "Điều hướng chính" });
  await expect(navigation.getByRole("link", { name: "Trợ lý" })).toHaveCount(1);

  for (const role of INTERACTIVE_ROLES) {
    if (role === "link") continue;
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
  await expect(navigation.getByRole("link", { name: "Trợ lý" })).toBeVisible();
  await assertAssistantIsANavigationDestinationOnly(page);

  await page.getByRole("button", { name: "Đóng menu" }).click();
  await expect(page.getByRole("button", { name: "Mở menu" })).toBeVisible();

  // With the menu closed the assistant link is out of the way again, so the archive screen
  // is not competing for space on a small viewport.
  await expect(page.getByRole("link", { name: "Trợ lý" })).toHaveCount(0);
}

async function uploadReviewableDocument(page: Page) {
  const fixturePath = prepareUniquePdf(FIXTURE_PDF, "responsive_workspace");
  const fileName = path.basename(fixturePath);

  await page.getByRole("button", { name: "Tải văn bản PDF" }).click();
  await page.setInputFiles("#upload-file-input", fixturePath);
  await expect(page.getByText(fileName, { exact: true })).toBeVisible();
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
