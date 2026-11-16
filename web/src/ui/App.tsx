import { useCallback, useEffect, useMemo, useState } from "react";
import { fromNewerVersion } from "../core/model.ts";
import { BoardViewer } from "../board/viewer.ts";
import type { BoardCanvas } from "../canvas/controller.ts";
import { canvasMeasurer } from "../canvas/measure.ts";
import { DARK, LIGHT } from "../canvas/theme.ts";
import { BoardFileError, parseBoard, pickBoardFile, readBoardFile, type OpenedBoard } from "../platform/files.ts";
import { readSetting, writeSetting } from "../platform/settings.ts";
import { BoardView } from "./BoardView.tsx";
import { DEMOS, demoById, type Demo } from "./demos.ts";

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
  viewer: BoardViewer;
  name: string;
  notes: string[];
}

export function App() {
  const measurer = useMemo(() => canvasMeasurer(), []);
  const [shown, setShown] = useState<Shown | null>(null);
  const [error, setError] = useState("");
  const [canvas, setCanvas] = useState<BoardCanvas | null>(null);
  const [zoom, setZoom] = useState(1);
  const [dragging, setDragging] = useState(false);
  const [themeChoice, setThemeChoice] = useState<ThemeChoice>(() => readSetting("theme", "system", THEMES));
  const [minimapOpen, setMinimapOpen] = useState(() => readSetting("minimap", "open", ["open", "closed"]) === "open");
  const [, setTick] = useState(0); // re-render after board changes (fold all, details)
  const systemDark = useSystemDark();
  const dark = themeChoice === "dark" || (themeChoice === "system" && systemDark);
  const theme = dark ? DARK : LIGHT;

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  useEffect(() => {
    document.title = shown ? `${shown.name} · Heddle` : "Heddle";
  }, [shown]);

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

  const show = useCallback((opened: OpenedBoard) => {
    const notes = [...opened.board.load_notes];
    if (fromNewerVersion(opened.board)) {
      notes.unshift("This board was saved by a newer version of Heddle: some of it may not show here.");
    }
    setError("");
    setShown({ viewer: new BoardViewer(opened.board, measurer), name: opened.name, notes });
  }, [measurer]);

  const showDemo = useCallback((demo: Demo, text: string) => {
    try {
      show({ ...parseBoard(text, `${demo.id}.json`), name: demo.name });
      const url = new URL(window.location.href);
      url.searchParams.set("demo", demo.id);
      history.replaceState(null, "", url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [show]);

  const openDemo = useCallback(
    (demo: Demo) => demo.load().then((text) => showDemo(demo, text), (e) => setError(String(e))),
    [showDemo],
  );

  const openFile = useCallback(async (file: File) => {
    try {
      show(await readBoardFile(file));
      const url = new URL(window.location.href);
      url.searchParams.delete("demo");
      history.replaceState(null, "", url);
    } catch (e) {
      setError(e instanceof BoardFileError ? e.message : `Couldn't open “${file.name}”: ${String(e)}`);
    }
  }, [show]);

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

  const viewer = shown?.viewer ?? null;
  const allDetails = viewer ? viewer.details.size > 0 : false;
  const toggleAllDetails = useCallback(() => {
    if (!viewer) return;
    viewer.setAllDetails(viewer.details.size === 0);
    canvas?.boardChanged();
    setTick((n) => n + 1);
  }, [viewer, canvas]);
  const toggleAllCollapsed = useCallback(() => {
    if (!viewer) return;
    viewer.setAllCollapsed(!viewer.anyCollapsed);
    canvas?.boardChanged();
    setTick((n) => n + 1);
  }, [viewer, canvas]);

  // Keys: Ctrl+0 actual size, Shift+D every card's details, Shift+C every group.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      if ((e.ctrlKey || e.metaKey) && e.key === "0") {
        e.preventDefault();
        canvas?.resetZoom();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "1") {
        e.preventDefault(); // (most browsers keep Ctrl+1 for switching tabs)
        canvas?.fit();
      } else if (!e.ctrlKey && !e.metaKey && !e.altKey && e.shiftKey && e.code === "KeyD") {
        toggleAllDetails();
      } else if (!e.ctrlKey && !e.metaKey && !e.altKey && e.shiftKey && e.code === "KeyC") {
        toggleAllCollapsed();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [canvas, toggleAllDetails, toggleAllCollapsed]);

  const open = async () => {
    const file = await pickBoardFile();
    if (file) void openFile(file);
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

  const hasGroups = viewer?.board.cards.some((c) => c.kind === "group") ?? false;

  return (
    <div className="app">
      <header className="toolbar">
        <span className="brand">
          <img src={`${import.meta.env.BASE_URL}icon.svg`} alt="" width={20} height={20} />
          Heddle
        </span>
        <button type="button" onClick={open} title="Open a board file (.json) from your computer">Open…</button>
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
        {shown && <span className="board-name" title={shown.name}>{shown.name}</span>}
        <span className="spacer" />
        {viewer && (
          <>
            <button type="button" onClick={toggleAllDetails} title="Show or hide every card's details (Shift+D)">
              {allDetails ? "Hide details" : "Show details"}
            </button>
            {hasGroups && (
              <button type="button" onClick={toggleAllCollapsed} title="Collapse or expand every group (Shift+C)">
                {viewer.anyCollapsed ? "Expand groups" : "Collapse groups"}
              </button>
            )}
            <button type="button" onClick={() => canvas?.zoomBy(1 / 1.15)} title="Zoom out (Ctrl+scroll)" aria-label="Zoom out">−</button>
            <button type="button" className="zoom" onClick={() => canvas?.resetZoom()} title="Actual size (Ctrl+0)">
              {Math.round(zoom * 100)}%
            </button>
            <button type="button" onClick={() => canvas?.zoomBy(1.15)} title="Zoom in (Ctrl+scroll)" aria-label="Zoom in">+</button>
            <button type="button" onClick={() => canvas?.fit()} title="Fit the whole board on screen">Fit</button>
          </>
        )}
        <button type="button" onClick={cycleTheme} title="Light, dark, or follow your system">{THEME_LABELS[themeChoice]}</button>
      </header>

      {(error || (shown && shown.notes.length > 0)) && (
        <div className={error ? "notice error" : "notice"} role={error ? "alert" : "status"}>
          <span>{error || `Opened with repairs: ${shown!.notes.join("; ")}.`}</span>
          <button type="button" onClick={() => (error ? setError("") : setShown({ ...shown!, notes: [] }))} aria-label="Dismiss">×</button>
        </div>
      )}

      <main className="main">
        <BoardView viewer={viewer} theme={theme} measurer={measurer} minimapOpen={minimapOpen}
                   onToggleMinimap={toggleMinimap} onReady={setCanvas} />
        {!viewer && (
          <section className="welcome">
            <h1>Heddle</h1>
            <p>Map branching and converging story paths: cards on a canvas, joined by arrows.</p>
            <p className="muted">
              This browser version can show boards so far; editing is on its way. Boards stay on your computer:
              nothing is uploaded.
            </p>
            <div className="welcome-actions">
              <button type="button" className="primary" onClick={open}>Open a board…</button>
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
    </div>
  );
}
