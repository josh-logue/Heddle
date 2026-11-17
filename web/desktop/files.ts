// The desktop shell's files, in Node (no Electron here, so Vitest runs it directly):
// writing board files safely, backups in the Python app's layout (heddle/backups.py, so
// each app's backups show up in the other's Restore), the error log (heddle/error_log.py)
// and the Python app's settings and recent files, read once from the registry.
// Electron's Node runs this TypeScript as it is: erasable syntax only.

import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { promises as fs, realpathSync } from "node:fs";
import path from "node:path";
import { casefold } from "../src/core/pystr.ts";

/** %LOCALAPPDATA%\Heddle\<sub>, as the Python app's settings.data_dir. `override`: an
 *  environment variable naming another folder (tests). */
export function dataDir(sub: string, override?: string): string {
  if (override?.trim()) return path.resolve(override.trim());
  const base = process.env.LOCALAPPDATA || path.join(process.env.USERPROFILE ?? ".", "AppData", "Local");
  return path.join(base, "Heddle", sub);
}

// ----- board files ------------------------------------------------------------------------

const RETRIES = [50, 150, 400, 1000]; // OneDrive and virus scanners can hold a file briefly

async function retry<T>(fn: () => Promise<T>): Promise<T> {
  for (let i = 0; ; i++) {
    try {
      return await fn();
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code;
      if (i >= RETRIES.length || !["EBUSY", "EPERM", "EACCES", "EINVAL"].includes(code ?? "")) throw e;
      await new Promise((r) => setTimeout(r, RETRIES[i]));
    }
  }
}

/** Write a file whole or not at all: into `<file>.tmp`, then swapped in (as model.save_board).
 *  Both steps are tried again while something holds a file briefly; a failure leaves the
 *  file as it was and no temporary file behind. */
export async function writeAtomic(file: string, data: string | Uint8Array): Promise<void> {
  const tmp = `${file}.tmp`;
  try {
    await retry(() => fs.writeFile(tmp, data));
    await retry(() => fs.rename(tmp, file));
  } catch (e) {
    await fs.rm(tmp, { force: true }).catch(() => undefined); // (the write's error is the one to report)
    throw e;
  }
}

/** A file's text, or null if it isn't there or can't be read. */
export async function readText(file: string): Promise<string | null> {
  try {
    return await retry(() => fs.readFile(file, "utf-8"));
  } catch {
    return null;
  }
}

// ----- backups (heddle/backups.py) ----------------------------------------------------------

export const KEEP_BACKUPS = 20;
export const BACKUP_INTERVAL_MS = 5 * 60_000;

/** The full path as Python's Path.resolve() gives it (links followed where the file exists). */
function resolved(file: string): string {
  try {
    return realpathSync.native(file);
  } catch {
    return path.resolve(file);
  }
}

const stemOf = (file: string) => path.basename(file, path.extname(file));

/** <root>/<stem>-<first 8 of sha1(casefolded full path)>, as backups.backup_dir_for. */
export function backupDirFor(board: string, root: string): string {
  const digest = createHash("sha1").update(casefold(resolved(board)), "utf8").digest("hex").slice(0, 8);
  const stem = [...stemOf(board)].map((ch) => (/^[\p{L}\p{N} _-]$/u.test(ch) ? ch : "_")).join("") || "board";
  return path.join(root, `${stem}-${digest}`);
}

const pad = (n: number) => String(n).padStart(2, "0");
/** "2026-11-13 14-05-22" in local time, as the Python app names its backups. */
export const stamp = (ms: number) => {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;
};
const STAMP = /^(\d{4})-(\d{2})-(\d{2}) (\d{2})-(\d{2})-(\d{2})/;

export interface BackupFile {
  path: string;
  /** When it was made (ms, to the second). */
  at: number;
  /** Several in one second: " (1)", " (2)"… in the order made. */
  seq: number;
}

/** Backups of a board file, newest first. */
export async function listBackups(board: string, root: string): Promise<BackupFile[]> {
  const folder = backupDirFor(board, root);
  let names: string[];
  try {
    names = await fs.readdir(folder);
  } catch {
    return [];
  }
  const prefix = `${stemOf(board)} `;
  const found: BackupFile[] = [];
  for (const name of names) {
    if (!name.toLowerCase().endsWith(".json") || !name.startsWith(prefix)) continue;
    const rest = name.slice(prefix.length, -".json".length);
    const m = STAMP.exec(rest);
    if (!m) continue;
    const [y, mo, d, h, mi, s] = m.slice(1).map(Number) as [number, number, number, number, number, number];
    const at = new Date(y, mo - 1, d, h, mi, s).getTime();
    const tail = rest.slice(19).trim();
    const seq = /^\(\d+\)$/.test(tail) ? Number(tail.slice(1, -1)) : 0;
    found.push({ path: path.join(folder, name), at, seq });
  }
  return found.sort((a, b) => b.at - a.at || b.seq - a.seq);
}

/** Keep `text` (the board file as it is now, about to be overwritten) as a backup, as
 *  backups.make_backup: skipped when empty or, unless forced, when the newest backup is
 *  recent (or holds the same text). Older backups beyond `keep` go. Returns its path. */
export async function makeBackup(board: string, root: string, text: string, now: number, force = false,
                                 keep = KEEP_BACKUPS, interval = BACKUP_INTERVAL_MS): Promise<string | null> {
  if (!text.trim()) return null;
  const existing = await listBackups(board, root);
  const newest = existing[0];
  if (newest && !force && now - newest.at < interval) return null;
  if (newest && (await readText(newest.path)) === text) return null; // nothing new to keep
  const folder = backupDirFor(board, root);
  await fs.mkdir(folder, { recursive: true });
  const base = `${stemOf(board)} ${stamp(now)}`;
  let target = path.join(folder, `${base}.json`);
  for (let n = 1; await exists(target); n++) target = path.join(folder, `${base} (${n}).json`);
  await fs.writeFile(target, text, { flag: "wx" });
  for (const old of (await listBackups(board, root)).slice(keep)) await fs.rm(old.path, { force: true });
  return target;
}

async function exists(file: string): Promise<boolean> {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

// ----- the error log (heddle/error_log.py) -----------------------------------------------

export const MAX_LOG_BYTES = 1_000_000; // then error.log becomes error.log.old

/** Append an entry to `<dir>/error.log` in the Python app's format. */
export async function appendLog(dir: string, text: string, now = Date.now()): Promise<void> {
  const file = path.join(dir, "error.log");
  await fs.mkdir(dir, { recursive: true });
  try {
    if ((await fs.stat(file)).size > MAX_LOG_BYTES) await fs.rename(file, `${file}.old`);
  } catch {
    // (no log yet)
  }
  const when = stamp(now).replace(/^(\S+) (\d+)-(\d+)-(\d+)$/, "$1 $2:$3:$4");
  await fs.appendFile(file, `===== ${when} =====\n${text.trimEnd()}\n\n`, "utf-8");
}

// ----- the Python app's settings, read once ------------------------------------------------

export const PYTHON_KEY = "HKCU\\Software\\Heddle\\Heddle";

export interface PythonSettings {
  values: Record<string, string>;
  recent: string[];
}

/** The values `reg query <key>` prints (REG_SZ text; REG_MULTI_SZ split into a list). */
export function parseRegQuery(out: string): PythonSettings {
  const values: Record<string, string> = {};
  let recent: string[] = [];
  for (const line of out.split(/\r?\n/)) {
    const m = /^ {4}(\S+) {4}(REG_\w+) {4}(.*)$/.exec(line);
    if (!m) continue;
    const [, name, type, value] = m as unknown as [string, string, string, string];
    if (type === "REG_MULTI_SZ") {
      if (name === "recent_files") recent = value.split("\\0").filter((p) => p.trim());
    } else if (type === "REG_SZ") {
      values[name] = value;
    }
  }
  return { values, recent };
}

/** The Python app's settings, or null if it has none (or this isn't Windows). */
export function readPythonSettings(key = PYTHON_KEY): Promise<PythonSettings | null> {
  if (process.platform !== "win32" || !key) return Promise.resolve(null);
  return new Promise((resolve) => {
    execFile("reg", ["query", key], { windowsHide: true, timeout: 5000 }, (err, stdout) => {
      resolve(err ? null : parseRegQuery(stdout));
    });
  });
}

// ----- pictures ---------------------------------------------------------------------------

export const PICTURE_TYPES: Record<string, string> = {
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
  ".bmp": "image/bmp", ".svg": "image/svg+xml",
};
export const MAX_PICTURE_BYTES = 25_000_000;

/** A strand's picture path resolved as model.picture_from_file does: relative paths are
 *  relative to the board's folder. Null if it can't be resolved. */
export function picturePath(picture: string, board: string | null): string | null {
  if (!picture) return null;
  if (path.isAbsolute(picture)) return path.normalize(picture);
  return board ? path.normalize(path.join(path.dirname(board), picture)) : null;
}

/** An image file as a data: URL, or null (missing, not an image, too big). */
export async function pictureUrl(file: string): Promise<string | null> {
  const type = PICTURE_TYPES[path.extname(file).toLowerCase()];
  if (!type) return null;
  try {
    if ((await fs.stat(file)).size > MAX_PICTURE_BYTES) return null;
    return `data:${type};base64,${(await fs.readFile(file)).toString("base64")}`;
  } catch {
    return null;
  }
}
