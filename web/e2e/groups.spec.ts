// Groups in a real browser: dragging cards in and out, the resize grip, the editor's
// member list and arrange options, and the group menu.
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

const BOARD = {
  app: "Heddle", version: 12,
  cards: [
    { id: "g", title: "Act One", kind: "group", color: "#7b5ea7", x: 0, y: 0 },
    { id: "a", title: "Arrival", parent: "g", x: 30, y: 80 },
    { id: "b", title: "Bargain", parent: "g", x: 330, y: 260 },
    { id: "loose", title: "Loose", x: 900, y: 120 },
  ],
  connections: [{ id: "e", source: "a", target: "b" }],
};

async function open(page: Page) {
  await page.addInitScript(() => delete (window as { showOpenFilePicker?: unknown }).showOpenFilePicker);
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Open a board…" }).click();
  await (await chooser).setFiles({ name: "groups.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(BOARD)) });
  await expect(page.locator(".board-name")).toHaveText("groups");
}

type Box = { x: number; y: number; w: number; h: number; headerH: number };
/** A card's frame on the page, and its saved data. */
function cardOf(page: Page, id: string) {
  return page.evaluate((cid) => {
    const c = (window as unknown as { heddleCanvas: {
      store: { boxes: Map<string, Box & { card: Record<string, unknown> }> };
      camera: { toScreen(x: number, y: number): [number, number]; scale: number }; canvas: HTMLCanvasElement;
    } }).heddleCanvas;
    const b = c.store.boxes.get(cid)!;
    const r = c.canvas.getBoundingClientRect();
    const [sx, sy] = c.camera.toScreen(b.x, b.y);
    const k = c.camera.scale;
    return { left: r.left + sx, top: r.top + sy, w: b.w * k, h: b.h * k, header: b.headerH * k, card: b.card };
  }, id);
}

test("drags a card into a group and back out", async ({ page }) => {
  await open(page);
  const loose = await cardOf(page, "loose");
  const g = await cardOf(page, "g");
  await page.mouse.move(loose.left + 40, loose.top + 10);
  await page.mouse.down();
  await page.mouse.move(g.left + g.w - 60, g.top + g.header + 30, { steps: 8 });
  await shot(page, "drop-hint");
  await page.mouse.up();
  expect((await cardOf(page, "loose")).card.parent).toBe("g");
  const inGroup = await cardOf(page, "loose");
  await page.mouse.move(inGroup.left + 40, inGroup.top + 10);
  await page.mouse.down();
  await page.mouse.move(inGroup.left + 40, inGroup.top + 500, { steps: 8 });
  await page.mouse.up();
  expect((await cardOf(page, "loose")).card.parent).toBe("");
});

test("resizes a group with its grip; double-click fits it again", async ({ page }) => {
  await open(page);
  const g = await cardOf(page, "g");
  const grip = { x: g.left + g.w - 5, y: g.top + g.h - 5 };
  await page.mouse.move(grip.x, grip.y);
  await page.mouse.down();
  await page.mouse.move(grip.x + 120, grip.y + 80, { steps: 6 });
  await page.mouse.up();
  const grown = await cardOf(page, "g");
  expect(grown.w).toBeGreaterThan(g.w + 100);
  expect(grown.card.width).toBeGreaterThan(0);
  await shot(page, "resized-group");
  await page.mouse.dblclick(grown.left + grown.w - 5, grown.top + grown.h - 5);
  expect((await cardOf(page, "g")).card.width).toBe(0);
});

test("the group editor sets members, and Save & auto-arrange lays them out", async ({ page }) => {
  await open(page);
  const g = await cardOf(page, "g");
  await page.mouse.dblclick(g.left + 60, g.top + 10);
  const dialog = page.getByRole("dialog", { name: "Edit group" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Find a card").fill("loo");
  await dialog.getByRole("checkbox", { name: "Loose" }).check();
  await dialog.getByLabel("Find a card").fill("");
  await expect(dialog.getByRole("checkbox", { name: "Arrival" })).toBeChecked();
  await shot(page, "group-editor");
  await dialog.getByRole("button", { name: "Save & auto-arrange" }).click();
  await expect(dialog).toBeHidden();
  const a = await cardOf(page, "a");
  const b = await cardOf(page, "b");
  const loose = await cardOf(page, "loose");
  expect(loose.card.parent).toBe("g");
  expect(Math.abs(a.top - b.top)).toBeLessThan(1); // a chain in one row
  expect(b.left).toBeGreaterThan(a.left);
  await page.keyboard.press("Control+z");
  expect((await cardOf(page, "loose")).card.parent).toBe("");
});

test("the group menu arranges and ungroups", async ({ page }) => {
  await open(page);
  const g = await cardOf(page, "g");
  await page.mouse.click(g.left + 60, g.top + 10, { button: "right" });
  await page.getByRole("menuitemcheckbox", { name: "Arrange top to bottom" }).click();
  expect((await cardOf(page, "g")).card.arrange_vertical).toBe(true);
  await page.mouse.click(g.left + 60, g.top + 10, { button: "right" });
  await page.getByRole("menuitem", { name: /Auto-arrange cards/ }).click();
  const a = await cardOf(page, "a");
  const b = await cardOf(page, "b");
  expect(Math.abs(a.left - b.left)).toBeLessThan(1); // top to bottom: one column
  expect(b.top).toBeGreaterThan(a.top);
  await page.mouse.click(g.left + 60, g.top + 10, { button: "right" });
  await page.getByRole("menuitem", { name: "Ungroup (keep cards)" }).click();
  expect((await cardOf(page, "a")).card.parent).toBe("");
});
