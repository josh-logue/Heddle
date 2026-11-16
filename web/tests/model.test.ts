import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { APP_NAME, FORMAT_VERSION } from "../src/core/model.ts";

// Until the W1 fixtures exist, read the Python source directly so the two can't drift.
const modelPy = readFileSync(
  fileURLToPath(new URL("../../heddle/model.py", import.meta.url)),
  "utf-8",
);

describe("board format identifiers", () => {
  it("matches the desktop app's FORMAT_VERSION", () => {
    const match = /^FORMAT_VERSION = (\d+)$/m.exec(modelPy);
    expect(match).not.toBeNull();
    expect(FORMAT_VERSION).toBe(Number(match![1]));
  });

  it("writes the same app name", () => {
    expect(APP_NAME).toBe("Heddle");
  });
});
