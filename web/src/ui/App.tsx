import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fromNewerVersion, makeBoard } from "../core/model.ts";
import { BoardStore } from "../board/store.ts";
import type { BoardCanvas, CanvasHost } from "../canvas/controller.ts";
import { typing } from "../canvas/controller.ts";
import { canvasMeasurer } from "../canvas/measure.ts";
import { DARK, LIGHT } from "../canvas/theme.ts";
import {
  BoardFileError, FileGoneError, parseBoard, readBoardFile, type FileRef, type OpenedBoard,
} from "../platform/files.ts";
import { laterDb } from "../platform/db.ts";
import { getHost, matchesKey } from "../platform/host.ts";
import {
  describeTime, discardDraft, forgetFile, orphanDrafts, recentFiles, type Backup, type Draft, type FileEntry,
} from "../platform/safety.ts";
import { BoardSession, type ConflictChoice } from "./session.ts";
import { RestoreDialog } from "./SafetyDialogs.tsx";
import { OPTIONS, getOption, readJson, readSetting, writeJson, writeSetting, type OptionKey } from "../platform/settings.ts";
import { installErrorLog } from "../platform/errorLog.ts";
import { ErrorDialog, SettingsDialog } from "./SettingsDialog.tsx";
import { HelpDialog } from "./HelpDialog.tsx";
import { ExportImageDialog, ExportTextDialog, type ImageFormat, type TextScope } from "./ExportDialogs.tsx";
import { exportRoute, exportText, type TextOptions } from "../core/exportText.ts";
import { renderPng, renderSvg, type ImageOptions } from "../canvas/exportImage.ts";
import { describeCounts, searchCards } from "../core/filters.ts";
import { Sidebar, type PanelDef, type Side } from "./panels/Sidebar.tsx";
import { CardPanel } from "./panels/CardPanel.tsx";
import { FilterPanel, loadMatchAll, matchNote } from "./panels/FilterPanel.tsx";
import { SearchBar } from "./SearchBar.tsx";
import { BoardOptions, GoToCard, MultiEdit, Replace, strandInfoMap } from "./Tools.tsx";
import { CardListPanel } from "./panels/CardListPanel.tsx";
import { StrandsPanel, KIND_ONE, KIND_LABELS } from "./panels/StrandsPanel.tsx";
import { ApplyFields, RenameStrand, StrandChecklist } from "./StrandDialogs.tsx";
import { RENAMABLE_FIELDS, type StrandKind } from "../core/model.ts";
import { casefold } from "../core/pystr.ts";
import { COLORS_KEY, strandsOf, stateFromBoard } from "../board/store.ts";
import { BoardView } from "./BoardView.tsx";
import { DEMOS, demoById, type Demo } from "./demos.ts";
import { Choice, Confirm, type ChoiceButton } from "./Dialog.tsx";
import { ArrowEditor, CardEditor } from "./Editors.tsx";
import { ContextMenu } from "./ContextMenu.tsx";
import type { MenuItem } from "../canvas/menus.ts";
import { PathReader } from "../board/reader.ts";
import { ChecksPanel } from "./panels/ChecksPanel.tsx";
import { RoutesPanel } from "./panels/RoutesPanel.tsx";
import { ReaderPanel } from "./panels/ReaderPanel.tsx";
import { RouteDialog, ThreadChooser } from "./StoryDialogs.tsx";

const THEMES = ["system", "light", "dark"] as const;
type ThemeChoice = (typeof THEMES)[number];
const THEME_LABELS: Record<ThemeChoice, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

function useSystemDark(): boolean {
  const query = useMemo(() => window.matchMedia("(prefers-color-scheme: dark)"), []);
  const [dark, setDark] = useState(query.matches);
  useEffect(() => {
    const fn = () => setDark(query.matches);
    query.addEventListener("change", fn);
    return () => query.removeEventListener("change", fn);
  }, [query]);
  return dark;
}

interface Shown {
  store: BoardStore;
  /** Its saving: name, file, autosave, drafts, backups. */
  session: BoardSession;
  notes: string[];
}

type Modal =
  | { kind: "card"; id: string; isNew: boolean }
  | { kind: "arrows"; ids: string[] }
  | { kind: "confirm"; message: string; okLabel: string; resolve: (yes: boolean) => void }
  | { kind: "menu"; items: MenuItem[]; x: number; y: number }
  | { kind: "goto" } | { kind: "replace" } | { kind: "multi" } | { kind: "options" }
  | { kind: "rename"; strandKind: StrandKind; value: string }
  | { kind: "checklist"; title: string; intro: string; values: Record<string, string[]>; okLabel: string;
      extra?: Record<string, string[]>; extraLabel?: string; onOk: (chosen: Record<string, string[]>) => void }
  | { kind: "applyFields"; strandKind: StrandKind; source: string }
  | { kind: "route"; key: string[]; steps: string[]; defaultName: string }
  | { kind: "thread" }
  | { kind: "choice"; title: string; message: string; choices: ChoiceButton<string>[]; cancel: string; resolve: (v: string) => void }
  | { kind: "restore"; backups: [string, Backup][] }
  | { kind: "settings" } | { kind: "help" }
  | { kind: "exportText" } | { kind: "exportImage" }
  | { kind: "error"; summary: string };

/** The side panels, their keys, and where each one opens by default. */
const PANELS: { id: string; title: string; keys: string; tip: string }[] = [
  { id: "card", title: "Card", keys: "Ctrl+Shift+E", tip: "Edit the selected card's title, description and details beside the board" },
  { id: "filter", title: "Filter", keys: "Ctrl+L", tip: "Fade out the cards that don't have the tags, characters, colours… you tick" },
  { id: "cardList", title: "Card List", keys: "Ctrl+Shift+L", tip: "Every card on the board, group by group in story order: click one to find it" },
  { id: "strands", title: "Strands", keys: "Ctrl+Shift+B", tip: "Every strand on the board, where it's used, and its description and fields" },
  { id: "checks", title: "Story Checks", keys: "Ctrl+Shift+K", tip: "Show dead ends, extra starts, loops, loose cards and routes" },
  { id: "routes", title: "Routes", keys: "Ctrl+Shift+O", tip: "List every route from a start to an end, each with its own fields" },
  { id: "reader", title: "Path Reader", keys: "", tip: "Walk through the story card by card from the card you read from" },
];
/** Panels that belong to the story tools: hidden (and closed) while they're off. */
const STORY_PANELS = new Set(["checks", "routes", "reader"]);

interface PanelLayout {
  open: string[];
  side: Record<string, Side>;
  active: Partial<Record<Side, string>>;
  width: Record<Side, number>;
}
const DEFAULT_LAYOUT: PanelLayout = { open: [], side: {}, active: {}, width: { left: 280, right: 300 } };
const SEARCH_FLASH_MS = 700; // how long a search match's outline flashes

export function App() {
  /** Where the app runs: the browser, or the desktop shell (W9). Chosen once at startup. */
  const platform = useMemo(() => getHost(), []);
  const measurer = useMemo(() => canvasMeasurer(), []);
  const [shown, setShown] = useState<Shown | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [modal, setModal] = useState<Modal | null>(null);
  const [canvas, setCanvas] = useState<BoardCanvas | null>(null);
  const [zoom, setZoom] = useState(1);
  const [dragging, setDragging] = useState(false);
  const [themeChoice, setThemeChoice] = useState<ThemeChoice>(() => readSetting("theme", "system", THEMES));
  const [minimapOpen, setMinimapOpen] = useState(() => readSetting("minimap", "open", ["open", "closed"]) === "open");
  /** The Settings dialog's options (per browser). */
  const [options, setOptions] = useState(() =>
    Object.fromEntries((Object.keys(OPTIONS) as OptionKey[]).map((k) => [k, getOption(k)])) as Record<OptionKey, boolean>);
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);
  const snap = options.snap_to_grid;
  const setSnap = (on: boolean) => setOptions((o) => ({ ...o, snap_to_grid: on }));
  const [autosave, setAutosave] = useState(() => readSetting("autosave", "on", ["on", "off"]) === "on");
  const autosaveRef = useRef(autosave);
  const [recent, setRecent] = useState<FileEntry[]>([]);
  const getDb = useCallback(() => platform.storage(), [platform]);
  const locks = platform.locks;
  const modalRef = useRef<Modal | null>(null);
  const [, setTick] = useState(0); // re-render after board changes (undo state, modified)
  const [layout, setLayout] = useState<PanelLayout>(() => ({ ...DEFAULT_LAYOUT, ...readJson<Partial<PanelLayout>>("panels", {}) }));
  const [query, setQuery] = useState("");
  const [searchAt, setSearchAt] = useState<string | null>(null); // the match last jumped to
  const searchBox = useRef<HTMLInputElement>(null);
  const flashTimer = useRef(0);
  const systemDark = useSystemDark();
  const dark = themeChoice === "dark" || (themeChoice === "system" && systemDark);
  const theme = dark ? DARK : LIGHT;
  const store = shown?.store ?? null;
  const shownRef = useRef(shown);
  useEffect(() => {
    shownRef.current = shown;
  }, [shown]);
  useEffect(() => {
    modalRef.current = modal;
  }, [modal]);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  const modified = store?.modified ?? false;
  useEffect(() => {
    document.title = shown ? `${modified ? "● " : ""}${shown.session.name} · Heddle` : "Heddle";
  });

  // Development only: browser tests find cards on screen through this.
  useEffect(() => {
    if (import.meta.env.DEV) (window as unknown as { heddleCanvas?: BoardCanvas | null }).heddleCanvas = canvas;
  }, [canvas]);

  useEffect(() => {
    if (!canvas) return;
    return canvas.subscribe(() => {
      setZoom(canvas.camera.scale);
      setTick((n) => n + 1);
    });
  }, [canvas]);

  // Toolbar menus close on a click anywhere else.
  useEffect(() => {
    const down = (e: PointerEvent) => {
      for (const d of document.querySelectorAll<HTMLDetailsElement>("details.menu[open]")) {
        if (!d.contains(e.target as Node)) d.open = false;
      }
    };
    // …and once one of their commands is picked.
    const click = (e: MouseEvent) => {
      const item = (e.target as HTMLElement).closest(".menu-items button");
      if (item) (item.closest("details") as HTMLDetailsElement).open = false;
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("click", click);
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("click", click);
    };
  }, []);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(t);
  }, [notice]);

  const confirm = useCallback((message: string, okLabel = "Delete") =>
    new Promise<boolean>((resolve) => setModal({ kind: "confirm", message, okLabel, resolve })), []);
  const ask = useCallback(<T extends string>(title: string, message: string, choices: ChoiceButton<T>[], cancel: T) =>
    new Promise<T>((resolve) => setModal({
      kind: "choice", title, message, choices, cancel, resolve: (v) => resolve(v as T),
    })), []);

  /** Before replacing the board: ask if it has unsaved changes. */
  const mayDiscard = useCallback(async () => {
    const s = shownRef.current;
    if (!s?.store.modified) return true;
    return confirm(`“${s.session.name}” has changes that aren't saved.\n\nDiscard them?`, "Discard changes");
  }, [confirm]);

  /** What a board's saving asks of the page. */
  const sessionHost = useMemo(() => ({
    notice: (text: string) => setNotice(text),
    askConflict: (name: string) => ask<ConflictChoice>("File changed on disk",
      `“${name}” was changed outside this ${platform.words.holder} since you opened or last saved it, for example on another computer `
      + `or in another ${platform.words.holder}.\n\nOverwrite it with your version? The version in the file is backed up first `
      + "(File → Restore from backup…). Or save yours as a separate file.",
      [{ label: "Overwrite", value: "overwrite" }, { label: "Save as…", value: "save_as", primary: true }, { label: "Cancel", value: "cancel" }],
      "cancel"),
    busy: () => modalRef.current !== null && modalRef.current.kind !== "menu",
    autosaveOn: () => autosaveRef.current,
    changed: () => setTick((n) => n + 1),
  }), [ask, platform]);

  /** Show a board. The board it replaces (already confirmed) loses its draft. `recovered`:
   *  a draft brought back, which stays unsaved and keeps writing to the same draft. */
  const show = useCallback((opened: OpenedBoard, recovered?: Draft) => {
    const notes = [...opened.board.load_notes];
    if (fromNewerVersion(opened.board)) {
      notes.unshift("This board was saved by a newer version of Heddle: saving it here may lose what this version doesn't know about.");
    }
    setError("");
    void shownRef.current?.session.dispose(true);
    const store = new BoardStore(opened.board, measurer);
    store.setFilter(new Map(), loadMatchAll()); // a new board starts unfiltered; any / all stay as chosen
    if (recovered) store.markSaved(null); // never saved as it is: leaving asks
    // Shown straight away (the canvas needs the board in the same step); the storage
    // behind its saving catches up.
    const db = laterDb(getDb());
    const session = new BoardSession(store, {
      name: opened.name, handle: opened.handle, text: recovered ? recovered.disk ?? null : opened.text ?? null,
      draftId: recovered?.id,
    }, { db, locks, files: platform.files, backups: platform.backups }, sessionHost);
    setShown({ store, session, notes });
    setQuery("");
    setSearchAt(null);
    void session.start().then(async () => {
      if (session.openElsewhere) {
        const holder = platform.words.holder;
        setNotice(`“${session.name}” is also open in another ${holder}. Saving in one ${holder} can overwrite changes made in the other.`);
      }
      if (session.handle) setRecent(await recentFiles(db));
    });
  }, [measurer, getDb, locks, sessionHost, platform]);

  const setDemoInUrl = (id: string | null) => {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("demo", id);
    else url.searchParams.delete("demo");
    history.replaceState(null, "", url);
  };

  const showDemo = useCallback((demo: Demo, text: string) => {
    try {
      show({ ...parseBoard(text, `${demo.id}.json`), name: demo.name });
      setDemoInUrl(demo.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [show]);

  const openDemo = useCallback(async (demo: Demo) => {
    if (!(await mayDiscard())) return;
    try {
      showDemo(demo, await demo.load());
    } catch (e) {
      setError(String(e));
    }
  }, [mayDiscard, showDemo]);

  /** Nothing shown, or an untitled, unchanged, empty board: opening a board may use this
   *  window (the desktop: one board per window). */
  const isBlank = useCallback(() => {
    const s = shownRef.current;
    return !s || (!s.session.handle && !s.store.modified && !s.store.state.cards.length);
  }, []);

  /** May this window show the board (null: a new one)? Always in a browser. The desktop
   *  brings forward the window that has it, or opens it in a new window unless this one
   *  is blank. */
  const routeHere = useCallback(async (ref: FileRef | null) =>
    !platform.windows || (await platform.windows.route(ref, isBlank())) === "here", [platform, isBlank]);

  const openFile = useCallback(async (file: File) => {
    const ref = platform.files.refFor(file); // (the desktop can save back to it)
    try {
      if (ref && !(await routeHere(ref))) return;
      if (!(await mayDiscard())) return;
      show(await readBoardFile(file, ref));
      setDemoInUrl(null);
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't open “${file.name}”: ${String(e)}`);
    }
  }, [mayDiscard, show, platform, routeHere]);

  const open = useCallback(async () => {
    // (a browser asks before the file dialog; the desktop never replaces a board here)
    if (!platform.windows && !(await mayDiscard())) return;
    try {
      const picked = await platform.files.pickBoard();
      // (the desktop opens it here only in a blank window: nothing to discard)
      if (picked && (await routeHere(picked.ref))) {
        show(parseBoard(picked.text, picked.fileName, picked.ref));
        setDemoInUrl(null);
      }
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't open the board: ${String(e)}`);
    }
  }, [mayDiscard, show, platform, routeHere]);

  const newBoard = useCallback(async () => {
    try {
      if (!(await routeHere(null))) return; // (the desktop: a new window)
    } catch (e) {
      setError(`Couldn't open a new window: ${String(e)}`);
      return;
    }
    if (!(await mayDiscard())) return;
    show({ board: makeBoard(), name: "Untitled", handle: null, text: null });
    setDemoInUrl(null);
  }, [mayDiscard, show, routeHere]);

  const save = useCallback(async (as = false) => {
    const s = shownRef.current;
    if (!s) return;
    try {
      if (await s.session.save(as)) setDemoInUrl(null);
      setTick((n) => n + 1);
      void getDb().then(async (db) => setRecent(await recentFiles(db)));
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't save: ${String(e)}`);
    }
  }, [getDb]);

  // Leaving (or hiding the page) with unsaved changes: the host asks and keeps a draft.
  // Closing a desktop window asks here: Save / Don't save / Cancel.
  useEffect(() => platform.onLeave({
    unsaved: () => shownRef.current?.store.modified ?? false,
    keepDraft: () => void shownRef.current?.session.keepDraft(),
    askToClose: async () => {
      const s = shownRef.current;
      if (!s?.store.modified) return true;
      const choice = await ask("Save changes?", `“${s.session.name}” has changes that aren't saved.\n\nSave them before closing?`,
        [{ label: "Save", value: "save", primary: true }, { label: "Don't save", value: "discard" }, { label: "Cancel", value: "cancel" }],
        "cancel");
      if (choice === "save") {
        await save();
        return !shownRef.current?.store.modified; // (not if Save As was cancelled or failed)
      }
      if (choice === "discard") await s.session.dispose(true); // (and its draft)
      return choice === "discard";
    },
  }), [platform, ask, save]);

  // The desktop: what this window shows, so a board opens in one window only.
  const shownFile = shown?.session.handle ?? null;
  const blankNow = !shown || (!shownFile && !modified && !shown.store.state.cards.length);
  useEffect(() => platform.windows?.report(shownFile, blankNow), [platform, shownFile, blankNow]);

  const toggleAutosave = useCallback((on: boolean) => {
    autosaveRef.current = on;
    setAutosave(on);
    writeSetting("autosave", on ? "on" : "off");
    const s = shownRef.current;
    if (on && s?.store.modified) s.session.schedule();
  }, []);

  /** Open Recent: a board file used before (Chrome and Edge), asking to read it again. */
  const openRecent = useCallback(async (entry: FileEntry) => {
    try {
      if (!(await routeHere(entry.handle))) return;
      if (!(await mayDiscard())) return;
      const text = await platform.files.reopen(entry.handle);
      if (text === null) {
        setError(`Heddle wasn't allowed to open “${entry.name}”.`);
        return;
      }
      show(parseBoard(text, entry.handle.name, entry.handle));
      setDemoInUrl(null);
    } catch (e) {
      if (e instanceof FileGoneError) {
        setError(`“${entry.name}” can't be found any more: it was moved, renamed or deleted.`);
        const db = await getDb();
        await forgetFile(db, entry.key);
        setRecent(await recentFiles(db));
      } else {
        setError(e instanceof BoardFileError ? e.message : `Couldn't open “${entry.name}”: ${String(e)}`);
      }
    }
  }, [mayDiscard, show, getDb, platform, routeHere]);

  const restoreBackup = useCallback(async () => {
    const s = shownRef.current;
    if (!s) return;
    const backups = await s.session.backups();
    if (!backups.length) {
      setNotice(s.session.handle || s.session.diskText !== null
        ? `There are no backups of “${s.session.name}” yet. One is made the first time you save over it each session, then at most every 5 minutes.`
        : "This board hasn't been saved yet, so it has no backups.");
      return;
    }
    setModal({ kind: "restore", backups });
  }, []);

  // Unexpected errors are logged in this browser and reported (one dialog per burst).
  useEffect(() => installErrorLog((summary) => setModal((m) => (m?.kind === "error" ? m : { kind: "error", summary }))), []);

  // Development only: browser tests reach the board's saving, and open a file handle
  // directly (they can't drive the browser's file picker; they use its private files).
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const w = window as unknown as { heddleSession?: BoardSession | null; heddleOpen?: (h: FileRef) => Promise<void> };
    w.heddleSession = shown?.session ?? null;
    w.heddleOpen = async (h) => {
      if (!(await mayDiscard())) return;
      const text = await platform.files.reopen(h);
      if (text === null) throw new Error(`Not allowed to read “${h.name}”`);
      show(parseBoard(text, h.name, h));
    };
  }, [shown, mayDiscard, show, platform]);

  // The desktop: the board this window was opened for, and any handed over later (a
  // second launch with a board, into a blank window).
  const openedForWindow = useRef(false);
  useEffect(() => platform.windows?.onOpen((picked) => {
    openedForWindow.current = true;
    void (async () => {
      if (!(await mayDiscard())) return;
      if (!picked) { // (File → New in another window)
        show({ board: makeBoard(), name: "Untitled", handle: null, text: null });
        return;
      }
      try {
        show(parseBoard(picked.text, picked.fileName, picked.ref));
        setDemoInUrl(null);
      } catch (e) {
        setError(e instanceof BoardFileError ? e.message : `Couldn't open “${picked.fileName}”: ${String(e)}`);
      }
    })();
  }), [platform, mayDiscard, show]);

  // On opening the page: a board whose tab closed without saving it is offered back
  // (the newest; older ones wait for next time), as the desktop offers its recovery copies.
  // The desktop offers it in its first window only, unless that opened a board.
  useEffect(() => {
    let cancelled = false;
    void getDb().then(async (db) => {
      setRecent(await recentFiles(db));
      const found = await orphanDrafts(db, locks);
      const draft = found[0];
      if (cancelled || !draft || shownRef.current?.store.modified) return;
      if (openedForWindow.current || platform.windows?.first === false) return;
      const more = found.length > 1 ? `\n\n(${found.length - 1} older unsaved board${found.length > 2 ? "s" : ""} will be offered next time.)` : "";
      const when = describeTime(draft.at).replace(/^Today, /, "today at ").replace(/^Yesterday, /, "yesterday at ");
      const choice = await ask("Recover unsaved board",
        `“${draft.name}” wasn't saved before its ${platform.words.holder} closed.\n\nIt was last kept ${when} and has ${draft.cards} card${draft.cards === 1 ? "" : "s"}. Recover it?${more}`,
        [{ label: "Recover", value: "recover", primary: true }, { label: "Delete", value: "delete" }, { label: "Not now", value: "later" }],
        "later");
      if (choice === "delete") await discardDraft(db, draft.id);
      if (choice !== "recover") return;
      try {
        show({ ...parseBoard(draft.text, `${draft.name}.json`, draft.handle ?? null), text: draft.disk ?? null }, draft);
        setNotice("Recovered an unsaved board · Save to keep it");
      } catch (e) {
        setError(e instanceof BoardFileError ? e.message : `Couldn't recover “${draft.name}”: ${String(e)}`);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [getDb, locks, ask, show, platform]);

  // A link such as ?demo=lantern-tide opens that demo straight away.
  useEffect(() => {
    const demo = demoById(new URLSearchParams(window.location.search).get("demo"));
    if (demo) void demo.load().then((text) => showDemo(demo, text), (e) => setError(String(e)));
  }, [showDemo]);

  // Drop a board file anywhere on the page.
  useEffect(() => {
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const over = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setDragging(true);
    };
    const leave = (e: DragEvent) => {
      if (e.relatedTarget === null) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer?.files[0];
      if (file) void openFile(file);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [openFile]);

  const allDetails = store ? store.details.size > 0 : false;
  const toggleAllDetails = useCallback(() => {
    if (!store) return;
    store.setDetails(store.state.cards.map((c) => c.id), store.details.size === 0);
  }, [store]);
  const toggleAllCollapsed = useCallback(() => {
    if (!store) return;
    store.setCollapsed(store.state.cards.filter((c) => c.kind === "group").map((c) => c.id), !store.anyCollapsed);
  }, [store]);
  const undo = useCallback(() => store?.undo(), [store]);
  const redo = useCallback(() => store?.redo(), [store]);

  // ----- panels ---------------------------------------------------------------------------
  const saveLayout = useCallback((next: PanelLayout) => {
    setLayout(next);
    writeJson("panels", next);
  }, []);
  const panelSide = (id: string): Side => layout.side[id] ?? "right";
  const isOpen = (id: string) => layout.open.includes(id);
  const showPanel = useCallback((id: string, show?: boolean) => {
    const open = layout.open.includes(id);
    const want = show ?? !(open && layout.active[layout.side[id] ?? "right"] === id);
    if (!want) {
      saveLayout({ ...layout, open: layout.open.filter((x) => x !== id) });
      return;
    }
    const side = layout.side[id] ?? "right";
    saveLayout({ ...layout, open: open ? layout.open : [...layout.open, id], active: { ...layout.active, [side]: id } });
  }, [layout, saveLayout]);

  // ----- search ---------------------------------------------------------------------------
  /** [card id, field, snippet] for every match, in reading order. */
  const matchesFor = useCallback((text: string): [string, string, string][] => {
    if (!store || !text.trim()) return [];
    const boxes = store.boxes;
    const cards = [...store.state.cards].sort((a, b) => {
      const p = boxes.get(a.id)!;
      const q = boxes.get(b.id)!;
      return Math.round(p.y) - Math.round(q.y) || p.x - q.x;
    });
    return searchCards(cards, text, strandInfoMap(store));
  }, [store]);
  const searchMatches = useCallback(() => matchesFor(query), [matchesFor, query]);

  // ----- story tools ------------------------------------------------------------------------
  const canvasRef = useRef(canvas);
  useEffect(() => {
    canvasRef.current = canvas;
  }, [canvas]);
  /** The Path Reader's walk, one per board; each step selects its card and brings it into view. */
  const reader = useMemo(() => store && new PathReader(store, (id) => {
    store.reveal([id]);
    store.select([id]);
    const b = store.boxes.get(store.structure.visibleEnd(id));
    if (b) canvasRef.current?.centerOn(b.x + b.w / 2, b.y + b.h / 2);
  }), [store]);
  useEffect(() => () => reader?.dispose(), [reader]);
  const [readerFocus, setReaderFocus] = useState(0); // bumped to hand the keyboard to the reader

  /** Select cards (story check results, a route) and bring them all into view. */
  const showCards = useCallback((ids: string[]) => {
    if (!store || !canvas || !ids.length) return;
    store.reveal(ids);
    store.select(ids);
    const boxes = ids.map((id) => store.boxes.get(id)).filter((b) => b !== undefined);
    if (!boxes.length) return;
    const x1 = Math.min(...boxes.map((b) => b.x));
    const y1 = Math.min(...boxes.map((b) => b.y));
    const x2 = Math.max(...boxes.map((b) => b.x + b.w));
    const y2 = Math.max(...boxes.map((b) => b.y + b.h));
    canvas.centerOn((x1 + x2) / 2, (y1 + y2) / 2);
  }, [store, canvas]);

  /** Open the Path Reader at a card (default: the selected one). */
  const readFrom = useCallback((id?: string) => {
    if (!store || !reader || !store.state.display.story_tools) return;
    const start = id ?? (store.selected.size === 1 ? [...store.selected][0]! : null);
    if (start === null) {
      setNotice("Select one card to read from it");
      return;
    }
    showPanel("reader", true);
    reader.start(start);
    setReaderFocus((n) => n + 1);
  }, [store, reader, showPanel]);

  const chooseThread = useCallback(() => {
    if (!store || !store.state.display.story_tools) return;
    if (!store.allValues("characters").length) setNotice("No card has any characters yet");
    else setModal({ kind: "thread" });
  }, [store]);

  /** Show a card: unfold its groups, select it, bring it into view and outline it briefly. */
  const showCard = useCallback((id: string) => {
    if (!store || !canvas) return;
    store.reveal([id]);
    store.select([id]);
    const b = store.boxes.get(id);
    if (b) canvas.centerOn(b.x + b.w / 2, b.y + b.h / 2);
    store.setFlash(id);
    clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => store.setFlash(null), SEARCH_FLASH_MS);
  }, [store, canvas]);

  const jumpTo = useCallback((matches: [string, string, string][], index: number) => {
    const [id, label, snippet] = matches[index]!;
    showCard(id);
    setSearchAt(id);
    const where = store!.titleContext(id);
    const hidden = store!.dimmed.has(id) ? " · hidden by the filter" : "";
    setNotice(`${label}: ${snippet}${where ? ` · in “${where}”` : ""}${hidden}`);
  }, [showCard, store]);

  /** Typing shows the first match; collapsed groups say how many are folded inside them. */
  const searchChanged = (text: string) => {
    setQuery(text);
    setSearchAt(null);
    const matches = matchesFor(text);
    store?.setSearchHits(matches.map(([id]) => id));
    if (matches.length) jumpTo(matches, 0);
  };

  const searchStep = useCallback((direction: 1 | -1) => {
    const matches = searchMatches();
    if (!matches.length) return;
    const ids = matches.map(([id]) => id);
    const at = searchAt ? ids.indexOf(searchAt) : -1;
    const index = at >= 0 ? (at + direction + ids.length) % ids.length : direction > 0 ? 0 : ids.length - 1;
    jumpTo(matches, index);
  }, [searchMatches, searchAt, jumpTo]);
  const matchList = searchMatches();
  const searchIndex = searchAt ? matchList.findIndex(([id]) => id === searchAt) + 1 : 0;

  // ----- strands ------------------------------------------------------------------------------
  const renameStrand = useCallback((strandKind: StrandKind = "tags", value = "") => setModal({ kind: "rename", strandKind, value }), []);

  const removeUnused = useCallback(() => {
    if (!store) return;
    const unused = store.unusedSaved();
    const detailed = store.unusedStrands()[1] as Record<string, string[]>;
    const n = Object.values(detailed).reduce((t, v) => t + v.length, 0);
    if (!Object.keys(unused).length && !n) {
      setNotice("There are no strands or custom colors that nothing on the board uses.");
      return;
    }
    setModal({
      kind: "checklist", title: "Remove unused strands", okLabel: "Remove", values: unused, extra: detailed,
      intro: "Nothing on the board uses these strands or custom colors. Checked ones will be removed from this board's strands and palette.",
      extraLabel: `Also list unused strands with a description, picture or fields (${n})`,
      onOk: (chosen) => {
        const removed = store.removeSaved(chosen);
        setNotice(`Removed ${removed} unused strand${removed !== 1 ? "s" : ""} or color${removed !== 1 ? "s" : ""}`);
      },
    });
  }, [store]);

  /** Offer the strands (and custom colours) in another board file that this one lacks. */
  const importStrands = useCallback(async () => {
    if (!store) return;
    let opened: OpenedBoard | null;
    try {
      const picked = await platform.files.pickBoard();
      opened = picked && parseBoard(picked.text, picked.fileName, picked.ref);
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't read the board: ${String(e)}`);
      return;
    }
    if (!opened) return;
    const source = stateFromBoard(opened.board);
    const fresh: Record<string, string[]> = {};
    for (const f of RENAMABLE_FIELDS) {
      const have = new Set(store.allValues(f).map(casefold));
      const add = strandsOf(source, f).filter((v) => !have.has(casefold(v)));
      if (add.length) fresh[f] = add;
    }
    const colors = source.custom_colors.filter((c) => !store.state.custom_colors.includes(c));
    if (colors.length) fresh[COLORS_KEY] = colors;
    if (!Object.keys(fresh).length) {
      setNotice(`“${opened.name}” has no strands or custom colors this board doesn't already have.`);
      return;
    }
    const name = opened.name;
    setModal({
      kind: "checklist", title: "Import strands", okLabel: "Import", values: fresh,
      intro: `Strands and custom colors from “${name}” that this board doesn't have yet. Checked ones are added to this board's strands; no cards are copied.`,
      onOk: (chosen) => {
        const { [COLORS_KEY]: chosenColors = [], ...strands } = chosen;
        const added = store.importStrands(strands, chosenColors, source.strands);
        setNotice(`Imported ${added} strand${added !== 1 ? "s" : ""} or color${added !== 1 ? "s" : ""} from “${name}”`);
      },
    });
  }, [store, platform]);

  /** Cards picked in the Card List: select them and bring them into view. A card folded in a
   *  collapsed group selects that group, unless `unfold`, which opens it and hands the
   *  keyboard to the board. */
  /** A strand's picture, found from the board's file (relative paths), where the host can show it. */
  const boardFile = shown?.session.handle ?? null;
  const strandPicture = useCallback((picture: string) => platform.picture(picture, boardFile), [platform, boardFile]);

  const showListed = useCallback((ids: string[], unfold: boolean) => {
    if (!store || !canvas) return;
    if (unfold) store.reveal(ids);
    const targets = [...new Set(ids.map((id) => (unfold ? id : store.structure.visibleEnd(id))))];
    store.select(targets);
    const b = store.boxes.get(targets[0]!);
    if (b) canvas.reveal(b.card.id);
    if (unfold) requestAnimationFrame(() => canvas.canvas.focus({ preventScroll: true }));
  }, [store, canvas]);

  const focusCanvas = useCallback(() => requestAnimationFrame(() => canvas?.canvas.focus({ preventScroll: true })), [canvas]);

  /** Save an exported file and say where it went. */
  const saveExport = useCallback(async (data: string | Blob, fileName: string, type: string, description: string, extra = "") => {
    try {
      const done = await platform.files.saveExport(data, fileName, type, description);
      if (done === false) return;
      setNotice(`${done === "downloaded" ? "Downloaded" : "Exported"} “${fileName}”.${extra}`);
    } catch (e) {
      setError(`Couldn't export “${fileName}”: ${String(e)}`);
    }
  }, [platform]);

  /** File → Export story as text: the board, the selection or the route being read. */
  const runTextExport = useCallback((scope: TextScope, opts: TextOptions) => {
    const s = shownRef.current;
    if (!s) return;
    const title = s.session.name;
    const board = s.store.board;
    const text = scope === "route" && reader
      ? exportRoute(board, reader.route, reader.via, `${title}: a route`, opts)
      : exportText(board, s.store.storyGraph(), title, opts, scope === "selection" ? [...s.store.selected] : null);
    void saveExport(text, `${title}.md`, "text/markdown", "Markdown");
  }, [reader, saveExport]);

  /** File → Export board as image: PNG, SVG, or PDF (a browser prints the SVG: Save as PDF). */
  const runImageExport = useCallback(async (opts: ImageOptions, format: ImageFormat) => {
    const s = shownRef.current;
    if (!s) return;
    const look = opts.light ? LIGHT : theme;
    const nothing = opts.selectionOnly ? "Select some cards to export them." : "There's nothing on the board to export yet.";
    try {
      if (format === "png") {
        const png = await renderPng(s.store, look, measurer, opts);
        if (!png) return setNotice(nothing);
        const note = png.reducedTo ? ` It was made at ${png.reducedTo.toFixed(2)}× instead of ${opts.scale}× to fit the browser's limits.` : "";
        await saveExport(png.blob, `${s.session.name}.png`, "image/png", "PNG image", note);
        return;
      }
      const svg = renderSvg(s.store, look, measurer, opts);
      if (!svg) return setNotice(nothing);
      if (format === "pdf") {
        if ((await platform.pdf(svg, s.session.name)) === "saved") setNotice(`Exported “${s.session.name}.pdf”.`);
      }
      else await saveExport(svg, `${s.session.name}.svg`, "image/svg+xml", "SVG drawing");
    } catch (e) {
      setError(`Couldn't export the board: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [theme, measurer, saveExport, platform]);

  const addCardRef = useRef(() => {});

  // App-wide keys (the canvas handles its own while it has focus).
  useEffect(() => {
    const keys = platform.keys;
    const key = (e: KeyboardEvent) => {
      if (modal) return; // a dialog is open: it has the keyboard
      const ctrl = e.ctrlKey || e.metaKey;
      if (e.key === "F1") {
        e.preventDefault(); // (the browser's own help)
        setModal({ kind: "help" });
      } else if (ctrl && e.code === "KeyS") {
        e.preventDefault();
        void save(e.shiftKey);
      } else if (ctrl && !e.shiftKey && e.code === "KeyO") {
        e.preventDefault();
        void open();
      } else if (ctrl && !e.shiftKey && e.code === "KeyF" && store) {
        e.preventDefault();
        searchBox.current?.focus();
        searchBox.current?.select();
      } else if (e.key === "F3" && store) {
        e.preventDefault();
        searchStep(e.shiftKey ? -1 : 1);
      } else if (ctrl && !e.shiftKey && e.code === "KeyP" && store) {
        e.preventDefault(); // (the browser's print key)
        setModal({ kind: "goto" });
      } else if (ctrl && !e.shiftKey && e.code === "KeyH" && store) {
        e.preventDefault();
        setModal({ kind: "replace" });
      } else if (ctrl && !e.shiftKey && e.code === "KeyE" && store && store.selected.size) {
        e.preventDefault();
        if (store.selected.size === 1) setModal({ kind: "card", id: [...store.selected][0]!, isNew: false });
        else setModal({ kind: "multi" });
      } else if (ctrl && !e.shiftKey && e.code === "KeyL" && store) {
        e.preventDefault();
        showPanel("filter");
      } else if (ctrl && e.shiftKey && e.code === "KeyE" && store) {
        e.preventDefault();
        showPanel("card");
      } else if (ctrl && e.shiftKey && e.code === "KeyL" && store) {
        e.preventDefault();
        showPanel("cardList");
      } else if (ctrl && e.shiftKey && e.code === "KeyB" && store) {
        e.preventDefault();
        showPanel("strands");
      } else if (ctrl && e.shiftKey && e.code === "KeyK" && store && store.state.display.story_tools) {
        e.preventDefault();
        showPanel("checks");
      } else if (ctrl && e.shiftKey && e.code === "KeyO" && store && store.state.display.story_tools) {
        e.preventDefault(); // (Chrome's bookmark manager)
        showPanel("routes");
      } else if (ctrl && e.shiftKey && e.code === "KeyR" && store && store.state.display.story_tools) {
        e.preventDefault(); // (the browser's hard reload)
        readFrom();
      } else if (ctrl && !e.shiftKey && e.code === "Comma") {
        e.preventDefault();
        setModal({ kind: "settings" });
      } else if (ctrl && !e.shiftKey && e.code === "KeyR" && store) {
        e.preventDefault(); // (the browser's reload key)
        renameStrand();
      } else if (!e.defaultPrevented && keys.addCard.ctrl && matchesKey(keys.addCard, e) && store) {
        // The desktop's Ctrl+Shift+N and Ctrl+T work anywhere in the window (the board
        // handles them itself when it has the keyboard; a browser's N and T are board keys).
        e.preventDefault();
        addCardRef.current();
      } else if (!e.defaultPrevented && keys.thread.ctrl && matchesKey(keys.thread, e) && store?.state.display.story_tools) {
        e.preventDefault();
        chooseThread();
      } else if (typing(e)) {
        return;
      } else if (ctrl && !e.shiftKey && e.code === "KeyZ") {
        e.preventDefault();
        undo();
      } else if (ctrl && (e.code === "KeyY" || (e.shiftKey && e.code === "KeyZ"))) {
        e.preventDefault();
        redo();
      } else if (ctrl && e.key === "0") {
        e.preventDefault();
        canvas?.resetZoom();
      } else if (matchesKey(platform.keys.fit, e)) {
        e.preventDefault(); // (most browsers keep Ctrl+1 for switching tabs)
        canvas?.fit();
      } else if (!ctrl && !e.altKey && e.shiftKey && e.code === "KeyD") {
        toggleAllDetails();
      } else if (!ctrl && !e.altKey && e.shiftKey && e.code === "KeyC") {
        toggleAllCollapsed();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [canvas, modal, save, open, undo, redo, toggleAllDetails, toggleAllCollapsed, store, searchStep, showPanel, renameStrand, readFrom, platform, chooseThread]);

  const host = useMemo<CanvasHost>(() => ({
    editCard: (id, isNew) => setModal({ kind: "card", id, isNew }),
    editArrows: (ids) => setModal({ kind: "arrows", ids }),
    editSeveral: () => setModal({ kind: "multi" }),
    confirm: (message) => confirm(message),
    notice: (text) => setNotice(text),
    snapToGrid: () => snap,
    contextMenu: (items, x, y) => setModal({ kind: "menu", items, x, y }),
    read: (id) => readFrom(id),
    chooseThread,
    wheelZooms: () => optionsRef.current.wheel_zooms,
    keys: () => platform.keys,
  }), [confirm, snap, readFrom, chooseThread, platform]);

  const closeMenu = useCallback(() => {
    setModal((m) => (m?.kind === "menu" ? null : m));
    // The keyboard goes back to the board, unless the command handed it to something else
    // (a dialog, or the Path Reader for "Read from here").
    requestAnimationFrame(() => {
      const at = document.activeElement;
      const loose = !at || at === document.body || !!at.closest(".context-menu");
      if (loose && !document.querySelector("dialog[open]")) canvas?.canvas.focus({ preventScroll: true });
    });
  }, [canvas]);

  const closeModal = () => {
    setModal(null);
    // After the dialog has gone (closing it hands focus back to the page first).
    requestAnimationFrame(() => canvas?.canvas.focus({ preventScroll: true }));
  };

  const cycleTheme = () => {
    const next = THEMES[(THEMES.indexOf(themeChoice) + 1) % THEMES.length]!;
    setThemeChoice(next);
    writeSetting("theme", next);
  };

  const toggleMinimap = useCallback(() => {
    setMinimapOpen((was) => {
      writeSetting("minimap", was ? "closed" : "open");
      return !was;
    });
  }, []);

  const hasGroups = store?.state.cards.some((c) => c.kind === "group") ?? false;
  const addCard = () => {
    if (!store || !canvas) return;
    const [x, y] = canvas.newCardPoint();
    const card = store.addCard(x, y, snap);
    canvas.reveal(card.id);
    setModal({ kind: "card", id: card.id, isNew: true });
  };
  useEffect(() => {
    addCardRef.current = addCard;
  });

  const panelDefs: Record<string, PanelDef> = store ? {
    card: { id: "card", title: "Card", render: () => (
      <CardPanel store={store} onEditCard={(id) => setModal({ kind: "card", id, isNew: false })} onEditSeveral={() => setModal({ kind: "multi" })} />
    ) },
    filter: { id: "filter", title: "Filter", render: () => (
      <FilterPanel store={store} onMenu={(items, x, y) => setModal({ kind: "menu", items, x, y })} />
    ) },
    cardList: { id: "cardList", title: "Card List", render: () => <CardListPanel store={store} onShow={showListed} /> },
    strands: { id: "strands", title: "Strands", render: () => (
      <StrandsPanel store={store} act={{
        picture: strandPicture,
        rename: (k, v) => renameStrand(k, v),
        removeUnused,
        applyFields: (k, v) => setModal({ kind: "applyFields", strandKind: k, source: v }),
        selectCards: (ids) => showListed(ids, false),
        addToBoard: (k, v) => {
          if (!canvas) return;
          const [x, y] = canvas.camera.toScene(canvas.camera.width / 2, canvas.camera.height / 2);
          store.addStrandCard(k, v, x, y, snap);
        },
      }} />
    ) },
    checks: { id: "checks", title: "Story Checks", render: () => <ChecksPanel store={store} onShow={showCards} /> },
    routes: { id: "routes", title: "Routes", render: () => (
      <RoutesPanel store={store} onShow={showCards}
                   onEdit={(key, steps, defaultName) => setModal({ kind: "route", key, steps, defaultName })} />
    ) },
    reader: { id: "reader", title: "Path Reader", render: () => <ReaderPanel key={readerFocus} reader={reader!} autoFocus={readerFocus > 0} /> },
  } : {};
  const storyTools = store?.state.display.story_tools ?? true;
  if (!storyTools) for (const id of STORY_PANELS) delete panelDefs[id];
  const sidebar = (side: Side) => {
    const panels = layout.open.filter((id) => panelDefs[id] && panelSide(id) === side).map((id) => panelDefs[id]!);
    return (
      <Sidebar side={side} panels={panels} active={layout.active[side] ?? null} width={layout.width[side]}
               onActivate={(id) => saveLayout({ ...layout, active: { ...layout.active, [side]: id } })}
               onClose={(id) => saveLayout({ ...layout, open: layout.open.filter((x) => x !== id) })}
               onMove={(id) => {
                 const to: Side = side === "left" ? "right" : "left";
                 saveLayout({ ...layout, side: { ...layout.side, [id]: to }, active: { ...layout.active, [to]: id } });
               }}
               onResize={(w) => saveLayout({ ...layout, width: { ...layout.width, [side]: w } })} />
    );
  };
  const filterPanelShown = isOpen("filter") && layout.active[panelSide("filter")] === "filter";
  /** Is a panel showing (open, and the front tab on its side)? */
  const shownPanel = (id: string) => {
    if (!isOpen(id) || !panelDefs[id]) return false;
    const side = panelSide(id);
    const onSide = layout.open.filter((x) => panelDefs[x] && panelSide(x) === side);
    return (onSide.includes(layout.active[side] ?? "") ? layout.active[side] : onSide[0]) === id;
  };
  const readerShown = shownPanel("reader");
  // Closing the Path Reader (or tabbing away from it) ends the reading and its highlight.
  useEffect(() => {
    if (!readerShown) reader?.stop();
  }, [readerShown, reader]);

  return (
    <div className="app">
      <header className="toolbar">
        <span className="brand">
          <img src={`${import.meta.env.BASE_URL}icon.svg`} alt="" width={20} height={20} />
          Heddle
        </span>
        <details className="menu">
          <summary>File</summary>
          <div className="menu-items">
            <button type="button" onClick={() => void newBoard()}>New board<span className="muted">Start an empty board</span></button>
            <button type="button" onClick={() => void open()}>Open…<kbd>Ctrl+O</kbd><span className="muted">A board file (.json) from your computer</span></button>
            {recent.length > 0 && (
              <>
                <p className="menu-heading">Open recent</p>
                {recent.map((r) => (
                  <button type="button" key={r.key} className="recent" onClick={() => void openRecent(r)}>{r.name}</button>
                ))}
              </>
            )}
            {store && (
              <>
                <button type="button" onClick={() => void save()}>Save<kbd>Ctrl+S</kbd>
                  <span className="muted">{platform.files.canSaveInPlace() ? "Back to its file" : "Downloads the board as a .json file"}</span></button>
                <button type="button" onClick={() => void save(true)}>Save as…<kbd>Ctrl+Shift+S</kbd><span className="muted">To a new file</span></button>
                <button type="button" onClick={() => void restoreBackup()}>Restore from backup…<span className="muted">An earlier version of this board</span></button>
                <button type="button" onClick={() => void importStrands()}>Import strands…<span className="muted">Another board's strands and colours, no cards</span></button>
                <button type="button" onClick={() => setModal({ kind: "exportText" })}>Export story as text…<span className="muted">The cards in story order, as Markdown</span></button>
                <button type="button" onClick={() => setModal({ kind: "exportImage" })}>Export board as image…<span className="muted">{platform.kind === "browser" ? "PNG, SVG, or print to PDF" : "PNG, SVG or PDF"}</span></button>
              </>
            )}
            <label className="menu-check" title={platform.words.holder === "window"
              ? "A minute after a change: saved to the board's file (an untitled board is kept as a draft)"
              : "A minute after a change: saved to the board's file where this browser can, otherwise kept as a draft in the browser"}>
              <input type="checkbox" checked={autosave} onChange={(e) => toggleAutosave(e.target.checked)} /> Autosave
            </label>
            <hr />
            <p className="menu-heading">Demo boards</p>
            {DEMOS.map((d) => (
              <button type="button" key={d.id} onClick={() => void openDemo(d)}>
                <strong>{d.name}</strong>
                <span>{d.blurb}</span>
              </button>
            ))}
          </div>
        </details>
        {store && (
          <>
            <button type="button" onClick={() => void save()}
                    title={platform.files.canSaveInPlace() ? "Save (Ctrl+S)" : "Save: downloads the board as a .json file (Ctrl+S)"}>Save</button>
            <span className="sep" />
            <button type="button" className="icon" onClick={undo} disabled={!store.history.canUndo()} title="Undo (Ctrl+Z)" aria-label="Undo">↶</button>
            <button type="button" className="icon" onClick={redo} disabled={!store.history.canRedo()} title="Redo (Ctrl+Y)" aria-label="Redo">↷</button>
            <button type="button" onClick={addCard} title={`Add a card (${platform.keys.addCard.label}, or double-click the canvas)`}>Add card</button>
          </>
        )}
        {shown && <span className="board-name" title={shown.session.name}>{modified ? "● " : ""}{shown.session.name}</span>}
        {shown?.session.status && <span className="save-status muted" title={shown.session.status}>{shown.session.status}</span>}
        <span className="spacer" />
        {store && (
          <SearchBar ref={searchBox} text={query} index={searchIndex} total={matchList.length} onChange={searchChanged}
                     onStep={searchStep} onLeave={focusCanvas} />
        )}
        {store && (
          <details className="menu right">
            <summary>Edit</summary>
            <div className="menu-items narrow">
              <button type="button" onClick={() => setModal({ kind: "goto" })}>Go to card…<kbd>Ctrl+P</kbd></button>
              <button type="button" onClick={() => setModal({ kind: "replace" })}>Replace…<kbd>Ctrl+H</kbd></button>
              <button type="button" disabled={store.selected.size < 2} onClick={() => setModal({ kind: "multi" })}>
                Edit selected cards…<kbd>Ctrl+E</kbd>
              </button>
              <button type="button" onClick={() => store.selectAll()}>Select all<kbd>Ctrl+A</kbd></button>
              <hr />
              <button type="button" onClick={() => renameStrand()}>Rename strand…<kbd>Ctrl+R</kbd></button>
              <button type="button" onClick={removeUnused}>Remove unused strands…</button>
              <hr />
              <button type="button" onClick={() => setModal({ kind: "settings" })}>Settings…<kbd>Ctrl+,</kbd><span className="muted">For {platform.words.here}, not saved with the board</span></button>
            </div>
          </details>
        )}
        {store && (
          <details className="menu right">
            <summary>Panels</summary>
            <div className="menu-items narrow">
              {PANELS.filter((pd) => storyTools || !STORY_PANELS.has(pd.id)).map((pd) => (
                <label key={pd.id} className="menu-check" title={pd.tip}>
                  <input type="checkbox" checked={isOpen(pd.id)} onChange={(e) => showPanel(pd.id, e.target.checked)} /> {pd.title}
                  {pd.keys && <kbd>{pd.keys}</kbd>}
                </label>
              ))}
            </div>
          </details>
        )}
        <details className="menu right">
          <summary>View</summary>
          <div className="menu-items narrow">
            {store && (
              <>
                <button type="button" onClick={toggleAllDetails} title="Shift+D">
                  {allDetails ? "Hide every card's details" : "Show every card's details"}<kbd>Shift+D</kbd>
                </button>
                {hasGroups && (
                  <button type="button" onClick={toggleAllCollapsed} title="Shift+C">
                    {store.anyCollapsed ? "Expand every group" : "Collapse every group"}<kbd>Shift+C</kbd>
                  </button>
                )}
                <label className="menu-check" title="Cards land on the grid when you move them">
                  <input type="checkbox" checked={snap} onChange={(e) => {
                    setSnap(e.target.checked);
                    writeSetting("snap", e.target.checked ? "on" : "off"); // (the Settings dialog's snap_to_grid)
                  }} /> Snap cards to the grid
                </label>
                <button type="button" onClick={() => setModal({ kind: "options" })}>Board options…<span className="muted">Saved with this board</span></button>
                <hr />
                <p className="menu-heading">Story</p>
                <label className="menu-check" title="★ introductions, Story Checks, Routes, the Path Reader and character threads. Turn off for a board that just sorts things into groups.">
                  <input type="checkbox" checked={storyTools} onChange={(e) => store.setDisplay({ story_tools: e.target.checked })} /> Story tools
                </label>
                <button type="button" title="Light up everything that can come before and after the selected card (H again clears)"
                        onClick={() => { const n = store.togglePaths(); if (n) setNotice(n); }}>Highlight paths<kbd>H</kbd></button>
                <button type="button" title="Switch the path highlight between before and after, only what leads here and only what follows"
                        onClick={() => { const n = store.cyclePathsMode(); if (n) setNotice(n); }}>Highlight before / after<kbd>Shift+H</kbd></button>
                <label className="menu-check" title="While on, selecting a card lights up its paths">
                  <input type="checkbox" checked={store.state.display.follow_paths}
                         onChange={(e) => store.setDisplay({ follow_paths: e.target.checked })} /> Highlight paths of selection
                </label>
                {storyTools && (
                  <>
                    <button type="button" title="Leave the selected cards out of the story tools, or put them back"
                            onClick={() => { const n = store.toggleOutside(); if (n) setNotice(n); }}>Not part of the story<kbd>O</kbd></button>
                    <button type="button" title="Walk through the story from the selected card in the Path Reader"
                            onClick={() => readFrom()}>Read from selected card<kbd>Ctrl+Shift+R</kbd></button>
                    <button type="button" title="Light up every card featuring a character, numbered in story order"
                            onClick={chooseThread}>Character thread…<kbd>{platform.keys.thread.label}</kbd></button>
                  </>
                )}
                {store.highlight && <button type="button" onClick={() => store.clearHighlight()}>Clear highlight<kbd>Esc</kbd></button>}
                <hr />
              </>
            )}
            <button type="button" onClick={cycleTheme}>{THEME_LABELS[themeChoice]}<span className="muted">Light, dark, system</span></button>
          </div>
        </details>
        {store && (
          <span className="zoom-group">
            <button type="button" className="icon" onClick={() => canvas?.zoomBy(1 / 1.15)} title="Zoom out (Ctrl+scroll)" aria-label="Zoom out">−</button>
            <button type="button" className="zoom" onClick={() => canvas?.resetZoom()} title="Actual size (Ctrl+0)">
              {Math.round(zoom * 100)}%
            </button>
            <button type="button" className="icon" onClick={() => canvas?.zoomBy(1.15)} title="Zoom in (Ctrl+scroll)" aria-label="Zoom in">+</button>
            <button type="button" onClick={() => canvas?.fit()} title="Fit the whole board on screen">Fit</button>
          </span>
        )}
        <button type="button" className="icon" onClick={() => setModal({ kind: "help" })} title="Help: the controls (F1)" aria-label="Help">?</button>
      </header>

      <div className="workspace">
      {store && sidebar("left")}
      <main className="main">
        {(error || notice || (shown && shown.notes.length > 0)) && (
          <div className={error ? "notice error" : "notice"} role={error ? "alert" : "status"}>
            <span>{error || notice || `Opened with repairs: ${shown!.notes.join("; ")}.`}</span>
            <button type="button" aria-label="Dismiss" onClick={() => {
              if (error) setError("");
              else if (notice) setNotice("");
              else setShown({ ...shown!, notes: [] });
            }}>×</button>
          </div>
        )}

        <BoardView store={store} theme={theme} measurer={measurer} host={host} minimapOpen={minimapOpen}
                   onToggleMinimap={toggleMinimap} onReady={setCanvas} />
        {!store && (
          <section className="welcome">
            <h1>Heddle</h1>
            <p>Map branching and converging story paths: cards on a canvas, joined by arrows.</p>
            <p className="muted">
              Boards stay on your computer: nothing is uploaded. This browser version does what the desktop app does,
              apart from showing strand pictures. Once visited it works offline, and Chrome or Edge can install it as
              an app. Press F1 for the controls.
            </p>
            <div className="welcome-actions">
              <button type="button" className="primary" onClick={() => void open()}>Open a board…</button>
              <button type="button" onClick={() => void newBoard()}>Start an empty board</button>
              <span className="muted">or drop a .json board file anywhere on the page</span>
            </div>
            <h2>Or look at a demo board</h2>
            <ul className="demo-list">
              {DEMOS.map((d) => (
                <li key={d.id}>
                  <button type="button" onClick={() => void openDemo(d)}>
                    <strong>{d.name}</strong>
                    <span>{d.blurb}</span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="muted small">
              The desktop app is on <a href="https://github.com/josh-logue/Heddle">GitHub</a>.
            </p>
          </section>
        )}
        {options.show_banners && (store?.filterActive || store?.highlight) && (
          <div className="banners">
            {store.filterActive && (
              <div className="filter-banner" role="status">
                <span><strong>Filter on</strong> · showing {describeCounts(store.filterCounts)}{matchNote(store) ? ` · ${matchNote(store)}` : ""}</span>
                {!filterPanelShown && <button type="button" onClick={() => showPanel("filter", true)}>Show filter</button>}
                <button type="button" onClick={() => store.setFilter(new Map(), store.filter.matchAll)}>Clear</button>
              </div>
            )}
            {store.highlight && (
              <div className="filter-banner highlight-banner" role="status">
                <span><strong>{store.highlight.label}</strong> · Esc to clear</span>
                <button type="button" onClick={() => store.clearHighlight()}>Clear</button>
              </div>
            )}
          </div>
        )}
        {dragging && <div className="drop-hint">Drop a board file to open it</div>}
      </main>
      {store && sidebar("right")}
      </div>

      {store && modal?.kind === "card" && store.card(modal.id) && (
        <CardEditor key={modal.id} store={store} id={modal.id} isNew={modal.isNew} onClose={closeModal} />
      )}
      {store && modal?.kind === "arrows" && <ArrowEditor store={store} ids={modal.ids} onClose={closeModal} />}
      {store && modal?.kind === "goto" && (
        <GoToCard store={store} onClose={closeModal} onGo={(id) => {
          closeModal();
          showCard(id);
          const where = store.titleContext(id);
          setNotice(`Went to “${store.card(id)?.title.trim() || "Untitled"}”${where ? ` in “${where}”` : ""}`);
        }} />
      )}
      {store && modal?.kind === "replace" && (
        <Replace store={store} onClose={closeModal} onDone={(n) => {
          closeModal();
          setNotice(n ? `Replaced text in ${n} card${n !== 1 ? "s" : ""}` : "Nothing to replace");
        }} />
      )}
      {store && modal?.kind === "multi" && (
        <MultiEdit store={store} onClose={closeModal} onDone={(n) => {
          closeModal();
          setNotice(`Changed ${n} card${n !== 1 ? "s" : ""}`);
        }} />
      )}
      {store && modal?.kind === "options" && <BoardOptions store={store} onClose={closeModal} />}
      {store && modal?.kind === "rename" && (
        <RenameStrand store={store} kind={modal.strandKind} value={modal.value} onClose={closeModal}
                      onConfirm={(k, old, name, message) => {
                        setModal({ kind: "confirm", message, okLabel: "Rename", resolve: (yes) => {
                          if (!yes) return;
                          const n = store.renameStrand(k, old, name);
                          setNotice(`Renamed ${KIND_ONE[k]} “${old}” to “${name}”${n ? ` on ${n} card${n !== 1 ? "s" : ""}` : ""}`);
                        } });
                      }} />
      )}
      {modal?.kind === "checklist" && (
        <StrandChecklist title={modal.title} intro={modal.intro} values={modal.values} okLabel={modal.okLabel}
                         extra={modal.extra} extraLabel={modal.extraLabel} onClose={closeModal}
                         onOk={(chosen) => {
                           closeModal();
                           modal.onOk(chosen);
                         }} />
      )}
      {store && modal?.kind === "applyFields" && (
        <ApplyFields kind={modal.strandKind} source={modal.source} fields={store.strand(modal.strandKind, modal.source)?.fields ?? []}
                     others={store.allValues(modal.strandKind).filter((v) => casefold(v) !== casefold(modal.source))}
                     onClose={closeModal} onOk={(targets, names, withValues) => {
                       closeModal();
                       const k = modal.strandKind;
                       const [changed, added] = store.applyStrandFields(k, modal.source, targets, names, withValues);
                       const plural = KIND_LABELS[k].toLowerCase();
                       setNotice(changed ? `Added ${added} field${added === 1 ? "" : "s"} to ${changed} ${changed === 1 ? KIND_ONE[k] : plural}`
                         : targets.length === 1 ? `That ${KIND_ONE[k]} already has these fields` : `Those ${plural} already have these fields`);
                     }} />
      )}
      {store && modal?.kind === "route" && (
        <RouteDialog store={store} routeKey={modal.key} steps={modal.steps} defaultName={modal.defaultName} onClose={closeModal} />
      )}
      {store && modal?.kind === "thread" && (
        <ThreadChooser store={store} onClose={closeModal} onPick={(name) => {
          closeModal();
          if (!store.showThread(name)) setNotice(`No card features ${name}`);
        }} />
      )}
      {modal?.kind === "menu" && <ContextMenu items={modal.items} x={modal.x} y={modal.y} onClose={closeMenu} />}
      {modal?.kind === "settings" && (
        <SettingsDialog onClose={closeModal} onSaved={(values) => {
          setOptions(values);
          closeModal();
        }} />
      )}
      {modal?.kind === "error" && <ErrorDialog summary={modal.summary} onClose={closeModal} />}
      {modal?.kind === "help" && <HelpDialog onClose={closeModal} />}
      {store && modal?.kind === "exportText" && (
        <ExportTextDialog hasSelection={store.selected.size > 0} hasRoute={!!reader?.route.length} onClose={closeModal}
                          onExport={(scope, opts) => {
                            closeModal();
                            runTextExport(scope, opts);
                          }} />
      )}
      {store && modal?.kind === "exportImage" && (
        <ExportImageDialog hasSelection={store.selected.size > 0} pdfByPrint={platform.kind === "browser"} onClose={closeModal} onExport={(opts, format) => {
          closeModal();
          void runImageExport(opts, format);
        }} />
      )}
      {modal?.kind === "choice" && (
        <Choice title={modal.title} message={modal.message} choices={modal.choices} cancel={modal.cancel} onAnswer={(v) => {
          modal.resolve(v);
          closeModal();
        }} />
      )}
      {store && shown && modal?.kind === "restore" && (
        <RestoreDialog name={shown.session.name} backups={modal.backups} onClose={closeModal} onRestore={(b) => {
          closeModal();
          try {
            store.replaceBoard(parseBoard(b.text, `${b.name}.json`).board);
            setNotice(`Restored the backup from ${describeTime(b.at)}. Undo (Ctrl+Z) to go back; save to keep it.`);
          } catch (e) {
            setError(e instanceof BoardFileError ? e.message : `Couldn't restore the backup: ${String(e)}`);
          }
        }} />
      )}
      {modal?.kind === "confirm" && (
        <Confirm message={modal.message} okLabel={modal.okLabel} onAnswer={(yes) => {
          modal.resolve(yes);
          closeModal();
        }} />
      )}
    </div>
  );
}
