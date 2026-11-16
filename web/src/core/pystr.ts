// Python's string and ordering rules, for a port that must give the same answers as the
// desktop app. JavaScript differs in ways that matter here:
// - there's no casefold() (ß, ς, ligatures, Cherokee: see casefoldTable.ts);
// - str.split(), strip() and splitlines() use a different set of whitespace and line
//   breaks from JavaScript's \s and trim();
// - Python compares and counts strings by code point, JavaScript by UTF-16 unit, which
//   differs for emoji and other characters outside the Basic Multilingual Plane;
// - sorted() compares tuples element by element.

import { CASEFOLD_EXCEPTIONS } from "./casefoldTable.ts";

/** Python's str.casefold(). */
export function casefold(s: string): string {
  // eslint-disable-next-line no-control-regex
  if (/^[\x00-\x7f]*$/.test(s)) return s.toLowerCase();
  let out = "";
  for (const ch of s) {
    // Per character, so JavaScript's final-sigma rule (Σ at a word end -> ς) can't apply.
    out += CASEFOLD_EXCEPTIONS.get(ch.codePointAt(0)!) ?? ch.toLowerCase();
  }
  return out;
}

// Python's str.isspace() characters, and str.splitlines() boundaries. Kept as escaped
// strings (not regex literals) so no raw line-separator character ends up in the source.
const WS = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const BREAKS = "\\n\\v\\f\\r\\x1c\\x1d\\x1e\\x85\\u2028\\u2029";
const STRIP_RE = new RegExp(`^[${WS}]+|[${WS}]+$`, "g");
const RSTRIP_RE = new RegExp(`[${WS}]+$`);
const SPLIT_RE = new RegExp(`[${WS}]+`);
const LINES_RE = new RegExp(`\\r\\n|[${BREAKS}]`); // \r\n counts as one break

/** Python's str.strip() with no argument. */
export function strip(s: string): string {
  return s.replace(STRIP_RE, "");
}

/** Python's str.rstrip() with no argument. */
export function rstrip(s: string): string {
  return s.replace(RSTRIP_RE, "");
}

/** Python's str.split() with no argument: words between runs of whitespace. */
export function splitWords(s: string): string[] {
  const t = strip(s);
  return t ? t.split(SPLIT_RE) : [];
}

/** `" ".join(text.split())`: whitespace runs (line breaks too) become one space. */
export function collapseSpaces(s: string): string {
  return splitWords(s).join(" ");
}

/** Python's str.splitlines(). */
export function splitLines(s: string): string[] {
  if (!s) return [];
  const parts = s.split(LINES_RE);
  // A trailing line break doesn't start another (empty) line.
  if (parts.length > 1 && parts[parts.length - 1] === "") parts.pop();
  return parts;
}

/** Code points, as Python indexes and counts a string. */
export function codePoints(s: string): string[] {
  return Array.from(s);
}

/** Compare two strings by code point, as Python does. */
export function compareStrings(a: string, b: string): number {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const x = a.charCodeAt(i);
    const y = b.charCodeAt(i);
    if (x !== y) {
      // Surrogates (0xD800-0xDFFF) stand for code points above 0xFFFF, which sort after
      // everything in the Basic Multilingual Plane; UTF-16 order puts 0xE000-0xFFFF last.
      const xs = x >= 0xd800 && x <= 0xdfff;
      const ys = y >= 0xd800 && y <= 0xdfff;
      if (xs !== ys) return xs ? 1 : -1;
      return x - y;
    }
  }
  return a.length - b.length;
}

/** A sort key: a number, a string, or a tuple of keys (compared element by element). */
export type SortKey = number | string | boolean | readonly SortKey[];

export function compareKeys(a: SortKey, b: SortKey): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) {
      const c = compareKeys(a[i] as SortKey, b[i] as SortKey);
      if (c !== 0) return c;
    }
    return a.length - b.length;
  }
  if (typeof a === "string" && typeof b === "string") return compareStrings(a, b);
  const x = Number(a);
  const y = Number(b);
  return x < y ? -1 : x > y ? 1 : 0;
}

/** Python's sorted(items, key=key): a new, stably sorted array. */
export function sortedBy<T>(items: Iterable<T>, key: (item: T) => SortKey): T[] {
  const decorated = Array.from(items, (item, i) => ({ item, k: key(item), i }));
  decorated.sort((p, q) => compareKeys(p.k, q.k) || p.i - q.i);
  return decorated.map((d) => d.item);
}

/** Python's sorted() on strings. */
export function sortedStrings(items: Iterable<string>): string[] {
  return Array.from(items).sort(compareStrings);
}

/** Python's min(items, key=key): the first of the smallest. */
export function minBy<T>(items: readonly T[], key: (item: T) => SortKey): T {
  let best = items[0]!;
  let bestKey = key(best);
  for (let i = 1; i < items.length; i++) {
    const k = key(items[i]!);
    if (compareKeys(k, bestKey) < 0) {
      best = items[i]!;
      bestKey = k;
    }
  }
  return best;
}

/** Python's max(items, key=key): the first of the largest. */
export function maxBy<T>(items: readonly T[], key: (item: T) => SortKey): T {
  let best = items[0]!;
  let bestKey = key(best);
  for (let i = 1; i < items.length; i++) {
    const k = key(items[i]!);
    if (compareKeys(k, bestKey) > 0) {
      best = items[i]!;
      bestKey = k;
    }
  }
  return best;
}

/** Escape text for use inside a regular expression (Python's re.escape). */
export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&");
}
