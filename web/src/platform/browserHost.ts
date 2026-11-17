// The app's host in a browser: files through the File System Access API or downloads,
// drafts and backups in IndexedDB, Web Locks between tabs, settings and the error log in
// localStorage, PDF through the browser's Print. The only module that imports
// platform/browser/ (lint enforces this).

import { MemoryDb, type Db } from "./db.ts";
import { MAX_ENTRIES, type ErrorEntry } from "./errorLog.ts";
import { BROWSER_KEYS, type Host, type HostErrors, type HostSettings, type LeavingPage } from "./host.ts";
import { dbBackups, type Locks } from "./safety.ts";
import { openDb } from "./browser/db.ts";
import { browserFiles } from "./browser/files.ts";
import { browserLocks } from "./browser/locks.ts";
import { printSvg } from "./browser/print.ts";

const PREFIX = "heddle.";
const ERRORS_KEY = "heddle.errors";

/** localStorage can be missing or blocked (private windows, cleared site data), so every
 *  read and write is allowed to fail quietly. */
const settings: HostSettings = {
  get(key) {
    try {
      return localStorage.getItem(PREFIX + key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(PREFIX + key, value);
    } catch {
      // (not remembered: nothing else to do)
    }
  },
};

function readErrors(): ErrorEntry[] {
  try {
    const raw = JSON.parse(localStorage.getItem(ERRORS_KEY) ?? "[]") as unknown;
    return Array.isArray(raw) ? raw.filter((e): e is ErrorEntry => typeof e?.text === "string" && typeof e?.at === "number") : [];
  } catch {
    return [];
  }
}

/** The error report's heading in a browser (`agent`: the browser's user agent). */
export function browserAbout(agent = typeof navigator === "undefined" ? "" : navigator.userAgent): string[] {
  return ["Heddle (web) error report", `Browser: ${agent}`, `Page: ${typeof location === "undefined" ? "" : location.origin + location.pathname}`];
}

const errors: HostErrors = {
  entries: readErrors,
  append(entry) {
    const entries = [...readErrors(), entry].slice(-MAX_ENTRIES);
    try {
      localStorage.setItem(ERRORS_KEY, JSON.stringify(entries));
    } catch {
      // (storage full or blocked: the report dialog still shows this one)
    }
  },
  clear() {
    try {
      localStorage.removeItem(ERRORS_KEY);
    } catch {
      // (nothing to clear)
    }
  },
  about: () => browserAbout(),
  place: "in this browser",
};

/** Leaving with unsaved changes: the browser asks (its own wording), unless `ask` is
 *  false (the desktop shell asks its own way). Hidden or closing with unsaved changes: keep
 *  a draft, offered next time if the tab doesn't come back (the browser may not finish
 *  writing it as the tab closes). */
export function watchLeaving(page: LeavingPage, ask = true): () => void {
  const before = (e: BeforeUnloadEvent) => {
    if (ask && page.unsaved()) e.preventDefault();
  };
  const hidden = () => {
    if (document.visibilityState === "hidden" && page.unsaved()) page.keepDraft();
  };
  const leaving = () => {
    if (page.unsaved()) page.keepDraft();
  };
  window.addEventListener("beforeunload", before);
  document.addEventListener("visibilitychange", hidden);
  window.addEventListener("pagehide", leaving);
  return () => {
    window.removeEventListener("beforeunload", before);
    document.removeEventListener("visibilitychange", hidden);
    window.removeEventListener("pagehide", leaving);
  };
}

/** Works offline once visited, and can be installed (web/offline.ts). */
function installOffline(): void {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => undefined);
  });
}

let db: Promise<Db> | null = null;
let locks: Locks | null = null;
const storage = () => (db ??= openDb().catch(() => new MemoryDb()));

export const browserHost: Host = {
  kind: "browser",
  files: browserFiles,
  windows: null,
  storage,
  backups: dbBackups(storage),
  picture: async () => null, // (a page can't read picture files by path)
  // Made on first use, so importing this module touches no browser API (Node tests).
  locks: {
    hold: (name, shared) => (locks ??= browserLocks()).hold(name, shared),
    held: (name) => (locks ??= browserLocks()).held(name),
  },
  settings,
  errors,
  clipboard: { writeText: async (text) => navigator.clipboard.writeText(text) },
  pdf: async (svg, title) => {
    printSvg(svg, title);
    return "printed";
  },
  onLeave: (page) => watchLeaving(page),
  installOffline,
  keys: BROWSER_KEYS,
  words: { holder: "tab", here: "this browser" },
};
