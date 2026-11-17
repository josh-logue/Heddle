// Strand groups in a real browser: made and edited in the Strands panel, ticked in the
// Filter panel, and added to cards by dragging, from the right-click menu and the editor.
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

type Group = { kind: string; name: string; members: string[]; description: string };
type Store = {
  state: { strand_groups: Group[]; cards: { id: string; characters: string[] }[] };
  createStrandGroup(kind: string, name: string, members: string[]): Group | null;
  filter: { selection: Map<string, Set<string>> };
  boxes: Map<string, { x: number; y: number; w: number }>;
};
const store = () => (window as unknown as { heddleCanvas: { store: Store } }).heddleCanvas.store;
const groups = (page: Page) => page.evaluate(() =>
  (window as unknown as { heddleCanvas: { store: Store } }).heddleCanvas.store.state.strand_groups);
const characters = (page: Page, id: string) => page.evaluate((cid) =>
  (window as unknown as { heddleCanvas: { store: Store } }).heddleCanvas.store.state.cards.find((c) => c.id === cid)!.characters, id);
const makeGroup = (page: Page, name: string, members: string[]) => page.evaluate(([n, m]) =>
  (window as unknown as { heddleCanvas: { store: Store } }).heddleCanvas.store.createStrandGroup("characters", n as string, m as string[]),
[name, members] as const);

async function lantern(page: Page) {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await page.waitForFunction(() => !!(window as unknown as { heddleCanvas?: { store: unknown } | null }).heddleCanvas?.store);
}

/** A card's middle on the page. */
function cardAt(page: Page, id: string) {
  return page.evaluate((cid) => {
    const c = (window as unknown as { heddleCanvas: { store: Store; camera: { toScreen(x: number, y: number): [number, number] };
      canvas: HTMLCanvasElement } }).heddleCanvas;
    const b = c.store.boxes.get(cid)!;
    const [sx, sy] = c.camera.toScreen(b.x + b.w / 2, b.y + 40);
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + sx, y: r.top + sy };
  }, id);
}

void store; // (documents the shape page.evaluate reaches)

test("makes a strand group from picked strands and edits it in the Strands panel", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+Shift+B");
  const panel = page.getByRole("tabpanel", { name: "Strands" });
  const chars = panel.getByRole("listbox", { name: "Characters" });
  await chars.getByRole("option", { name: /^Old Hesk/ }).click();
  await chars.getByRole("option", { name: /^The Tidewright/ }).click({ modifiers: ["ControlOrMeta"] });
  await panel.getByRole("button", { name: "New strand group…" }).click();
  const dialog = page.getByRole("dialog", { name: "New Strand Group" });
  await expect(dialog).toContainText("It starts with the 2 characters you picked.");
  await dialog.getByLabel("Name").fill("Harbour folk");
  await dialog.getByRole("button", { name: "Create" }).click();
  expect(await groups(page)).toEqual([{ kind: "characters", name: "Harbour folk", members: ["Old Hesk", "The Tidewright"], description: "" }]);

  // The new group is picked: its strands are under it, and its details show.
  await expect(chars.getByRole("option", { name: "Strand group Harbour folk" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("heading", { name: /Harbour folk/ })).toContainText("character strand group");
  await panel.getByRole("list", { name: "Members" }).getByLabel("Tobias Quill").check();
  await expect.poll(async () => (await groups(page))[0]!.members).toEqual(["Old Hesk", "The Tidewright", "Tobias Quill"]);
  await shot(page, "strand-group");

  // A name the kind already uses is refused.
  await chars.getByRole("option", { name: /^Mira Fenn/ }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Add Mira Fenn to Strand Group" }).hover();
  await page.getByRole("menuitem", { name: "New Strand Group…" }).click();
  const again = page.getByRole("dialog", { name: "New Strand Group" });
  await again.getByLabel("Name").fill("harbour FOLK");
  await expect(again.getByRole("alert")).toHaveText("There's already a character strand group called “harbour FOLK”.");
  await again.getByRole("button", { name: "Cancel" }).click();

  // Right-click the group: delete it; its strands stay.
  await chars.getByRole("option", { name: "Strand group Harbour folk" }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Delete Strand Group" }).click();
  expect(await groups(page)).toEqual([]);
  await expect(chars.getByRole("option", { name: /^Old Hesk/ })).toBeVisible();
});

test("ticking a strand group in the Filter panel ticks its strands", async ({ page }) => {
  await lantern(page);
  await makeGroup(page, "Lamp keepers", ["Mira Fenn", "Captain Ilse Varn"]);
  await page.keyboard.press("Control+L");
  const panel = page.getByRole("tabpanel", { name: "Filter" });
  const group = panel.getByRole("checkbox", { name: "Strand group Lamp keepers" }).first();
  await group.check();
  const ticked = () => page.evaluate(() => [...((window as unknown as { heddleCanvas: { store: Store } }).heddleCanvas
    .store.filter.selection.get("characters") ?? [])].sort());
  expect(await ticked()).toEqual(["captain ilse varn", "mira fenn"]);
  // Untick one strand: the group shows partly ticked; a click ticks it again.
  await panel.getByRole("checkbox", { name: /^Mira Fenn/ }).first().uncheck();
  expect(await group.evaluate((el: HTMLInputElement) => el.indeterminate)).toBe(true);
  await group.click();
  expect(await ticked()).toEqual(["captain ilse varn", "mira fenn"]);
  await shot(page, "filter-strand-group");
});

test("adds a strand group to cards by dragging, from the right-click menu and in the editor", async ({ page }) => {
  await lantern(page);
  await page.getByRole("button", { name: /%$/ }).click(); // actual size
  await makeGroup(page, "Harbour folk", ["Old Hesk", "The Tidewright"]);
  await page.keyboard.press("Control+Shift+B");
  const panel = page.getByRole("tabpanel", { name: "Strands" });

  // Drag the strand group onto a card.
  const target = await cardAt(page, "hall");
  const box = (await page.locator(".board-canvas").boundingBox())!;
  await panel.getByRole("option", { name: "Strand group Harbour folk" })
    .dragTo(page.locator(".board-canvas"), { targetPosition: { x: target.x - box.x, y: target.y - box.y } });
  expect(await characters(page, "hall")).toEqual(["Mira Fenn", "Captain Ilse Varn", "Old Hesk", "The Tidewright"]);
  await page.keyboard.press("Control+z");
  expect(await characters(page, "hall")).toEqual(["Mira Fenn", "Captain Ilse Varn"]);

  // Right-click the card: Add Strand Group ▸ (one kind of group: a flat list).
  await page.mouse.click(target.x, target.y, { button: "right" });
  await page.getByRole("menuitem", { name: "Add Strand Group" }).hover();
  await page.getByRole("menuitem", { name: /Harbour folk/ }).click();
  expect(await characters(page, "hall")).toEqual(["Mira Fenn", "Captain Ilse Varn", "Old Hesk", "The Tidewright"]);
  await page.keyboard.press("Control+z");

  // The card editor's Characters box offers the strand group after the strands.
  await page.mouse.dblclick(target.x, target.y);
  const editor = page.getByRole("dialog", { name: /Edit card/ });
  await editor.getByLabel("Characters").fill("Harbour folk · strand group (2)");
  await expect(editor.getByRole("button", { name: "Remove character Old Hesk" })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Remove character The Tidewright" })).toBeVisible();
  await editor.getByRole("button", { name: "OK" }).click();
  expect(await characters(page, "hall")).toEqual(["Mira Fenn", "Captain Ilse Varn", "Old Hesk", "The Tidewright"]);
});
