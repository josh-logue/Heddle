// The desktop shell's bridge (src/platform/bridge.ts) without Electron: answers from a
// MemoryHost's "disk" and dialogs, so desktopHost runs the same tests as the in-memory
// host. The main process's side (desktop/files.ts) has tests of its own.

import type { Answer, DesktopBackup, DesktopBridge, DesktopSeed } from "../src/platform/bridge.ts";
import { BACKUP_INTERVAL_MS } from "../src/platform/safety.ts";
import type { MemoryHost } from "./memoryHost.ts";

const ok = <T>(value: T): Answer<T> => ({ ok: true, value });
const baseOf = (p: string) => p.slice(p.lastIndexOf("/") + 1);

export interface FakeBridge extends DesktopBridge {
  /** What went to error.log. */
  logged: string[];
  /** Backups by board path, newest first. */
  backupFiles: Map<string, DesktopBackup[]>;
  /** What this window reported showing, and where boards were sent. */
  reported: [string | null, boolean][];
  routed: (string | null)[];
  /** Paths "open in another window" (route answers "elsewhere" for them). */
  elsewhere: Set<string>;
  /** The shell asks to close the window; resolves whether the page let it. */
  requestClose(): Promise<boolean>;
  /** The shell hands this window a board (a second launch). */
  handOver(path: string): void;
}

export function fakeBridge(mem: MemoryHost, seed: DesktopSeed | null = null): FakeBridge {
  const backupFiles = new Map<string, DesktopBackup[]>();
  const logged: string[] = [];
  const reported: [string | null, boolean][] = [];
  const routed: (string | null)[] = [];
  const elsewhere = new Set<string>();
  let closeListener: (() => void) | null = null;
  let openListener: (() => void) | null = null;
  let closed: ((yes: boolean) => void) | null = null;
  let handed: { path: string; name: string; text: string } | null = null;
  return {
    info: { version: "1.2.3", electron: "45.3.3", chrome: "156.0", os: "Windows_NT 10.0" },
    seed,
    open: null,
    newBoard: false,
    first: true,
    logged,
    backupFiles,
    reported,
    routed,
    elsewhere,
    report: (p, blank) => void reported.push([p, blank]),
    async route(p, blank) {
      routed.push(p);
      if (p !== null && !mem.disk.has(p)) return { ok: false, error: "can't be found", code: "gone" };
      return ok(p !== null && elsewhere.has(p) ? "elsewhere" : blank ? "here" : "elsewhere");
    },
    onOpen: (listener) => void (openListener = listener),
    takeOpen: async () => {
      const f = handed;
      handed = null;
      return f;
    },
    handOver(p) {
      handed = { path: p, name: baseOf(p), text: mem.disk.get(p) ?? "" };
      openListener?.();
    },
    onCloseRequest: (listener) => void (closeListener = listener),
    closeNow: () => closed?.(true),
    requestClose() {
      return new Promise<boolean>((resolve) => {
        closed = resolve;
        closeListener?.();
        setTimeout(() => resolve(false), 50); // (no closeNow by then: the page said no)
      });
    },
    async openDialog() {
      const p = mem.opens.shift() ?? null;
      if (p === null) return ok(null);
      const text = mem.disk.get(p);
      return text === undefined ? { ok: false, error: "ENOENT", code: "ENOENT" } : ok({ path: p, name: baseOf(p), text });
    },
    saveDialog: async () => ok(mem.saves.shift() ?? null),
    async read(p) {
      const text = mem.disk.get(p);
      return text === undefined ? { ok: false, error: "can't be found", code: "gone" } : ok(text);
    },
    async write(p, text) {
      if (mem.readOnly.has(p)) return { ok: false, error: "EPERM: operation not permitted", code: "EPERM" };
      mem.disk.set(p, text);
      return ok(null);
    },
    async saveExport(data, fileName) {
      mem.exports.push([fileName, typeof data === "string" ? data : new Blob([data as Uint8Array<ArrayBuffer>])]);
      return ok(true);
    },
    async pdf(svg) { // (the Save dialog answers from mem.saves)
      const p = mem.saves.shift() ?? null;
      if (p !== null) mem.pdfs.push(svg);
      return ok(p !== null);
    },
    backups: async (board) => ok([...(backupFiles.get(board) ?? [])]),
    async backup(board, text, now, force) {
      const list = backupFiles.get(board) ?? [];
      const newest = list[0];
      if (text.trim() && !(newest && !force && now - newest.at < BACKUP_INTERVAL_MS) && newest?.text !== text) {
        backupFiles.set(board, [{ path: `${board} backup ${list.length}`, at: now, seq: 0, text }, ...list]);
      }
      return ok(null);
    },
    log: (text) => void logged.push(text),
    picture: async (picture, board) => (picture === "pictures/rowan.png" && board ? "data:image/png;base64,AAAA" : null),
    pathFor: (file) => (file as File & { path?: string }).path ?? "",
  };
}
