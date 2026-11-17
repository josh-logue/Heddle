// The desktop shell (W9b, W9d): starts on the built app, keeps the page sandboxed, serves
// only its own files, keeps settings and drafts in its profile across restarts, and asks
// Save / Don't save / Cancel before closing a board with unsaved changes.
import { expect, test } from "@playwright/test";
import { APP, closeWindowTitled, crash, launch, makeProfile, quit, type Profile } from "./shell.ts";

let profile: Profile;
test.beforeEach(() => {
  profile = makeProfile();
});
test.afterEach(() => profile.remove());

test("starts on the built app, sandboxed, with the desktop bridge", async () => {
  const { app, page } = await launch(profile);
  try {
    expect(page.url()).toBe(APP);
    await expect(page).toHaveTitle("Heddle");
    await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
    const seen = await page.evaluate(() => ({
      require: typeof (globalThis as { require?: unknown }).require,
      process: typeof (globalThis as { process?: unknown }).process,
      electron: window.heddleDesktop?.info.electron,
      ipc: typeof (window.heddleDesktop as unknown as Record<string, unknown>)?.ipcRenderer,
    }));
    expect(seen).toEqual({ require: "undefined", process: "undefined", electron: expect.stringMatching(/^\d+\./), ipc: "undefined" });
    // Only the app's files: nothing outside the build, and no other origin.
    const status = (url: string) => page.evaluate((u) => fetch(u).then((r) => r.status, () => -1), url);
    expect(await status(`${APP}index.html`)).toBe(200);
    expect(await status(`${APP}..%2F..%2Fpackage.json`)).toBe(404);
    expect(await status("heddle://app/package.json")).toBe(404);
  } finally {
    await quit(app);
  }
});

test("opens a demo board, and links out open in the user's browser, not the window", async () => {
  const { app, page } = await launch(profile);
  try {
    await page.goto(`${APP}?demo=lantern-tide`);
    await expect(page).toHaveTitle("Lantern Tide · Heddle");
    await expect(page.locator(".board-canvas")).toBeVisible();
    await app.evaluate(({ shell }) => {
      (globalThis as { opened?: string[] }).opened = [];
      shell.openExternal = async (url: string) => void (globalThis as unknown as { opened: string[] }).opened.push(url);
    });
    const popup = await page.evaluate(() => window.open("https://example.com/") === null);
    expect(popup).toBe(true);
    expect(app.windows()).toHaveLength(1);
    expect(await app.evaluate(() => (globalThis as unknown as { opened: string[] }).opened)).toEqual(["https://example.com/"]);
  } finally {
    await quit(app);
  }
});

test("asks before closing a changed board, and offers it back after a crash", async () => {
  let { app, page } = await launch(profile);
  await page.evaluate(() => localStorage.setItem("heddle.theme", "dark"));
  await page.getByRole("button", { name: "Start an empty board" }).click();
  await page.getByRole("button", { name: "Add card" }).click();
  const editor = page.getByRole("dialog", { name: "New card" });
  await editor.getByLabel("Title").fill("Greta");
  await editor.getByRole("button", { name: "OK" }).click();
  await expect(page.locator(".board-name")).toHaveText("● Untitled");

  // The close button: Heddle asks; Cancel keeps the window.
  await closeWindowTitled(app, "● Untitled · Heddle");
  const ask = page.getByRole("dialog", { name: "Save changes?" });
  await expect(ask).toContainText("“Untitled” has changes that aren't saved.");
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(ask).toHaveCount(0);
  expect(app.windows()).toHaveLength(1);

  // The page goes without asking (a crash, or the computer stopping): its draft stays.
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide")));
  await page.waitForTimeout(300); // (the draft is written)
  await crash(app);

  ({ app, page } = await launch(profile));
  try {
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    const offer = page.getByRole("dialog", { name: "Recover unsaved board" });
    await expect(offer).toContainText("wasn't saved before its window closed");
    await expect(offer).toContainText("1 card");
    await offer.getByRole("button", { name: "Recover" }).click();
    await expect(page.locator(".board-name")).toHaveText("● Untitled");
    // Don't save: the window closes, and the draft goes with it.
    await closeWindowTitled(app, "● Untitled · Heddle");
    const exitedAgain = new Promise((resolve) => app.process().once("exit", resolve));
    await page.getByRole("dialog", { name: "Save changes?" }).getByRole("button", { name: "Don't save" }).click();
    await exitedAgain;
  } catch (e) {
    await app.close().catch(() => undefined);
    throw e;
  }
  ({ app, page } = await launch(profile));
  try {
    await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
    await page.waitForTimeout(500);
    await expect(page.getByRole("dialog", { name: "Recover unsaved board" })).toHaveCount(0);
  } finally {
    await quit(app);
  }
});
