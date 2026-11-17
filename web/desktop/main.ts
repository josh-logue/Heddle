// Heddle's desktop shell (W9): the web app in its own window, run by Electron.
//
// - The built app (web/dist) is served from a private scheme, heddle://app/Heddle/, so it
//   gets the same paths as the published site and its own storage, and never touches the
//   network. `HEDDLE_DEV_URL` loads Vite's dev server instead (npm run desktop:dev).
// - The page is sandboxed: context isolation, no Node. The preload (preload.cjs) hands it a
//   few plain values and IPC calls (src/platform/bridge.ts); everything here checks that a
//   message comes from the app's own page.
// - No menu bar: the app's toolbar menus are the menus (decided 2026-11-16).
// - One board per window (windows.ts), and one running shell: a second launch hands its
//   board files to this one (`Heddle.exe board.json`, or double-clicking a board).
//
// Electron's Node runs this TypeScript directly (type stripping), so: erasable syntax only.
//
// Environment, for development and tests:
//   HEDDLE_DEV_URL    load this URL (Vite's dev server) instead of the built app
//   HEDDLE_DIST       the built app's folder (default: ../dist)
//   HEDDLE_USER_DATA  the profile folder (default: %APPDATA%\Heddle)
//   HEDDLE_HIDDEN=1   never show the window (tests)
//   HEDDLE_BACKUP_DIR, HEDDLE_LOG_DIR  backups and error.log elsewhere (as the Python app)
//   HEDDLE_REGISTRY_KEY  where the Python app's settings are read from on the first run
//                     ("" = don't)

import { Menu, app, net, protocol, session, shell, type IpcMainEvent, type IpcMainInvokeEvent, type WebContents } from "electron";
import { existsSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { DesktopInfo, DesktopSeed } from "../src/platform/bridge.ts";
import { PYTHON_KEY, readPythonSettings } from "./files.ts";
import { registerIpc } from "./ipc.ts";
import { boardArgs } from "./place.ts";
import { Windows } from "./windows.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.resolve(process.env.HEDDLE_DIST ?? path.join(here, "..", "dist"));
const DEV_URL = process.env.HEDDLE_DEV_URL || null;
const HIDDEN = process.env.HEDDLE_HIDDEN === "1";

const SCHEME = "heddle";
const ORIGIN = `${SCHEME}://app`;
const BASE = "/Heddle/"; // the site's base path (vite.config.ts)
export const START_URL = DEV_URL ?? `${ORIGIN}${BASE}`;

// Before the app is ready: the scheme behaves like https (storage, fetch, secure context).
protocol.registerSchemesAsPrivileged([
  { scheme: SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);
app.setName("Heddle");
app.setPath("userData", path.resolve(process.env.HEDDLE_USER_DATA ?? path.join(app.getPath("appData"), "Heddle")));

// One running shell per profile: a second launch passes its arguments here and quits.
const single = app.requestSingleInstanceLock();
if (!single) app.quit();
/** Arguments before the files: the program, and the script when run as `electron main.ts`. */
const SKIP_ARGS = process.defaultApp ? 2 : 1;

/** Is this URL the app's own page (or its dev server)? */
function isAppUrl(url: string): boolean {
  try {
    const u = new URL(url);
    if (DEV_URL) return u.origin === new URL(DEV_URL).origin;
    // (not `origin`: Node's URL gives "null" for a scheme it doesn't know)
    return u.protocol === `${SCHEME}:` && u.host === "app" && u.pathname.startsWith(BASE);
  } catch {
    return false;
  }
}

/** A message from the app's own page, not from anything it might have loaded. */
function trusted(e: IpcMainEvent | IpcMainInvokeEvent): boolean {
  return !!e.senderFrame && isAppUrl(e.senderFrame.url);
}

/** heddle://app/Heddle/<file> → that file of the built app; nothing outside it. */
async function serve(request: Request): Promise<Response> {
  const url = new URL(request.url);
  if (url.host !== "app" || !url.pathname.startsWith(BASE)) return new Response("Not found", { status: 404 });
  let rel: string;
  try {
    rel = decodeURIComponent(url.pathname.slice(BASE.length));
  } catch {
    return new Response("Bad request", { status: 400 });
  }
  const file = path.resolve(DIST, rel === "" || rel.endsWith("/") ? path.join(rel, "index.html") : rel);
  if (file !== DIST && !file.startsWith(DIST + path.sep)) return new Response("Not found", { status: 404 });
  try {
    return await net.fetch(pathToFileURL(file).toString());
  } catch {
    return new Response("Not found", { status: 404 });
  }
}

/** Links out of the app (the GitHub link on the start page) open in the user's browser. */
function openOutside(url: string): void {
  if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
}

function guard(contents: WebContents): void {
  contents.setWindowOpenHandler(({ url }) => {
    openOutside(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (e, url) => {
    if (isAppUrl(url)) return;
    e.preventDefault();
    openOutside(url);
  });
  contents.on("will-attach-webview", (e) => e.preventDefault());
}

function info(): DesktopInfo {
  return {
    version: app.getVersion(),
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    os: `${os.type()} ${os.release()}`,
  };
}

app.on("web-contents-created", (_e, contents) => guard(contents));

/** On the shell's first run (no marker in its profile): the Python app's settings and
 *  recent boards, handed to the page once, which keeps them in the shell's own storage. */
async function firstRunSeed(): Promise<DesktopSeed | null> {
  const marker = path.join(app.getPath("userData"), "python-settings-read");
  if (existsSync(marker)) return null;
  const found = await readPythonSettings(process.env.HEDDLE_REGISTRY_KEY ?? PYTHON_KEY);
  try {
    writeFileSync(marker, new Date().toISOString());
  } catch {
    // (asked again next time)
  }
  return found && (Object.keys(found.values).length || found.recent.length) ? found : null;
}

const windows = new Windows({
  preload: path.join(here, "preload.cjs"),
  startUrl: START_URL,
  hidden: HIDDEN,
  dev: !!DEV_URL,
  stateFile: path.join(app.getPath("userData"), "window.json"),
});

/** Boards named on a command line: each in its own window (or brought forward). */
async function openArgs(argv: readonly string[], cwd: string): Promise<boolean> {
  const files = boardArgs(argv, cwd, SKIP_ARGS);
  for (const file of files) await windows.openFromOutside(file);
  return files.length > 0;
}

app.on("second-instance", (_e, argv, cwd) => {
  void openArgs(argv, cwd).then((opened) => {
    if (!opened) windows.create(); // (launched again with no board: a new window, as before)
  });
});

app.whenReady().then(async () => {
  if (!single) return;
  Menu.setApplicationMenu(null);
  protocol.handle(SCHEME, serve);
  // The page asks for nothing beyond writing to the clipboard (copying cards): files go
  // through the shell (ipc.ts).
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback) => {
    callback(isAppUrl(contents.getURL()) && permission === "clipboard-sanitized-write");
  });
  let seed = await firstRunSeed();
  registerIpc({
    trusted,
    info,
    takeSeed: () => {
      const s = seed;
      seed = null;
      return s;
    },
    windows,
  });
  if (!(await openArgs(process.argv, process.cwd()))) windows.create();
  // (a board on the command line that couldn't be read leaves no window: open the start page)
  if (!windows.count()) windows.create();
});

app.on("window-all-closed", () => app.quit());
