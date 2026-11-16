import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { MenuItem } from "../canvas/menus.ts";

interface Props {
  items: MenuItem[];
  x: number;
  y: number;
  onClose: () => void;
}

/** A right-click menu at a point on the page: arrow keys move, Enter picks, Esc or a click
 *  elsewhere closes it. Submenus open beside their item. */
export function ContextMenu({ items, x, y, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Keep it on screen.
  useLayoutEffect(() => {
    const r = ref.current!.getBoundingClientRect();
    setPos({ left: Math.max(4, Math.min(x, window.innerWidth - r.width - 4)), top: Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) });
    ref.current!.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [x, y]);

  useEffect(() => {
    const down = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("keydown", key);
    window.addEventListener("blur", onClose);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("keydown", key);
      window.removeEventListener("blur", onClose);
    };
  }, [onClose]);

  return (
    <div ref={ref} className="context-menu" role="menu" style={pos} onContextMenu={(e) => e.preventDefault()}>
      <Items items={items} onClose={onClose} />
    </div>
  );
}

function Items({ items, onClose }: { items: MenuItem[]; onClose: () => void }) {
  const [open, setOpen] = useState<number | null>(null);
  const move = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>(":scope > .menu-entry > button:not(:disabled)")];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "ArrowDown" ? (at + 1) % buttons.length : (at - 1 + buttons.length) % buttons.length;
    buttons[next]?.focus();
  };
  return (
    <div className="menu-list" onKeyDown={move}>
      {items.map((item, i) => item.label === "-" ? <hr key={i} /> : (
        <div key={i} className="menu-entry" onMouseEnter={() => setOpen(item.submenu ? i : null)}>
          <button type="button" role={item.checked !== undefined ? "menuitemcheckbox" : "menuitem"}
                  aria-checked={item.checked} disabled={item.disabled} aria-haspopup={item.submenu ? "menu" : undefined}
                  onClick={() => {
                    if (item.submenu) {
                      setOpen(open === i ? null : i);
                      return;
                    }
                    onClose();
                    item.action?.();
                  }}
                  onKeyDown={(e) => {
                    if (item.submenu && e.key === "ArrowRight") {
                      e.preventDefault();
                      setOpen(i);
                    }
                  }}>
            <span className="check-mark">{item.checked ? "✓" : ""}</span>
            {item.swatch && <span className={item.swatch === "theme" ? "dot theme" : "dot"} style={item.swatch === "theme" ? undefined : { background: item.swatch }} />}
            <span className="menu-label">{item.label}</span>
            {item.keys && <kbd>{item.keys}</kbd>}
            {item.submenu && <span className="arrow">▸</span>}
          </button>
          {item.submenu && open === i && (
            <div className="context-menu submenu" role="menu">
              <Items items={item.submenu} onClose={onClose} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
