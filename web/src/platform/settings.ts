// Preferences and remembered layout, kept by the host (browserHost: localStorage, where
// reads and writes are allowed to fail quietly).

import { getHost } from "./host.ts";

export function readSetting<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  const v = getHost().settings.get(key);
  return v !== null && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
}

export function writeSetting(key: string, value: string): void {
  getHost().settings.set(key, value);
}

/** A remembered value stored as JSON (panel layout and the like); `fallback` if missing
 *  or unreadable. */
export function readJson<T>(key: string, fallback: T): T {
  const raw = getHost().settings.get(key);
  try {
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  writeSetting(key, JSON.stringify(value));
}

// ----- the Settings dialog's options (heddle/settings.OPTIONS) ----------------------------

/** key -> [default, section, label, tip]. The desktop's "show the menu bar" has no web
 *  counterpart (the browser owns the Alt key and the top of the window). */
export const OPTIONS = {
  commit_pending_entries: [true, "Card editor", "Save tag/location/character on dialog accept",
    "When you press OK in the card editor, any tag, character or location still typed in its box (not yet added with Enter) is added to the card instead of being discarded."],
  wheel_zooms: [false, "Canvas", "Mouse wheel zooms (Ctrl+wheel scrolls)",
    "Off (default, trackpad-friendly): scrolling pans the board, Shift+scroll pans sideways, and Ctrl+scroll or pinching zooms.\nOn: the wheel zooms and Ctrl+wheel pans."],
  show_banners: [true, "Canvas", "Show bars over the canvas for filters and highlights",
    "A bar at the top of the canvas says when a filter or highlight is on, with buttons to clear it. Off: Esc still clears a highlight, and the Filter panel still shows the filter."],
  snap_to_grid: [false, "Canvas", "Snap cards to the grid",
    "Cards land on the 25 px grid when you drop or nudge them, and new cards start on it (arrow keys then step to the next grid line; Shift+arrow still moves 1 px). Cards you don't move stay where they are."],
} as const satisfies Record<string, readonly [boolean, string, string, string]>;
export type OptionKey = keyof typeof OPTIONS;

/** Where each option is kept ("snap" predates the Settings dialog). */
const STORED: Record<OptionKey, string> = {
  commit_pending_entries: "commitPending", wheel_zooms: "wheelZooms", show_banners: "banners", snap_to_grid: "snap",
};

export function getOption(key: OptionKey): boolean {
  const fallback = OPTIONS[key][0] ? "on" : "off";
  return readSetting(STORED[key], fallback, ["on", "off"]) === "on";
}

export function setOption(key: OptionKey, on: boolean): void {
  writeSetting(STORED[key], on ? "on" : "off");
}
