// What the desktop shell's preload (web/desktop/preload.cjs) puts on the page as
// `window.heddleDesktop`: plain data and functions that send IPC messages to the shell's
// main process (web/desktop/main.ts). Nothing else of Electron or Node reaches the page.
// Types only, plus the channel names: shared by the page, the preload and the main process.

/** What's running, for the error report. */
export interface DesktopInfo {
  /** Heddle's version. */
  version: string;
  electron: string;
  chrome: string;
  /** "Windows_NT 10.0.26300" and the like. */
  os: string;
}

/** The Python app's settings and recent files, handed over once (the shell's first run). */
export interface DesktopSeed {
  /** Its settings as stored (key → "true" / "false"). */
  values: Record<string, string>;
  /** Its recent boards, newest first. */
  recent: string[];
}

/** A board file the shell opened: its full path, name and text. */
export interface DesktopFile {
  path: string;
  name: string;
  text: string;
}

/** A backup of a board file (heddle/backups.py's layout). */
export interface DesktopBackup {
  path: string;
  at: number;
  seq: number;
  text: string;
}

/** How a call that can fail answers: an error's message travels as text. */
export type Answer<T> = { ok: true; value: T } | { ok: false; error: string; code?: string };

export interface DesktopBridge {
  info: DesktopInfo;
  /** Set on the shell's first run only. */
  seed: DesktopSeed | null;
  /** The board this window was opened for (a new window, the command line). */
  open: DesktopFile | null;
  /** This window was opened for a new, empty board (File → New). */
  newBoard: boolean;
  /** The first window of this run: only it offers unsaved boards back. */
  first: boolean;
  /** Tell the shell what this window shows (so a board opens in one window only). */
  report(path: string | null, blank: boolean): void;
  /** Where should this board (null: a new one) open? "here" when this window is blank;
   *  otherwise the window that has it comes forward, or a new window opens it. Code
   *  "gone" if the file isn't there. */
  route(path: string | null, blank: boolean): Promise<Answer<"here" | "elsewhere">>;
  /** The shell has a board for this window (a second launch): `takeOpen` gets it. */
  onOpen(listener: () => void): void;
  takeOpen(): Promise<DesktopFile | null>;
  /** Closing the window asks the page first: `listener` decides, then calls closeNow. */
  onCloseRequest(listener: () => void): void;
  closeNow(): void;
  /** File → Open: the native dialog. Null if cancelled. */
  openDialog(): Promise<Answer<DesktopFile | null>>;
  /** Save As: the native dialog; the chosen path (null if cancelled). */
  saveDialog(suggestedName: string, folder: string | null): Promise<Answer<string | null>>;
  /** A board file's text; code "gone" if it isn't there. */
  read(path: string): Promise<Answer<string>>;
  write(path: string, text: string): Promise<Answer<null>>;
  /** Export: the native dialog, then the file written. False if cancelled. */
  saveExport(data: string | Uint8Array, fileName: string, description: string, extension: string): Promise<Answer<boolean>>;
  /** File → Export as PDF: the native Save dialog, then the drawing as a one-page PDF.
   *  False if cancelled. */
  pdf(svg: string, title: string): Promise<Answer<boolean>>;
  backups(board: string): Promise<Answer<DesktopBackup[]>>;
  backup(board: string, text: string, now: number, force: boolean): Promise<Answer<null>>;
  /** Append to error.log (never fails). */
  log(text: string): void;
  /** A strand's picture as a data: URL (relative paths from the board's folder), or null. */
  picture(picture: string, board: string | null): Promise<string | null>;
  /** The path of a file dropped on the window ("" if it has none). */
  pathFor(file: File): string;
}

/** IPC channel names (main.ts answers them; the preload sends them). */
export const CHANNELS = {
  /** Synchronous, once, as the preload starts: { info, seed }. */
  start: "heddle:start",
  openDialog: "heddle:open-dialog",
  saveDialog: "heddle:save-dialog",
  read: "heddle:read",
  write: "heddle:write",
  saveExport: "heddle:save-export",
  pdf: "heddle:pdf",
  backups: "heddle:backups",
  backup: "heddle:backup",
  log: "heddle:log",
  picture: "heddle:picture",
  report: "heddle:report",
  route: "heddle:route",
  /** Main → page: a board is waiting (takeOpen). */
  open: "heddle:open",
  takeOpen: "heddle:take-open",
  /** Page → main: this page asks before closing. Main → page: closing, ask now. */
  asksBeforeClosing: "heddle:asks-before-closing",
  closeRequest: "heddle:close-request",
  closeNow: "heddle:close-now",
} as const;

declare global {
  interface Window {
    /** Set by the desktop shell's preload; absent in a browser. */
    heddleDesktop?: DesktopBridge;
  }
}
