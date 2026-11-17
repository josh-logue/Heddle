// Pure helpers for the shell's windows (no Electron, so Vitest runs them): where a new
// window goes, which command-line arguments are boards, and when two paths are one board.

import path from "node:path";
import { casefold } from "../src/core/pystr.ts";

export const CASCADE = 30; // px down and right of the window in front (as the Python app)
export const DEFAULT_SIZE = { width: 1280, height: 800 };
const MIN_VISIBLE = 100; // px of a remembered window that must be on a screen to reuse it

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SavedBounds {
  bounds: Bounds;
  maximized: boolean;
}

const overlap = (a: Bounds, b: Bounds) =>
  Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) >= MIN_VISIBLE
  && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) >= MIN_VISIBLE;

/** A new window's place: down and right of the window in front, if there is one;
 *  else where the last window was, if that's still on a screen; else the default size,
 *  centred on the first screen. */
export function placeWindow(saved: SavedBounds | null, lead: SavedBounds | null, screens: Bounds[],
                            cascade = CASCADE): { bounds: Partial<Bounds> & { width: number; height: number }; maximized: boolean } {
  if (lead) {
    const b = lead.bounds;
    const moved = { x: b.x + cascade, y: b.y + cascade, width: b.width, height: b.height };
    return { bounds: screens.some((s) => overlap(moved, s)) ? moved : { ...b }, maximized: lead.maximized };
  }
  if (saved && isBounds(saved.bounds) && screens.some((s) => overlap(saved.bounds, s))) {
    return { bounds: { ...saved.bounds }, maximized: !!saved.maximized };
  }
  return { bounds: { ...DEFAULT_SIZE }, maximized: false };
}

function isBounds(b: unknown): b is Bounds {
  const r = b as Bounds;
  return !!r && [r.x, r.y, r.width, r.height].every((n) => Number.isFinite(n)) && r.width > 0 && r.height > 0;
}

/** Do two paths name the same board file (Windows: case and slashes don't matter)? */
export function sameBoardPath(a: string, b: string): boolean {
  const norm = (p: string) => {
    const full = path.resolve(p);
    return process.platform === "win32" ? casefold(full) : full;
  };
  return norm(a) === norm(b);
}

/** The board files named on a command line (resolved from `cwd`): arguments ending in
 *  .json that aren't switches. `skip`: leading arguments that are the program itself (and
 *  the script, when run as `electron main.ts`). */
export function boardArgs(argv: readonly string[], cwd: string, skip: number): string[] {
  return argv.slice(skip)
    .filter((a) => !a.startsWith("-") && a.toLowerCase().endsWith(".json"))
    .map((a) => path.resolve(cwd, a));
}
