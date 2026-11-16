import { useEffect, useRef } from "react";
import type { BoardViewer } from "../board/viewer.ts";
import type { TextMeasurer } from "../board/text.ts";
import { BoardCanvas } from "../canvas/controller.ts";
import { Minimap } from "../canvas/minimap.ts";
import type { Theme } from "../canvas/theme.ts";

interface Props {
  viewer: BoardViewer | null;
  theme: Theme;
  measurer: TextMeasurer;
  minimapOpen: boolean;
  onToggleMinimap: () => void;
  /** Receives the canvas controller once it exists (for the toolbar's zoom buttons). */
  onReady: (canvas: BoardCanvas | null) => void;
}

/** The board canvas with its tooltip and minimap. */
export function BoardView({ viewer, theme, measurer, minimapOpen, onToggleMinimap, onReady }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<HTMLCanvasElement>(null);
  const boardRef = useRef<BoardCanvas | null>(null);

  useEffect(() => {
    const board = new BoardCanvas(canvasRef.current!, measurer, tooltipRef.current!);
    boardRef.current = board;
    onReady(board);
    return () => {
      board.destroy();
      boardRef.current = null;
      onReady(null);
    };
  }, [measurer, onReady]);

  useEffect(() => boardRef.current?.setViewer(viewer), [viewer]);
  useEffect(() => boardRef.current?.setTheme(theme), [theme]);

  const hasViewer = viewer !== null;
  useEffect(() => {
    if (!minimapOpen || !hasViewer || !mapRef.current || !boardRef.current) return;
    const map = new Minimap(mapRef.current, boardRef.current);
    return () => map.destroy();
  }, [minimapOpen, measurer, hasViewer]);

  return (
    <div className="board">
      <canvas ref={canvasRef} className="board-canvas" aria-label="Board" tabIndex={0} />
      <div ref={tooltipRef} className="tooltip" role="tooltip" hidden />
      {viewer && (minimapOpen ? (
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
