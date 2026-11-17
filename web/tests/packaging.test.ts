// The packaged desktop app (electron-builder.yml) must hold every file its main process and
// preload import: a missing one only shows when the installed app fails to start.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const WEB = fileURLToPath(new URL("..", import.meta.url));

/** Files reachable from `entry` by relative imports. */
function imported(entry: string, seen = new Set<string>()): Set<string> {
  if (seen.has(entry)) return seen;
  seen.add(entry);
  const text = readFileSync(path.join(WEB, entry), "utf-8");
  for (const m of text.matchAll(/(?:^|\n)\s*(?:import|export)\s[^;]*?from\s+"(\.{1,2}\/[^"]+)"|require\("(\.{1,2}\/[^"]+)"\)/g)) {
    const spec = m[1] ?? m[2]!;
    if (/^import\s+type\s/.test(m[0].trim())) continue; // (types only: erased)
    imported(path.posix.normalize(path.posix.join(path.posix.dirname(entry), spec)), seen);
  }
  return seen;
}

describe("the packaged app", () => {
  it("holds every file the shell imports", () => {
    const yml = readFileSync(path.join(WEB, "electron-builder.yml"), "utf-8");
    const listed = new Set([...yml.matchAll(/^ {2}- ([\w./-]+)$/gm)].map((m) => m[1]!));
    const needed = [...imported("desktop/main.ts"), ...imported("desktop/preload.cjs")];
    expect(needed).toContain("src/core/casefoldTable.ts");
    expect(needed.filter((f) => !listed.has(f))).toEqual([]);
  });
});
