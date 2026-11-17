import { useEffect, useRef } from "react";
import type { BoardStore } from "../board/store.ts";
import type { TextMeasurer } from "../board/text.ts";
import { BoardCanvas, type CanvasHost } from "../canvas/controller.ts";
import { Minimap } from "../canvas/minimap.ts";
import type { Theme } from "../canvas/theme.ts";

interface Props {
  store: BoardStore | null;
  theme: Theme;
  measurer: TextMeasurer;
  host: CanvasHost;
  minimapOpen: boolean;
  onToggleMinimap: () => void;
  /** Receives the canvas controller once it exists (for the toolbar's zoom buttons). */
  onReady: (canvas: BoardCanvas | null) => void;
}

/** The board canvas with its tooltip and minimap. */
export function BoardView({ store, theme, measurer, host, minimapOpen, onToggleMinimap, onReady }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<HTMLCanvasElement>(null);
  const boardRef = useRef<BoardCanvas | null>(null);
  // The controller is made once; it calls whatever host callbacks are current.
  const hostRef = useRef(host);
  useEffect(() => {
    hostRef.current = host;
  }, [host]);

  useEffect(() => {
    const proxy: CanvasHost = {
      editCard: (id, isNew) => hostRef.current.editCard(id, isNew),
      editArrows: (ids) => hostRef.current.editArrows(ids),
      editSeveral: () => hostRef.current.editSeveral(),
      confirm: (message) => hostRef.current.confirm(message),
      notice: (text) => hostRef.current.notice(text),
      snapToGrid: () => hostRef.current.snapToGrid(),
      contextMenu: (items, x, y) => hostRef.current.contextMenu(items, x, y),
      read: (id) => hostRef.current.read(id),
      chooseThread: () => hostRef.current.chooseThread(),
      wheelZooms: () => hostRef.current.wheelZooms(),
      keys: () => hostRef.current.keys(),
    };
    const board = new BoardCanvas(canvasRef.current!, measurer, tooltipRef.current!, proxy);
    boardRef.current = board;
    onReady(board);
    return () => {
      board.destroy();
      boardRef.current = null;
      onReady(null);
    };
  }, [measurer, onReady]);

  useEffect(() => boardRef.current?.setStore(store), [store]);
  useEffect(() => boardRef.current?.setTheme(theme), [theme]);

  const hasStore = store !== null;
  useEffect(() => {
    if (!minimapOpen || !hasStore || !mapRef.current || !boardRef.current) return;
    const map = new Minimap(mapRef.current, boardRef.current);
    return () => map.destroy();
  }, [minimapOpen, measurer, hasStore]);

  return (
    <div className="board">
      <canvas ref={canvasRef} className="board-canvas" aria-label="Board" tabIndex={0} />
      <div ref={tooltipRef} className="tooltip" role="tooltip" hidden />
      {store && (minimapOpen ? (
        <div className="minimap">
          <canvas ref={mapRef} aria-label="Minimap: click to jump, drag to pan, double-click to fit" />
          <button type="button" className="minimap-hide" title="Hide the minimap" onClick={onToggleMinimap}>−</button>
        </div>
      ) : (
        <button type="button" className="minimap-show" title="Show the minimap" onClick={onToggleMinimap}>▣</button>
      ))}
    </div>
  );
}
