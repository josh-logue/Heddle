// The editable board: what heddle/scene.py and scene_history.py keep, without drawing.
//
// The board is an immutable BoardState. Cards and arrows are never changed in place: an
// edit replaces the objects it touches, so undo snapshots share everything else (the
// desktop's snapshots share unchanged cards the same way). A gesture such as a drag
// previews new states and records one undo step when it ends.
//
// Beside the saved board the store keeps what's only on screen: the selection, which
// cards show their details, and the make-room pushes for open details.

import { StoryGraph } from "../core/graph.ts";
import { History, deepEqual } from "../core/history.ts";
import { V_GAP } from "../core/layout.ts";
import {
  CARD_COLORS, KIND_GROUP, boardToJson, makeBoard, makeCard, newId,
  type BoardData, type CardData, type ConnectionData, type Display, type RouteData, type SavedValues,
  type StrandInfo,
} from "../core/model.ts";
import { CARD_WIDTH, Layouter, Structure, type CardBox, type Rect } from "./metrics.ts";
import { routeArrows, type ArrowShape } from "./routing.ts";
import type { TextMeasurer } from "./text.ts";

export const GRID = 25;
export const PUSH_GAP = V_GAP;
export const NUDGE_STEP = 10;
export const NUDGE_FINE = 1;

export interface BoardState {
  readonly cards: readonly CardData[];
  readonly connections: readonly ConnectionData[];
  readonly custom_colors: readonly string[];
  readonly saved_values: SavedValues;
  readonly display: Display;
  readonly routes: readonly RouteData[];
  readonly strands: readonly StrandInfo[];
}

const sameList = <T>(a: readonly T[], b: readonly T[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** Equal boards: the same card and arrow objects, and equal everything else. */
export function sameState(a: BoardState, b: BoardState): boolean {
  return sameList(a.cards, b.cards) && sameList(a.connections, b.connections)
    && deepEqual(a.custom_colors, b.custom_colors) && deepEqual(a.saved_values, b.saved_values)
    && deepEqual(a.display, b.display) && deepEqual(a.routes, b.routes) && deepEqual(a.strands, b.strands);
}

export function stateFromBoard(b: BoardData): BoardState {
  return {
    cards: b.cards, connections: b.connections, custom_colors: b.custom_colors, saved_values: b.saved_values,
    display: b.display, routes: b.routes, strands: b.strands,
  };
}

export function boardFromState(s: BoardState): BoardData {
  return makeBoard({
    cards: [...s.cards], connections: [...s.connections], custom_colors: [...s.custom_colors],
    saved_values: s.saved_values, display: s.display, routes: [...s.routes], strands: [...s.strands],
  });
}

/** Qt's QRectF.intersects: rectangles that only touch don't count. */
const intersects = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const rectOf = (b: CardBox): Rect => ({ x: b.x, y: b.y, w: b.w, h: b.h });
export const snapped = (v: number) => Math.round(v / GRID) * GRID;
/** The next grid line beyond `value` in `direction` (+, −, or 0 for none). */
export function nextLine(value: number, direction: number): number {
  if (direction > 0) return (Math.floor(value / GRID + 1e-9) + 1) * GRID;
  if (direction < 0) return (Math.ceil(value / GRID - 1e-9) - 1) * GRID;
  return value;
}

type Move = [id: string, dx: number, dy: number];
type Listener = () => void;

export class BoardStore {
  state: BoardState;
  readonly history: History<BoardState>;
  structure!: Structure;
  boxes!: Map<string, CardBox>;
  arrows!: ArrowShape[];
  /** Selected cards and groups, and selected arrows (by id). */
  selected = new Set<string>();
  selectedArrows = new Set<string>();
  readonly details = new Set<string>();
  /** Bumped on every change, so the canvas and panels know to redraw. */
  version = 0;
  /** True while cards are being dragged: arrows skip the slow "avoid cards" search. */
  moving = false;

  private readonly shift = new Map<string, [number, number]>();
  private readonly loans = new Map<string, Move[]>();
  private readonly introductions = new Map<string, string[]>();
  private layouter!: Layouter;
  private layoutKey: unknown[] = [];
  private graph: StoryGraph | null = null;
  private readonly listeners = new Set<Listener>();

  constructor(board: BoardData, private readonly m: TextMeasurer) {
    this.state = stateFromBoard(board);
    this.history = new History<BoardState>(undefined, sameState);
    this.refresh();
    this.state = this.withAnchors(this.state); // groups fitted round their cards, as on loading
    this.refresh();
    this.history.reset(this.state);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private notify(): void {
    this.version++;
    for (const fn of this.listeners) fn();
  }

  get modified(): boolean {
    return !this.history.atSaved();
  }

  get board(): BoardData {
    return boardFromState(this.state);
  }

  toJson(): string {
    return boardToJson(this.board);
  }

  markSaved(): void {
    this.history.markSaved();
    this.notify();
  }

  card(id: string): CardData | undefined {
    return this.structure.byId.get(id);
  }

  storyGraph(): StoryGraph {
    this.graph ??= new StoryGraph(this.state.cards, this.state.connections);
    return this.graph;
  }

  // ----- deriving the layout -------------------------------------------------------

  /** Work out the structure, layout and arrows for the current state. */
  private refresh(): void {
    const s = this.state;
    this.structure = new Structure(s.cards);
    this.graph = null;
    this.introductions.clear();
    if (s.display.story_tools) for (const [k, v] of this.storyGraph().introductions()) this.introductions.set(k, v);
    const key = [s.display, s.strands];
    if (!this.layouter || !sameList(key, this.layoutKey)) {
      this.layouter = new Layouter({
        cards: s.cards, display: s.display, introductions: this.introductions, details: this.details,
        strands: s.strands, shift: this.shift,
      }, this.m, this.structure);
      this.layoutKey = key;
    }
    this.layouter.structure = this.structure;
    this.boxes = this.layouter.all(s.cards);
    for (const id of this.selected) if (!this.boxes.get(id)?.visible) this.selected.delete(id);
    const ids = new Set(s.connections.map((c) => c.id));
    for (const id of this.selectedArrows) if (!ids.has(id)) this.selectedArrows.delete(id);
    this.reroute();
  }

  private reroute(): void {
    const display = this.moving && this.state.display.arrow_routing === "avoid"
      ? { ...this.state.display, arrow_routing: "curved" as const } : this.state.display;
    this.arrows = routeArrows(this.state.connections, this.boxes, this.structure, display, this.m);
  }

  /** Groups fitted round their cards keep their saved corner with them (the desktop
   *  writes it back on every refit), so an emptied group stays where it was. */
  private withAnchors(s: BoardState): BoardState {
    let changed = false;
    const cards = s.cards.map((c) => {
      const b = this.boxes.get(c.id);
      if (!b?.isGroup || (b.anchorX === c.x && b.anchorY === c.y)) return c;
      changed = true;
      return { ...c, x: b.anchorX, y: b.anchorY };
    });
    return changed ? { ...s, cards } : s;
  }

  // ----- changing the board ----------------------------------------------------------

  /** Show a new state without recording it (during a gesture). */
  preview(next: BoardState): void {
    this.state = next;
    this.refresh();
    this.notify();
  }

  /** Make `next` the board and record an undo step (none if nothing changed). */
  commit(next: BoardState = this.state): boolean {
    this.state = next;
    this.refresh();
    const anchored = this.withAnchors(this.state);
    if (anchored !== this.state) {
      this.state = anchored;
      this.refresh();
    }
    const recorded = this.history.commit(this.state);
    this.notify();
    return recorded;
  }

  undo(): boolean {
    const s = this.history.undo();
    if (!s) return false;
    this.restore(s);
    return true;
  }

  redo(): boolean {
    const s = this.history.redo();
    if (!s) return false;
    this.restore(s);
    return true;
  }

  private restore(s: BoardState): void {
    this.state = s;
    // Pushes made for open details don't survive moving back in time.
    this.shift.clear();
    this.loans.clear();
    this.refresh();
    this.notify();
  }

  private replaceCards(changes: ReadonlyMap<string, Partial<CardData>>, base = this.state): BoardState {
    return { ...base, cards: base.cards.map((c) => (changes.has(c.id) ? { ...c, ...changes.get(c.id)! } : c)) };
  }

  // ----- selection -------------------------------------------------------------------

  select(cards: Iterable<string>, arrows: Iterable<string> = [], add = false): void {
    if (!add) {
      this.selected.clear();
      this.selectedArrows.clear();
    }
    for (const id of cards) if (this.boxes.get(id)?.visible) this.selected.add(id);
    for (const id of arrows) this.selectedArrows.add(id);
    this.notify();
  }

  toggleSelected(card?: string, arrow?: string): void {
    if (card) {
      if (this.selected.has(card)) this.selected.delete(card);
      else this.selected.add(card);
    }
    if (arrow) {
      if (this.selectedArrows.has(arrow)) this.selectedArrows.delete(arrow);
      else this.selectedArrows.add(arrow);
    }
    this.notify();
  }

  clearSelection(): void {
    if (!this.selected.size && !this.selectedArrows.size) return;
    this.selected.clear();
    this.selectedArrows.clear();
    this.notify();
  }

  selectAll(): void {
    this.select([...this.boxes.values()].filter((b) => b.visible).map((b) => b.card.id),
      this.arrows.map((a) => a.conn.id));
  }

  // ----- moving ----------------------------------------------------------------------

  /** The selected cards not inside another selected group (which carries them). */
  moveRoots(ids: Iterable<string> = this.selected): string[] {
    const chosen = new Set(ids);
    return [...chosen].filter((id) => ![...this.structure.ancestors(id)].some((a) => chosen.has(a)));
  }

  /** Everything that moves with a card: itself and, for a group, all its contents. */
  private carried(id: string): string[] {
    return this.boxes.get(id)?.isGroup ? [id, ...this.structure.descendants(id)] : [id];
  }

  /** `state` with the cards in `roots` (and what they carry) moved by (dx, dy). A card
   *  moved by hand keeps where it's drawn: a make-room push becomes its own position. */
  movedBy(roots: readonly string[], dx: number, dy: number, base = this.state): BoardState {
    const changes = new Map<string, Partial<CardData>>();
    for (const root of roots) {
      for (const id of this.carried(root)) {
        const c = base.cards.find((x) => x.id === id) ?? this.card(id);
        if (!c || changes.has(id)) continue;
        const [sx, sy] = this.shift.get(id) ?? [0, 0];
        this.shift.delete(id);
        changes.set(id, { x: c.x + sx + dx, y: c.y + sy + dy });
      }
    }
    return this.replaceCards(changes, base);
  }

  /** Move the selection by arrow keys (with snap: to the next grid line that way). */
  nudge(dx: number, dy: number, snap = false): boolean {
    const roots = this.moveRoots();
    if (!roots.length) return false;
    let next = this.state;
    for (const id of roots) {
      const b = this.boxes.get(id)!;
      const [mx, my] = snap ? [nextLine(b.x, dx) - b.x, nextLine(b.y, dy) - b.y] : [dx, dy];
      next = this.movedBy([id], mx, my, next);
    }
    return this.commit(next) || true;
  }

  /** The current board with each card's (or group frame's) top-left corner on the grid. */
  snappedState(roots: readonly string[]): BoardState {
    let next = this.state;
    for (const id of roots) {
      const b = this.boxes.get(id)!;
      next = this.movedBy([id], snapped(b.x) - b.x, snapped(b.y) - b.y, next);
    }
    return next;
  }

  // ----- adding, editing and removing --------------------------------------------------

  /** A new card centred on (x, y) (in `parent`, a group, if given), selected. It's
   *  recorded only when its editor keeps it (updateCard); discardNew drops it. */
  addCard(x: number, y: number, snap = false, color?: string, parent?: string): CardData {
    color ??= CARD_COLORS[this.state.cards.length % CARD_COLORS.length]!;
    let [cx, cy] = [x - CARD_WIDTH / 2, y - 20];
    if (snap) [cx, cy] = [snapped(cx), snapped(cy)];
    const card = makeCard({ x: cx, y: cy, color, parent: parent ?? "" });
    this.preview({ ...this.state, cards: [...this.state.cards, card] });
    this.select([card.id]);
    return card;
  }

  /** An arrow from `source` to a card just added (recorded along with it). */
  connectNew(source: string, target: string): void {
    const conn: ConnectionData = { source, target, label: "", style: "solid", color: "", id: newId() };
    this.preview({ ...this.state, connections: [...this.state.connections, conn] });
  }

  /** Move the selection without recording it yet: a burst of arrow-key nudges is
   *  recorded as one step (commit) when it settles. */
  nudgePreview(dx: number, dy: number, snap = false): void {
    let next = this.state;
    for (const id of this.moveRoots()) {
      const b = this.boxes.get(id)!;
      const [mx, my] = snap ? [nextLine(b.x, dx) - b.x, nextLine(b.y, dy) - b.y] : [dx, dy];
      next = this.movedBy([id], mx, my, next);
    }
    this.preview(next);
  }

  /** Replace a card with edited data (one undo step). */
  updateCard(id: string, data: Partial<CardData>): void {
    const old = this.card(id);
    if (!old) return;
    const next = makeCard({ ...old, ...data, id });
    if (deepEqual(next, old)) {
      this.commit(); // (a new card kept as it was still needs recording)
      return;
    }
    let state = this.replaceCards(new Map([[id, next]]));
    if (next.color !== old.color && !(CARD_COLORS as readonly string[]).includes(next.color)
        && !state.custom_colors.includes(next.color)) {
      state = { ...state, custom_colors: [...state.custom_colors, next.color] };
    }
    this.commit(state);
  }

  /** Throw away a card added but never kept (its editor was cancelled). */
  discardNew(id: string): void {
    this.state = this.history.current ?? this.state;
    this.refresh();
    this.selected.delete(id);
    this.notify();
  }

  /** Remove cards (a group's cards move up to the nearest surviving group) and arrows,
   *  plus any arrow attached to a removed card. One undo step. */
  remove(cardIds: Iterable<string>, arrowIds: Iterable<string> = [], withContents = false): void {
    const doomed = new Set<string>();
    for (const id of cardIds) {
      if (!this.boxes.has(id)) continue;
      doomed.add(id);
      if (withContents) for (const d of this.structure.descendants(id)) doomed.add(d);
    }
    const deadArrows = new Set(arrowIds);
    const survivingParent = (id: string) => {
      let p = this.structure.parentOf.get(id);
      while (p !== undefined && doomed.has(p)) p = this.structure.parentOf.get(p);
      return p ?? "";
    };
    const cards = this.state.cards.filter((c) => !doomed.has(c.id)).map((c) => {
      const p = this.structure.parentOf.get(c.id);
      return p !== undefined && doomed.has(p) ? { ...c, parent: survivingParent(c.id) } : c;
    });
    const connections = this.state.connections.filter(
      (e) => !deadArrows.has(e.id) && !doomed.has(e.source) && !doomed.has(e.target));
    for (const id of doomed) {
      this.details.delete(id);
      this.selected.delete(id);
    }
    this.commit({ ...this.state, cards, connections });
  }

  removeSelection(): void {
    this.remove(this.selected, this.selectedArrows);
  }

  /** What deleting the selection would remove, in words, when it's more than one thing
   *  (the desktop asks first then); "" for one thing or nothing. */
  describeSelection(): string {
    const cards = [...this.selected];
    const total = cards.length + this.selectedArrows.size;
    if (total <= 1) return "";
    const groups = cards.filter((id) => this.boxes.get(id)?.isGroup).length;
    const parts: [number, string][] = [[cards.length - groups, "card"], [groups, "group"], [this.selectedArrows.size, "connection"]];
    const summary = parts.filter(([n]) => n).map(([n, noun]) => `${n} ${noun}${n !== 1 ? "s" : ""}`).join(", ");
    return `${total} items (${summary})`;
  }

  // ----- folding and details (not saved changes: details aren't saved at all) ----------

  setCollapsed(ids: readonly string[], collapsed: boolean): void {
    const groups = ids.map((id) => this.card(id)).filter((c): c is CardData => c?.kind === KIND_GROUP && c.collapsed !== collapsed);
    if (!groups.length) return;
    const before = new Map<string, Rect>();
    for (const g of groups) for (const id of [g.id, ...this.structure.ancestors(g.id)]) before.set(id, rectOf(this.boxes.get(id)!));
    this.state = this.replaceCards(new Map(groups.map((g) => [g.id, { collapsed }])));
    this.refresh();
    // Unfolding pushes neighbours aside, as on the desktop (a real move, saved).
    if (!collapsed) {
      const moves: Move[] = [];
      for (const g of groups) this.makeRoom(g.id, before, moves);
      this.state = this.movesToState(moves);
    }
    this.commit();
  }

  get anyCollapsed(): boolean {
    return this.state.cards.some((c) => c.kind === KIND_GROUP && c.collapsed);
  }

  /** Real moves made by making room for an unfolded group: written into the cards. */
  private movesToState(moves: readonly Move[]): BoardState {
    const total = new Map<string, [number, number]>();
    for (const [id, dx, dy] of moves) {
      for (const x of this.carried(id)) {
        const [tx, ty] = total.get(x) ?? [0, 0];
        total.set(x, [tx + dx, ty + dy]);
      }
    }
    const changes = new Map<string, Partial<CardData>>();
    for (const [id, [dx, dy]] of total) {
      const c = this.card(id)!;
      const [sx, sy] = this.shift.get(id) ?? [0, 0];
      this.shift.set(id, [sx - dx, sy - dy]); // the push is now in the position itself
      changes.set(id, { x: c.x + dx, y: c.y + dy });
    }
    const next = this.replaceCards(changes);
    for (const [id, [sx, sy]] of this.shift) if (!sx && !sy) this.shift.delete(id);
    return next;
  }

  setDetails(ids: readonly string[], visible: boolean): void {
    // Cards top to bottom (each pushes what's below before that opens), then groups
    // deepest first; hiding goes in reverse.
    const cards = ids.filter((id) => !this.boxes.get(id)?.isGroup).map((id) => this.boxes.get(id)!)
      .filter(Boolean).map((b, i) => ({ b, i })).sort((p, q) => p.b.y - q.b.y || p.b.x - q.b.x || p.i - q.i)
      .map(({ b }) => b.card.id);
    const groups = ids.filter((id) => this.boxes.get(id)?.isGroup).map((id, i) => ({ id, i }))
      .sort((p, q) => this.structure.depth.get(q.id)! - this.structure.depth.get(p.id)! || p.i - q.i).map(({ id }) => id);
    const order = [...cards, ...groups];
    for (const id of visible ? order : order.reverse()) this.showDetails(id, visible);
    this.reroute();
    this.notify();
  }

  toggleDetails(id: string): void {
    this.setDetails([id], !this.details.has(id));
  }

  private showDetails(id: string, visible: boolean): void {
    if (visible === this.details.has(id) || !this.boxes.has(id)) return;
    if (!visible) {
      this.details.delete(id);
      this.layouter.update(id, this.boxes);
      this.giveBack(id);
      return;
    }
    const before = new Map<string, Rect>();
    for (const g of [id, ...this.structure.ancestors(id)]) before.set(g, rectOf(this.boxes.get(g)!));
    this.details.add(id);
    this.layouter.update(id, this.boxes);
    const moves: Move[] = [];
    this.makeRoom(id, before, moves);
    if (moves.length) this.loans.set(id, moves);
  }

  private makeRoom(grown: string, before: ReadonlyMap<string, Rect>, moves: Move[]): void {
    for (let level: string | undefined = grown; level !== undefined; level = this.structure.parentOf.get(level)) {
      this.pushAside(level, before.get(level)!, moves);
      const parent = this.structure.parentOf.get(level);
      if (parent !== undefined) this.layouter.update(parent, this.boxes);
    }
  }

  private giveBack(id: string): void {
    const moves = this.loans.get(id) ?? [];
    this.loans.delete(id);
    const touched = new Set<string>();
    for (const [mid, dx, dy] of [...moves].reverse()) {
      if (!this.shift.has(mid)) continue; // moved by hand since: its place is its own now
      this.pushBy(mid, -dx, -dy);
      const parent = this.structure.parentOf.get(mid);
      if (parent !== undefined) touched.add(parent);
    }
    for (const g of touched) this.layouter.update(g, this.boxes);
  }

  /** Move a card (or group with its contents) on screen only, for open details. */
  private pushBy(id: string, dx: number, dy: number): void {
    for (const x of this.carried(id)) {
      const [sx, sy] = this.shift.get(x) ?? [0, 0];
      this.shift.set(x, [sx + dx, sy + dy]);
      const box = this.boxes.get(x);
      if (box) {
        box.x += dx;
        box.y += dy;
      }
    }
  }

  private pushAside(grown: string, old: Rect, moves: Move[]): void {
    const parent = this.structure.parentOf.get(grown);
    const siblings = this.state.cards.filter((c) => c.id !== grown && this.structure.parentOf.get(c.id) === parent).map((c) => c.id);
    const movers: [string, Rect, Rect][] = [[grown, old, rectOf(this.boxes.get(grown)!)]];
    const tol = 0.5;
    for (let round = 0; round < siblings.length * 4 + 4 && movers.length; round++) {
      const [mover, was, now] = movers.shift()!;
      for (const s of siblings) {
        const r = rectOf(this.boxes.get(s)!);
        if (s === mover || !intersects(r, now) || intersects(r, was)) continue;
        const right = r.x >= was.x + was.w - tol ? now.x + now.w + PUSH_GAP - r.x : null;
        const down = r.y >= was.y + was.h - tol ? now.y + now.h + PUSH_GAP - r.y : null;
        if (right === null && down === null) continue;
        const [dx, dy] = down === null || (right !== null && right <= down) ? [right!, 0] : [0, down];
        this.pushBy(s, dx, dy);
        moves.push([s, dx, dy]);
        movers.push([s, r, rectOf(this.boxes.get(s)!)]);
      }
    }
  }

  // ----- arrows ----------------------------------------------------------------------

  /** Connect two cards (none if they're the same, or already connected that way). */
  connect(source: string, target: string, like?: Partial<ConnectionData>): ConnectionData | null {
    if (source === target || !this.boxes.has(source) || !this.boxes.has(target)) return null;
    if (this.state.connections.some((e) => e.source === source && e.target === target)) return null;
    const conn: ConnectionData = {
      label: "", style: "solid", color: "", ...like, source, target, id: newId(),
    };
    this.commit({ ...this.state, connections: [...this.state.connections, conn] });
    return conn;
  }

  updateArrows(ids: Iterable<string>, data: Partial<Pick<ConnectionData, "label" | "style" | "color">>): void {
    const set = new Set(ids);
    this.commit({ ...this.state, connections: this.state.connections.map((e) => (set.has(e.id) ? { ...e, ...data } : e)) });
  }

  /** Reverse arrows; one already going the other way is left alone (it would repeat it). */
  reverseArrows(ids: Iterable<string>): void {
    const set = new Set(ids);
    const pairs = new Set(this.state.connections.map((e) => `${e.source}\u0000${e.target}`));
    const connections = this.state.connections.map((e) => {
      if (!set.has(e.id) || pairs.has(`${e.target}\u0000${e.source}`)) return e;
      return { ...e, source: e.target, target: e.source };
    });
    this.commit({ ...this.state, connections });
  }
}
