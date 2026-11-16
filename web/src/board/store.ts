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
import { V_GAP, arrange, edgeKey, makeNode } from "../core/layout.ts";
import {
  CARD_COLORS, KIND_GROUP, applyBulkEdit, boardToJson, cleanDisplay, cloneFragment, copyCard, makeBoard, makeCard, newId,
  replaceText, type BulkEdit, type TextField,
  type BoardData, type CardData, type ConnectionData, type Display, type RouteData, type SavedValues,
  type StrandInfo,
} from "../core/model.ts";
import {
  CARD_WIDTH, GROUP_MIN_BODY, GROUP_MIN_WIDTH, GROUP_PAD, Layouter, Structure, type CardBox, type Rect,
} from "./metrics.ts";
import { labelTexts, routeArrows, type ArrowShape } from "./routing.ts";
import { lineHeight, type TextMeasurer } from "./text.ts";
import { matches as filterMatches, type Extras, type FilterCounts } from "../core/filters.ts";

export const GRID = 25;
export const PUSH_GAP = V_GAP;
export const NUDGE_STEP = 10;
export const NUDGE_FINE = 1;
/** Pasting or duplicating without a pointer position: this far from the originals. */
export const PASTE_OFFSET = 30;
/** Space left by group commands: cards stepped out beside a frame, grids of new members. */
export const ARRANGE_GAP = 30;
export const ARRANGE_COLUMNS = 3;

/** A group's arrange options (also on its right-click menu). */
export type ArrangeOptions = Partial<Pick<CardData, "arrange_by_color" | "arrange_vertical" | "arrange_grid" | "arrange_wrap">>;

/** Extra changes the card editor can make along with a card's fields, in one undo step. */
export interface CardEditExtras {
  /** For a group: exactly these cards become its direct members. */
  members?: readonly string[];
  /** For a group: auto-arrange it afterwards ("Save & auto-arrange"). */
  arrange?: boolean;
}

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
  /** The Filter panel's ticks: {category: casefolded keys}, and the "match all" categories. */
  filter: { selection: Map<string, Set<string>>; matchAll: Set<string> } = { selection: new Map(), matchAll: new Set() };
  /** Cards and groups the filter fades out, and how many it shows. */
  dimmed = new Set<string>();
  filterCounts: FilterCounts = { cards_shown: 0, cards_total: 0, groups_shown: 0, groups_total: 0 };
  /** Collapsed groups: how many search matches are folded away inside each. */
  searchHits = new Map<string, number>();
  /** A card outlined for a moment so the eye finds it (a search match, Go to Card). */
  flash: string | null = null;

  private readonly shift = new Map<string, [number, number]>();
  private readonly loans = new Map<string, Move[]>();
  private readonly introductions = new Map<string, string[]>();
  private layouter!: Layouter;
  private layoutKey: unknown[] = [];
  private graph: StoryGraph | null = null;
  /** During a drag: the frames of the groups around what's moving, held still (the
   *  desktop refits them only when the drag ends, so a card can be dragged out). */
  private frozen = new Map<string, CardBox>();
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
    for (const [id, box] of this.frozen) {
      const now = this.boxes.get(id);
      if (now) this.boxes.set(id, { ...box, visible: now.visible });
    }
    for (const id of this.selected) if (!this.boxes.get(id)?.visible) this.selected.delete(id);
    const ids = new Set(s.connections.map((c) => c.id));
    for (const id of this.selectedArrows) if (!ids.has(id)) this.selectedArrows.delete(id);
    this.applyFilter();
    this.reroute();
  }

  // ----- filter, search hits ----------------------------------------------------------

  get introductionMap(): ReadonlyMap<string, readonly string[]> {
    return this.introductions;
  }

  /** Values worked out from the arrows rather than typed on cards (for the filter). */
  filterExtras(): Extras {
    return new Map([["introduces", this.introductions]]);
  }

  get filterActive(): boolean {
    return [...this.filter.selection.values()].some((s) => s.size > 0);
  }

  setFilter(selection: Map<string, Set<string>>, matchAll: Set<string>): void {
    this.filter = { selection, matchAll };
    this.applyFilter();
    this.notify();
  }

  /** Fade cards and groups the filter doesn't match (each group judged on its own
   *  values), and count what's shown. */
  private applyFilter(): void {
    const active = this.filterActive;
    const extras = this.filterExtras();
    const counts = [0, 0, 0, 0];
    this.dimmed.clear();
    for (const c of this.state.cards) {
      const ok = !active || filterMatches(c, this.filter.selection, this.filter.matchAll, extras);
      if (!ok) this.dimmed.add(c.id);
      const base = c.kind === KIND_GROUP ? 2 : 0;
      counts[base]! += ok ? 1 : 0;
      counts[base + 1]!++;
    }
    this.filterCounts = { cards_shown: counts[0]!, cards_total: counts[1]!, groups_shown: counts[2]!, groups_total: counts[3]! };
  }

  /** Collapsed groups show how many search matches are hidden inside them. */
  setSearchHits(ids: Iterable<string>): void {
    this.searchHits.clear();
    for (const id of ids) {
      const shown = this.structure.visibleEnd(id);
      if (shown !== id) this.searchHits.set(shown, (this.searchHits.get(shown) ?? 0) + 1);
    }
    this.notify();
  }

  setFlash(id: string | null): void {
    if (this.flash === id) return;
    this.flash = id;
    this.notify();
  }

  /** Unfold every collapsed group hiding one of `ids` (one undo step). True if any did. */
  reveal(ids: Iterable<string>): boolean {
    const hidden = new Set<string>();
    for (const id of ids) for (const a of this.structure.ancestors(id)) if (this.card(a)?.collapsed) hidden.add(a);
    if (!hidden.size) return false;
    this.setCollapsed([...hidden], false);
    return true;
  }

  /** Where a card sits, for telling apart cards with the same title ("" at the top level). */
  titleContext(id: string): string {
    const parent = this.structure.parentOf.get(id);
    return parent === undefined ? "" : this.card(parent)?.title.trim() || "Untitled";
  }

  // ----- board-wide edits ------------------------------------------------------------------

  /** Change display options (Board Options: one undo step). */
  setDisplay(values: Partial<Display>): void {
    this.commit({ ...this.state, display: cleanDisplay({ ...this.state.display, ...values }) });
  }

  /** Edit several cards at once (model.applyBulkEdit): one undo step; how many changed. */
  bulkEdit(ids: Iterable<string>, edit: BulkEdit): number {
    const set = new Set(ids);
    const copies = this.state.cards.filter((c) => set.has(c.id)).map(copyCard);
    const changed = new Set(applyBulkEdit(copies, edit).map((c) => c.id));
    if (!changed.size) return 0;
    const byId = new Map(copies.map((c) => [c.id, makeCard({ ...c })]));
    let state: BoardState = { ...this.state, cards: this.state.cards.map((c) => (changed.has(c.id) ? byId.get(c.id)! : c)) };
    const color = edit.color;
    if (color && !(CARD_COLORS as readonly string[]).includes(color) && !state.custom_colors.includes(color)) {
      state = { ...state, custom_colors: [...state.custom_colors, color] };
    }
    this.commit(state);
    return changed.size;
  }

  /** Replace text in cards' titles, descriptions and notes (one undo step); how many
   *  cards changed. `ids`: only those cards. */
  replaceInCards(find: string, replacement: string, fields: readonly TextField[], matchCase: boolean,
                 ids: Iterable<string> | null = null): number {
    const only = ids === null ? null : new Set(ids);
    const copies = this.state.cards.filter((c) => only === null || only.has(c.id)).map(copyCard);
    const changed = new Map(replaceText(copies, find, replacement, fields, matchCase).map((c) => [c.id, c]));
    if (!changed.size) return 0;
    this.commit({ ...this.state, cards: this.state.cards.map((c) => changed.get(c.id) ?? c) });
    return changed.size;
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

  /** A drag of `roots` starts: hold the frames of the groups around them still. */
  beginMove(roots: readonly string[]): void {
    const moving = new Set(roots.flatMap((r) => this.carried(r)));
    this.frozen.clear();
    for (const r of roots) {
      for (const a of this.structure.ancestors(r)) {
        if (!moving.has(a)) this.frozen.set(a, { ...this.boxes.get(a)! });
      }
    }
    this.moving = true;
  }

  /** The drag is over: frames fit their cards again (at the next refresh). */
  endMove(): void {
    this.frozen.clear();
    this.moving = false;
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

  private freshSize: [number, number] | null = null;

  /** A brand-new card's size (for the outline shown where one would be created). */
  newCardSize(): [number, number] {
    if (!this.freshSize) {
      const b = new Layouter({ cards: [], display: this.state.display }, this.m).all([makeCard()]).values().next().value!;
      this.freshSize = [b.w, b.h];
    }
    return this.freshSize;
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

  /** Replace a card with edited data, and for a group set its members and maybe arrange
   *  it: one undo step. A group turned into a card first lets its cards go. */
  updateCard(id: string, data: Partial<CardData>, extras: CardEditExtras = {}): void {
    const old = this.card(id);
    if (!old) return;
    const next = makeCard({ ...old, ...data, id });
    if (!deepEqual(next, old)) {
      if (old.kind === KIND_GROUP && next.kind !== KIND_GROUP) this.releaseInto(id, old.parent);
      let state = this.replaceCards(new Map([[id, next]]));
      if (next.color !== old.color && !(CARD_COLORS as readonly string[]).includes(next.color)
          && !state.custom_colors.includes(next.color)) {
        state = { ...state, custom_colors: [...state.custom_colors, next.color] };
      }
      this.state = state;
      this.refresh();
    }
    if (next.kind === KIND_GROUP && extras.members) this.applyMembers(id, extras.members);
    if (next.kind === KIND_GROUP && extras.arrange) this.arrangeInPlace(id);
    this.commit(); // (a new card kept as it was still needs recording)
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

  // ----- groups ----------------------------------------------------------------------------

  /** The group a drag of `roots` would drop into at (x, y): never one of the moving groups
   *  or anything inside them. */
  groupForDrop(roots: readonly string[], x: number, y: number): string | null {
    const exclude = new Set<string>();
    for (const r of roots) for (const id of this.carried(r)) exclude.add(id);
    return this.groupAt(x, y, exclude);
  }

  /** While dragging: the group to outline, if the drop would change anything. */
  dropHint(roots: readonly string[], x: number, y: number): string | null {
    const target = this.groupForDrop(roots, x, y);
    // All staying put: nothing to announce.
    if (target !== null && roots.every((r) => this.structure.parentOf.get(r) === target)) return null;
    return target;
  }

  /** After a drag: everything that moved goes into the group under the pointer, or out of
   *  its group if the pointer isn't over one (cards inside a moving group stay in it). A
   *  card dropped on a collapsed group's title bar goes under its other cards. */
  dropInto(roots: readonly string[], x: number, y: number): void {
    const target = this.groupForDrop(roots, x, y);
    const parentChanges = new Map<string, Partial<CardData>>();
    for (const r of roots) {
      const now = this.structure.parentOf.get(r) ?? "";
      if (now !== (target ?? "")) parentChanges.set(r, { parent: target ?? "" });
    }
    if (!parentChanges.size) return;
    this.state = this.replaceCards(parentChanges);
    this.refresh();
    const folded = target !== null && this.card(target)!.collapsed;
    if (folded) for (const r of parentChanges.keys()) this.park(target!, r);
  }

  /** Put a card dropped on a collapsed group under its other cards (where it'll be when the
   *  group unfolds), not on the title bar. */
  private park(group: string, id: string): void {
    const others = (this.structure.members.get(group) ?? []).filter((m) => m !== id).map((m) => this.boxes.get(m)!);
    const g = this.boxes.get(group)!;
    const b = this.boxes.get(id)!;
    const [x, y] = others.length
      ? [Math.min(...others.map((o) => o.x)), Math.max(...others.map((o) => o.y + o.h)) + ARRANGE_GAP]
      : [g.x + GROUP_PAD, g.y + g.headerH + GROUP_PAD];
    this.state = this.movedBy([id], x - b.x, y - b.y);
    this.refresh();
  }

  /** Take a card out of its group, into the group around that one, stepped just outside
   *  the frame so it doesn't look as if it's still inside. One undo step. */
  removeFromGroup(id: string): void {
    const group = this.structure.parentOf.get(id);
    if (group === undefined) return;
    const frame = this.boxes.get(group)!;
    const b = this.boxes.get(id)!;
    let next = this.replaceCards(new Map([[id, { parent: this.structure.parentOf.get(group) ?? "" }]]));
    next = this.movedBy([id], frame.x + frame.w + ARRANGE_GAP - b.x, 0, next);
    this.commit(next);
  }

  /** Ungroup: the group's cards move up to its own group and stay where they are. */
  ungroup(id: string): void {
    this.releaseInto(id, this.structure.parentOf.get(id) ?? "");
    this.commit();
  }

  private releaseInto(id: string, parent: string): void {
    const members = this.structure.members.get(id) ?? [];
    if (!members.length) return;
    this.state = this.replaceCards(new Map(members.map((m) => [m, { parent }])));
    this.refresh();
  }

  /** Who could go in a group: everything but the group itself and the groups around it
   *  (that would make a loop), as [id, label, is a member], by title. */
  memberCandidates(id: string): [string, string, boolean][] {
    const blocked = new Set([id, ...this.structure.ancestors(id)]);
    return this.state.cards.filter((c) => !blocked.has(c.id))
      .map((c) => {
        let label = c.title || "Untitled";
        if (c.kind === KIND_GROUP) label += "  [group]";
        const parent = this.structure.parentOf.get(c.id);
        if (parent !== undefined && parent !== id) label += `  · in “${this.card(parent)!.title || "Untitled"}”`;
        return [c.id, label, parent === id] as [string, string, boolean];
      })
      .sort((a, b) => (a[1].toLowerCase() < b[1].toLowerCase() ? -1 : a[1].toLowerCase() > b[1].toLowerCase() ? 1 : 0));
  }

  /** Make exactly `ids` the group's direct members: new ones go in a grid inside the
   *  frame, below what's there; removed ones are placed beside it. */
  private applyMembers(group: string, ids: readonly string[]): void {
    const wanted = new Set(ids);
    const blocked = new Set([group, ...this.structure.ancestors(group)]);
    const outer = this.structure.parentOf.get(group) ?? "";
    const frame = this.boxes.get(group)!;
    let outY = frame.y;
    for (const m of [...(this.structure.members.get(group) ?? [])]) {
      if (wanted.has(m)) continue;
      const b = this.boxes.get(m)!;
      let next = this.replaceCards(new Map([[m, { parent: outer }]]));
      next = this.movedBy([m], frame.x + frame.w + ARRANGE_GAP * 2 - b.x, outY - b.y, next);
      outY += b.h + ARRANGE_GAP;
      this.state = next;
      this.refresh();
    }
    const toAdd = ids.filter((i) => this.boxes.has(i) && !blocked.has(i) && this.structure.parentOf.get(i) !== group);
    if (!toAdd.length) return;
    const existing = (this.structure.members.get(group) ?? []).map((m) => this.boxes.get(m)!);
    const g = this.boxes.get(group)!;
    const x0 = existing.length ? Math.min(...existing.map((b) => b.x)) : g.x + GROUP_PAD;
    let y = existing.length ? Math.max(...existing.map((b) => b.y + b.h)) + ARRANGE_GAP : g.y + g.headerH + GROUP_PAD;
    let x = x0;
    let rowH = 0;
    let col = 0;
    for (const m of toAdd) {
      const b = this.boxes.get(m)!;
      let next = this.replaceCards(new Map([[m, { parent: group }]]));
      next = this.movedBy([m], x - b.x, y - b.y, next); // a nested group brings its cards
      this.state = next;
      rowH = Math.max(rowH, b.h);
      col++;
      if (col >= ARRANGE_COLUMNS) {
        [x, y, rowH, col] = [x0, y + rowH + ARRANGE_GAP, 0, 0];
      } else {
        x += b.w + ARRANGE_GAP;
      }
    }
    this.refresh();
  }

  setArrangeOptions(ids: readonly string[], options: ArrangeOptions): void {
    this.commit(this.replaceCards(new Map(ids.filter((i) => this.boxes.get(i)?.isGroup).map((i) => [i, options]))));
  }

  /** Auto-arrange groups (heddle/layout.py): one undo step. */
  autoArrange(ids: readonly string[]): void {
    for (const id of ids) this.arrangeInPlace(id);
    this.commit();
  }

  /** Lay out a group's cards by their arrows, fit the frame snugly, and push aside what
   *  the grown frame now covers (a group can only grow right or down: it keeps its
   *  top-left). Arrows to cards inside a nested group count as arrows to that group. */
  private arrangeInPlace(id: string): void {
    const members = this.structure.members.get(id) ?? [];
    if (!members.length || !this.boxes.get(id)?.isGroup) return;
    const before = new Map<string, Rect>();
    for (const g of [id, ...this.structure.ancestors(id)]) before.set(g, rectOf(this.boxes.get(g)!));
    const memberSet = new Set(members);
    const rep = new Map<string, string>();
    for (const c of this.state.cards) {
      if (memberSet.has(c.id)) rep.set(c.id, c.id);
      else {
        for (const a of this.structure.ancestors(c.id)) {
          if (memberSet.has(a)) {
            rep.set(c.id, a);
            break;
          }
        }
      }
    }
    const edges: [string, string][] = [];
    const labels = new Map<string, [number, number]>();
    for (const e of this.state.connections) {
      const s = rep.get(e.source);
      const t = rep.get(e.target);
      if (s === undefined || t === undefined) continue;
      edges.push([s, t]);
      const [, text] = labelTexts(e, 0, this.state.display, this.m);
      if (text) { // room for the widest label between the two
        const w = this.m.width(text, "edge") + 12;
        const h = lineHeight(this.m, "edge") + 4;
        const old = labels.get(edgeKey(s, t)) ?? [0, 0];
        labels.set(edgeKey(s, t), [Math.max(old[0], w), Math.max(old[1], h)]);
      }
    }
    const nodes = members.map((m) => {
      const b = this.boxes.get(m)!;
      return makeNode(m, b.w, b.h, { x: b.x, y: b.y, color: b.card.color.toLowerCase(), group: b.isGroup });
    });
    const group = this.card(id)!;
    const placed = arrange(nodes, edges, {
      byColor: group.arrange_by_color, vertical: group.arrange_vertical, grid: group.arrange_grid,
      labels, wrap: group.arrange_wrap,
    });
    const g = this.boxes.get(id)!;
    const ox = g.x + GROUP_PAD;
    const oy = g.y + g.headerH + GROUP_PAD;
    let next = this.replaceCards(new Map([[id, { width: 0, height: 0 }]])); // back to a snug fit
    for (const m of members) {
      const [x, y] = placed.get(m)!;
      const b = this.boxes.get(m)!;
      next = this.movedBy([m], ox + x - b.x, oy + y - b.y, next);
    }
    this.state = next;
    this.refresh();
    const moves: Move[] = [];
    this.makeRoom(id, before, moves);
    this.state = this.movesToState(moves);
    this.refresh();
  }

  /** The state with a group's frame sized by hand from its top-left (it still grows to
   *  hold all its cards). Stored as the frame with details hidden. */
  resizedGroup(id: string, width: number, height: number): BoardState {
    const b = this.boxes.get(id)!;
    const hdr = b.headerH;
    const hdr0 = b.closedHeaderH;
    return this.replaceCards(new Map([[id, {
      x: b.x, y: b.y + hdr - hdr0, width: Math.max(width, GROUP_MIN_WIDTH), height: hdr0 + Math.max(height - hdr, GROUP_MIN_BODY),
    }]]));
  }

  /** Back to fitting snugly round the cards. */
  fitFrame(id: string): void {
    this.commit(this.replaceCards(new Map([[id, { width: 0, height: 0 }]])));
  }

  // ----- copy, cut, paste, duplicate ---------------------------------------------------

  /** The selected cards as a self-contained board: a selected group brings everything
   *  inside it, arrows come along when both ends do, and the custom colours the cards use
   *  come too, so they paste correctly into another board. Null with nothing selected. */
  selectionFragment(): BoardData | null {
    if (!this.selected.size) return null;
    const ids = new Set<string>();
    for (const id of this.selected) for (const x of this.carried(id)) ids.add(x);
    const cards = this.state.cards.filter((c) => ids.has(c.id));
    const used = new Set(cards.map((c) => c.color.toLowerCase()));
    return makeBoard({
      cards: cards.map((c) => ({ ...c, tags: [...c.tags], characters: [...c.characters], locations: [...c.locations] })),
      connections: this.state.connections.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ ...e })),
      custom_colors: this.state.custom_colors.filter((c) => used.has(c.toLowerCase())),
    });
  }

  /** The innermost visible group frame under a point, if any (not one of `exclude`). */
  groupAt(x: number, y: number, exclude: ReadonlySet<string> = new Set()): string | null {
    let best: CardBox | null = null;
    for (const b of this.boxes.values()) {
      if (!b.isGroup || !b.visible || exclude.has(b.card.id)) continue;
      if (x < b.x || x > b.x + b.w || y < b.y || y > b.y + b.h) continue;
      if (!best || b.depth >= best.depth) best = b;
    }
    return best ? best.card.id : null;
  }

  /** Add a copy of `fragment` (fresh ids) and select it: one undo step. With `at` (the
   *  pointer), the copy's top-left goes there and it joins the group under that point;
   *  without, it sits beside the originals and stays in their groups. */
  paste(fragment: BoardData, at: [number, number] | null = null): string[] {
    if (!fragment.cards.length) return [];
    let copy: BoardData;
    let target: string | null = null;
    if (at === null) {
      copy = cloneFragment(fragment, new Set(this.state.cards.map((c) => c.id)));
      for (const c of copy.cards) {
        c.x += PASTE_OFFSET;
        c.y += PASTE_OFFSET;
      }
    } else {
      copy = cloneFragment(fragment);
      const left = Math.min(...fragment.cards.map((c) => c.x));
      const top = Math.min(...fragment.cards.map((c) => c.y));
      for (const c of copy.cards) {
        c.x += at[0] - left;
        c.y += at[1] - top;
      }
      target = this.groupAt(at[0], at[1]);
    }
    const ids = new Set(copy.cards.map((c) => c.id));
    const cards = copy.cards.map((c) => (target !== null && !c.parent ? { ...c, parent: target } : c));
    const colors = [...this.state.custom_colors];
    for (const c of copy.custom_colors) if (!colors.includes(c)) colors.push(c);
    this.selected = new Set(cards.filter((c) => !ids.has(c.parent)).map((c) => c.id));
    this.selectedArrows.clear();
    this.commit({
      ...this.state, cards: [...this.state.cards, ...cards],
      connections: [...this.state.connections, ...copy.connections], custom_colors: colors,
    });
    return cards.map((c) => c.id);
  }

  duplicate(): string[] {
    const fragment = this.selectionFragment();
    return fragment ? this.paste(fragment) : [];
  }

  /** Remove the selected cards (with whatever their groups hold), returning them. */
  cut(): BoardData | null {
    const fragment = this.selectionFragment();
    if (fragment) this.remove(this.selected, [], true);
    return fragment;
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
    const changes = (e: ConnectionData) => (Object.keys(data) as (keyof typeof data)[]).some((k) => e[k] !== data[k]);
    this.commit({ ...this.state, connections: this.state.connections.map((e) => (set.has(e.id) && changes(e) ? { ...e, ...data } : e)) });
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
