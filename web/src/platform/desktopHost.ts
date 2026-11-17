// The app's host in the desktop shell (W9), over the shell's bridge (bridge.ts).
//
// Files are real paths: native Open and Save dialogs, saving and autosaving always in
// place (written whole, then swapped in), backups as files in the Python app's layout
// (%LOCALAPPDATA%\Heddle\backups: each app's appear in the other's Restore), and
// unexpected errors appended to %LOCALAPPDATA%\Heddle\logs\error.log as well.
// Drafts, recent files, locks between windows and settings stay in the shell's own
// profile (IndexedDB, Web Locks and localStorage behave there as in a browser, without
// the browser clearing them). On the first run the Python app's settings and recent
// boards are copied in.
//
// One board per window, as the Python app (W9d): opening a board brings forward the
// window that has it, else opens it here if this window is blank, else in a new window.
// Closing a window with unsaved changes asks Save / Don't save / Cancel (the page's own
// dialog). The desktop's keys: Ctrl+Shift+N, Ctrl+T, Ctrl+1.

import { casefold } from "../core/pystr.ts";
import type { Answer, DesktopBridge, DesktopSeed } from "./bridge.ts";
import { browserHost, watchLeaving } from "./browserHost.ts";
import type { Db } from "./db.ts";
import { BoardFileError, FileGoneError, baseName, type FileRef } from "./files.ts";
import { DESKTOP_KEYS, type Host, type HostFiles, type HostSettings, type HostWindows, type LeavingPage, type PickedFile } from "./host.ts";
import { cardCount, type FileEntry } from "./safety.ts";

/** A board file in the shell: its full path. Plain data (kept with drafts and recent files). */
export interface PathRef extends FileRef {
  path: string;
}

const fileName = (p: string) => p.slice(Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\")) + 1);
export const pathRef = (p: string): PathRef => ({ name: fileName(p), path: p });
const pathOf = (ref: FileRef | null) => (ref && typeof (ref as PathRef).path === "string" ? (ref as PathRef).path : null);
/** The same file? Windows paths ignore case and slash direction. */
const samePath = (a: string, b: string) => casefold(a.replace(/\//g, "\\")) === casefold(b.replace(/\//g, "\\"));

function unwrap<T>(a: Answer<T>, what: string): T {
  if (a.ok) return a.value;
  throw new BoardFileError(`${what}: ${a.error}`);
}

function files(bridge: DesktopBridge): HostFiles {
  return {
    canSaveInPlace: () => true,
    async pickBoard() {
      const picked = unwrap(await bridge.openDialog(), "Couldn't open the board");
      return picked && { ref: pathRef(picked.path), fileName: picked.name, text: picked.text };
    },
    async reopen(ref) {
      const p = pathOf(ref);
      if (!p) return null;
      const a = await bridge.read(p);
      if (!a.ok && a.code === "gone") throw new FileGoneError(ref.name);
      return unwrap(a, `Couldn't open “${ref.name}”`);
    },
    async read(ref) {
      const p = pathOf(ref);
      const a = p ? await bridge.read(p) : null;
      return a?.ok ? a.value : null;
    },
    async write(ref, text) {
      const p = pathOf(ref);
      if (!p) throw new BoardFileError(`Heddle doesn't know where “${ref.name}” is. Use Save As to choose a file.`);
      const a = await bridge.write(p, text);
      if (!a.ok) throw new BoardFileError(`Couldn't save “${ref.name}”: ${a.error}`);
    },
    async pickSave(suggestedName) {
      const p = unwrap(await bridge.saveDialog(suggestedName, null), "Couldn't choose a file");
      return p ? pathRef(p) : null;
    },
    download() {
      throw new Error("The desktop app saves in place: there's nothing to download.");
    },
    async same(a, b) {
      const pa = pathOf(a);
      const pb = pathOf(b);
      return a === b || (!!pa && !!pb && samePath(pa, pb));
    },
    async saveExport(data, name, _type, description) {
      const bytes = typeof data === "string" ? data : new Uint8Array(await data.arrayBuffer());
      return unwrap(await bridge.saveExport(bytes, name, description, name.slice(name.lastIndexOf(".") + 1)), `Couldn't export “${name}”`);
    },
    refFor(file) {
      const p = bridge.pathFor(file);
      return p && p.toLowerCase().endsWith(".json") ? pathRef(p) : null;
    },
  };
}

/** The Python app's settings → the shell's (settings.ts keys), unless already set. */
const SETTING_KEYS: Record<string, [key: string, on: string, off: string]> = {
  commit_pending_entries: ["commitPending", "on", "off"],
  wheel_zooms: ["wheelZooms", "on", "off"],
  show_banners: ["banners", "on", "off"],
  snap_to_grid: ["snap", "on", "off"],
  autosave: ["autosave", "on", "off"],
  dark_mode: ["theme", "dark", "light"],
};

export function seedSettings(seed: DesktopSeed, settings: HostSettings): void {
  for (const [python, [key, on, off]] of Object.entries(SETTING_KEYS)) {
    const v = seed.values[python]?.toLowerCase();
    if ((v === "true" || v === "false") && settings.get(key) === null) settings.set(key, v === "true" ? on : off);
  }
}

/** Its recent boards → Open Recent (only into an empty list). */
export async function seedRecent(seed: DesktopSeed, db: Db, now = Date.now()): Promise<void> {
  if ((await db.all("files")).length) return;
  for (const [i, p] of seed.recent.slice(0, 10).entries()) {
    const ref = pathRef(p);
    const key = `file:python-${i}`;
    await db.put("files", key, { key, name: baseName(ref.name), handle: ref, at: now - i } satisfies FileEntry);
  }
}

function windows(bridge: DesktopBridge): HostWindows {
  const toPicked = (f: { path: string; name: string; text: string }): PickedFile => ({ ref: pathRef(f.path), fileName: f.name, text: f.text });
  let waiting: (PickedFile | null)[] = bridge.open ? [toPicked(bridge.open)] : bridge.newBoard ? [null] : [];
  let show: ((file: PickedFile | null) => void) | null = null;
  const deliver = () => {
    if (!show) return;
    const now = waiting;
    waiting = [];
    for (const f of now) show(f);
  };
  // (listened to once for the page's life: React may subscribe and unsubscribe several times)
  bridge.onOpen(() => {
    void bridge.takeOpen().then((f) => {
      if (f) waiting.push(toPicked(f));
      deliver();
    });
  });
  return {
    first: bridge.first,
    async route(ref, blank) {
      const p = ref ? pathOf(ref) : null;
      const a = await bridge.route(p, blank);
      if (!a.ok && a.code === "gone") throw new FileGoneError(ref?.name ?? "");
      return unwrap(a, "Couldn't open the board");
    },
    report: (ref, blank) => bridge.report(pathOf(ref), blank),
    onOpen(listener) {
      show = listener;
      deliver();
      return () => {
        if (show === listener) show = null;
      };
    },
  };
}

/** `base`: what the shell keeps as a browser does (storage, locks, settings…), and
 *  `watch`, how it notices the page being hidden or closed; tests pass in-memory ones. */
export function desktopHost(bridge: DesktopBridge, base: Host = browserHost,
                            watch: (page: LeavingPage, askOnUnload: boolean) => () => void = watchLeaving): Host {
  const { info, seed } = bridge;
  if (seed) seedSettings(seed, base.settings);
  let storage: Promise<Db> | null = null;
  // Closing the window: the shell asks the page (once at a time), the page asks the user.
  let leaving: LeavingPage | null = null;
  let asking = false;
  bridge.onCloseRequest(() => {
    if (asking) return;
    asking = true;
    void Promise.resolve(leaving ? leaving.askToClose() : true).then((close) => {
      asking = false;
      if (close) bridge.closeNow();
    }, () => {
      asking = false;
    });
  });
  return {
    ...base,
    kind: "desktop",
    keys: DESKTOP_KEYS,
    windows: windows(bridge),
    onLeave(page) {
      leaving = page;
      const stop = watch(page, false); // (drafts when hidden; no browser "Leave site?")
      return () => {
        stop();
        if (leaving === page) leaving = null;
      };
    },
    files: files(bridge),
    storage: () => (storage ??= base.storage().then(async (db) => {
      if (seed) await seedRecent(seed, db).catch(() => undefined);
      return db;
    })),
    backups: {
      async make(target, text, now, force) {
        const p = pathOf(target.ref);
        if (p) unwrap(await bridge.backup(p, text, now, force), "Couldn't back up");
      },
      async list(target) {
        const p = pathOf(target.ref);
        if (!p) return [];
        return unwrap(await bridge.backups(p), "Couldn't list the backups").map((b) =>
          [b.path, { file: target.key, name: target.name, text: b.text, at: b.at, seq: b.seq, cards: cardCount(b.text) }]);
      },
    },
    picture: (picture, board) => bridge.picture(picture, pathOf(board)),
    pdf: async (svg, title) => (unwrap(await bridge.pdf(svg, title), "Couldn't export the PDF") ? "saved" : "cancelled"),
    errors: {
      ...base.errors,
      append(entry) {
        base.errors.append(entry);
        bridge.log(entry.text);
      },
      about: () => [`Heddle ${info.version} (desktop) error report`, `Electron ${info.electron} (Chromium ${info.chrome})`, `System: ${info.os}`],
      place: "on this computer (and in error.log)",
    },
    words: { holder: "window", here: "this computer" },
    installOffline() {
      // (nothing to do: the shell has every file already)
    },
  };
}
