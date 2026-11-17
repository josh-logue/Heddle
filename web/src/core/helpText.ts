// The web controls, written once in src/controls.md: shown by the Help dialog and turned
// into the README's "Web version keys" section (a port of heddle/help_text.py).
//
//   cd web; npm run help      # refresh the README

export const CONTROLS_START = "<!-- web-controls:start (generated from web/src/controls.md: edit that file, then run `npm run help` in web/) -->";
export const CONTROLS_END = "<!-- web-controls:end -->";
const ENTRY = /^- \*\*(.+?)\*\*(?: \[(browser|desktop)\])?: (.+)$/;
const HEADING = /^## (.+?)(?: \[(browser|desktop)\])?$/;

/** Which app's controls: entries and sections marked for the other one are left out. */
export type ControlsKind = "browser" | "desktop";
const BACKSLASH = String.fromCharCode(92); // (escapes a "|" inside a Markdown table cell)

export type Sections = [section: string, entries: [action: string, how: string][]][];

/** controls.md without its editing note. */
export function helpMarkdown(text: string): string {
  return text.replace(/<!--[\s\S]*?-->\s*/g, "").trim() + "\n";
}

/** [(section, [(action, how), …]), …] for one app (the browser's by default). Throws on a
 *  line that isn't a heading, an entry or blank, so a slip in controls.md is caught by the
 *  tests. */
export function parseControls(text: string, kind: ControlsKind = "browser"): Sections {
  const sections: Sections = [];
  let skipping = false; // in a section for the other app
  let started = false;
  helpMarkdown(text).split("\n").forEach((line, i) => {
    if (!line.trim()) return;
    const h = HEADING.exec(line);
    if (line.startsWith("## ") && h) {
      started = true;
      skipping = !!h[2] && h[2] !== kind;
      if (!skipping) sections.push([h[1]!.trim(), []]);
      return;
    }
    const m = ENTRY.exec(line);
    if (!m || !started) throw new Error(`controls.md line ${i + 1} isn't '## Section' or '- **Action**: how': ${line}`);
    if (skipping || (m[2] && m[2] !== kind)) return;
    sections[sections.length - 1]![1].push([m[1]!, m[3]!]);
  });
  return sections;
}

/** The README's tables: one per section. */
export function readmeSection(text: string): string {
  const out: string[] = [];
  for (const [section, entries] of parseControls(text)) {
    out.push(`#### ${section}`, "", "| Action | How |", "|---|---|");
    for (const [action, how] of entries) out.push(`| ${action} | ${how.replaceAll("|", BACKSLASH + "|")} |`);
    out.push("");
  }
  return out.join("\n").trimEnd() + "\n";
}

/** The README with its generated web section brought up to date. */
export function readmeWithControls(readme: string, text: string): string {
  const start = readme.indexOf(CONTROLS_START);
  const end = readme.indexOf(CONTROLS_END);
  if (start < 0 || end < start) throw new Error("README.md has no web-controls:start / web-controls:end markers");
  return readme.slice(0, start) + CONTROLS_START + "\n\n" + readmeSection(text) + "\n" + readme.slice(end);
}

/** **bold** and *italic* runs of one line, for the Help dialog. */
export function inlineRuns(text: string): [string, "b" | "i" | ""][] {
  const out: [string, "b" | "i" | ""][] = [];
  const re = /\*\*(.+?)\*\*|\*(.+?)\*/g;
  let at = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > at) out.push([text.slice(at, m.index), ""]);
    out.push(m[1] !== undefined ? [m[1], "b"] : [m[2]!, "i"]);
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push([text.slice(at), ""]);
  return out;
}
