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
