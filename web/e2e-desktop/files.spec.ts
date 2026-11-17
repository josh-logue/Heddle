// The desktop shell's files (W9c): native dialogs and real paths, saving in place with a
// backup in the Python app's layout, Save As, Open Recent after a restart, error.log and
// strand pictures. Native dialogs are answered from the main process.
import { expect, test, type Page } from "@playwright/test";
import { existsSync, readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { backupDirFor } from "../desktop/files.ts";
import { answerDialog, focus, launch, makeProfile, quit, type Profile } from "./shell.ts";

const BOARD = JSON.stringify({
  app: "Heddle", version: 12,
  cards: [{ id: "a", title: "Rowan", x: 100, y: 100, characters: ["Rowan"] }], connections: [],
  strands: [{ kind: "characters", name: "Rowan", description: "", picture: "pictures/rowan.png", fields: [] }],
});
// 1×1 PNG
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", "base64");

let profile: Profile;
let board: string;
test.beforeEach(() => {
  profile = makeProfile();
  board = path.join(profile.boards, "Tracks.json");
  writeFileSync(board, BOARD);
});
test.afterEach(() => profile.remove());

async function addCard(page: Page, title: string) {
  await page.getByRole("button", { name: "Add card" }).click();
  const editor = page.getByRole("dialog", { name: "New card" });
  await editor.getByLabel("Title").fill(title);
  await editor.getByRole("button", { name: "OK" }).click();
}

test("opens and saves in place with a backup, follows Save As, and lists it in Open recent after a restart", async () => {
  let { app, page } = await launch(profile);
  await answerDialog(app, "open", board);
  await focus(page);
  await page.keyboard.press("Control+o");
  await expect(page.locator(".board-name")).toHaveText("Tracks");

  await addCard(page, "Mabel");
  await page.keyboard.press("Control+s");
  await expect(page.locator(".board-name")).toHaveText("Tracks");
  expect(readFileSync(board, "utf-8")).toContain('"title": "Mabel"');
  expect(readdirSync(profile.boards)).toEqual(["Tracks.json"]); // (no temporary file left)
  // The file as it was before, kept where the Python app keeps its backups.
  const folder = backupDirFor(board, profile.backups);
  const [kept] = readdirSync(folder);
  expect(kept).toMatch(/^Tracks \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.json$/);
  expect(readFileSync(path.join(folder, kept!), "utf-8")).toBe(BOARD);

  const copy = path.join(profile.boards, "Copy.json");
  await answerDialog(app, "save", copy);
  await page.keyboard.press("Control+Shift+S");
  await expect(page.locator(".board-name")).toHaveText("Copy");
  expect(readFileSync(copy, "utf-8")).toContain('"title": "Mabel"');
  await quit(app);

  ({ app, page } = await launch(profile));
  try {
    await page.getByText("File", { exact: true }).click();
    await page.locator(".menu-items .recent", { hasText: "Copy" }).click();
    await expect(page.locator(".board-name")).toHaveText("Copy");
  } finally {
    await quit(app);
  }
});

test("a cancelled dialog changes nothing", async () => {
  const { app, page } = await launch(profile);
  try {
    await answerDialog(app, "open", null);
    await focus(page);
    await page.keyboard.press("Control+o");
    await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
    await expect(page.locator(".board-name")).toHaveCount(0);
  } finally {
    await quit(app);
  }
});

test("unexpected errors are written to error.log", async () => {
  const { app, page } = await launch(profile);
  try {
    await page.evaluate(() => setTimeout(() => {
      throw new Error("Boom in a test");
    }, 0));
    await expect(page.getByRole("dialog", { name: "Something went wrong" })).toBeVisible();
    const log = path.join(profile.logs, "error.log");
    await expect.poll(() => existsSync(log) && readFileSync(log, "utf-8")).toMatch(/^===== \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} =====\nError: Boom in a test/);
  } finally {
    await quit(app);
  }
});

test("shows a strand's picture from the board's folder", async () => {
  mkdirSync(path.join(profile.boards, "pictures"));
  writeFileSync(path.join(profile.boards, "pictures", "rowan.png"), PNG);
  const { app, page } = await launch(profile);
  try {
    await answerDialog(app, "open", board);
    await focus(page);
    await page.keyboard.press("Control+o");
    await expect(page.locator(".board-name")).toHaveText("Tracks");
    await page.locator(".board-canvas").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Control+Shift+B");
    const panel = page.getByRole("tabpanel", { name: "Strands" });
    await panel.getByRole("option", { name: /Rowan/ }).click();
    const img = panel.getByRole("img", { name: "Picture: pictures/rowan.png" });
    await expect(img).toBeVisible();
    expect(await img.getAttribute("src")).toMatch(/^data:image\/png;base64,/);
  } finally {
    await quit(app);
  }
});
