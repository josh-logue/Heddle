// The web controls (src/controls.md): they parse, and the README's web section matches them
// (as tests/test_improvements.py does for the desktop's).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  CONTROLS_END, CONTROLS_START, inlineRuns, parseControls, readmeSection, readmeWithControls,
} from "../src/core/helpText.ts";

const controls = readFileSync(new URL("../src/controls.md", import.meta.url), "utf-8");
const readme = readFileSync(new URL("../../README.md", import.meta.url), "utf-8");

describe("the web controls", () => {
  it("parse into sections, and a slip is caught", () => {
    const sections = parseControls(controls);
    expect(sections.map(([s]) => s)).toEqual(
      ["Cards", "Connections", "Groups", "Story", "Finding", "Files", "View and settings", "Keys the browser keeps"]);
    expect(() => parseControls("## A\nnot an entry")).toThrow(/line 2/);
  });

  it("match the README (run `npm run help` after editing controls.md)", () => {
    expect(readmeWithControls(readme, controls)).toBe(readme);
    expect(readme.indexOf(CONTROLS_START)).toBeLessThan(readme.indexOf(CONTROLS_END));
  });

  it("escape a | inside a table cell, and mark bold and italic for the Help dialog", () => {
    expect(readmeSection("## S\n- **A**: x | y")).toContain("| A | x " + String.fromCharCode(92) + "| y |");
    expect(inlineRuns("Press **H** or *right-click*.")).toEqual([["Press ", ""], ["H", "b"], [" or ", ""], ["right-click", "i"], [".", ""]]);
  });

  it("mention the web's own keys", () => {
    for (const key of ["N", "T", "Ctrl+,", "F1", "Ctrl+Shift+R", "Ctrl+Shift+K", "Ctrl+Shift+O"]) expect(controls).toContain(key);
  });
});

describe("the desktop's controls", () => {
  const browser = parseControls(controls, "browser");
  const desktop = parseControls(controls, "desktop");
  const actions = (s: ReturnType<typeof parseControls>) => s.flatMap(([, entries]) => entries.map(([a]) => a));

  it("leave out the browser's keys and add the windows; each action once", () => {
    expect(desktop.map(([s]) => s)).toEqual(
      ["Cards", "Connections", "Groups", "Story", "Finding", "Files", "View and settings", "Windows"]);
    for (const s of [browser, desktop]) expect(new Set(actions(s)).size).toBe(actions(s).length);
    const how = (s: ReturnType<typeof parseControls>, action: string) => s.flatMap(([, e]) => e).find(([a]) => a === action)?.[1];
    expect(how(browser, "Add card")).toContain("or N with the board focused");
    expect(how(desktop, "Add card")).toContain("Ctrl+Shift+N");
    expect(how(desktop, "Character thread")).toMatch(/^Ctrl\+T /);
    expect(how(desktop, "Zoom")).toContain("Ctrl+1");
    expect(JSON.stringify(desktop)).not.toMatch(/Chrome|Edge|this browser|browser tabs/);
  });

  it("a mark for another app hides its heading's entries too", () => {
    const text = "## A [desktop]\n- **X**: x\n## B\n- **Y** [browser]: y\n- **Y** [desktop]: why";
    expect(parseControls(text, "browser")).toEqual([["B", [["Y", "y"]]]]);
    expect(parseControls(text, "desktop")).toEqual([["A", [["X", "x"]]], ["B", [["Y", "why"]]]]);
  });
});
