// Drafts, backups and recent files (heddle/backups.py and recovery.py, in browser storage).
//
// - A draft is a board's unsaved state, written by autosave when the board can't be saved
//   back to its file (untitled, or a browser without in-place saving) and when the tab is
//   hidden or closed. Each draft is locked while its tab is open, so only drafts whose tab
//   has gone are offered for recovery. Saving the board, or discarding it, removes it.
// - A backup is a board file's contents just before they're overwritten: the first save
//   of each session, then at most every 5 minutes, and always before overwriting changes
//   made elsewhere. The newest 20 are kept per board.
// - Files: the board files opened or saved (the host's references to them: handles in
//   Chrome and Edge), so they can be told apart, reopened (Open Recent) and spotted open in
//   another tab.
// Pure logic over the host's storage and locks: no browser APIs here.

import type { Db } from "./db.ts";
import type { FileRef, HostBackups } from "./host.ts";

export const KEEP_BACKUPS = 20;
export const BACKUP_INTERVAL_MS = 5 * 60_000;
export const RECENT_MAX = 10;

// ----- locks (which tab holds what) -------------------------------------------------------

/** Named locks held by tabs (the Web Locks API), released when the tab goes. */
export interface Locks {
  /** Hold a lock until the returned function is called (or the tab closes). A shared
   *  lock can be held by several tabs at once; an exclusive one waits for the others. */
  hold(name: string, shared?: boolean): Promise<() => void>;
  /** Is the lock held by any tab (this one included)? */
  held(name: string): Promise<boolean>;
}

/** In memory, for tests: like Web Locks, an exclusive lock waits until nobody holds it. */
export class MemoryLocks implements Locks {
  readonly names = new Map<string, number>();
  private waiting: (() => void)[] = [];
  async hold(name: string, shared = false): Promise<() => void> {
    while (!shared && this.names.has(name)) await new Promise<void>((wake) => this.waiting.push(wake));
    this.names.set(name, (this.names.get(name) ?? 0) + 1);
    let done = false;
    return () => {
      if (done) return;
      done = true;
      const n = (this.names.get(name) ?? 1) - 1;
      if (n) this.names.set(name, n);
      else this.names.delete(name);
      const wake = this.waiting;
      this.waiting = [];
      for (const w of wake) w();
    };
  }
  async held(name: string): Promise<boolean> {
    return this.names.has(name);
  }
}

const draftLock = (id: string) => `heddle-draft:${id}`;
const boardLock = (key: string) => `heddle-board:${key}`;

// ----- drafts -----------------------------------------------------------------------------

export interface Draft {
  id: string;
  /** The board's name (its file name without .json, or "Untitled"). */
  name: string;
  text: string;
  /** When it was written (ms since 1970). */
  at: number;
  cards: number;
  /** The file it came from, where the browser can save back to one. */
  handle?: FileRef | null;
  /** That file's text as last read or written here (to spot changes made since). */
  disk?: string | null;
}

export async function writeDraft(db: Db, draft: Draft): Promise<void> {
  db.persist?.();
  await db.put("drafts", draft.id, draft);
}

export async function discardDraft(db: Db, id: string): Promise<void> {
  await db.delete("drafts", id);
}

/** Hold a draft's lock while its board is open in this tab. */
export function lockDraft(locks: Locks, id: string): Promise<() => void> {
  return locks.hold(draftLock(id));
}

/** Drafts whose tab has gone (closed, crashed or reloaded), newest first. */
export async function orphanDrafts(db: Db, locks: Locks): Promise<Draft[]> {
  const out: Draft[] = [];
  for (const [, d] of await db.all<Draft>("drafts")) if (!(await locks.held(draftLock(d.id)))) out.push(d);
  return out.sort((a, b) => b.at - a.at);
}

// ----- backups ----------------------------------------------------------------------------

export interface Backup {
  /** The board file it's a backup of (see fileKey). */
  file: string;
  name: string;
  text: string;
  at: number;
  /** Several in the same millisecond keep their order. */
  seq: number;
  /** How many cards it has (null: unreadable). */
  cards: number | null;
}

/** Backups of a board file, newest first. */
export async function listBackups(db: Db, file: string): Promise<[string, Backup][]> {
  const found = (await db.all<Backup>("backups")).filter(([, b]) => b.file === file);
  return found.sort(([, a], [, b]) => b.at - a.at || b.seq - a.seq);
}

/** Keep `text` (the file as it is now, about to be overwritten). Skipped when it's empty
 *  or, unless forced, when the newest backup is recent. Older backups beyond `keep` go.
 *  Returns the new backup's key, or null if none was made. */
export async function makeBackup(db: Db, file: string, name: string, text: string, now: number, force = false,
                                 keep = KEEP_BACKUPS, interval = BACKUP_INTERVAL_MS): Promise<string | null> {
  if (!text.trim()) return null;
  const existing = await listBackups(db, file);
  const newest = existing[0]?.[1];
  if (newest && !force && now - newest.at < interval) return null;
  if (newest && newest.text === text && newest.at <= now) return null; // nothing new to keep
  const seq = existing.filter(([, b]) => b.at === now).length;
  const key = `${file}\u0001${now}\u0001${seq}`;
  db.persist?.();
  await db.put("backups", key, { file, name, text, at: now, seq, cards: cardCount(text) } satisfies Backup);
  for (const [old] of (await listBackups(db, file)).slice(keep)) await db.delete("backups", old);
  return key;
}

/** Backups kept in a Db (a browser's, and tests'), under each board's file key. */
export function dbBackups(db: () => Promise<Db>): HostBackups {
  return {
    make: async (target, text, now, force) => void (await makeBackup(await db(), target.key, target.name, text, now, force)),
    list: async (target) => listBackups(await db(), target.key),
  };
}

/** How many cards a board's text has (null if it isn't readable). */
export function cardCount(text: string): number | null {
  try {
    const raw = JSON.parse(text) as { cards?: unknown };
    return Array.isArray(raw.cards) ? raw.cards.length : null;
  } catch {
    return null;
  }
}

/** "Today, 14:05:22", "Yesterday, …" or "Mon 16 Nov 2026, …" (heddle/backup_dialog.describe). */
export function describeTime(at: number, now = Date.now()): string {
  const when = new Date(at);
  const today = new Date(now);
  const day0 = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day0(today) - day0(when)) / 86_400_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(when.getHours())}:${pad(when.getMinutes())}:${pad(when.getSeconds())}`;
  if (days === 0) return `Today, ${time}`;
  if (days === 1) return `Yesterday, ${time}`;
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][when.getDay()];
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][when.getMonth()];
  return `${wd} ${pad(when.getDate())} ${mon} ${when.getFullYear()}, ${time}`;
}

// ----- board files: identity, recent, open in another tab ---------------------------------

export interface FileEntry {
  key: string;
  name: string;
  handle: FileRef;
  /** Last opened or saved (ms). */
  at: number;
}

/** A stable key for a board file: the same file always gets the same key, whatever it's
 *  called, so backups and the other-tab check follow it. A board without a file (a
 *  download-only browser) is known by its name. Recorded as recently used. */
export async function fileKey(db: Db, handle: FileRef | null, name: string, now: number,
                              same: (a: FileRef, b: FileRef) => Promise<boolean> = async (a, b) => a === b): Promise<string> {
  if (!handle) return `name:${name}`;
  let found: FileEntry | undefined;
  for (const [, e] of await db.all<FileEntry>("files")) {
    if (await same(e.handle, handle)) {
      found = e;
      break;
    }
  }
  const key = found?.key ?? `file:${now.toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  try {
    await db.put("files", key, { key, name, handle, at: now } satisfies FileEntry);
  } catch {
    // (a handle the browser can't store: no Open Recent for it, nothing else lost)
  }
  await pruneRecent(db);
  return key;
}

/** The recently used board files, newest first. */
export async function recentFiles(db: Db): Promise<FileEntry[]> {
  return (await db.all<FileEntry>("files")).map(([, e]) => e).sort((a, b) => b.at - a.at).slice(0, RECENT_MAX);
}

export async function forgetFile(db: Db, key: string): Promise<void> {
  await db.delete("files", key);
}

/** Older entries go, unless they still have backups (which need their key to be found). */
async function pruneRecent(db: Db): Promise<void> {
  const all = (await db.all<FileEntry>("files")).map(([, e]) => e).sort((a, b) => b.at - a.at);
  if (all.length <= RECENT_MAX * 3) return;
  const backed = new Set((await db.all<Backup>("backups")).map(([, b]) => b.file));
  for (const e of all.slice(RECENT_MAX * 3)) if (!backed.has(e.key)) await db.delete("files", e.key);
}

/** Hold "this board file is open here" while a tab shows it (shared: another tab may
 *  open it too, after a warning). */
export function lockBoard(locks: Locks, key: string): Promise<() => void> {
  return locks.hold(boardLock(key), true);
}

/** Is a board file open in some tab (ask before holding its lock yourself)? */
export function boardOpenElsewhere(locks: Locks, key: string): Promise<boolean> {
  return locks.held(boardLock(key));
}
