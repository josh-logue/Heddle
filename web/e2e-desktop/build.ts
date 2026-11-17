// Playwright's global setup for the desktop tests: build the app the shell serves, and
// with HEDDLE_PACKAGED=1 the packaged app too (unpacked, without an installer).
import { execSync } from "node:child_process";

export default function build(): void {
  if (process.env.HEDDLE_SKIP_BUILD === "1") return;
  execSync("npm run build", { stdio: "inherit" });
  if (process.env.HEDDLE_PACKAGED === "1") execSync("npx electron-builder --win --dir --publish never", { stdio: "inherit" });
}
