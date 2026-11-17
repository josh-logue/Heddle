// Refresh the fixtures (web/fixtures) from today's core: `npm run fixtures`.
// For a deliberate change of behaviour or board format only. A case is rewritten only when
// its results changed, so the diff shows exactly what moved; read it before keeping it,
// because this records whatever the core answers now, bugs included.
// It updates existing cases. For a new one, copy a similar case file, change its name and
// input, add it to manifest.json and run this.
// The work happens in tests/fixtures.test.ts under Vitest (Node alone can't load every core
// file: it only strips types), told to refresh by HEDDLE_UPDATE_FIXTURES.
import { spawnSync } from "node:child_process";

const run = spawnSync("npx vitest run tests/fixtures.test.ts", {
  cwd: new URL("..", import.meta.url), shell: true, stdio: "inherit",
  env: { ...process.env, HEDDLE_UPDATE_FIXTURES: "1" },
});
if (run.status !== 0) process.exit(run.status ?? 1);
// What changed (Vitest keeps the test's own output to itself).
console.log("Fixture files changed from the last commit (none listed: nothing changed):");
spawnSync("git status --short -- fixtures", { cwd: new URL("..", import.meta.url), shell: true, stdio: "inherit" });
