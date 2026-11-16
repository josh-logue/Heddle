// Settings, the error report, and exporting (text, PNG, SVG, print to PDF) in a real browser.
// The browser's save dialog can't be driven by a test, so it's hidden here and exports come
// as downloads, as they do in Firefox and Safari.
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    delete (window as unknown as { showSaveFilePicker?: unknown }).showSaveFilePicker;
  });
});

async function lantern(page: Page) {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await page.waitForFunction(() => !!(window as unknown as { heddleCanvas?: { store: unknown } | null }).heddleCanvas?.store); // (WebKit is slower to start)
}

async function fileMenu(page: Page, item: RegExp) {
  const button = page.getByRole("button", { name: item });
  // (a toolbar menu is a <details>: click its summary only while it's closed)
  if (!(await button.isVisible())) await page.getByText("File", { exact: true }).click();
  await button.click();
}

async function downloaded(page: Page, run: () => Promise<void>) {
  const [download] = await Promise.all([page.waitForEvent("download"), run()]);
  return { name: download.suggestedFilename(), path: (await download.path())! };
}

test("exports the story as Markdown, remembering the choices", async ({ page }) => {
  await lantern(page);
  await fileMenu(page, /Export story as text/);
  const dialog = page.getByRole("dialog", { name: "Export story as text" });
  await expect(dialog.getByLabel("The route being read in the Path Reader")).toBeDisabled();
  await dialog.getByLabel("Outline: nested bullet points").check();
  await shot(page, "export-text");
  const file = await downloaded(page, () => dialog.getByRole("button", { name: "Export…" }).click());
  expect(file.name).toBe("Lantern Tide.md");
  const text = readFileSync(file.path, "utf-8");
  expect(text.startsWith("# Lantern Tide")).toBe(true);
  expect(text).toContain("- **The Eleventh Lantern Fails**");
  await fileMenu(page, /Export story as text/);
  await expect(page.getByRole("dialog", { name: "Export story as text" }).getByLabel("Outline: nested bullet points")).toBeChecked();
});

test("exports the route being read", async ({ page }) => {
  await lantern(page);
  const at = await page.evaluate(() => {
    const c = (window as unknown as { heddleCanvas: { store: { boxes: Map<string, { x: number; y: number; w: number }> };
      camera: { toScreen(x: number, y: number): [number, number] }; canvas: HTMLCanvasElement } }).heddleCanvas;
    const b = c.store.boxes.get("lantern")!;
    const [sx, sy] = c.camera.toScreen(b.x + b.w / 2, b.y + 14);
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + sx, y: r.top + sy };
  });
  await page.mouse.click(at.x, at.y, { button: "right" });
  await page.getByRole("menuitem", { name: /Read from here/ }).click();
  await page.keyboard.press("ArrowRight");
  await fileMenu(page, /Export story as text/);
  const dialog = page.getByRole("dialog", { name: "Export story as text" });
  await expect(dialog.getByLabel("The route being read in the Path Reader")).toBeChecked();
  const file = await downloaded(page, () => dialog.getByRole("button", { name: "Export…" }).click());
  const text = readFileSync(file.path, "utf-8");
  expect(text).toContain("# Lantern Tide: a route");
  expect(text).toMatch(/1\. The Eleventh Lantern Fails[\s\S]*2\. Hesk's Warning/);
});

test("exports the board as PNG and SVG, and prints it for PDF", async ({ page }) => {
  await lantern(page);
  await fileMenu(page, /Export board as image/);
  let dialog = page.getByRole("dialog", { name: "Export board as image" });
  await shot(page, "export-image");
  const png = await downloaded(page, () => dialog.getByRole("button", { name: "Export…" }).click());
  expect(png.name).toBe("Lantern Tide.png");
  const bytes = readFileSync(png.path);
  expect(bytes.subarray(1, 4).toString()).toBe("PNG");
  const width = bytes.readUInt32BE(16);
  expect(width).toBeGreaterThan(2000); // 2× by default

  await fileMenu(page, /Export board as image/);
  dialog = page.getByRole("dialog", { name: "Export board as image" });
  await dialog.getByLabel(/SVG drawing/).check();
  await expect(dialog.getByLabel("PNG scale")).toBeDisabled();
  const svg = await downloaded(page, () => dialog.getByRole("button", { name: "Export…" }).click());
  expect(svg.name).toBe("Lantern Tide.svg");
  const text = readFileSync(svg.path, "utf-8");
  expect(text).toContain("<svg");
  expect(text).toContain(">The Stolen Ledger</text>");
  if (shots) {
    // What the SVG looks like in a browser, next to the screen.
    await page.setContent(text.replace(/^<\?xml[^>]*>/, ""));
    await page.screenshot({ path: `${shots}/export-svg.png` });
    await lantern(page);
  }

  await fileMenu(page, /Export board as image/);
  dialog = page.getByRole("dialog", { name: "Export board as image" });
  await dialog.getByLabel(/PDF/).check();
  await dialog.getByRole("button", { name: "Print…" }).click();
  await expect(page.locator("iframe[aria-hidden=true]")).toHaveCount(1);
  expect(await page.locator("iframe[aria-hidden=true]").getAttribute("srcdoc")).toContain("<svg");
});

test("Settings: banners, the wheel, and keeping what's typed in a chip box", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+,");
  const settings = page.getByRole("dialog", { name: "Settings" });
  await shot(page, "settings");
  await settings.getByLabel(/Show bars over the canvas/).uncheck();
  await settings.getByLabel(/Mouse wheel zooms/).check();
  await settings.getByLabel(/Save tag\/location\/character/).uncheck();
  await settings.getByRole("button", { name: "OK" }).click();

  await page.getByRole("button", { name: "Add card" }).click();
  const editor = page.getByRole("dialog", { name: "New card" });
  await editor.getByLabel("Title").fill("Rowan");
  await editor.getByPlaceholder(/Type a tag/).fill("half-typed");
  await editor.getByRole("button", { name: "OK" }).click();
  const tags = await page.evaluate(() => {
    const s = (window as unknown as { heddleCanvas: { store: { state: { cards: { title: string; tags: string[] }[] } } } }).heddleCanvas.store;
    return s.state.cards.find((c) => c.title === "Rowan")!.tags;
  });
  expect(tags).toEqual([]); // not kept: the setting is off

  await page.evaluate(() => {
    const c = (window as unknown as { heddleCanvas: { store: { select(ids: string[]): void }; canvas: HTMLCanvasElement } }).heddleCanvas;
    c.store.select(["ledger"]);
    c.canvas.focus();
  });
  await page.keyboard.press("h");
  await expect(page.locator(".highlight-banner")).toHaveCount(0); // no bar…
  expect(await page.evaluate(() => !!(window as unknown as { heddleCanvas: { store: { highlight: unknown } } }).heddleCanvas.store.highlight)).toBe(true);

  const zoom = page.locator("button.zoom");
  const before = await zoom.textContent();
  await page.mouse.move(640, 400);
  await page.mouse.wheel(0, -200); // plain wheel: zooms now
  await expect(zoom).not.toHaveText(before!);
});

test("an unexpected error is logged and reported, with a copyable report", async ({ page, context, browserName }) => {
  const clipboard = browserName === "chromium"; // (only Chromium lets a test read the clipboard)
  if (clipboard) await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await lantern(page);
  await page.evaluate(() => setTimeout(() => {
    throw new Error("Test failure in a click");
  }));
  const dialog = page.getByRole("dialog", { name: "Something went wrong" });
  await expect(dialog).toContainText("Test failure in a click");
  await shot(page, "error");
  if (clipboard) {
    await dialog.getByRole("button", { name: "Copy error report" }).click();
    await expect(dialog).toContainText("Copied");
    const report = await page.evaluate(() => navigator.clipboard.readText());
    expect(report).toContain("Heddle (web) error report");
    expect(report).toContain("Test failure in a click");
  }
  await dialog.getByRole("button", { name: "Close" }).click();
  await page.keyboard.press("Control+,");
  await expect(page.getByRole("dialog", { name: "Settings" })).toContainText("1 unexpected error logged");
});
