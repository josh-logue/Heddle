// Files and safety in a real browser: drafts and recovery, saving in place with backups
// and the changed-on-disk check, Restore, Open Recent and the other-tab warning. Files
// live in the browser's private file system (OPFS), whose handles behave like a picked
// file's in Chrome and Edge.
import { expect, test, type Page } from "@playwright/test";

const shots = process.env.HEDDLE_SHOTS;
async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

const BOARD = JSON.stringify({ app: "Heddle", version: 12, cards: [{ id: "a", title: "Rowan", x: 100, y: 100 }], connections: [] });

/** Write a board file into the private file system, and open it as if picked. */
async function openFile(page: Page, name: string, text = BOARD) {
  await page.evaluate(async ([n, t]) => {
    const dir = await navigator.storage.getDirectory();
    const h = await dir.getFileHandle(n!, { create: true });
    const w = await h.createWritable();
    await w.write(t!);
    await w.close();
    await (window as unknown as { heddleOpen(h: unknown): Promise<void> }).heddleOpen(h);
  }, [name, text]);
  await expect(page.locator(".board-name")).toHaveText(name.replace(/\.json$/, ""));
  await page.waitForFunction(() => !!(window as unknown as { heddleCanvas?: { store: unknown } | null }).heddleCanvas?.store); // (WebKit is slower to start)
}

/** The file's text. A read while the app is writing it can fail for a moment (the browser
 *  swaps the new file in when the write finishes): try again. */
const readFile = (page: Page, name: string) => page.evaluate(async (n) => {
  const dir = await navigator.storage.getDirectory();
  for (let tries = 0; ; tries++) {
    try {
      return await (await (await dir.getFileHandle(n)).getFile()).text();
    } catch (e) {
      if (tries > 20) throw e;
      await new Promise((r) => setTimeout(r, 25));
    }
  }
}, name);

/** Someone else changes the file. */
const writeFile = (page: Page, name: string, text: string) => page.evaluate(async ([n, t]) => {
  const dir = await navigator.storage.getDirectory();
  const w = await (await dir.getFileHandle(n!)).createWritable();
  await w.write(t!);
  await w.close();
}, [name, text]);

const titles = (page: Page) => page.evaluate(() => (window as unknown as { heddleCanvas: { store: { state: { cards: { title: string }[] } } } })
  .heddleCanvas.store.state.cards.map((c) => c.title));

/** Rename the first card through the store (quicker than the editor; it's the saving under test). */
const retitle = (page: Page, title: string) => page.evaluate((t) => {
  const s = (window as unknown as { heddleCanvas: { store: { state: { cards: { id: string }[] }; updateCard(id: string, d: object): void } } }).heddleCanvas.store;
  s.updateCard(s.state.cards[0]!.id, { title: t });
}, title);

const autosave = (page: Page) => page.evaluate(() => (window as unknown as { heddleSession: { autosave(): Promise<void> } }).heddleSession.autosave());

test("an untitled board's draft is offered back after the tab goes", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Start an empty board" }).click();
  await page.getByRole("button", { name: "Add card" }).click();
  const editor = page.getByRole("dialog", { name: "New card" });
  await editor.getByLabel("Title").fill("Greta");
  await editor.getByRole("button", { name: "OK" }).click();
  await autosave(page);
  await expect(page.locator(".save-status")).toContainText("Draft kept");
  await page.reload(); // (the browser asks before leaving: Playwright says yes)
  const offer = page.getByRole("dialog", { name: "Recover unsaved board" });
  await expect(offer).toContainText("“Untitled” wasn't saved before its tab closed");
  await expect(offer).toContainText("1 card");
  await shot(page, "recover");
  await offer.getByRole("button", { name: "Recover" }).click();
  expect(await titles(page)).toEqual(["Greta"]);
  await expect(page.locator(".board-name")).toHaveText("● Untitled"); // still unsaved
  // Its draft stays its own: reloading again offers it again; Delete forgets it.
  await page.reload();
  await page.getByRole("dialog", { name: "Recover unsaved board" }).getByRole("button", { name: "Delete" }).click();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Recover unsaved board" })).toHaveCount(0);
});

test("saving in place backs up the file, refuses to overwrite changes made elsewhere unasked, and Restore brings a version back", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "Saving in place and Open recent are Chrome and Edge features");
  await page.goto("/");
  await openFile(page, "Tracks.json");
  await retitle(page, "Mabel");
  await page.keyboard.press("Control+s");
  await expect.poll(() => readFile(page, "Tracks.json")).toContain("Mabel");
  await expect(page.locator(".board-name")).toHaveText("Tracks");

  // Someone else saves; autosave won't overwrite it without asking.
  await writeFile(page, "Tracks.json", BOARD.replace("Rowan", "Theirs"));
  await retitle(page, "Greta");
  await autosave(page);
  const ask = page.getByRole("dialog", { name: "File changed on disk" });
  await expect(ask).toBeVisible();
  expect(await readFile(page, "Tracks.json")).toContain("Theirs");
  await shot(page, "conflict");
  await ask.getByRole("button", { name: "Overwrite" }).click();
  await expect.poll(() => readFile(page, "Tracks.json")).toContain("Greta");

  // Backups: the file as opened, and their version (kept before overwriting it).
  await page.getByText("File", { exact: true }).click();
  await page.getByRole("button", { name: /Restore from backup/ }).click();
  const restore = page.getByRole("dialog", { name: "Restore from backup" });
  const options = restore.getByRole("option");
  await expect(options).toHaveCount(2);
  await options.nth(0).click(); // newest: theirs
  await shot(page, "restore");
  await restore.getByRole("button", { name: "Restore" }).click();
  expect(await titles(page)).toEqual(["Theirs"]);
  await expect(page.locator(".board-name")).toHaveText("● Tracks"); // restored, not saved
  await page.locator("canvas").first().click({ position: { x: 600, y: 600 } });
  await page.keyboard.press("Control+z");
  expect(await titles(page)).toEqual(["Greta"]);
});

test("Open recent lists files used before, and opening one already open in another tab warns", async ({ page, context, browserName }) => {
  test.skip(browserName !== "chromium", "Saving in place and Open recent are Chrome and Edge features");
  await page.goto("/");
  await openFile(page, "Hollow.json");
  await page.reload();
  await page.getByText("File", { exact: true }).click();
  await page.getByRole("button", { name: "Hollow", exact: true }).click();
  await expect(page.locator(".board-name")).toHaveText("Hollow");
  expect(await titles(page)).toEqual(["Rowan"]);

  const other = await context.newPage();
  await other.goto("/");
  await other.getByText("File", { exact: true }).click();
  await other.getByRole("button", { name: "Hollow", exact: true }).click();
  await expect(other.locator(".notice")).toContainText("also open in another tab");
});

test("autosave can be turned off", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "Saving in place and Open recent are Chrome and Edge features");
  await page.goto("/");
  await openFile(page, "Quiet.json");
  await page.getByText("File", { exact: true }).click();
  await page.getByLabel("Autosave").uncheck();
  await retitle(page, "Mabel");
  await autosave(page);
  expect(await readFile(page, "Quiet.json")).toContain("Rowan");
  await page.reload();
  await page.getByText("File", { exact: true }).click();
  await expect(page.getByLabel("Autosave")).not.toBeChecked(); // remembered by this browser
});
