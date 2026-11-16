import { defineConfig, devices } from "@playwright/test";

// Browser tests (real mouse, keyboard and screenshots) against the dev server.
// Unit tests are Vitest's (tests/); these live in e2e/.
// Which engines run: HEDDLE_BROWSERS=chromium,webkit,firefox (or --project=…). Locally the
// default leaves Firefox out: Playwright's Firefox build needs the Microsoft Visual C++
// runtime on Windows, which isn't on every machine. CI runs all three.
const BROWSERS = (process.env.HEDDLE_BROWSERS ?? "chromium,webkit,firefox").split(",").map((s) => s.trim())
  .filter((s) => process.env.HEDDLE_BROWSERS || process.env.CI || s !== "firefox");

export default defineConfig({
  testDir: "e2e",
  outputDir: process.env.PLAYWRIGHT_OUTPUT ?? "test-results",
  fullyParallel: true,
  // CI only: one retry, reported as "flaky" (a WebKit test has timed out once under the
  // full parallel load and never on its own).
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:5174",
    viewport: { width: 1280, height: 800 },
  },
  // Chrome and Edge (Chromium), Safari's engine (WebKit) and Firefox. Keys the browser keeps
  // for itself can't be checked here: tests send keys straight to the page.
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "webkit", use: { ...devices["Desktop Safari"], viewport: { width: 1280, height: 800 } } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], viewport: { width: 1280, height: 800 } } },
  ].filter((p) => BROWSERS.includes(p.name)),
  webServer: {
    command: "npm run dev -- --port 5174 --strictPort",
    url: "http://localhost:5174",
    reuseExistingServer: !process.env.CI,
  },
});
