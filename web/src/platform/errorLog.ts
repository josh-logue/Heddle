// Unexpected errors: kept by the host and reported, instead of vanishing
// (heddle/error_log.py). The browser has no file to write, so browserHost keeps the log in
// localStorage, and the "Copy error report" button puts it on the clipboard.

import { getHost } from "./host.ts";

export const MAX_ENTRIES = 50; // the oldest go first (where the host keeps a list)
export const MAX_ENTRY_CHARS = 8000;
export const QUIET_MS = 10_000; // after a report, more errors this soon are only logged

export interface ErrorEntry {
  at: number;
  text: string;
}

export function errorEntries(): ErrorEntry[] {
  return getHost().errors.entries();
}

export function logError(text: string, at = Date.now()): void {
  getHost().errors.append({ at, text: text.slice(0, MAX_ENTRY_CHARS) });
}

export function clearErrors(): void {
  getHost().errors.clear();
}

/** An error, its stack, as text. */
export function describeError(e: unknown): string {
  if (e instanceof Error) return e.stack && e.stack.includes(e.message) ? e.stack : `${e.name}: ${e.message}\n${e.stack ?? ""}`;
  return String(e);
}

/** The text "Copy error report" copies: what's running, then the logged errors. */
export function errorReport(entries = errorEntries(), about = getHost().errors.about()): string {
  const lines = [...about, ""];
  if (!entries.length) lines.push("No errors logged.");
  for (const e of entries) lines.push(`===== ${new Date(e.at).toISOString()} =====`, e.text.trimEnd(), "");
  return lines.join("\n");
}

/** Route uncaught errors through `report` (logged first, so nothing is lost if the
 *  report can't be shown). A burst shows only its first report. */
export function installErrorLog(report: (summary: string) => void): () => void {
  let last = -Infinity;
  const handle = (e: unknown) => {
    const text = describeError(e);
    logError(text);
    const now = Date.now();
    if (now - last < QUIET_MS) return;
    last = now;
    report(text.split("\n")[0] ?? "Error");
  };
  const onError = (ev: ErrorEvent) => handle(ev.error ?? ev.message);
  const onRejection = (ev: PromiseRejectionEvent) => handle(ev.reason);
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
