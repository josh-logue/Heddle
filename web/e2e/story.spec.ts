// The story tools in a real browser: path highlights, threads, Story Checks, Routes and
// the Path Reader, on the Lantern Tide demo.
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

interface StoreView {
  highlight: { label: string; owner: string; focus: string | null } | null;
  lit: Set<string>;
  thread: { name: string; ids: string[] } | null;
  selected: Set<string>;
  state: { cards: { id: string; outside_story: boolean }[]; routes: { key: string[]; name: string }[] };
  select(ids: string[]): void;
}
const view = (page: Page) => page.evaluate(() => {
  const s = (window as unknown as { heddleCanvas: { store: StoreView } }).heddleCanvas.store;
  return {
    owner: s.highlight?.owner ?? "", label: s.highlight?.label ?? "", focus: s.highlight?.focus ?? null, lit: [...s.lit].sort(),
    thread: s.thread?.ids ?? [], selected: [...s.selected],
  };
});

async function lantern(page: Page) {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await page.waitForFunction(() => !!(window as unknown as { heddleCanvas?: { store: unknown } | null }).heddleCanvas?.store); // (WebKit is slower to start)
}

/** A card's middle on the page. */
function cardAt(page: Page, id: string) {
  return page.evaluate((cid) => {
    const c = (window as unknown as { heddleCanvas: { store: { boxes: Map<string, { x: number; y: number; w: number }> };
      camera: { toScreen(x: number, y: number): [number, number] }; canvas: HTMLCanvasElement } }).heddleCanvas;
    const b = c.store.boxes.get(cid)!;
    const [sx, sy] = c.camera.toScreen(b.x + b.w / 2, b.y + 14);
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + sx, y: r.top + sy };
  }, id);
}

async function clickCard(page: Page, id: string, button: "left" | "right" = "left") {
  const p = await cardAt(page, id);
  await page.mouse.click(p.x, p.y, { button });
}

const banner = (page: Page) => page.locator(".highlight-banner");

test("H lights a card's paths, Shift+H steps the direction, Esc clears", async ({ page }) => {
  await lantern(page);
  await clickCard(page, "ledger");
  await page.keyboard.press("h");
  await expect(banner(page)).toContainText("Paths through “The Stolen Ledger”");
  const lit = (await view(page)).lit;
  expect(lit).toEqual(expect.arrayContaining(["lantern", "warning", "ledger", "offer", "ch2", "act1"])); // groups round lit cards too
  expect(lit).not.toContain("festival");
  await shot(page, "paths");
  await page.keyboard.press("Shift+H");
  await expect(banner(page)).toContainText("What leads to “The Stolen Ledger”");
  await page.keyboard.press("Escape");
  await expect(banner(page)).toHaveCount(0);
  expect((await view(page)).selected).toEqual(["ledger"]); // Esc took the highlight, not the selection
  await page.keyboard.press("h");
  await page.getByRole("button", { name: "Clear" }).click(); // the banner's button
  await expect(banner(page)).toHaveCount(0);
});

test("T follows a character: numbered cards and a banner", async ({ page }) => {
  await lantern(page);
  await clickCard(page, "coldopen");
  await page.keyboard.press("t");
  const dialog = page.getByRole("dialog", { name: "Character thread" });
  await expect(dialog.getByLabel("Follow which character?")).toHaveValue("Tobias Quill"); // the card's first character
  await dialog.getByRole("button", { name: "Show thread" }).click();
  await expect(banner(page)).toContainText("Thread: Tobias Quill");
  await expect(banner(page)).toContainText("introduced in “Cold Open: The Tideway Run”");
  const v = await view(page);
  expect(v.thread[0]).toBe("coldopen");
  expect(v.lit).toContain("s_tobias"); // his strand card lights up too
  await shot(page, "thread");
});

test("the right-click menu reads from a card; the reader steps with the keys and its panel ends it", async ({ page }) => {
  await lantern(page);
  await clickCard(page, "lantern", "right");
  await page.getByRole("menuitem", { name: /Read from here/ }).click();
  const panel = page.getByRole("tabpanel", { name: "Path Reader" });
  await expect(panel.getByRole("heading", { name: "The Eleventh Lantern Fails" })).toBeVisible();
  await expect(banner(page)).toContainText("Reading a path · step 1");
  await page.keyboard.press("ArrowRight"); // the reader has the keyboard
  await expect(panel.getByRole("heading", { name: "Hesk's Warning" })).toBeVisible();
  await page.keyboard.press("Space");
  await page.keyboard.press("ArrowRight");
  await expect(panel.getByRole("heading", { name: "A Smuggler's Offer" })).toBeVisible();
  await expect(panel).toContainText("The story branches here");
  await page.keyboard.press("2");
  expect((await view(page)).focus).toBe("crossing");
  await expect(banner(page)).toContainText("step 5");
  await shot(page, "reader");
  await page.keyboard.press("Backspace");
  await expect(panel.getByRole("heading", { name: "A Smuggler's Offer" })).toBeVisible();
  expect((await view(page)).selected).toEqual(["offer"]); // each step selects its card
  await page.getByRole("button", { name: "Close Path Reader" }).click();
  await expect(banner(page)).toHaveCount(0);
});

test("Story Checks finds a result's cards", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+Shift+K");
  const panel = page.getByRole("tabpanel", { name: "Story Checks" });
  await expect(panel.locator(".panel-summary")).toContainText("route");
  await panel.getByRole("button", { name: /^⚠ +Dead ends/ }).click();
  await expect(banner(page)).toContainText("Check: Dead ends");
  const v = await view(page);
  expect(v.selected.length).toBeGreaterThan(0);
  expect(v.lit).toEqual(expect.arrayContaining(v.selected));
  await shot(page, "checks");
  await page.getByRole("tab", { name: "Story Checks" }).isVisible();
  await page.getByRole("button", { name: "Close Story Checks" }).click(); // leaving the panel ends its highlight
  await expect(banner(page)).toHaveCount(0);
});

test("Routes lights a route and edits its fields", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+Shift+O");
  const panel = page.getByRole("tabpanel", { name: "Routes" });
  const list = panel.getByRole("list", { name: "Routes" });
  await expect(list.locator(".route-row").first()).toBeVisible();
  const first = list.locator(".route-row").first();
  await first.locator(".row-button").click();
  await expect(banner(page)).toContainText("Route: ");
  await first.getByRole("button", { name: "Show the route's cards and fields" }).click();
  await first.getByRole("button", { name: "Edit fields…" }).click();
  const dialog = page.getByRole("dialog", { name: "Edit route" });
  await dialog.getByLabel("Name").fill("The quick way");
  await dialog.getByRole("button", { name: "OK" }).click();
  await expect(first.locator(".row-button")).toHaveText("The quick way");
  await shot(page, "routes");
  await page.keyboard.press("Control+z");
  await expect(first.locator(".row-button")).not.toHaveText("The quick way");
  await panel.getByLabel("Filter routes").fill("zzzz nothing");
  await expect(list.locator(".route-row")).toHaveCount(0);
});

test("O leaves a card out of the story and the menu shows it", async ({ page }) => {
  await lantern(page);
  await clickCard(page, "festival");
  await page.keyboard.press("o");
  const out = () => page.evaluate(() => (window as unknown as { heddleCanvas: { store: StoreView } }).heddleCanvas.store
    .state.cards.find((c) => c.id === "festival")!.outside_story);
  expect(await out()).toBe(true);
  await clickCard(page, "festival", "right");
  await expect(page.getByRole("menuitemcheckbox", { name: /Not part of the story/ })).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape");
  await expect(page.locator(".board canvas, canvas").first()).toBeFocused(); // the board has the keyboard back
  await page.keyboard.press("o");
  expect(await out()).toBe(false);
});

test("Show thread from the Strands panel", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+Shift+B");
  const panel = page.getByRole("tabpanel", { name: "Strands" });
  await panel.getByLabel("Find a strand").fill("hesk");
  await panel.getByRole("option", { name: /Old Hesk/ }).click();
  await panel.getByRole("button", { name: "Show thread" }).click();
  await expect(banner(page)).toContainText("Thread: Old Hesk · 2 cards");
});
