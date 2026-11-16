import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fromNewerVersion, makeBoard } from "../core/model.ts";
import { BoardStore } from "../board/store.ts";
import type { BoardCanvas, CanvasHost } from "../canvas/controller.ts";
import { typing } from "../canvas/controller.ts";
import { canvasMeasurer } from "../canvas/measure.ts";
import { DARK, LIGHT } from "../canvas/theme.ts";
import {
  BoardFileError, canSaveInPlace, parseBoard, pickBoard, readBoardFile, saveAs, saveToHandle,
  type FileHandle, type OpenedBoard,
} from "../platform/files.ts";
import { readSetting, writeSetting } from "../platform/settings.ts";
import { BoardView } from "./BoardView.tsx";
import { DEMOS, demoById, type Demo } from "./demos.ts";
import { Confirm } from "./Dialog.tsx";
import { ArrowEditor, CardEditor } from "./Editors.tsx";

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
  name: string;
  handle: FileHandle | null;
  notes: string[];
}

type Modal =
  | { kind: "card"; id: string; isNew: boolean }
  | { kind: "arrows"; ids: string[] }
  | { kind: "confirm"; message: string; okLabel: string; resolve: (yes: boolean) => void };

export function App() {
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
  const [snap, setSnap] = useState(() => readSetting("snap", "off", ["on", "off"]) === "on");
  const [, setTick] = useState(0); // re-render after board changes (undo state, modified)
  const systemDark = useSystemDark();
  const dark = themeChoice === "dark" || (themeChoice === "system" && systemDark);
  const theme = dark ? DARK : LIGHT;
  const store = shown?.store ?? null;
  const shownRef = useRef(shown);
  useEffect(() => {
    shownRef.current = shown;
  }, [shown]);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  const modified = store?.modified ?? false;
  useEffect(() => {
    document.title = shown ? `${modified ? "● " : ""}${shown.name} · Heddle` : "Heddle";
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

  // Leaving with unsaved changes: the browser asks (its own wording).
  useEffect(() => {
    const before = (e: BeforeUnloadEvent) => {
      if (shownRef.current?.store.modified) e.preventDefault();
    };
    window.addEventListener("beforeunload", before);
    return () => window.removeEventListener("beforeunload", before);
  }, []);

  // Toolbar menus close on a click anywhere else.
  useEffect(() => {
    const down = (e: PointerEvent) => {
      for (const d of document.querySelectorAll<HTMLDetailsElement>("details.menu[open]")) {
        if (!d.contains(e.target as Node)) d.open = false;
      }
    };
    document.addEventListener("pointerdown", down);
    return () => document.removeEventListener("pointerdown", down);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(t);
  }, [notice]);

  const confirm = useCallback((message: string, okLabel = "Delete") =>
    new Promise<boolean>((resolve) => setModal({ kind: "confirm", message, okLabel, resolve })), []);

  /** Before replacing the board: ask if it has unsaved changes. */
  const mayDiscard = useCallback(async () => {
    const s = shownRef.current;
    if (!s?.store.modified) return true;
    return confirm(`“${s.name}” has changes that aren't saved.\n\nDiscard them?`, "Discard changes");
  }, [confirm]);

  const show = useCallback((opened: OpenedBoard) => {
    const notes = [...opened.board.load_notes];
    if (fromNewerVersion(opened.board)) {
      notes.unshift("This board was saved by a newer version of Heddle: saving it here may lose what this version doesn't know about.");
    }
    setError("");
    setShown({ store: new BoardStore(opened.board, measurer), name: opened.name, handle: opened.handle, notes });
  }, [measurer]);

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

  const openFile = useCallback(async (file: File) => {
    if (!(await mayDiscard())) return;
    try {
      show(await readBoardFile(file));
      setDemoInUrl(null);
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't open “${file.name}”: ${String(e)}`);
    }
  }, [mayDiscard, show]);

  const open = useCallback(async () => {
    if (!(await mayDiscard())) return;
    try {
      const opened = await pickBoard();
      if (opened) {
        show(opened);
        setDemoInUrl(null);
      }
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't open the board: ${String(e)}`);
    }
  }, [mayDiscard, show]);

  const newBoard = useCallback(async () => {
    if (!(await mayDiscard())) return;
    show({ board: makeBoard(), name: "Untitled", handle: null });
    setDemoInUrl(null);
  }, [mayDiscard, show]);

  const save = useCallback(async (as = false) => {
    const s = shownRef.current;
    if (!s) return;
    try {
      const text = s.store.toJson();
      const saved = !as && s.handle ? await saveToHandle(s.handle, text) : await saveAs(text, s.name);
      if (!saved) return;
      s.store.markSaved();
      setShown({ ...s, name: saved.name, handle: saved.handle });
      setDemoInUrl(null);
      setNotice(saved.downloaded
        ? `Downloaded “${saved.name}.json”. This browser can't save in place: each save downloads a new copy.`
        : `Saved “${saved.name}”.`);
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't save: ${String(e)}`);
    }
  }, []);

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

  // App-wide keys (the canvas handles its own while it has focus).
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (modal) return; // a dialog is open: it has the keyboard
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.code === "KeyS") {
        e.preventDefault();
        void save(e.shiftKey);
      } else if (ctrl && !e.shiftKey && e.code === "KeyO") {
        e.preventDefault();
        void open();
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
      } else if (ctrl && e.key === "1") {
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
  }, [canvas, modal, save, open, undo, redo, toggleAllDetails, toggleAllCollapsed]);

  const host = useMemo<CanvasHost>(() => ({
    editCard: (id, isNew) => setModal({ kind: "card", id, isNew }),
    editArrows: (ids) => setModal({ kind: "arrows", ids }),
    confirm: (message) => confirm(message),
    notice: (text) => setNotice(text),
    snapToGrid: () => snap,
  }), [confirm, snap]);

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

  return (
    <div className="app">
      <header className="toolbar">
        <span className="brand">
          <img src={`${import.meta.env.BASE_URL}icon.svg`} alt="" width={20} height={20} />
          Heddle
        </span>
        <button type="button" onClick={() => void newBoard()} title="Start an empty board">New</button>
        <button type="button" onClick={() => void open()} title="Open a board file (.json) from your computer (Ctrl+O)">Open…</button>
        {store && (
          <>
            <button type="button" onClick={() => void save()}
                    title={canSaveInPlace() ? "Save (Ctrl+S)" : "Save: downloads the board as a .json file (Ctrl+S)"}>Save</button>
            <button type="button" onClick={() => void save(true)} title="Save to a new file (Ctrl+Shift+S)">Save as…</button>
            <span className="sep" />
            <button type="button" className="icon" onClick={undo} disabled={!store.history.canUndo()} title="Undo (Ctrl+Z)" aria-label="Undo">↶</button>
            <button type="button" className="icon" onClick={redo} disabled={!store.history.canRedo()} title="Redo (Ctrl+Y)" aria-label="Redo">↷</button>
            <button type="button" onClick={addCard} title="Add a card (N, or double-click the canvas)">Add card</button>
          </>
        )}
        <details className="menu">
          <summary>Demo boards</summary>
          <div className="menu-items">
            {DEMOS.map((d) => (
              <button type="button" key={d.id} onClick={(e) => {
                (e.currentTarget.closest("details") as HTMLDetailsElement).open = false;
                void openDemo(d);
              }}>
                <strong>{d.name}</strong>
                <span>{d.blurb}</span>
              </button>
            ))}
          </div>
        </details>
        {shown && <span className="board-name" title={shown.name}>{modified ? "● " : ""}{shown.name}</span>}
        <span className="spacer" />
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
                    writeSetting("snap", e.target.checked ? "on" : "off");
                  }} /> Snap cards to the grid
                </label>
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
      </header>

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

      <main className="main">
        <BoardView store={store} theme={theme} measurer={measurer} host={host} minimapOpen={minimapOpen}
                   onToggleMinimap={toggleMinimap} onReady={setCanvas} />
        {!store && (
          <section className="welcome">
            <h1>Heddle</h1>
            <p>Map branching and converging story paths: cards on a canvas, joined by arrows.</p>
            <p className="muted">
              Boards stay on your computer: nothing is uploaded. The browser version is still being built:
              cards, arrows and saving work; groups, story tools and the side panels are on their way.
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
        {dragging && <div className="drop-hint">Drop a board file to open it</div>}
      </main>

      {store && modal?.kind === "card" && store.card(modal.id) && (
        <CardEditor key={modal.id} store={store} id={modal.id} isNew={modal.isNew} onClose={closeModal} />
      )}
      {store && modal?.kind === "arrows" && <ArrowEditor store={store} ids={modal.ids} onClose={closeModal} />}
      {modal?.kind === "confirm" && (
        <Confirm message={modal.message} okLabel={modal.okLabel} onAnswer={(yes) => {
          modal.resolve(yes);
          closeModal();
        }} />
      )}
    </div>
  );
}
