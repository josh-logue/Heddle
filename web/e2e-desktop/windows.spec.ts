// The desktop shell's windows (W9d), as the Python app's: one board per window, a board
// already open comes forward, Save As won't overwrite a board open elsewhere, one running
// shell (a second launch hands its board over), boards on the command line, the
// desktop's keys and Help, and the window's size remembered.
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { answerDialog, focus, launch, launchAgain, makeProfile, quit, windowTitled, type Profile } from "./shell.ts";

const board = (title: string, characters: string[] = []) =>
  JSON.stringify({ app: "Heddle", version: 12, cards: [{ id: "a", title, x: 100, y: 100, characters }], connections: [] });

let profile: Profile;
let tracks: string;
let garden: string;
test.beforeEach(() => {
  profile = makeProfile();
  tracks = path.join(profile.boards, "Tracks.json");
  garden = path.join(profile.boards, "Garden.json");
  writeFileSync(tracks, board("Rowan", ["Rowan"]));
  writeFileSync(garden, board("Mabel"));
});
test.afterEach(() => profile.remove());

async function openFile(app: ElectronApplication, page: Page, file: string) {
  await answerDialog(app, "open", file);
  await focus(page);
  await page.keyboard.press("Control+o");
}

test("one board per window: an open board comes forward, others open in a new window", async () => {
  const { app, page } = await launch(profile);
  try {
    await openFile(app, page, tracks); // (this window is blank: here)
    await expect(page).toHaveTitle("Tracks · Heddle");
    await openFile(app, page, tracks); // (already here: nothing new)
    await page.waitForTimeout(300);
    expect(app.windows()).toHaveLength(1);

    await openFile(app, page, garden);
    const second = await windowTitled(app, "Garden · Heddle");
    await expect(page).toHaveTitle("Tracks · Heddle"); // (never replaced)
    expect(app.windows()).toHaveLength(2);

    // The second window can't be saved over the first's board.
    await answerDialog(app, "save", tracks);
    await focus(second);
    await second.keyboard.press("Control+Shift+S");
    await expect(second.locator(".error")).toContainText("“Tracks.json” is open in another window");
    expect(readFileSync(tracks, "utf-8")).toBe(board("Rowan", ["Rowan"]));

    // Opening Tracks from the second window brings the first forward instead. (Hidden
    // windows can't take the focus: see which one was asked to.)
    await app.evaluate(({ BrowserWindow }) => {
      const g = globalThis as { focused?: string[] };
      g.focused = [];
      const focus = BrowserWindow.prototype.focus;
      BrowserWindow.prototype.focus = function (this: Electron.BrowserWindow) {
        g.focused!.push(this.getTitle());
        focus.call(this);
      };
    });
    await openFile(app, second, tracks);
    await expect.poll(() => app.evaluate(() => (globalThis as { focused?: string[] }).focused)).toEqual(["Tracks · Heddle"]);
    expect(app.windows()).toHaveLength(2);

    // File → New board: a new window with an empty board.
    await page.getByText("File", { exact: true }).click();
    await page.getByRole("button", { name: /^New board/ }).click();
    const fresh = await windowTitled(app, "Untitled · Heddle");
    await expect(fresh.locator(".board-name")).toHaveText("Untitled");
    expect(app.windows()).toHaveLength(3);
  } finally {
    await quit(app);
  }
});

test("opens boards named on its command line, and a second launch hands its board over", async () => {
  const { app, page } = await launch(profile, [tracks]);
  try {
    await expect(page).toHaveTitle("Tracks · Heddle");
    expect(await launchAgain(profile, [garden])).toBe(0); // (it hands over and quits)
    await windowTitled(app, "Garden · Heddle");
    expect(await launchAgain(profile, [tracks])).toBe(0); // (open already: comes forward)
    await page.waitForTimeout(300);
    expect(app.windows()).toHaveLength(2);
  } finally {
    await quit(app);
  }
});

test("a board handed over goes into a blank window", async () => {
  const { app, page } = await launch(profile);
  try {
    await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
    expect(await launchAgain(profile, [garden])).toBe(0);
    await expect(page).toHaveTitle("Garden · Heddle");
    expect(app.windows()).toHaveLength(1);
  } finally {
    await quit(app);
  }
});

test("the desktop's keys: Ctrl+Shift+N adds a card, Ctrl+T a thread, N does nothing; Help says so", async () => {
  const { app, page } = await launch(profile, [tracks]);
  try {
    await expect(page).toHaveTitle("Tracks · Heddle");
    await focus(page);
    await page.keyboard.press("n");
    await page.waitForTimeout(200);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.keyboard.press("Control+Shift+N");
    const editor = page.getByRole("dialog", { name: "New card" });
    await expect(editor).toBeVisible();
    await editor.getByRole("button", { name: "Cancel" }).click();
    await focus(page);
    await page.keyboard.press("Control+t");
    const thread = page.getByRole("dialog", { name: "Character thread" });
    await expect(thread).toBeVisible();
    await thread.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: "Add card" })).toHaveAttribute("title", /Ctrl\+Shift\+N/);

    await page.keyboard.press("F1");
    const help = page.getByRole("dialog", { name: "Heddle controls" });
    await expect(help).toContainText("Ctrl+Shift+N");
    await expect(help).toContainText("A window per board");
    await expect(help).not.toContainText("Keys the browser keeps");
    await help.getByRole("button", { name: "Close" }).click();
  } finally {
    await quit(app);
  }
});

test("remembers the window's size and place; a second window opens down and right of the first", async () => {
  let { app } = await launch(profile);
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setBounds({ x: 140, y: 120, width: 900, height: 640 }));
  await quit(app);
  ({ app } = await launch(profile, [tracks]));
  try {
    const bounds = () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().map((w) => w.getBounds()).sort((a, b) => a.x - b.x));
    expect(await bounds()).toEqual([{ x: 140, y: 120, width: 900, height: 640 }]);
    expect(await launchAgain(profile, [garden])).toBe(0);
    await windowTitled(app, "Garden · Heddle");
    expect(await bounds()).toEqual([{ x: 140, y: 120, width: 900, height: 640 }, { x: 170, y: 150, width: 900, height: 640 }]);
  } finally {
    await quit(app);
  }
});
