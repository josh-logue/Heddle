import { defineConfig, devices } from "@playwright/test";

// Browser tests (real mouse, keyboard and screenshots) against the dev server.
// Unit tests are Vitest's (tests/); these live in e2e/.
export default defineConfig({
  testDir: "e2e",
  outputDir: process.env.PLAYWRIGHT_OUTPUT ?? "test-results",
  fullyParallel: true,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:5174",
    viewport: { width: 1280, height: 800 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
  webServer: {
    command: "npm run dev -- --port 5174 --strictPort",
    url: "http://localhost:5174",
    reuseExistingServer: !process.env.CI,
  },
});
