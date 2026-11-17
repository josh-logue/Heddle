// npm run test:packaged: the desktop tests against the packaged app (release/win-unpacked),
// as installed, rather than `electron desktop/main.ts`.
import { execSync } from "node:child_process";

try {
  execSync("npx playwright test -c playwright.desktop.config.ts", { stdio: "inherit", env: { ...process.env, HEDDLE_PACKAGED: "1" } });
} catch {
  process.exit(1);
}
