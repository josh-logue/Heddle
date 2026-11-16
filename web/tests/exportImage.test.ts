// Image export and the SVG writer, settings and the error log. The SVG export runs the real
// drawing code in Node, so what it draws can be checked directly.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { boardFromDict } from "../src/core/model.ts";
import { BoardStore } from "../src/board/store.ts";
import { fakeMeasurer } from "../src/board/text.ts";
import { DARK, LIGHT } from "../src/canvas/theme.ts";
import { SvgContext, SvgPath, escapeXml, svgColor } from "../src/canvas/svg.ts";
import {
  DEFAULT_IMAGE_OPTIONS, MARGIN, MAX_PNG_SIDE, exportCards, exportRect, fittedScale, renderSvg, type ImageOptions,
} from "../src/canvas/exportImage.ts";
import { drawBoard } from "../src/canvas/draw.ts";
import { Camera } from "../src/canvas/camera.ts";
import { PORT_RADIUS } from "../src/board/metrics.ts";
import { MAX_ENTRIES, clearErrors, errorEntries, errorReport, logError } from "../src/platform/errorLog.ts";
import { getOption, setOption } from "../src/platform/settings.ts";

const m = fakeMeasurer();

describe("the SVG writer", () => {
  it("turns canvas colours into SVG colour and opacity", () => {
    expect(svgColor("rgba(10,20,30,0.250)")).toEqual(["rgb(10,20,30)", 0.25]);
    expect(svgColor("#11223380")).toEqual(["#112233", 128 / 255]);
    expect(svgColor("#abcdef")).toEqual(["#abcdef", 1]);
    expect(escapeXml(`<"Rowan" & co>`)).toBe("&lt;&quot;Rowan&quot; &amp; co&gt;");
  });

  it("records paths: rounded rectangles, full circles and curves", () => {
    const p = new SvgPath();
    p.roundRect(0, 0, 100, 40, 6);
    expect(p.data).toBe("M6 0h88a6 6 0 0 1 6 6v28a6 6 0 0 1 -6 6h-88a6 6 0 0 1 -6 -6v-28a6 6 0 0 1 6 -6Z");
    const c = new SvgPath();
    c.arc(10, 10, 5, 0, Math.PI * 2);
    expect(c.data).toBe("M15 10A5 5 0 0 1 5 10A5 5 0 0 1 15 10");
  });

  it("keeps transforms, dashes, opacity and nested clips", () => {
    const ctx = new SvgContext();
    ctx.translate(10, 20);
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.beginPath();
    ctx.rect(0, 0, 50, 50);
    ctx.clip();
    ctx.beginPath();
    ctx.rect(5, 5, 10, 10);
    ctx.clip();
    ctx.strokeStyle = "#ff0000";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 2]);
    ctx.stroke(Object.assign(new SvgPath(), {}) as SvgPath);
    ctx.fillStyle = "rgba(0,0,0,0.5)";
    ctx.textAlign = "center";
    ctx.fillText("A & B", 1, 2);
    ctx.restore();
    ctx.fillRect(0, 0, 1, 1);
    const svg = ctx.svg(100, 80);
    expect(svg).toContain('<clipPath id="c2" clipPathUnits="userSpaceOnUse" clip-path="url(#c1)">');
    expect(svg).toContain('<g clip-path="url(#c2)"><text x="1" y="2" fill="rgb(0,0,0)" fill-opacity="0.25" text-anchor="middle"');
    expect(svg).toContain(">A &amp; B</text>");
    expect(svg).toContain('transform="matrix(1 0 0 1 10 20)"');
    // After restore: no clip, full opacity.
    expect(svg.trim().split("\n").at(-2)).toBe('<path d="M0 0h1v1h-1Z" fill="#000" transform="matrix(1 0 0 1 10 20)"/>');
    expect(svg).toContain('width="100" height="80" viewBox="0 0 100 80"');
  });
});

/** Two cards joined by an arrow, a group holding a third, and a far card. */
function board(): BoardStore {
  return new BoardStore(boardFromDict({
    cards: [
      { id: "a", title: "Rowan & the <Lamp>", x: 0, y: 0 },
      { id: "b", title: "Mabel", x: 400, y: 0 },
      { id: "g", kind: "group", title: "East Ward" },
      { id: "p", title: "Greta", parent: "g", x: 0, y: 400 },
      { id: "far", title: "Warden", x: 2000, y: 2000 },
    ],
    connections: [{ id: "ab", source: "a", target: "b" }],
  }), m);
}
/** The board drawn as on screen (no export look), as SVG. */
function onScreen(s: BoardStore): string {
  const camera = new Camera();
  camera.width = 3000;
  camera.height = 3000;
  camera.ox = -100;
  camera.oy = -100;
  const ctx = new SvgContext();
  drawBoard(ctx as unknown as CanvasRenderingContext2D, {
    store: s, camera, theme: LIGHT, m, hover: {}, dpr: 1, newPath: () => new SvgPath() as unknown as Path2D,
  });
  return ctx.svg(3000, 3000);
}
const opts = (o: Partial<ImageOptions> = {}): ImageOptions => ({ ...DEFAULT_IMAGE_OPTIONS, format: "svg", ...o });

describe("image export", () => {
  it("exports everything, or the selection with what's in selected groups", () => {
    const s = board();
    expect([...exportCards(s, false)].sort()).toEqual(["a", "b", "far", "g", "p"]);
    s.select(["g", "a"]);
    expect([...exportCards(s, true)].sort()).toEqual(["a", "g", "p"]);
    s.setCollapsed(["g"], true);
    expect([...exportCards(s, false)].sort()).toEqual(["a", "b", "far", "g"]); // folded cards aren't drawn
  });

  it("frames the cards with a margin, and shrinks PNGs that would be too big", () => {
    const s = board();
    const a = s.boxes.get("a")!;
    const b = s.boxes.get("b")!;
    const r = exportRect(s, new Set(["a", "b"]))!;
    expect(r.x).toBe(a.x - MARGIN);
    expect(r.x + r.w).toBeCloseTo(b.x + b.w + MARGIN);
    expect(exportRect(s, new Set())).toBeNull();
    expect(fittedScale({ x: 0, y: 0, w: 1000, h: 500 }, 2)).toBe(2);
    expect(fittedScale({ x: 0, y: 0, w: 10_000, h: 500 }, 3)).toBe(MAX_PNG_SIDE / 10_000);
    expect(fittedScale({ x: 0, y: 0, w: 8000, h: 8000 }, 2)).toBeLessThan(MAX_PNG_SIDE / 8000); // the area limit
  });

  it("draws the board as SVG: titles escaped, no selection, handles or toggles", () => {
    const s = board();
    s.select(["a"]);
    const svg = renderSvg(s, LIGHT, m, opts())!;
    expect(svg.startsWith("<?xml")).toBe(true);
    expect(svg).toContain("Rowan &amp; the &lt;Lamp&gt;");
    expect(svg).toContain(">Greta</text>");
    expect(svg).not.toContain(LIGHT.selected); // the selection isn't drawn
    const handle = `A${PORT_RADIUS} ${PORT_RADIUS}`; // a handle's circle
    expect(svg).not.toContain(handle); // nor the handles…
    expect(onScreen(s)).toContain(handle); // …which the screen has
    expect(svg).toContain(`fill="${LIGHT.canvasBg}"`); // the canvas colour, no grid
    const bg = (x: string) => x.split(`fill="${LIGHT.canvasBg}"`).length - 1; // (groups use it as their base too)
    expect(bg(renderSvg(s, LIGHT, m, opts({ transparent: true }))!)).toBe(bg(svg) - 1); // no background
    const onlyA = renderSvg(s, LIGHT, m, opts({ selectionOnly: true }))!;
    expect(onlyA).not.toContain(">Mabel</text>");
    expect(renderSvg(s, DARK, m, opts())).toContain(DARK.canvasBg);
  });

  it("keeps a highlight's fading only when asked", () => {
    const s = board();
    s.highlightPaths("a");
    const plain = renderSvg(s, LIGHT, m, opts())!;
    const shown = renderSvg(s, LIGHT, m, opts({ asShown: true }))!;
    expect(plain).not.toContain(LIGHT.highlight);
    expect(shown).toContain(LIGHT.highlight);
    expect(shown).toContain('opacity="0.2"');
  });
});

/** localStorage for Node. */
class MemoryStorage {
  private data = new Map<string, string>();
  getItem(k: string) { return this.data.get(k) ?? null; }
  setItem(k: string, v: string) { this.data.set(k, v); }
  removeItem(k: string) { this.data.delete(k); }
}

describe("settings and the error log", () => {
  beforeEach(() => {
    (globalThis as { localStorage?: unknown }).localStorage = new MemoryStorage();
  });
  afterEach(() => {
    delete (globalThis as { localStorage?: unknown }).localStorage;
  });

  it("settings have the desktop's defaults and are remembered; snap keeps its old key", () => {
    expect([getOption("commit_pending_entries"), getOption("wheel_zooms"), getOption("show_banners"), getOption("snap_to_grid")])
      .toEqual([true, false, true, false]);
    setOption("wheel_zooms", true);
    expect(getOption("wheel_zooms")).toBe(true);
    localStorage.setItem("heddle.snap", "on"); // set from the View menu before Settings existed
    expect(getOption("snap_to_grid")).toBe(true);
  });

  it("keeps the newest errors and builds a report", () => {
    expect(errorReport([], "TestBrowser")).toContain("No errors logged.");
    for (let i = 0; i < MAX_ENTRIES + 5; i++) logError(`Error ${i}`, Date.UTC(2026, 10, 16, 9, 0, i));
    const entries = errorEntries();
    expect(entries.length).toBe(MAX_ENTRIES);
    expect(entries[0]!.text).toBe("Error 5");
    const report = errorReport(entries, "TestBrowser");
    expect(report).toContain("Browser: TestBrowser");
    expect(report).toContain("===== 2026-11-16T09:00:54.000Z =====\nError 54");
    clearErrors();
    expect(errorEntries()).toEqual([]);
  });
});
