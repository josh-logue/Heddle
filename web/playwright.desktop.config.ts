import { defineConfig } from "@playwright/test";

// The desktop shell (desktop/main.ts) driven by Playwright's Electron support, on the
// built app (built once here, as the shell serves it). Each test launches the shell with
// its own profile folder and a hidden window. Windows only for now (W9f adds CI).
export default defineConfig({
  testDir: "e2e-desktop",
  outputDir: process.env.PLAYWRIGHT_OUTPUT ?? "test-results",
  reporter: process.env.CI ? "github" : "list",
  timeout: 60_000,
  globalSetup: "./e2e-desktop/build.ts",
});
