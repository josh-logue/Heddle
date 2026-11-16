// The Card List and Strands panel in a real browser, and dragging a strand onto the board.
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

type Card = { id: string; title: string; kind: string; strand: string; characters: string[]; tags: string[] };
const cards = (page: Page) => page.evaluate(() => (window as unknown as { heddleCanvas: { store: { state: { cards: Card[] } } } })
  .heddleCanvas.store.state.cards);
const selected = (page: Page) => page.evaluate(() => [...(window as unknown as { heddleCanvas: { store: { selected: Set<string> } } }).heddleCanvas.store.selected]);

async function lantern(page: Page) {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
}

/** A card's middle on the page. */
function cardAt(page: Page, id: string) {
  return page.evaluate((cid) => {
    const c = (window as unknown as { heddleCanvas: { store: { boxes: Map<string, { x: number; y: number; w: number }> };
      camera: { toScreen(x: number, y: number): [number, number] }; canvas: HTMLCanvasElement } }).heddleCanvas;
    const b = c.store.boxes.get(cid)!;
    const [sx, sy] = c.camera.toScreen(b.x + b.w / 2, b.y + 40);
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + sx, y: r.top + sy };
  }, id);
}

test("the Card List follows the groups and finds cards", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+Shift+L");
  const panel = page.getByRole("tabpanel", { name: "Card List" });
  const tree = panel.getByRole("tree", { name: "Cards" });
  await expect(tree.getByRole("treeitem").first()).toBeVisible();
  await panel.getByLabel("Find a card").fill("drowned");
  // Two cards have that title: the scene, and a location card in the map.
  await expect(tree.getByRole("treeitem", { name: /The Drowned Market/ })).toHaveCount(2);
  await tree.getByRole("treeitem", { name: /The Drowned Market/ }).first().click();
  expect((await selected(page)).length).toBe(1);
  await shot(page, "card-list");
});

test("the Strands panel describes a strand and renames it everywhere", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+Shift+B");
  const panel = page.getByRole("tabpanel", { name: "Strands" });
  await panel.getByLabel("Find a strand").fill("tobias");
  await panel.getByRole("option", { name: /Tobias Quill/ }).click();
  await expect(panel.getByRole("heading", { name: /Tobias Quill/ })).toBeVisible();
  await panel.getByLabel("Description").fill("A smuggler with a ledger.");
  await panel.getByRole("button", { name: "Add field" }).click();
  await panel.getByLabel("Field value").fill("Smuggler");
  await panel.getByLabel("Field value").press("Enter");
  await expect.poll(() => page.evaluate(() => {
    const s = (window as unknown as { heddleCanvas: { store: { strand(k: string, n: string): { description: string; fields: string[][] } | undefined } } }).heddleCanvas.store;
    return s.strand("characters", "Tobias Quill");
  })).toMatchObject({ description: "A smuggler with a ledger.", fields: [["Field", "Smuggler"]] });
  await shot(page, "strands");

  await panel.getByRole("button", { name: "Rename…" }).click();
  const dialog = page.getByRole("dialog", { name: "Rename strand" });
  await dialog.getByLabel("New name").fill("Tobias Quillon");
  await dialog.getByRole("button", { name: "Rename…" }).click();
  const ask = page.getByRole("dialog", { name: "Heddle" });
  await expect(ask).toContainText(/This changes \d+ cards/);
  await ask.getByRole("button", { name: "Rename" }).click();
  const all = await cards(page);
  expect(all.some((c) => c.characters.includes("Tobias Quill"))).toBe(false);
  expect(all.some((c) => c.characters.includes("Tobias Quillon"))).toBe(true);
});

test("drags a strand onto a card, and onto the blank board for a strand card", async ({ page }) => {
  await lantern(page);
  await page.getByRole("button", { name: /%$/ }).click(); // actual size
  await page.keyboard.press("Control+Shift+B");
  const panel = page.getByRole("tabpanel", { name: "Strands" });
  await panel.getByLabel("Find a strand").fill("Clue");
  const strand = panel.getByRole("option", { name: /^Clue/ });
  const target = await cardAt(page, "hall");
  await strand.dragTo(page.locator(".board-canvas"), { targetPosition: await canvasPoint(page, target) });
  expect((await cards(page)).find((c) => c.id === "hall")!.tags).toContain("Clue");
  await strand.dragTo(page.locator(".board-canvas"), { targetPosition: { x: 40, y: 40 } });
  const made = (await cards(page)).at(-1)!;
  expect([made.kind, made.strand]).toEqual(["strand", "Clue"]);
});

async function canvasPoint(page: Page, p: { x: number; y: number }) {
  const box = (await page.locator(".board-canvas").boundingBox())!;
  return { x: p.x - box.x, y: p.y - box.y };
}

test("Remove unused strands lists what nothing uses", async ({ page }) => {
  await page.goto("/?demo=hollybank-garden");
  await expect(page.locator(".board-name")).toHaveText("Hollybank Garden");
  await page.getByText("Edit", { exact: true }).click();
  await page.getByRole("button", { name: "Remove unused strands…" }).click();
  const dialog = page.getByRole("dialog", { name: "Remove unused strands" });
  // Frost Tender has a description, so it's listed only when asked for.
  await dialog.getByRole("checkbox", { name: /Also list unused strands/ }).check();
  await expect(dialog).toContainText("Frost Tender");
  await dialog.getByRole("button", { name: "Remove" }).click();
  const tags = await page.evaluate(() => (window as unknown as { heddleCanvas: { store: { allValues(f: string): string[] } } }).heddleCanvas.store.allValues("tags"));
  expect(tags).not.toContain("Frost Tender");
});
