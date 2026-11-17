// Launching the desktop shell for tests: a temporary profile, backups and error log in
// it, hidden windows, and never the Python app's real settings.
import { _electron as electron, type ElectronApplication, type Page } from "@playwright/test";
import { execSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MAIN = fileURLToPath(new URL("../desktop/main.ts", import.meta.url));
export const APP = "heddle://app/Heddle/";
/** HEDDLE_PACKAGED=1: test the packaged app (release/win-unpacked/Heddle.exe, built by the
 *  global setup) instead of `electron desktop/main.ts`. npm run test:packaged. */
const PACKAGED = process.env.HEDDLE_PACKAGED === "1"
  ? fileURLToPath(new URL("../release/win-unpacked/Heddle.exe", import.meta.url)) : null;
const program = (args: string[]) => (PACKAGED ? { executablePath: PACKAGED, args } : { args: [MAIN, ...args] });

export interface Profile {
  dir: string;
  backups: string;
  logs: string;
  /** Where tests keep their board files. */
  boards: string;
  remove(): void;
}

export function makeProfile(): Profile {
  const dir = mkdtempSync(path.join(os.tmpdir(), "heddle-shell-"));
  const boards = path.join(dir, "boards");
  mkdirSync(boards);
  return {
    dir, boards, backups: path.join(dir, "backups"), logs: path.join(dir, "logs"),
    // (Windows may hold the profile for a moment after the shell exits)
    remove: () => rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }),
  };
}

function env(profile: Profile): Record<string, string> {
  const e = {
    ...process.env, HEDDLE_USER_DATA: path.join(profile.dir, "profile"), HEDDLE_HIDDEN: "1",
    HEDDLE_BACKUP_DIR: profile.backups, HEDDLE_LOG_DIR: profile.logs, HEDDLE_REGISTRY_KEY: "",
  } as Record<string, string>;
  delete e.HEDDLE_DEV_URL;
  return e;
}

/** Start the shell (`args`: boards on its command line); its first window. */
export async function launch(profile: Profile, args: string[] = []): Promise<{ app: ElectronApplication; page: Page }> {
  // Right after a shell was killed, its helper processes can hold the one-shell lock for a
  // moment: the new one then hands over and quits. Try again.
  for (let tries = 0; ; tries++) {
    try {
      const app = await electron.launch({ ...program(args), env: env(profile) });
      const page = await app.firstWindow();
      await page.waitForLoadState("domcontentloaded");
      return { app, page };
    } catch (e) {
      if (tries >= 10 || !/closed/i.test(String(e))) throw e;
      await new Promise((r) => setTimeout(r, 500));
    }
  }
}

/** Start the shell again while it's running, as double-clicking a board does: the second
 *  one hands its arguments to the first and quits. Resolves with its exit code. */
export function launchAgain(profile: Profile, args: string[]): Promise<number | null> {
  const electronPath = PACKAGED ?? (createRequire(import.meta.url)("electron") as string);
  const child = spawn(electronPath, PACKAGED ? args : [MAIN, ...args], { env: env(profile), stdio: "ignore" });
  return new Promise((resolve) => child.once("exit", (code) => resolve(code)));
}

/** Close every window as its close button does, and wait for the shell to exit. Pages with
 *  unsaved changes would ask: tests leave none, or answer first. */
export async function quit(app: ElectronApplication): Promise<void> {
  const exited = new Promise<void>((resolve) => app.process().once("exit", () => resolve()));
  await app.evaluate(({ BrowserWindow }) => {
    setTimeout(() => {
      for (const w of BrowserWindow.getAllWindows()) w.close();
    }, 20);
  });
  await exited;
}

/** Stop the shell as a crash would: no questions, nothing saved. (Killing just the main
 *  process on Windows leaves its other processes running, holding the one-shell lock.) */
export async function crash(app: ElectronApplication): Promise<void> {
  const exited = new Promise<void>((resolve) => app.process().once("exit", () => resolve()));
  execSync(`taskkill /F /T /PID ${app.process().pid}`, { stdio: "ignore" });
  await exited;
}

/** Close one window (by its page's title), as its close button does. */
export async function closeWindowTitled(app: ElectronApplication, title: string): Promise<void> {
  await app.evaluate(({ BrowserWindow }, t) => {
    const win = BrowserWindow.getAllWindows().find((w) => w.getTitle() === t);
    if (!win) throw new Error(`No window titled ${t}`);
    setTimeout(() => win.close(), 20);
  }, title);
}

/** The window whose page has this title (waits for it). */
export async function windowTitled(app: ElectronApplication, title: string | RegExp): Promise<Page> {
  for (let i = 0; i < 100; i++) {
    for (const p of app.windows()) {
      const t = await p.title().catch(() => "");
      if (typeof title === "string" ? t === title : title.test(t)) return p;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`No window titled ${String(title)}`);
}

/** The next native Open or Save dialog answers `file` (null: cancelled). */
export async function answerDialog(app: ElectronApplication, kind: "open" | "save", file: string | null): Promise<void> {
  await app.evaluate(({ dialog }, [k, f]) => {
    const result = k === "open" ? { canceled: f === null, filePaths: f ? [f] : [] } : { canceled: f === null, filePath: f ?? "" };
    const name = k === "open" ? "showOpenDialog" : "showSaveDialog";
    (dialog as unknown as Record<string, unknown>)[name] = async () => result;
  }, [kind, file] as const);
}

/** A hidden window has no keyboard focus until something in it is clicked. */
export async function focus(page: Page): Promise<void> {
  if (await page.locator(".board-name").count()) await page.locator(".board-canvas").click({ position: { x: 5, y: 5 } });
  else await page.getByRole("heading", { name: "Heddle" }).click();
}
