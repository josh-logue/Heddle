// Finding and panels in a real browser: side panels, the Card panel, the Filter panel and
// its bar, search, Go to Card, Replace, editing several cards, Board Options.
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

type Card = { id: string; title: string; tags: string[]; color: string; parent: string; collapsed: boolean };
function cards(page: Page): Promise<Card[]> {
  return page.evaluate(() => (window as unknown as { heddleCanvas: { store: { state: { cards: Card[] } } } })
    .heddleCanvas.store.state.cards);
}
function selected(page: Page): Promise<string[]> {
  return page.evaluate(() => [...(window as unknown as { heddleCanvas: { store: { selected: Set<string> } } }).heddleCanvas.store.selected]);
}
async function selectCard(page: Page, id: string) {
  await page.evaluate((cid) => (window as unknown as { heddleCanvas: { store: { select(ids: string[]): void } } })
    .heddleCanvas.store.select([cid]), id);
}

async function lantern(page: Page) {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await page.waitForFunction(() => !!(window as unknown as { heddleCanvas?: { store: unknown } | null }).heddleCanvas?.store); // (WebKit is slower to start)
}

async function openPanel(page: Page, name: string) {
  await page.getByText("Panels", { exact: true }).click();
  await page.getByRole("checkbox", { name: new RegExp(`^${name} Ctrl`) }).check(); // (the name ends with its key)
  await page.mouse.click(10, 400); // close the menu
}

test("opens panels on the right, moves one left, remembers the layout", async ({ page }) => {
  await lantern(page);
  await openPanel(page, "Card");
  await openPanel(page, "Filter");
  const right = page.getByRole("complementary", { name: "Right panels" });
  await expect(right.getByRole("tab")).toHaveText(["Card", "Filter"]);
  await right.getByRole("button", { name: "Move Filter to the other side" }).click();
  const left = page.getByRole("complementary", { name: "Left panels" });
  await expect(left.getByRole("tab")).toHaveText(["Filter"]);
  await page.reload();
  await expect(page.getByRole("complementary", { name: "Left panels" }).getByRole("tab")).toHaveText(["Filter"]);
  await shot(page, "panels");
  await page.getByRole("complementary", { name: "Left panels" }).getByRole("button", { name: "Close Filter" }).click();
  await expect(page.getByRole("complementary", { name: "Left panels" })).toHaveCount(0);
});

test("the Card panel edits the selected card as you type", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+Shift+E");
  await selectCard(page, "hall");
  const panel = page.getByRole("tabpanel", { name: "Card" });
  await expect(panel.getByLabel("Title")).toHaveValue("The Warden Hall");
  await panel.getByLabel("Title").fill("The Wardens' Hall");
  await expect.poll(async () => (await cards(page)).find((c) => c.id === "hall")!.title).toBe("The Wardens' Hall");
  await page.keyboard.press("Escape");
  await page.locator(".board-canvas").focus();
  await page.keyboard.press("Control+z");
  await expect(panel.getByLabel("Title")).toHaveValue("The Warden Hall"); // follows the undo
});

test("the filter fades cards, the bar says so, and Clear lifts it", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+l");
  const panel = page.getByRole("tabpanel", { name: "Filter" });
  await panel.getByRole("checkbox", { name: /^Twist/ }).check();
  const bar = page.locator(".filter-banner");
  await expect(bar).toContainText("Filter on");
  await expect(bar).toContainText(/showing \d+ of \d+ cards/);
  await shot(page, "filter");
  await bar.getByRole("button", { name: "Clear" }).click();
  await expect(bar).toHaveCount(0);
  await expect(panel.getByRole("checkbox", { name: /^Twist/ })).not.toBeChecked();
});

test("search steps through matches both ways", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+f");
  await page.keyboard.type("lantern");
  await expect(page.locator(".search-count")).toHaveText(/^1 of \d+$/);
  const first = (await selected(page))[0];
  await page.keyboard.press("Enter");
  await expect(page.locator(".search-count")).toHaveText(/^2 of \d+$/);
  expect((await selected(page))[0]).not.toBe(first);
  await page.keyboard.press("Shift+Enter");
  expect((await selected(page))[0]).toBe(first);
  await expect(page.locator(".notice")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("searchbox", { name: "Search cards" })).toHaveValue("");
});

test("Go to Card jumps to a card by part of its title", async ({ page }) => {
  await lantern(page);
  await page.locator(".board-canvas").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+p");
  const dialog = page.getByRole("dialog", { name: "Go to Card" });
  await dialog.getByLabel("Card title").fill("drowned");
  await expect(dialog.getByRole("option").first()).toContainText("The Drowned Market");
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  expect(await selected(page)).toEqual(["market"]);
});

test("Replace changes text in every card as one step", async ({ page }) => {
  await lantern(page);
  await page.keyboard.press("Control+h");
  const dialog = page.getByRole("dialog", { name: "Replace" });
  await dialog.getByLabel("Find", { exact: true }).fill("Mira");
  await dialog.getByLabel("Replace with").fill("Mirabel");
  await expect(dialog.getByRole("status")).toContainText(/\d+ matches in \d+ cards/);
  await dialog.getByRole("button", { name: "Replace all" }).click();
  await expect(page.locator(".notice")).toContainText(/Replaced text in \d+ cards/);
  const before = (await cards(page)).filter((c) => JSON.stringify(c).includes("Mirabel")).length;
  expect(before).toBeGreaterThan(0);
  await page.keyboard.press("Control+z");
  expect((await cards(page)).some((c) => JSON.stringify(c).includes("Mirabel"))).toBe(false);
});

test("edits several selected cards together", async ({ page }) => {
  await lantern(page);
  await page.evaluate(() => (window as unknown as { heddleCanvas: { store: { select(ids: string[]): void } } })
    .heddleCanvas.store.select(["hall", "test"]));
  await page.locator(".board-canvas").focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Edit 2 cards" });
  await dialog.getByRole("radio", { name: "Red" }).click();
  await dialog.getByLabel("Add tags").fill("Climax");
  await dialog.getByRole("button", { name: "Apply to 2 cards" }).click();
  const two = (await cards(page)).filter((c) => ["hall", "test"].includes(c.id));
  expect(two.every((c) => c.color === "#b8475b" && c.tags.includes("Climax"))).toBe(true);
});

test("Board Options change how the board is drawn", async ({ page }) => {
  await lantern(page);
  await page.getByText("View", { exact: true }).click();
  await page.getByRole("button", { name: /Board options/ }).click();
  const dialog = page.getByRole("dialog", { name: "Board Options" });
  await dialog.getByRole("checkbox", { name: "Grid" }).uncheck();
  await dialog.getByRole("checkbox", { name: "Descriptions" }).uncheck();
  await expect(dialog.getByRole("checkbox", { name: "Compact cards" })).toBeEnabled();
  await dialog.getByRole("button", { name: "OK" }).click();
  const display = await page.evaluate(() => (window as unknown as { heddleCanvas: { store: { state: { display: Record<string, unknown> } } } })
    .heddleCanvas.store.state.display);
  expect(display).toMatchObject({ show_grid: false, show_description: false });
  await shot(page, "no-descriptions");
});
