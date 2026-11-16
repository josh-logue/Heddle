// Editing in a real browser: adding and editing cards, moving, selecting, deleting,
// connecting, undo, and saving.
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

interface Snapshot {
  cards: { id: string; title: string; x: number; y: number }[];
  arrows: { source: string; target: string; label: string }[];
  selected: string[];
  canUndo: boolean;
}

/** The board as the store has it (development builds expose the canvas controller). */
function board(page: Page): Promise<Snapshot> {
  return page.evaluate(() => {
    type Store = {
      state: { cards: Snapshot["cards"]; connections: Snapshot["arrows"] };
      selected: Set<string>;
      history: { canUndo(): boolean };
    };
    const s = (window as unknown as { heddleCanvas: { store: Store } }).heddleCanvas.store;
    return {
      cards: s.state.cards.map((c) => ({ id: c.id, title: c.title, x: c.x, y: c.y })),
      arrows: s.state.connections.map((e) => ({ source: e.source, target: e.target, label: e.label })),
      selected: [...s.selected],
      canUndo: s.history.canUndo(),
    };
  });
}

/** A point on a card, on the page: its middle, or its ● handle. */
function onCard(page: Page, title: string, where: "middle" | "port" = "middle") {
  return page.evaluate(([t, w]) => {
    type Box = { card: { title: string }; x: number; y: number; w: number; h: number; closedH: number };
    const c = (window as unknown as { heddleCanvas: {
      store: { boxes: Map<string, Box> }; camera: { toScreen(x: number, y: number): [number, number] }; canvas: HTMLCanvasElement;
    } }).heddleCanvas;
    const b = [...c.store.boxes.values()].find((x) => x.card.title === t)!;
    const [sx, sy] = w === "port" ? c.camera.toScreen(b.x + b.w, b.y + b.closedH / 2) : c.camera.toScreen(b.x + b.w / 2, b.y + 16);
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + sx, y: r.top + sy };
  }, [title, where] as const);
}

async function newBoard(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Start an empty board" }).click();
  await expect(page.locator(".board-name")).toHaveText("Untitled");
}

async function addCard(page: Page, title: string, x: number, y: number) {
  await page.mouse.dblclick(x, y);
  const dialog = page.getByRole("dialog", { name: "New card" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Title").fill(title);
  await dialog.getByRole("button", { name: "OK" }).click();
  await expect(dialog).toBeHidden();
}

test("adds a card by double-clicking, and undoes and redoes it", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "Rowan arrives", 400, 300);
  expect((await board(page)).cards.map((c) => c.title)).toEqual(["Rowan arrives"]);
  await expect(page.locator(".board-name")).toHaveText("● Untitled");
  await page.keyboard.press("Control+z");
  expect((await board(page)).cards).toEqual([]);
  await page.keyboard.press("Control+y");
  expect((await board(page)).cards.length).toBe(1);
});

test("cancelling a new card's editor leaves no card", async ({ page }) => {
  await newBoard(page);
  await page.locator(".board-canvas").click({ position: { x: 300, y: 300 } });
  await page.keyboard.press("n");
  const dialog = page.getByRole("dialog", { name: "New card" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  expect((await board(page)).cards).toEqual([]);
  expect((await board(page)).canUndo).toBe(false);
});

test("the card editor sets text, chips and colour", async ({ page }) => {
  await newBoard(page);
  await page.mouse.dblclick(400, 300);
  const dialog = page.getByRole("dialog", { name: "New card" });
  await dialog.getByLabel("Title").fill("The Warden");
  await dialog.getByLabel("Tags").fill("Plot");
  await dialog.getByLabel("Tags").press("Enter");
  await dialog.getByLabel("Tags").fill("act 1,");
  await dialog.getByRole("radio", { name: "Green" }).click();
  await dialog.getByLabel("Description").fill("Keeps the lamps.");
  await dialog.getByLabel("Characters").fill("Mabel"); // still typed when OK is pressed: added
  await dialog.getByRole("button", { name: "OK" }).click();
  const card = await page.evaluate(() => {
    const s = (window as unknown as { heddleCanvas: { store: { state: { cards: Record<string, unknown>[] } } } }).heddleCanvas.store;
    return s.state.cards[0];
  });
  expect(card).toMatchObject({ title: "The Warden", tags: ["Plot", "act 1"], color: "#3f9e6e",
    description: "Keeps the lamps.", characters: ["Mabel"] });
  await shot(page, "edited-card");
});

test("drags a card, box-selects and deletes with a question", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "A", 300, 250);
  await addCard(page, "B", 700, 250);
  const a = await onCard(page, "A");
  const before = (await board(page)).cards[0]!;
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(a.x + 60, a.y + 40, { steps: 6 });
  await page.mouse.up();
  const after = (await board(page)).cards[0]!;
  expect([after.x - before.x, after.y - before.y]).toEqual([60, 40]);

  // A box round both cards selects them.
  await page.mouse.move(150, 120);
  await page.mouse.down();
  await page.mouse.move(1150, 600, { steps: 6 });
  await page.mouse.up();
  expect((await board(page)).selected.length).toBe(2);
  await page.keyboard.press("Delete");
  const ask = page.getByRole("dialog", { name: "Heddle" });
  await expect(ask).toContainText("Delete 2 items (2 cards)?");
  await ask.getByRole("button", { name: "Delete" }).click();
  expect((await board(page)).cards).toEqual([]);
  await page.keyboard.press("Control+z");
  expect((await board(page)).cards.length).toBe(2);
});

test("nudges with the arrow keys: one undo step per burst", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "A", 400, 300);
  const a = await onCard(page, "A");
  await page.mouse.click(a.x, a.y); // select it (the canvas has the keyboard)
  const x0 = (await board(page)).cards[0]!.x;
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Shift+ArrowRight");
  await expect.poll(async () => (await board(page)).cards[0]!.x).toBe(x0 + 21);
  await page.waitForTimeout(700); // the burst settles
  await page.keyboard.press("Control+z");
  expect((await board(page)).cards[0]!.x).toBe(x0);
});

test("connects two cards by dragging the handle, and edits the arrow", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "A", 300, 250);
  await addCard(page, "B", 800, 250);
  const port = await onCard(page, "A", "port");
  const b = await onCard(page, "B");
  await page.mouse.move(port.x, port.y);
  await page.mouse.down();
  await page.mouse.move(b.x, b.y + 20, { steps: 8 });
  await page.mouse.up();
  const { arrows, cards } = await board(page);
  expect(arrows).toEqual([{ source: cards[0]!.id, target: cards[1]!.id, label: "" }]);

  const mid = { x: (port.x + b.x - 115) / 2, y: port.y };
  await page.mouse.dblclick(mid.x, mid.y);
  const dialog = page.getByRole("dialog", { name: "Edit arrow" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Label").fill("if she refuses");
  await dialog.getByRole("radio", { name: "Dashed" }).check();
  await dialog.getByRole("button", { name: "OK" }).click();
  expect((await board(page)).arrows[0]!.label).toBe("if she refuses");
  await shot(page, "connected");
});

test("dragging a handle onto empty canvas makes a connected card", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "A", 300, 250);
  const port = await onCard(page, "A", "port");
  await page.mouse.move(port.x, port.y);
  await page.mouse.down();
  await page.mouse.move(port.x + 300, port.y, { steps: 8 });
  await page.mouse.up();
  const dialog = page.getByRole("dialog", { name: "New card" });
  await dialog.getByLabel("Title").fill("B");
  await dialog.getByRole("button", { name: "OK" }).click();
  const { cards, arrows } = await board(page);
  expect(cards.map((c) => c.title)).toEqual(["A", "B"]);
  expect(arrows.length).toBe(1);
  await page.keyboard.press("Control+z"); // the card and its arrow are one step
  expect((await board(page)).cards.length).toBe(1);
  expect((await board(page)).arrows).toEqual([]);
});

test("saves by downloading where the browser can't save in place", async ({ page }) => {
  await page.addInitScript(() => delete (window as { showSaveFilePicker?: unknown }).showSaveFilePicker);
  await newBoard(page);
  await addCard(page, "Rowan", 400, 300);
  const download = page.waitForEvent("download");
  await page.keyboard.press("Control+s");
  const file = await download;
  expect(file.suggestedFilename()).toBe("Untitled.json");
  const text = await (await file.createReadStream()).toArray();
  const saved = JSON.parse(Buffer.concat(text).toString("utf-8"));
  expect(saved.app).toBe("Heddle");
  expect(saved.cards[0].title).toBe("Rowan");
  await expect(page.locator(".board-name")).toHaveText("Untitled");
  await expect(page.getByRole("status")).toContainText("each save downloads a new copy");
});

test("asks before replacing a board with unsaved changes", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "Rowan", 400, 300);
  await page.getByRole("button", { name: "New", exact: true }).click();
  const ask = page.getByRole("dialog", { name: "Heddle" });
  await expect(ask).toContainText("has changes that aren't saved");
  await ask.getByRole("button", { name: "Cancel" }).click();
  expect((await board(page)).cards.length).toBe(1);
});

test("copies and pastes with the keyboard, and duplicates with Ctrl+D", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "Rowan", 300, 250);
  const a = await onCard(page, "Rowan");
  await page.mouse.click(a.x, a.y);
  await page.keyboard.press("Control+c");
  await expect(page.getByRole("status")).toContainText("Copied 1 card");
  await page.mouse.move(700, 450);
  await page.keyboard.press("Control+v");
  let cards = (await board(page)).cards;
  expect(cards.map((c) => c.title)).toEqual(["Rowan", "Rowan"]);
  expect(cards[1]!.id).not.toBe(cards[0]!.id);
  await page.keyboard.press("Control+d");
  cards = (await board(page)).cards;
  expect(cards.length).toBe(3);
  expect([cards[2]!.x - cards[1]!.x, cards[2]!.y - cards[1]!.y]).toEqual([30, 30]);
  await page.keyboard.press("Control+x");
  expect((await board(page)).cards.length).toBe(2);
});

test("right-click menus: delete a card, change an arrow's style", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "A", 300, 250);
  await addCard(page, "B", 800, 250);
  const port = await onCard(page, "A", "port");
  const b = await onCard(page, "B");
  await page.mouse.move(port.x, port.y);
  await page.mouse.down();
  await page.mouse.move(b.x, b.y + 20, { steps: 8 });
  await page.mouse.up();

  await page.mouse.click((port.x + b.x - 115) / 2, port.y, { button: "right" });
  const menu = page.getByRole("menu").first();
  await expect(menu).toBeVisible();
  await menu.getByRole("menuitem", { name: "Line style" }).hover();
  await page.getByRole("menuitemcheckbox", { name: "Dotted" }).click();
  await expect(menu).toBeHidden();
  expect(await page.evaluate(() => (window as unknown as { heddleCanvas: { store: { state: { connections: { style: string }[] } } } })
    .heddleCanvas.store.state.connections[0]!.style)).toBe("dotted");

  await page.mouse.click(b.x, b.y, { button: "right" });
  await expect(page.getByRole("menuitem", { name: /Edit card/ })).toBeVisible();
  await shot(page, "card-menu");
  await page.getByRole("menuitem", { name: /Delete card/ }).click();
  expect((await board(page)).cards.map((c) => c.title)).toEqual(["A"]);
  expect((await board(page)).arrows).toEqual([]);
  await page.keyboard.press("Escape");
});

test("Connect to… (L) connects to the next card clicked; Esc cancels", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "A", 300, 250);
  await addCard(page, "B", 800, 450);
  const a = await onCard(page, "A");
  const b = await onCard(page, "B");
  await page.mouse.click(a.x, a.y);
  await page.keyboard.press("l");
  await page.keyboard.press("Escape");
  await page.mouse.click(b.x, b.y);
  expect((await board(page)).arrows).toEqual([]);
  await page.mouse.click(a.x, a.y);
  await page.keyboard.press("l");
  await page.mouse.move(b.x, b.y, { steps: 4 });
  await shot(page, "connect-to");
  await page.mouse.click(b.x, b.y);
  const { arrows, cards } = await board(page);
  expect(arrows).toEqual([{ source: cards[0]!.id, target: cards[1]!.id, label: "" }]);
});

test("Ctrl+dropping a handle on empty canvas makes a card without the editor", async ({ page }) => {
  await newBoard(page);
  await addCard(page, "A", 300, 250);
  const port = await onCard(page, "A", "port");
  await page.mouse.move(port.x, port.y);
  await page.mouse.down();
  await page.mouse.move(port.x + 300, port.y + 100, { steps: 8 });
  await shot(page, "connect-ghost");
  await page.keyboard.down("Control");
  await page.mouse.up();
  await page.keyboard.up("Control");
  await expect(page.getByRole("dialog")).toBeHidden();
  expect((await board(page)).cards.length).toBe(2);
  expect((await board(page)).arrows.length).toBe(1);
});
