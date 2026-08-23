import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../..");
const FIXTURE_PDF = path.resolve(
  __dirname,
  "../../../benchmarks/parser/fixtures/quyet_dinh_dieu_khoan.pdf",
);

function indexDocument(documentId: string): void {
  execFileSync(
    "uv",
    [
      "run",
      "python",
      "-c",
      `
import sys
from pathlib import Path
repo = Path("${REPO_ROOT}")
for p in reversed([
    repo / "services/api",
    repo / "packages/contracts/python",
    repo / "packages/docpipe/python",
    repo / "packages/retrieval/python",
    repo / "packages/eval/python",
    repo / "packages/rag/python",
]):
    sys.path.insert(0, str(p))

from app.db import get_session_factory
from app.models import Document, ParseRun
from app.settings import get_settings
from app.indexing import index_parse_run_sync
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.index import SqlDocumentIndex

settings = get_settings()
session_factory = get_session_factory()
with session_factory() as session:
    doc = session.get(Document, "${documentId}")
    if doc and doc.current_parse_run_id:
        parse_run = session.get(ParseRun, doc.current_parse_run_id)
        embedding = FakeEmbeddingProvider(
            model_id=settings.embedding_model,
            embedding_version=f"{settings.embedding_model}-v1",
        )
        index = SqlDocumentIndex(session, default_embedding_version=embedding.embedding_version)
        index_parse_run_sync(
            session,
            parse_run,
            embedding_provider=embedding,
            document_index=index,
            settings=settings,
        )
`,
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        DATABASE_URL: `sqlite:///${path.join(REPO_ROOT, "var", "e2e", "e2e.db")}`,
        STORAGE_ROOT: path.join(REPO_ROOT, "var", "e2e", "storage"),
        APP_ENV: "test",
        UV_CACHE_DIR: path.join(REPO_ROOT, ".uv-cache"),
      },
    },
  );
}

function cleanDatabase(): void {
  execFileSync(
    "uv",
    [
      "run",
      "python",
      "-c",
      `
import sys
from pathlib import Path
repo = Path("${REPO_ROOT}")
for p in reversed([
    repo / "services/api",
    repo / "packages/contracts/python",
    repo / "packages/docpipe/python",
    repo / "packages/retrieval/python",
    repo / "packages/eval/python",
    repo / "packages/rag/python",
]):
    sys.path.insert(0, str(p))

from app.db import get_session_factory
from app.models import Document, Job, ParseRun, DocumentChunk, FeedbackEvent
from sqlalchemy import delete

session_factory = get_session_factory()
with session_factory() as session:
    session.execute(delete(DocumentChunk))
    session.execute(delete(FeedbackEvent))
    session.execute(delete(Job))
    session.execute(delete(ParseRun))
    session.execute(delete(Document))
    session.commit()
`,
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        DATABASE_URL: `sqlite:///${path.join(REPO_ROOT, "var", "e2e", "e2e.db")}`,
        STORAGE_ROOT: path.join(REPO_ROOT, "var", "e2e", "storage"),
        APP_ENV: "test",
        UV_CACHE_DIR: path.join(REPO_ROOT, ".uv-cache"),
      },
    },
  );
}

async function loginAndUploadReadyDocument(page: Page): Promise<string> {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dang-nhap$/);

  await page.getByLabel("Tên của bạn").fill("Mẹ Lan");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page).toHaveURL(/\/van-ban$/);
  await expect(page.getByRole("heading", { name: "Văn bản" })).toBeVisible();

  await page.getByRole("button", { name: "Tải văn bản PDF" }).click();
  await page.setInputFiles("#upload-file-input", FIXTURE_PDF);
  await expect(page.getByText("quyet_dinh_dieu_khoan.pdf", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tải lên" })).toBeEnabled();
  await page.getByRole("button", { name: "Tải lên" }).click();

  await expect(page).toHaveURL(/\/van-ban\/doc_[^/?]+/);
  const match = page.url().match(/\/van-ban\/(doc_[^/?]+)/);
  const documentId = match?.[1];
  expect(documentId).toBeTruthy();

  // Wait until parser worker has extracted fields
  const deadlineRow = page.locator('[data-field-name="deadline"]');
  await expect(deadlineRow.getByText("30/04/2026")).toBeVisible({ timeout: 30_000 });

  // Index the parsed run to transition document to READY for Phase 4 Assistant QA
  indexDocument(documentId!);
  await page.reload();

  // Confirm workspace is in READY state with Assistant tab available
  await expect(page.getByRole("tab", { name: "Trợ lý" })).toBeVisible({ timeout: 15_000 });
  return documentId!;
}

test.describe("Phase 4 Grounded Assistant QA browser journey", () => {
  test.afterAll(() => {
    cleanDatabase();
  });

  test("full journey: asks question, verifies grounded answer with citation chip, and navigates to exact source block", async ({
    page,
  }) => {
    await loginAndUploadReadyDocument(page);

    // Open Assistant panel
    await page.getByRole("tab", { name: "Trợ lý" }).click();
    await expect(page.getByRole("heading", { name: "Trợ lý" })).toBeVisible();
    await expect(page.getByText("Hôm nay mẹ cần tìm gì trong văn bản này?")).toBeVisible();

    // First ensure SourceViewer is moved to Page 2 to prove citation jump genuinely changes page
    await page.getByRole("button", { name: "Trang sau" }).click();
    const pageIndicator = page.getByText(/^Trang \d+ \/ \d+$/);
    await expect(pageIndicator).toHaveText("Trang 2 / 2");

    // Ask a factual question about the document
    const composer = page.getByRole("textbox", { name: "Câu hỏi" });
    await composer.fill("Số văn bản là bao nhiêu?");
    await page.getByRole("button", { name: "Gửi câu hỏi" }).click();

    // Verify response status and answer view
    const qaSlot = page.locator('[data-qa-status="answered"]');
    await expect(qaSlot).toBeVisible({ timeout: 15_000 });

    const answerView = page.locator("[data-answer-view]");
    await expect(answerView).toBeVisible();
    await expect(answerView).toContainText("QUY ĐỊNH CHUNG");

    // Assert citation chip renders with correct page label
    const citationChip = page.locator('[data-citation-id="c1"]');
    await expect(citationChip).toBeVisible();
    await expect(citationChip).toContainText("Trang 1");

    // Click the citation chip: must navigate SourceViewer to Page 1 and highlight block b_1_0005
    await citationChip.click();
    await expect(pageIndicator).toHaveText("Trang 1 / 2");

    // Assert the exact cited source block is highlighted on the page
    const highlightedBlock = page.locator('[data-source-block-id="b_1_0005"]');
    await expect(highlightedBlock).toBeVisible();

    // Verify URL search parameters reflect the cited page and block
    await expect(page).toHaveURL(/[?&]page=1/);
    await expect(page).toHaveURL(/[?&]block=b_1_0005/);

    // Click quick question button to verify multi-turn flow
    const quickBtn = page.getByRole("button", { name: "Tóm tắt" });
    await expect(quickBtn).toBeVisible();
    await quickBtn.click();

    // Assert answer updates with citation chip and navigation remains functional
    await expect(qaSlot).toBeVisible({ timeout: 15_000 });
    const quickCitationChip = page.locator('[data-citation-id="c1"]');
    await expect(quickCitationChip).toBeVisible();
    await quickCitationChip.click();
    await expect(page.locator("[data-source-block-id]").first()).toBeVisible();
  });
});
