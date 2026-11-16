// The right-click menus for a card, group, arrow or the canvas (heddle/scene_menus.py),
// as data: the UI draws them. Items for later stages (highlight paths, reading, threads,
// auto-arrange, ungroup) join as those stages land.

import { ARROW_STYLES, CARD_COLORS, COLOR_NAMES } from "../core/model.ts";
import type { BoardStore } from "../board/store.ts";
import type { Hover } from "./draw.ts";

export interface MenuItem {
  label: string;
  /** The key that does the same, shown at the right. */
  keys?: string;
  action?: () => void;
  disabled?: boolean;
  checked?: boolean;
  /** A colour swatch shown before the label. */
  swatch?: string;
  submenu?: MenuItem[];
}

export const SEPARATOR: MenuItem = { label: "-" };

export interface MenuActions {
  editCard(id: string): void;
  editArrows(ids: string[]): void;
  addCardAt(x: number, y: number, group?: string): void;
  startConnect(source: string): void;
  copy(): void;
  cut(): void;
  pasteAt(x: number, y: number): void;
  canPaste(): boolean;
  deleteSelection(): void;
  notice(text: string): void;
}

const STYLE_LABELS: Record<string, string> = { solid: "Solid", dashed: "Dashed", dotted: "Dotted" };

/** The menu for what was right-clicked at scene point (x, y). */
export function buildMenu(store: BoardStore, hit: Hover, x: number, y: number, act: MenuActions): MenuItem[] {
  const box = hit.card ? store.boxes.get(hit.card) : undefined;
  if (box) {
    // Right-clicking a card that isn't selected acts on just that card.
    if (!store.selected.has(box.card.id)) store.select([box.card.id]);
    const id = box.card.id;
    const n = store.selected.size;
    const suffix = n > 1 ? ` ${n} cards` : "";
    const items: MenuItem[] = [
      { label: box.isGroup ? "Edit group…" : "Edit card…", keys: "Enter", action: () => act.editCard(id) },
    ];
    if (box.isGroup) {
      const groups = [...store.selected].filter((g) => store.boxes.get(g)?.isGroup);
      items.push({
        label: box.card.collapsed ? "Expand group" : "Collapse group", keys: "C",
        action: () => store.setCollapsed(groups, !box.card.collapsed),
      });
    }
    items.push(
      { label: box.detailsVisible ? "Hide details" : "Show details", keys: "D", action: () => store.toggleDetails(id) },
      { label: "Connect to…", keys: "L", action: () => act.startConnect(id) },
    );
    if (box.isGroup) items.push({ label: "Add card here", action: () => act.addCardAt(x, y, id) });
    items.push(
      SEPARATOR,
      { label: `Copy${suffix}`, keys: "Ctrl+C", action: act.copy },
      { label: `Cut${suffix}`, keys: "Ctrl+X", action: act.cut },
      { label: `Duplicate${suffix}`, keys: "Ctrl+D", action: () => store.duplicate() },
      { label: "Paste here", keys: "Ctrl+V", action: () => act.pasteAt(x, y), disabled: !act.canPaste() },
      SEPARATOR,
    );
    if (box.isGroup) {
      items.push(
        { label: "Delete group (keep cards)", action: () => store.remove([id]) },
        { label: "Delete group and its cards", keys: "Del", action: () => {
          store.select([id]);
          act.deleteSelection();
        } },
      );
    } else {
      items.push({ label: n > 1 ? `Delete${suffix}` : "Delete card", keys: "Del", action: act.deleteSelection });
    }
    return items;
  }
  if (hit.arrow) {
    // Right-clicking one of several selected arrows acts on all of them.
    if (!store.selectedArrows.has(hit.arrow)) store.select([], [hit.arrow]);
    const targets = [...store.selectedArrows];
    const conns = store.state.connections.filter((c) => targets.includes(c.id));
    const n = targets.length;
    const colors: [string, string][] = [["", "Default"], ...CARD_COLORS.map((c) => [c, COLOR_NAMES.get(c)!] as [string, string]),
      ...store.state.custom_colors.map((c) => [c, c] as [string, string])];
    return [
      { label: n === 1 ? "Edit arrow…" : `Edit ${n} arrows…`, keys: "Enter", action: () => act.editArrows(targets) },
      {
        label: "Line style", submenu: ARROW_STYLES.map((s) => ({
          label: STYLE_LABELS[s]!, checked: conns.every((c) => c.style === s), action: () => store.updateArrows(targets, { style: s }),
        })),
      },
      {
        label: "Color", submenu: [
          ...colors.map(([value, name]) => ({
            label: name, swatch: value || "theme", checked: conns.every((c) => c.color === value),
            action: () => store.updateArrows(targets, { color: value }),
          })),
          SEPARATOR,
          { label: "Custom…", action: () => act.editArrows(targets) },
        ],
      },
      SEPARATOR,
      {
        label: n === 1 ? "Reverse direction" : `Reverse ${n} arrows`, keys: "R", action: () => {
          const before = store.state.connections;
          store.reverseArrows(targets);
          if (store.state.connections === before || store.state.connections.every((c, i) => c === before[i])) {
            act.notice("There's already an arrow the other way: nothing to reverse.");
          }
        },
      },
      SEPARATOR,
      { label: n === 1 ? "Delete connection" : `Delete ${n} connections`, keys: "Del", action: act.deleteSelection },
    ];
  }
  return [
    { label: "Add card here", keys: "N", action: () => act.addCardAt(x, y) },
    SEPARATOR,
    { label: "Paste here", keys: "Ctrl+V", action: () => act.pasteAt(x, y), disabled: !act.canPaste() },
    { label: "Select all", keys: "Ctrl+A", action: () => store.selectAll() },
  ];
}
