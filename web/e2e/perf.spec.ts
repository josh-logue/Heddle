// A 1,000-card board: how long opening, drawing, dragging, editing, undo, the "avoid
// cards" routing and the story tools take. The budgets are generous (a slow machine
// mustn't fail them); the numbers are printed so changes can be compared.
import { expect, test } from "@playwright/test";

/** 40 groups of 25 cards in a grid; each group a chain with a branch every 5 cards,
 *  groups chained to the next, every 7th arrow labelled. */
function bigBoard(): string {
  const cards: Record<string, unknown>[] = [];
  const connections: Record<string, unknown>[] = [];
  const colours = ["#4a7fc1", "#3f9e6e", "#c9792e", "#7b5ea7", "#c0504d"];
  for (let g = 0; g < 40; g++) {
    const gx = (g % 8) * 1400;
    const gy = Math.floor(g / 8) * 900;
    cards.push({ id: `g${g}`, kind: "group", title: `Chapter ${g + 1}`, color: colours[g % 5], x: gx, y: gy });
    for (let i = 0; i < 25; i++) {
      const id = `c${g}-${i}`;
      cards.push({
        id, parent: `g${g}`, title: `Scene ${g + 1}.${i + 1}`, color: colours[(g + i) % 5],
        x: gx + 30 + (i % 5) * 260, y: gy + 80 + Math.floor(i / 5) * 160,
        description: "Rowan meets Mabel at the East Ward gate and the lamps go out.",
        tags: i % 3 ? ["Act 1"] : ["Act 2", "Subplot"], characters: i % 2 ? ["Rowan"] : ["Mabel", "Greta"],
      });
      if (i > 0) {
        const from = i % 5 === 0 ? `c${g}-${i - 5}` : `c${g}-${i - 1}`;
        connections.push({ id: `e${g}-${i}`, source: from, target: id, label: i % 7 === 0 ? "if she agrees" : "" });
      }
    }
    if (g > 0) connections.push({ id: `G${g}`, source: `c${g - 1}-24`, target: `c${g}-0` });
  }
  return JSON.stringify({ app: "Heddle", version: 12, cards, connections });
}

test("a 1,000-card board stays quick", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "Timed in Chromium only");
  test.setTimeout(120_000);
  await page.goto("/");
  const t = await page.evaluate(async (text) => {
    type Store = {
      state: { cards: { id: string }[] }; boxes: Map<string, unknown>; history: { current: unknown };
      movedBy(r: string[], dx: number, dy: number): unknown; preview(s: unknown): void; commit(s?: unknown): void;
      updateCard(id: string, d: object): void; undo(): boolean; setDisplay(d: object): void; storyGraph(): unknown;
      highlightPaths(id: string): string;
    };
    type Canvas = { store: Store | null; camera: { scale: number }; fit(): void; resetZoom(): void; centerOn(x: number, y: number): void };
    const w = window as unknown as { heddleCanvas: Canvas; heddleOpen(h: unknown): Promise<void> };
    const time = (fn: () => void, n = 1) => {
      const t0 = performance.now();
      for (let i = 0; i < n; i++) fn();
      return (performance.now() - t0) / n;
    };
    const dir = await navigator.storage.getDirectory();
    const h = await dir.getFileHandle("big.json", { create: true });
    const out = await h.createWritable();
    await out.write(text);
    await out.close();
    const t0 = performance.now();
    await w.heddleOpen(h);
    while (!w.heddleCanvas.store || w.heddleCanvas.store.state.cards.length < 1040) await new Promise((r) => setTimeout(r, 5));
    const open = performance.now() - t0;
    const c = w.heddleCanvas;
    const s = c.store!;
    const draw = () => (c as unknown as { draw(): void }).draw();
    c.resetZoom();
    c.centerOn(700, 450);
    const draw100 = time(draw, 10);
    c.camera.scale = 0.35; // titles on hundreds of cards: the busiest picture
    c.centerOn(5600, 2200);
    const drawMid = time(draw, 10);
    c.fit();
    const drawFit = time(draw, 10);
    const base = s.history.current;
    let k = 0;
    const dragStep = time(() => s.preview(s.movedBy(["c5-3"], ++k * 3, k * 2)), 20);
    s.preview(base);
    const edit = time(() => s.updateCard("c7-7", { title: `Scene ${++k}` }), 10);
    const undo = time(() => s.undo(), 10);
    const avoid = time(() => s.setDisplay({ arrow_routing: "avoid" }));
    const highlight = time(() => s.highlightPaths("c20-12"));
    return { open, draw100, drawMid, drawFit, dragStep, edit, undo, avoid, highlight, scale: c.camera.scale };
  }, bigBoard());

  // Story Checks and Routes, through their panels (they run on the settled board).
  const t1 = Date.now();
  await page.keyboard.press("Control+Shift+K");
  await expect(page.getByRole("tabpanel", { name: "Story Checks" }).locator(".panel-summary")).toContainText("route", { timeout: 20_000 });
  const checks = Date.now() - t1;
  const t2 = Date.now();
  await page.keyboard.press("Control+Shift+O");
  await expect(page.getByRole("tabpanel", { name: "Routes" }).locator(".route-row").first()).toBeVisible({ timeout: 20_000 });
  const routes = Date.now() - t2;

  const report = { ...t, checks, routes };
  console.log("PERF", JSON.stringify(Object.fromEntries(Object.entries(report).map(([k, v]) => [k, Math.round(v * 10) / 10]))));
  expect(t.open).toBeLessThan(5000);
  expect(t.draw100).toBeLessThan(50);
  expect(t.drawMid).toBeLessThan(100);
  expect(t.drawFit).toBeLessThan(100);
  expect(t.dragStep).toBeLessThan(60);
  expect(t.edit).toBeLessThan(150);
  expect(t.undo).toBeLessThan(150);
  expect(checks).toBeLessThan(5000);
  expect(routes).toBeLessThan(5000);
});
