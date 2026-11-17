// The host: everything the app needs from where it runs, in one typed interface.
//
// In a browser that's `browserHost` (File System Access or downloads, IndexedDB, Web Locks,
// localStorage, the browser's Print). W9's desktop shell supplies its own implementation
// over Electron IPC (files with real paths, backups and the error log in %LOCALAPPDATA%,
// its own windows): `desktopHost`, chosen in main.tsx when the shell's preload has put its
// bridge on the page (bridge.ts). The rest of the app reaches the platform only through
// here: `getHost()`, or a host passed in (tests use an in-memory one, see
// tests/memoryHost.ts). Only the hosts import platform/browser/.
//
// Methods that touch files or storage are async and take plain data, so a desktop version
// can forward them over IPC. Settings and the error log are synchronous because the app
// reads them while drawing its first frame: a shell hands them over at startup and writes
// them back in the background.

import type { Db } from "./db.ts";
import type { ErrorEntry } from "./errorLog.ts";
import type { Backup, Locks } from "./safety.ts";

/** A board file as the host knows it: a File System Access handle in Chrome and Edge, a
 *  path in the desktop shell. The app only reads its name; it keeps the rest opaque and
 *  stores it with drafts and recent files, so it must survive structured cloning. */
export interface FileRef {
  readonly name: string;
}

/** A board file the user picked: its text, and where to save back to (null where the
 *  host can only read it, e.g. a browser without in-place saving). */
export interface PickedFile {
  ref: FileRef | null;
  /** The file's name, with its extension. */
  fileName: string;
  text: string;
}

export interface HostFiles {
  /** Can Save write back to the file a board came from (else every Save downloads)? */
  canSaveInPlace(): boolean;
  /** File → Open: ask for a board file. Null if the user cancelled. */
  pickBoard(): Promise<PickedFile | null>;
  /** Open Recent: read a file used before, asking for permission where needed (that
   *  needs the user's click). Null if not allowed; throws FileGoneError if it's gone. */
  reopen(ref: FileRef): Promise<string | null>;
  /** A file's text as it is now, or null if it can't be read (gone, not allowed). Never asks. */
  read(ref: FileRef): Promise<string | null>;
  /** Write a board file in place. Without permission, `ask` asks (needs a click); else
   *  this throws NoPermissionError. */
  write(ref: FileRef, text: string, ask: boolean): Promise<void>;
  /** Save As's file choice: a file, null if cancelled, or "download" where only that works. */
  pickSave(suggestedName: string): Promise<FileRef | null | "download">;
  /** Hand a board's text to the user as a downloaded file (hosts that can't save in place). */
  download(text: string, fileName: string): void;
  /** Are two references the same file (whatever it's called now)? */
  same(a: FileRef, b: FileRef): Promise<boolean>;
  /** Save an exported file (Markdown, PNG, SVG): true if saved, false if cancelled,
   *  "downloaded" where the host can only download. */
  saveExport(data: string | Blob, fileName: string, type: string, description: string): Promise<boolean | "downloaded">;
  /** A file dropped on the page, as a reference to save back to (null where the host
   *  can only read it). */
  refFor(file: File): FileRef | null;
}

/** Which board file a backup belongs to: its key (session.fileKey), the host's
 *  reference to it, and its name. */
export interface BackupTarget {
  key: string;
  ref: FileRef | null;
  name: string;
}

/** Backups of board files, made just before they're overwritten (safety.ts has the rules). */
export interface HostBackups {
  /** Keep `text` (the file as it is now). Skipped, unless `force`, when the newest backup
   *  is recent; older ones beyond the limit go. */
  make(target: BackupTarget, text: string, now: number, force: boolean): Promise<void>;
  /** Newest first, each with a key the host knows it by. */
  list(target: BackupTarget): Promise<[string, Backup][]>;
}

/** Settings and remembered layout: small strings by key. */
export interface HostSettings {
  get(key: string): string | null;
  set(key: string, value: string): void;
}

/** Where unexpected errors are kept (errorLog.ts decides what goes in). */
export interface HostErrors {
  entries(): ErrorEntry[];
  /** Keep one more (the oldest go once there are too many). Must not throw. */
  append(entry: ErrorEntry): void;
  clear(): void;
  /** The error report's first lines: what's running, and where. */
  about(): string[];
  /** Where the log stays, for Settings ("in this browser"). */
  place: string;
}

/** What the page tells the host about leaving it. */
export interface LeavingPage {
  /** Are there changes that aren't saved? */
  unsaved(): boolean;
  /** Keep the unsaved changes as a draft (offered back next time). */
  keepDraft(): void;
  /** The window is closing (a desktop host): ask Save / Don't save / Cancel if there are
   *  unsaved changes, and save if asked. True when the window may close. */
  askToClose(): Promise<boolean>;
}

/** One board per window (the desktop shell), as the Python app. */
export interface HostWindows {
  /** The first window of this run (only it offers unsaved boards back). */
  readonly first: boolean;
  /** Where should a board (null: a new one) open, given whether this window is blank
   *  (nothing, or an untitled, unchanged, empty board)? "here", or "elsewhere" when the
   *  window that has it came forward or a new window opened it. Throws FileGoneError. */
  route(ref: FileRef | null, blank: boolean): Promise<"here" | "elsewhere">;
  /** What this window shows now. */
  report(ref: FileRef | null, blank: boolean): void;
  /** Boards to show in this window: the one it was opened for (null: a new, empty one),
   *  then any handed over later (a second launch). One already waiting is shown straight
   *  away. Returns a function that stops listening. */
  onOpen(show: (file: PickedFile | null) => void): () => void;
}

/** One key: `code` (the physical key, KeyboardEvent.code) or `key` (the character).
 *  Ctrl means Ctrl or Cmd. `shift` and `alt` left out mean "either". */
export interface KeyCombo {
  code?: string;
  key?: string;
  ctrl: boolean;
  shift?: boolean;
  alt?: boolean;
  /** How menus and tooltips show it ("N", "Ctrl+Shift+N"). */
  label: string;
}

/** The keys that differ between a browser (which keeps Ctrl+T, Ctrl+Shift+N and usually
 *  Ctrl+1 for itself) and the desktop. Help will follow this in W9d. */
export interface KeyProfile {
  addCard: KeyCombo;
  thread: KeyCombo;
  fit: KeyCombo;
}

export const BROWSER_KEYS: KeyProfile = {
  addCard: { code: "KeyN", ctrl: false, shift: false, alt: false, label: "N" },
  thread: { code: "KeyT", ctrl: false, shift: false, alt: false, label: "T" },
  // Also bound in a browser, where it works if the browser lets it through; Help points
  // to the toolbar's Fit button instead.
  fit: { key: "1", ctrl: true, label: "Ctrl+1" },
};

export const DESKTOP_KEYS: KeyProfile = {
  addCard: { code: "KeyN", ctrl: true, shift: true, alt: false, label: "Ctrl+Shift+N" },
  thread: { code: "KeyT", ctrl: true, shift: false, alt: false, label: "Ctrl+T" },
  fit: { key: "1", ctrl: true, label: "Ctrl+1" },
};

type KeyLike = Pick<KeyboardEvent, "code" | "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">;

/** Does a key press match a combo? */
export function matchesKey(combo: KeyCombo, e: KeyLike): boolean {
  if ((e.ctrlKey || e.metaKey) !== combo.ctrl) return false;
  if (combo.shift !== undefined && e.shiftKey !== combo.shift) return false;
  if (combo.alt !== undefined && e.altKey !== combo.alt) return false;
  return (combo.code === undefined || e.code === combo.code) && (combo.key === undefined || e.key === combo.key);
}

export interface Host {
  /** Which app this is: Help shows each one's controls. */
  kind: "browser" | "desktop";
  files: HostFiles;
  /** Null in a browser: each tab shows one board and replaces it when another opens. */
  windows: HostWindows | null;
  /** Drafts, backups and recent files. Opened once, on first use. */
  storage(): Promise<Db>;
  /** Which board files and drafts other tabs or windows hold. */
  locks: Locks;
  backups: HostBackups;
  /** A strand's picture, ready for an <img> (relative paths are from the board's file),
   *  or null where the host can't show pictures or the file isn't there. */
  picture(picture: string, board: FileRef | null): Promise<string | null>;
  settings: HostSettings;
  errors: HostErrors;
  /** Plain text onto the system clipboard (copying cards also goes through the page's
   *  copy and paste events, which every host has). */
  clipboard: { writeText(text: string): Promise<void> };
  /** File → Export as PDF: the board drawn as SVG. "printed": handed to Print (a
   *  browser, where the user saves it from there); "saved" or "cancelled": the desktop's
   *  Save dialog and a one-page PDF. */
  pdf(svg: string, title: string): Promise<"printed" | "saved" | "cancelled">;
  /** Watch for the page being hidden or closed with unsaved changes. Returns a function
   *  that stops watching. */
  onLeave(page: LeavingPage): () => void;
  /** Words for messages: what holds one board ("tab" or "window"), and whose settings
   *  these are ("this browser" or "this computer"). */
  words: { holder: "tab" | "window"; here: string };
  /** Make the app work offline, where that needs doing (the browser's service worker). */
  installOffline(): void;
  keys: KeyProfile;
}

let active: Host | null = null;

/** The host the app runs on (set once at startup). */
export function getHost(): Host {
  if (!active) throw new Error("No host: call setHost() before starting the app.");
  return active;
}

export function setHost(host: Host): void {
  active = host;
}
