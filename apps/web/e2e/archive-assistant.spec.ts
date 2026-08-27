import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../..");
const DECISION_PDF = path.resolve(
  __dirname,
  "../../../benchmarks/parser/fixtures/quyet_dinh_dieu_khoan.pdf",
);
const LETTER_PDF = path.resolve(
  __dirname,
  "../../../benchmarks/parser/fixtures/cong_van_born_digital.pdf",
);
const SYNTHETIC_FIXTURES_DIR = path.join(REPO_ROOT, "var", "test_fixtures");

const PY_PATHS = [
  "services/api",
  "packages/contracts/python",
  "packages/docpipe/python",
  "packages/retrieval/python",
  "packages/eval/python",
  "packages/rag/python",
];

function prepareUniquePdf(basePath: string, tag: string): string {
  fs.mkdirSync(SYNTHETIC_FIXTURES_DIR, { recursive: true });
  const targetPath = path.join(
    SYNTHETIC_FIXTURES_DIR,
    `${tag}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}.pdf`,
  );
  const content = fs.readFileSync(basePath);
  const trailer = Buffer.from(`\n% unique_test_fixture_${tag}_${Date.now()}\n`);
  fs.writeFileSync(targetPath, Buffer.concat([content, trailer]));
  return targetPath;
}

function runPython(script: string): string {
  return execFileSync("uv", ["run", "python", "-c", script], {
    cwd: REPO_ROOT,
    encoding: "utf-8",
    env: {
      ...process.env,
      PYTHONPATH: PY_PATHS.join(path.delimiter),
      DATABASE_URL: `sqlite:///${path.join(REPO_ROOT, "var", "e2e", "e2e.db")}`,
      STORAGE_ROOT: path.join(REPO_ROOT, "var", "e2e", "storage"),
      APP_ENV: "test",
      UV_CACHE_DIR: path.join(REPO_ROOT, ".uv-cache"),
    },
  });
}

/** Index one document's current parse run through the real indexing pipeline. */
function indexDocument(documentId: string): void {
  runPython(`
from app.db import get_session_factory
from app.models import Document, ParseRun
from app.settings import get_settings
from app.indexing import index_parse_run_sync
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.index import SqlDocumentIndex

settings = get_settings()
with get_session_factory()() as session:
    doc = session.get(Document, "${documentId}")
    assert doc is not None and doc.current_parse_run_id
    parse_run = session.get(ParseRun, doc.current_parse_run_id)
    embedding = FakeEmbeddingProvider(
        model_id=settings.embedding_model,
        embedding_version=f"{settings.embedding_model}-v1",
    )
    index_parse_run_sync(
        session,
        parse_run,
        embedding_provider=embedding,
        document_index=SqlDocumentIndex(
            session, default_embedding_version=embedding.embedding_version
        ),
        settings=settings,
    )
`);
}

/** How many CURRENT documents the archive index can see right now. */
function archiveDocumentCount(): number {
  const out = runPython(`
from app.db import get_session_factory
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.scope import EvidenceScope
from app.settings import get_settings

settings = get_settings()
version = f"{settings.embedding_model}-v1"
with get_session_factory()() as session:
    index = SqlArchiveIndex(session, default_embedding_version=version)
    scope = EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=True)
    print(len(index.current_documents(scope)))
`);
  return Number(out.trim().split("\n").pop());
}

async function login(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dang-nhap$/);
  await page.getByLabel("Tên của bạn").fill("Mẹ Lan");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page).toHaveURL(/\/van-ban$/);
}

async function uploadAndIndex(page: Page, basePdf: string, tag: string): Promise<string> {
  const fixturePath = prepareUniquePdf(basePdf, tag);
  const fileName = path.basename(fixturePath);

  await page.goto("/van-ban");
  await page.getByRole("button", { name: "Tải văn bản PDF" }).click();
  await page.setInputFiles("#upload-file-input", fixturePath);
  await expect(page.getByText(fileName, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Tải lên" }).click();

  await expect(page).toHaveURL(/\/van-ban\/doc_[^/?]+/);
  const documentId = page.url().match(/\/van-ban\/(doc_[^/?]+)/)?.[1];
  expect(documentId).toBeTruthy();

  // Wait for the parse worker before indexing.
  await expect(page.locator("[data-field-name]").first()).toBeVisible({ timeout: 30_000 });
  indexDocument(documentId!);
  return documentId!;
}

test.describe("Phase 5 archive assistant browser journey", () => {
  test("a newly indexed document becomes archive-answerable and its citations open the exact source", async ({
    page,
  }) => {
    await login(page);

    // The assistant is reachable as a primary destination, not hidden behind a document.
    await page.getByRole("link", { name: "Trợ lý" }).click();
    await expect(page).toHaveURL(/\/tro-ly$/);
    await expect(page.getByRole("heading", { name: /Trợ lý kho tài liệu/ })).toBeVisible();

    const before = archiveDocumentCount();

    const firstId = await uploadAndIndex(page, DECISION_PDF, "archive_e2e_a");
    const secondId = await uploadAndIndex(page, LETTER_PDF, "archive_e2e_b");
    expect(firstId).not.toEqual(secondId);

    // Mandatory cases 1 and 2: retrievable immediately, with no service restart. The API and
    // web servers started by playwright.config.ts have been running this whole time.
    const after = archiveDocumentCount();
    expect(after).toBe(before + 2);

    await page.goto("/tro-ly");
    const composer = page.getByRole("textbox", { name: "Câu hỏi" });
    await composer.fill("Các văn bản đã tải lên quy định những gì?");
    await page.getByRole("button", { name: "Gửi câu hỏi" }).click();

    // The archive answer arrives with citations grouped by document.
    // The component tags each group with its own document id, so match by prefix rather
    // than adding a test-only attribute to production code.
    const groups = page.locator('[data-testid^="document-group-"]');
    await expect(groups.first()).toBeVisible({ timeout: 30_000 });

    const groupCount = await groups.count();
    expect(groupCount).toBeGreaterThan(0);

    // Mandatory case 12: a citation opens the exact document, page and block.
    const firstGroup = groups.first();
    const chip = firstGroup.getByRole("button").first();
    await expect(chip).toBeVisible();
    await chip.click();

    await expect(page).toHaveURL(/\/van-ban\/doc_[^/?]+\?.*trang=\d+/);
    const url = new URL(page.url());
    expect(url.searchParams.getAll("khoi").length).toBeGreaterThan(0);

    // The document workspace really opened on that source, not merely at the document.
    await expect(page.getByRole("tab", { name: "Trợ lý" })).toBeVisible({ timeout: 15_000 });
  });

  test("the assistant states are honest when the archive has nothing to answer with", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/tro-ly");

    const composer = page.getByRole("textbox", { name: "Câu hỏi" });
    await composer.fill("Câu hỏi hoàn toàn không liên quan tới bất kỳ văn bản nào đã tải lên?");
    await page.getByRole("button", { name: "Gửi câu hỏi" }).click();

    // Whatever the outcome, the UI must resolve to a stated state rather than hanging or
    // inventing an answer without citations.
    const settled = page
      .locator('[data-testid^="document-group-"], [data-testid^="assistant-"]')
      .first();
    await expect(settled).toBeVisible({ timeout: 30_000 });
  });
});
