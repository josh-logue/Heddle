// The desktop shell's windows (W9d), as the Python app keeps them (heddle/main_window.py):
// one board per window. Opening a board that's already open brings its window forward;
// any other board opens in the window asking if that one is still blank, else in a new
// window. Closing a window lets its page ask Save / Don't save / Cancel first. Window
// size and position are remembered; new windows cascade from the one in front.

import { BrowserWindow, screen, type WebContents } from "electron";
import { promises as fs, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { CHANNELS, type DesktopFile } from "../src/platform/bridge.ts";
import { CASCADE, placeWindow, sameBoardPath, type SavedBounds } from "./place.ts";

export interface WindowOptions {
  preload: string;
  startUrl: string;
  hidden: boolean;
  dev: boolean;
  /** Where the last window's size and position are kept. */
  stateFile: string;
}

interface Entry {
  win: BrowserWindow;
  /** The board file it shows (null: untitled or the start page). */
  path: string | null;
  /** Untitled, unchanged and empty: opening a board may use this window. */
  blank: boolean;
  /** A board to open once its page asks (made for it, or handed over while loading);
   *  "new": an empty board (File → New). */
  pending: DesktopFile | "new" | null;
  /** The first window of this run (only it offers unsaved boards back). */
  first: boolean;
  /** Its page asks before closing; set once the page has said so. */
  asksBeforeClosing: boolean;
  /** The page agreed to close: let it go. */
  closing: boolean;
}

export class Windows {
  private readonly entries = new Map<number, Entry>(); // by webContents id
  private madeFirst = false;
  private readonly options: WindowOptions;

  constructor(options: WindowOptions) {
    this.options = options;
  }

  private entryFor(contents: WebContents): Entry | undefined {
    return this.entries.get(contents.id);
  }

  /** The window showing this board, if any. */
  holding(file: string, except?: WebContents): BrowserWindow | null {
    for (const e of this.entries.values()) {
      if (e.win.isDestroyed() || e.win.webContents === except) continue;
      const shows = e.path ?? (e.pending && e.pending !== "new" ? e.pending.path : null);
      if (shows && sameBoardPath(shows, file)) return e.win;
    }
    return null;
  }

  front(win: BrowserWindow): void {
    if (win.isMinimized()) win.restore();
    if (!this.options.hidden) win.show();
    win.focus();
  }

  /** A new window, showing `file` once its page has started ("new": an empty board;
   *  null: the start page). */
  create(file: DesktopFile | "new" | null = null): BrowserWindow {
    const { options } = this;
    const lead = BrowserWindow.getFocusedWindow() ?? [...this.entries.values()].at(-1)?.win ?? null;
    const place = placeWindow(this.saved(), lead && !lead.isDestroyed()
      ? { bounds: lead.getNormalBounds(), maximized: lead.isMaximized() } : null,
    screen.getAllDisplays().map((d) => d.workArea), CASCADE);
    const win = new BrowserWindow({
      ...place.bounds,
      minWidth: 640,
      minHeight: 420,
      show: false,
      title: "Heddle",
      webPreferences: {
        preload: options.preload,
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        // (tests drive hidden windows: keep them drawing)
        backgroundThrottling: !options.hidden,
      },
    });
    const id = win.webContents.id;
    this.entries.set(id, {
      win, path: file && file !== "new" ? file.path : null, blank: !file, pending: file, first: !this.madeFirst,
      asksBeforeClosing: false, closing: false,
    });
    this.madeFirst = true;
    if (!options.hidden) {
      win.once("ready-to-show", () => {
        if (place.maximized) win.maximize();
        win.show();
      });
    }
    win.on("close", (e) => {
      const entry = this.entries.get(id);
      this.remember(win);
      if (!entry || entry.closing || !entry.asksBeforeClosing || win.webContents.isCrashed()) return;
      e.preventDefault(); // the page asks, and closes the window when it may (closeNow)
      win.webContents.send(CHANNELS.closeRequest);
    });
    win.on("closed", () => this.entries.delete(id));
    win.webContents.on("render-process-gone", () => {
      const entry = this.entries.get(id);
      if (entry) entry.asksBeforeClosing = false; // nothing left to ask
    });
    if (options.dev) {
      win.webContents.on("before-input-event", (_e, input) => {
        if (input.type === "keyDown" && input.key === "F12") win.webContents.toggleDevTools();
      });
    }
    void win.loadURL(options.startUrl);
    return win;
  }

  /** The page started: what it should open, and whether it's the first window. */
  started(contents: WebContents): { open: DesktopFile | null; newBoard: boolean; first: boolean } {
    const entry = this.entryFor(contents);
    if (!entry) return { open: null, newBoard: false, first: false };
    const pending = entry.pending;
    entry.pending = null;
    return { open: pending === "new" ? null : pending, newBoard: pending === "new", first: entry.first };
  }

  /** What a window's page now shows. */
  report(contents: WebContents, state: { path: string | null; blank: boolean }): void {
    const entry = this.entryFor(contents);
    if (!entry) return;
    entry.path = state.path;
    entry.blank = state.blank && !entry.pending;
  }

  asksBeforeClosing(contents: WebContents): void {
    const entry = this.entryFor(contents);
    if (entry) entry.asksBeforeClosing = true;
  }

  /** The page agreed: close its window now. */
  closeNow(contents: WebContents): void {
    const entry = this.entryFor(contents);
    if (!entry) return;
    entry.closing = true;
    entry.win.close();
  }

  /** Where should a board (null: a new one) open, asked by the window `from` (blank or
   *  not)? Brings an open one forward, or opens it in a new window. */
  async route(from: WebContents, file: string | null, blank: boolean): Promise<"here" | "elsewhere"> {
    if (file) {
      const open = this.holding(file); // (this window too: it just comes forward, unchanged)
      if (open) {
        this.front(open);
        return "elsewhere";
      }
    }
    if (blank) return "here";
    this.create(file ? await readBoard(file) : "new");
    return "elsewhere";
  }

  /** A board handed over from outside (the command line, a second launch): brought
   *  forward if open, else into a blank window, else a new one. */
  async openFromOutside(file: string): Promise<void> {
    const open = this.holding(file);
    if (open) {
      this.front(open);
      return;
    }
    const board = await readBoard(file).catch(() => null);
    if (!board) return; // (not readable: nothing to show)
    const blank = [...this.entries.values()].find((e) => !e.win.isDestroyed() && e.blank && !e.pending && e.path === null);
    if (blank) {
      blank.pending = board;
      blank.blank = false;
      blank.win.webContents.send(CHANNELS.open);
      this.front(blank.win);
      return;
    }
    this.create(board);
  }

  /** Hand a page the board waiting for it (after "heddle:open"). */
  takeOpen(contents: WebContents): DesktopFile | null {
    const entry = this.entryFor(contents);
    const open = entry?.pending ?? null;
    if (entry) entry.pending = null;
    return open === "new" ? null : open;
  }

  count(): number {
    return this.entries.size;
  }

  any(): BrowserWindow | null {
    return [...this.entries.values()].at(-1)?.win ?? null;
  }

  // ----- size and position ------------------------------------------------------------

  private saved(): SavedBounds | null {
    try {
      return JSON.parse(readFileSync(this.options.stateFile, "utf-8")) as SavedBounds;
    } catch {
      return null;
    }
  }

  private remember(win: BrowserWindow): void {
    try {
      const state: SavedBounds = { bounds: win.getNormalBounds(), maximized: win.isMaximized() };
      writeFileSync(this.options.stateFile, JSON.stringify(state));
    } catch {
      // (not remembered)
    }
  }
}

/** A board file to open: its text, read now so a window is only made for a readable one. */
export async function readBoard(file: string): Promise<DesktopFile> {
  const full = path.resolve(file);
  try {
    return { path: full, name: path.basename(full), text: await fs.readFile(full, "utf-8") };
  } catch (e) {
    throw Object.assign(new Error(`“${path.basename(full)}” can't be found`), { code: (e as NodeJS.ErrnoException).code === "ENOENT" ? "gone" : "unreadable" });
  }
}
