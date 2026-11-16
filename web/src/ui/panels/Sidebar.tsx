import { useRef, type ReactNode } from "react";

export type Side = "left" | "right";

export interface PanelDef {
  id: string;
  title: string;
  render: () => ReactNode;
}

interface Props {
  side: Side;
  panels: PanelDef[];
  active: string | null;
  width: number;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
  onMove: (id: string) => void;
  onResize: (width: number) => void;
}

export const MIN_WIDTH = 220;
export const MAX_WIDTH = 560;

/** One side of the board: a tab per open panel (heddle's side docks, fixed to a side). The
 *  edge facing the board drags to resize. */
export function Sidebar({ side, panels, active, width, onActivate, onClose, onMove, onResize }: Props) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  if (!panels.length) return null;
  const current = panels.find((p) => p.id === active) ?? panels[0]!;
  return (
    <aside className={`sidebar ${side}`} style={{ width }} aria-label={`${side === "left" ? "Left" : "Right"} panels`}>
      <div className="sidebar-tabs" role="tablist">
        {panels.map((p) => (
          <button key={p.id} type="button" role="tab" aria-selected={p.id === current.id}
                  className={p.id === current.id ? "tab active" : "tab"} onClick={() => onActivate(p.id)}>{p.title}</button>
        ))}
        <span className="spacer" />
        <button type="button" className="icon" title={`Move ${current.title} to the ${side === "left" ? "right" : "left"}`}
                aria-label={`Move ${current.title} to the other side`} onClick={() => onMove(current.id)}>{side === "left" ? "⇥" : "⇤"}</button>
        <button type="button" className="icon" title={`Close ${current.title}`} aria-label={`Close ${current.title}`}
                onClick={() => onClose(current.id)}>×</button>
      </div>
      <div className="sidebar-body" role="tabpanel" aria-label={current.title}>{current.render()}</div>
      <div className="sidebar-resize" role="separator" aria-orientation="vertical" title="Drag to resize"
           onPointerDown={(e) => {
             (e.target as HTMLElement).setPointerCapture(e.pointerId);
             drag.current = { x: e.clientX, width };
           }}
           onPointerMove={(e) => {
             if (!drag.current) return;
             const dx = e.clientX - drag.current.x;
             onResize(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, drag.current.width + (side === "left" ? dx : -dx))));
           }}
           onPointerUp={() => (drag.current = null)} />
    </aside>
  );
}
