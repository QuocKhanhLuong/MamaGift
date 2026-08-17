import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../..");
const E2E_DATA_DIR = path.join(REPO_ROOT, "var", "e2e");
const DATABASE_URL = `sqlite:///${path.join(E2E_DATA_DIR, "e2e.db")}`;
const STORAGE_ROOT = path.join(E2E_DATA_DIR, "storage");

const API_PORT = 8123;
const WEB_PORT = 5183;
const API_BASE_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_BASE_URL = `http://127.0.0.1:${WEB_PORT}`;

const PYTHONPATH = ["services/api", "packages/contracts/python", "packages/docpipe/python"].join(
  path.delimiter,
);

const apiEnv = {
  PYTHONPATH,
  UV_CACHE_DIR: path.join(REPO_ROOT, ".uv-cache"),
  DATABASE_URL,
  STORAGE_ROOT,
  APP_ENV: "test",
  CORS_ORIGINS: WEB_BASE_URL,
  MAX_UPLOAD_BYTES: String(50 * 1024 * 1024),
};

/**
 * E2E runs against a real API + worker + SQLite database, not mocks: the required
 * flow (`docs/04_PHASE_PLAN.md` Phase 3) is upload -> background processing ->
 * correction persistence, which only a real backend can prove.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: WEB_BASE_URL,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `rm -rf "${E2E_DATA_DIR}" && mkdir -p "${E2E_DATA_DIR}" && uv run alembic -c services/api/alembic.ini upgrade head && uv run uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port ${API_PORT}`,
      cwd: REPO_ROOT,
      env: apiEnv,
      url: `${API_BASE_URL}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `uv run python -m app.worker --interval 1`,
      cwd: REPO_ROOT,
      env: apiEnv,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT}`,
      cwd: __dirname,
      env: { VITE_API_URL: API_BASE_URL },
      url: WEB_BASE_URL,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
