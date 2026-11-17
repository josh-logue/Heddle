// An in-memory Host, shaped like the desktop shell's (W9b/W9c): board files are paths
// that can always be written in place, and nothing touches a browser API. Tests run the
// app's platform-facing code on it; the desktop host should pass the same tests.

import { MemoryDb } from "../src/platform/db.ts";
import type { ErrorEntry } from "../src/platform/errorLog.ts";
import { FileGoneError, NoPermissionError } from "../src/platform/files.ts";
import { DESKTOP_KEYS, type FileRef, type Host, type LeavingPage, type PickedFile } from "../src/platform/host.ts";
import { MemoryLocks, dbBackups } from "../src/platform/safety.ts";

/** A file reference as plain data (what a desktop host would pass over IPC). */
export interface PathRef extends FileRef {
  path: string;
}

const baseOf = (path: string) => path.slice(path.lastIndexOf("/") + 1);
export const pathRef = (path: string): PathRef => ({ name: baseOf(path), path });

export class MemoryHost implements Host {
  /** The "disk": path → text. */
  readonly disk = new Map<string, string>();
  /** What the next Open and Save As dialogs answer (null: cancelled). */
  readonly opens: (string | null)[] = [];
  readonly saves: (string | null)[] = [];
  /** Paths this host may not write to without asking. */
  readonly readOnly = new Set<string>();
  /** Paths this host may not even read without asking (a browser file handle whose
   *  permission lapsed, as after recovering a draft). */
  readonly unreadable = new Set<string>();
  readonly downloads: [string, string][] = [];
  readonly exports: [string, string | Blob][] = [];
  readonly pdfs: string[] = [];
  readonly db = new MemoryDb();
  readonly locks = new MemoryLocks();
  readonly settingsData = new Map<string, string>();
  readonly errorData: ErrorEntry[] = [];
  clipboardText = "";
  leaving: LeavingPage | null = null;
  kind = "desktop" as const;
  windows = null;
  keys = DESKTOP_KEYS;
  words = { holder: "window" as const, here: "the test host" };
  backups = dbBackups(async () => this.db);
  picture = async () => null;

  files: Host["files"] = {
    canSaveInPlace: () => true,
    pickBoard: async (): Promise<PickedFile | null> => {
      const path = this.opens.shift() ?? null;
      if (path === null) return null;
      const text = this.disk.get(path);
      if (text === undefined) throw new FileGoneError(baseOf(path));
      return { ref: pathRef(path), fileName: baseOf(path), text };
    },
    reopen: async (ref) => {
      const text = this.disk.get((ref as PathRef).path);
      if (text === undefined) throw new FileGoneError(ref.name);
      return text;
    },
    read: async (ref, ask) => {
      const path = (ref as PathRef).path;
      if (this.unreadable.has(path) && !ask) return null;
      return this.disk.get(path) ?? null;
    },
    write: async (ref, text, ask) => {
      const path = (ref as PathRef).path;
      if (this.readOnly.has(path) && !ask) throw new NoPermissionError(`Not allowed to write ${ref.name}`);
      this.disk.set(path, text);
    },
    pickSave: async () => {
      const path = this.saves.shift() ?? null;
      return path === null ? null : pathRef(path);
    },
    download: (text, fileName) => void this.downloads.push([fileName, text]),
    same: async (a, b) => (a as PathRef).path === (b as PathRef).path,
    saveExport: async (data, fileName) => {
      this.exports.push([fileName, data]);
      return true;
    },
    refFor: (file) => {
      const path = (file as File & { path?: string }).path;
      return path ? pathRef(path) : null;
    },
  };

  storage = async () => this.db;

  settings: Host["settings"] = {
    get: (key) => this.settingsData.get(key) ?? null,
    set: (key, value) => void this.settingsData.set(key, value),
  };

  errors: Host["errors"] = {
    entries: () => [...this.errorData],
    append: (entry) => void this.errorData.push(entry),
    clear: () => void this.errorData.splice(0),
    about: () => ["Heddle (test host) error report"],
    place: "in the test host",
  };

  clipboard = { writeText: async (text: string) => void (this.clipboardText = text) };

  pdf = async (svg: string): Promise<"saved"> => {
    this.pdfs.push(svg);
    return "saved";
  };

  // (fields, not methods: desktopHost spreads its base host, which copies own fields only)
  onLeave = (page: LeavingPage): (() => void) => {
    this.leaving = page;
    return () => {
      this.leaving = null;
    };
  };

  installOffline = (): void => {};
}
