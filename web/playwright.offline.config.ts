import { defineConfig, devices } from "@playwright/test";

// The built site, as published (base /Heddle/): works offline once visited. Separate from
// the main browser tests, which run against the dev server (no service worker there).
export default defineConfig({
  testDir: "e2e-offline",
  outputDir: process.env.PLAYWRIGHT_OUTPUT ?? "test-results",
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: "http://localhost:4174/Heddle/", viewport: { width: 1280, height: 800 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
  webServer: {
    command: "npm run build && npx vite preview --port 4174 --strictPort",
    url: "http://localhost:4174/Heddle/",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
