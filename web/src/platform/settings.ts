// Per-browser preferences in localStorage. Storage can be missing or blocked (private
// windows, cleared site data), so every read and write is allowed to fail quietly.

const PREFIX = "heddle.";

export function readSetting<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(PREFIX + key);
    return v !== null && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeSetting(key: string, value: string): void {
  try {
    localStorage.setItem(PREFIX + key, value);
  } catch {
    // (not remembered: nothing else to do)
  }
}

/** A remembered value stored as JSON (panel layout and the like); `fallback` if missing
 *  or unreadable. */
export function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  writeSetting(key, JSON.stringify(value));
}
