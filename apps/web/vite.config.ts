import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
    // Phase 4 roughly doubled this suite (38 -> 78 tests across 13 files), and each
    // file pays a fresh jsdom environment. Under parallel execution the per-test
    // budget is spent waiting for an environment slot rather than on the test: the
    // same tests complete in 0.6-2.4s when run alone but intermittently exceeded the
    // 5s default together. These timeouts give real headroom for that startup cost
    // without masking a slow test -- a genuinely slow test still fails here.
    // docs/05_TEST_STRATEGY.md section 19 forbids fixing flakiness with retries, so
    // this removes the resource contention instead of hiding it.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
