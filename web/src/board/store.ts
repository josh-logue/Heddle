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
  BUILTIN_STATUSES, BULK_LIST_FIELDS, CARD_COLORS, KIND_GROUP, KIND_STRAND, RENAMABLE_FIELDS, applyFields, boardValues, cleanList,
  countValues, makeStrandInfo, mergeFields, renameInList, renameValue, strandIsBlank, strandKey, type StrandKind,
  applyBulkEdit, boardToJson, cleanDisplay, cloneFragment, copyCard, makeBoard, makeCard, newId,
  replaceText, type BulkEdit, type TextField,
  type BoardData, type CardData, type ConnectionData, type Display, type RouteData, type SavedValues,
  type ListField, type StrandGroup, type StrandInfo, copyRoute, groupHas, makeStrandGroup, routeIsBlank, routeKeyId,
  strandGroupKey, titleLabels,
} from "../core/model.ts";
import {
  CARD_WIDTH, GROUP_MIN_BODY, GROUP_MIN_WIDTH, GROUP_PAD, Layouter, Structure, paintOrder, type CardBox, type Rect,
} from "./metrics.ts";
import { labelTexts, routeArrows, type ArrowShape } from "./routing.ts";
import { lineHeight, type TextMeasurer } from "./text.ts";
import { matches as filterMatches, type Extras, type FilterCounts } from "../core/filters.ts";
import { casefold, sortedBy, strip } from "../core/pystr.ts";

/** Between two descriptions joined when strands merge (renaming one to the other's name). */
export const MERGED_DESCRIPTIONS = "\n\n———\n\n";
/** Where "Remove unused" and "Import" list custom palette colours beside the strands. */
export const COLORS_KEY = "custom_colors";

/** Every strand of a field on a board: on cards, on routes, saved, with details, in a
 *  strand group, stood for by a strand card, and for statuses the built-in ones
 *  (heddle/scene_strands.all_values). */
export function strandsOf(s: BoardState, field: StrandKind): string[] {
  const extra: string[] = [...(s.saved_values[field] ?? [])];
  if (field === "status") extra.push(...BUILTIN_STATUSES);
  for (const [spelling] of countValues(s.routes, field).values()) extra.push(spelling);
  for (const info of s.strands) if (info.kind === field) extra.push(info.name);
  for (const g of s.strand_groups) if (g.kind === field) extra.push(...g.members);
  for (const c of s.cards) if (c.kind === KIND_STRAND && c.strand_kind === field) extra.push(c.strand);
  return boardValues(s.cards, field, extra);
}

/** {"field\0casefolded": name} for every strand on a board. */
function strandNames(s: BoardState): Map<string, [StrandKind, string]> {
  const out = new Map<string, [StrandKind, string]>();
  for (const f of RENAMABLE_FIELDS) for (const name of strandsOf(s, f)) out.set(strandKey(f, name), [f, name]);
  return out;
}

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
  /** Custom colours taken off the board's palette in the editor. */
  removeColors?: readonly string[];
}

export interface BoardState {
  readonly cards: readonly CardData[];
  readonly connections: readonly ConnectionData[];
  readonly custom_colors: readonly string[];
  readonly saved_values: SavedValues;
  readonly display: Display;
  readonly routes: readonly RouteData[];
  readonly strands: readonly StrandInfo[];
  readonly strand_groups: readonly StrandGroup[];
}

const sameList = <T>(a: readonly T[], b: readonly T[]) => a.length === b.length && a.every((x, i) => x === b[i]);
/** Equal lists: mostly the same objects (shared between snapshots), so only the replaced
 *  ones are compared by value. */
const equalList = <T>(a: readonly T[], b: readonly T[]) =>
  a.length === b.length && a.every((x, i) => x === b[i] || deepEqual(x, b[i]));

/** Equal boards, by value as the desktop compares its snapshots: a card dragged away and
 *  back, or nudged there and back, is a new object but no change. */
export function sameState(a: BoardState, b: BoardState): boolean {
  return equalList(a.cards, b.cards) && equalList(a.connections, b.connections)
    && deepEqual(a.custom_colors, b.custom_colors) && deepEqual(a.saved_values, b.saved_values)
    && deepEqual(a.display, b.display) && deepEqual(a.routes, b.routes) && deepEqual(a.strands, b.strands)
    && deepEqual(a.strand_groups, b.strand_groups);
}

export function stateFromBoard(b: BoardData): BoardState {
  return {
    cards: b.cards, connections: b.connections, custom_colors: b.custom_colors, saved_values: b.saved_values,
    display: b.display, routes: b.routes, strands: b.strands, strand_groups: b.strand_groups,
  };
}

export function boardFromState(s: BoardState): BoardData {
  return makeBoard({
    cards: [...s.cards], connections: [...s.connections], custom_colors: [...s.custom_colors],
    saved_values: s.saved_values, display: s.display, routes: [...s.routes], strands: [...s.strands],
    strand_groups: [...s.strand_groups],
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

/** A path highlight's direction: before and after, only what leads here, only what follows. */
export type PathMode = "both" | "before" | "after";
export const PATH_MODES: readonly PathMode[] = ["both", "before", "after"];
/** Highlights that belong to the story tools, cleared when they're turned off. */
const STORY_OWNERS = new Set(["thread", "reader", "routes", "checks"]);

/** The highlight showing on the board (heddle/scene_consts.Highlight). View state only:
 *  not saved, not undoable. */
export interface Highlight {
  /** Lit cards. */
  readonly cards: ReadonlySet<string>;
  /** Lit arrows (connection ids). */
  readonly arrows: ReadonlySet<string>;
  /** The card it's centred on, drawn with a heavier outline. */
  readonly focus: string | null;
  /** What the banner says. */
  readonly label: string;
  /** Who made it ("paths", "thread", "reader", "checks", "routes"): each clears only its own. */
  readonly owner: string;
}
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
  /** The path, thread, route or check highlight showing, if any. */
  highlight: Highlight | null = null;
  /** The cards drawn lit: the highlight's cards and the groups holding them (so their
   *  frames don't fade). */
  lit = new Set<string>();
  /** The character thread showing: its cards in story order (numbered, joined by a line). */
  thread: { name: string; ids: string[] } | null = null;
  /** The last path highlight's direction (Shift+H steps it). */
  pathsMode: PathMode = "both";

  private readonly shift = new Map<string, [number, number]>();
  private readonly loans = new Map<string, Move[]>();
  private readonly introductions = new Map<string, string[]>();
  private layouter!: Layouter;
  private layoutKey: unknown[] = [];
  private graph: StoryGraph | null = null;
  /** During a drag: the frames of the groups around what's moving, held still (the
   *  desktop refits them only when the drag ends, so a card can be dragged out). */
  private frozen = new Map<string, CardBox>();
  /** Strands a rename or "Remove unused" took off the board: not kept as saved strands. */
  private letGo = new Set<string>();
  private readonly listeners = new Set<Listener>();
  /** What "Highlight paths of selection" last followed (the one selected card, "" for
   *  anything else, null while it's off). */
  private followed: string | null = null;

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
    this.followSelection();
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

  /** `state` (default: the board now) is what's in the file. */
  markSaved(state: BoardState | null = this.history.current): void {
    this.history.saved = state;
    this.notify();
  }

  /** The board as last committed (not a drag or nudge still in progress), as file text,
   *  with the state it is: what saving writes, so it can be marked saved afterwards even
   *  if the board changed while the file was being written. */
  committedJson(): [string, BoardState] {
    const s = this.history.current ?? this.state;
    return [boardToJson(boardFromState(s)), s];
  }

  /** Replace the whole board (restoring a backup): one undoable change. */
  replaceBoard(board: BoardData): void {
    this.selected.clear();
    this.selectedArrows.clear();
    this.details.clear();
    this.shift.clear();
    this.loans.clear();
    this.commit(stateFromBoard(board));
  }

  card(id: string): CardData | undefined {
    return this.structure.byId.get(id);
  }

  private drawOrder: { version: number; value: ReturnType<typeof paintOrder> } | null = null;

  /** The visible cards and groups in drawing order (metrics.paintOrder), worked out once
   *  per change rather than on every frame and every pointer move. Every change to the
   *  boxes notifies, which bumps the version. */
  paintOrder(): ReturnType<typeof paintOrder> {
    if (this.drawOrder?.version !== this.version) this.drawOrder = { version: this.version, value: paintOrder(this.boxes) };
    return this.drawOrder.value;
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
    this.refreshHighlight();
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
    this.state = this.withDroppedStrands(this.state);
    const recorded = this.history.commit(this.state);
    const current = this.history.current;
    if (!recorded && current && current !== this.state) {
      // Nothing changed after all (say a card dragged back where it was): keep the
      // recorded objects, which later snapshots and the layout cache share.
      this.state = current;
      this.refresh();
    }
    this.notify();
    return recorded;
  }

  /** Strands belong to the board, not to the cards using them: one an edit left unused
   *  (taken off its last card, or that card deleted) is kept as a saved strand. Only a
   *  rename or "Remove unused" takes one off the list. */
  private withDroppedStrands(next: BoardState): BoardState {
    const before = this.history.current;
    const letGo = this.letGo;
    this.letGo = new Set();
    if (!before) return next;
    const now = strandNames(next);
    const keep: Partial<Record<StrandKind, string[]>> = {};
    for (const [key, [f, name]] of strandNames(before)) {
      if (!now.has(key) && !letGo.has(key)) (keep[f] ??= []).push(name);
    }
    if (!Object.keys(keep).length) return next;
    const saved = { ...next.saved_values };
    for (const [f, names] of Object.entries(keep) as [StrandKind, string[]][]) saved[f] = [...(saved[f] ?? []), ...names];
    return { ...next, saved_values: saved };
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
    return this.movedEach(roots.map((r): Move => [r, dx, dy]), base);
  }

  /** `base` with each root (and what it carries) moved by its own offset, in one pass
   *  (moving every card of a big board is linear, not a search per card). */
  private movedEach(moves: readonly Move[], base = this.state): BoardState {
    const byId = new Map(base.cards.map((c) => [c.id, c]));
    const changes = new Map<string, Partial<CardData>>();
    for (const [root, dx, dy] of moves) {
      for (const id of this.carried(root)) {
        const c = byId.get(id) ?? this.card(id);
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
    return this.commit(this.movedEach(this.nudges(roots, dx, dy, snap))) || true;
  }

  /** Each root's nudge (with snap: to the next grid line that way). */
  private nudges(roots: readonly string[], dx: number, dy: number, snap: boolean): Move[] {
    return roots.map((id) => {
      const b = this.boxes.get(id)!;
      return snap ? [id, nextLine(b.x, dx) - b.x, nextLine(b.y, dy) - b.y] : [id, dx, dy];
    });
  }

  /** The current board with each card's (or group frame's) top-left corner on the grid. */
  snappedState(roots: readonly string[]): BoardState {
    return this.movedEach(roots.map((id) => {
      const b = this.boxes.get(id)!;
      return [id, snapped(b.x) - b.x, snapped(b.y) - b.y];
    }));
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
    this.preview(this.movedEach(this.nudges(this.moveRoots(), dx, dy, snap)));
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
    if (extras.removeColors?.length) {
      const gone = new Set(extras.removeColors.map((c) => c.toLowerCase()));
      this.state = { ...this.state, custom_colors: this.state.custom_colors.filter((c) => !gone.has(c.toLowerCase())) };
    }
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
    next = this.movedEach(members.map((m) => {
      const [x, y] = placed.get(m)!;
      const b = this.boxes.get(m)!;
      return [m, ox + x - b.x, oy + y - b.y];
    }), next);
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

  // ----- strands ------------------------------------------------------------------------------

  allValues(field: StrandKind): string[] {
    return strandsOf(this.state, field);
  }

  /** A strand's own details, if it has any. */
  strand(kind: string, name: string): StrandInfo | undefined {
    const key = strandKey(kind, strip(name));
    return this.state.strands.find((s) => strandKey(s.kind, s.name) === key);
  }

  /** {casefolded strand: [cards using it, routes using it]} for one field. */
  strandUsage(kind: StrandKind): Map<string, [number, number]> {
    const cards = countValues(this.state.cards, kind);
    const routes = countValues(this.state.routes, kind);
    const out = new Map<string, [number, number]>();
    for (const k of new Set([...cards.keys(), ...routes.keys()])) out.set(k, [cards.get(k)?.[1] ?? 0, routes.get(k)?.[1] ?? 0]);
    return out;
  }

  /** {casefolded strand: strand cards standing for it} for one field. */
  strandCardCounts(kind: StrandKind): Map<string, number> {
    const out = new Map<string, number>();
    for (const c of this.state.cards) {
      if (c.kind === KIND_STRAND && c.strand_kind === kind) out.set(casefold(c.strand), (out.get(casefold(c.strand)) ?? 0) + 1);
    }
    return out;
  }

  /** The cards that have a strand (or, for a strand card, stand for it). */
  cardsWith(kind: StrandKind, name: string): string[] {
    const key = casefold(strip(name));
    return this.state.cards.filter((c) => {
      if (c.kind === KIND_STRAND) return c.strand_kind === kind && casefold(c.strand) === key;
      const v = c[kind];
      return (Array.isArray(v) ? v : [v]).some((x) => casefold(strip(x)) === key);
    }).map((c) => c.id);
  }

  /** Store a strand's description, picture and fields (one undo step); blank details
   *  forget them. False if nothing changed. */
  setStrandInfo(info: StrandInfo): boolean {
    if (!info.kind || !info.name) return false;
    const key = strandKey(info.kind, info.name);
    const at = this.state.strands.findIndex((s) => strandKey(s.kind, s.name) === key);
    const before = at >= 0 ? this.state.strands[at]! : undefined;
    let strands: StrandInfo[];
    if (strandIsBlank(info)) {
      if (!before) return false;
      strands = this.state.strands.filter((_, i) => i !== at);
    } else {
      if (before && deepEqual([before.description, before.picture, before.fields], [info.description, info.picture, info.fields])) return false;
      const kept = { ...info, name: before ? before.name : info.name };
      strands = before ? this.state.strands.map((s, i) => (i === at ? kept : s)) : [...this.state.strands, kept];
    }
    this.commit({ ...this.state, strands });
    return true;
  }

  /** Rename a strand on every card, route, saved list, strand card and its details
   *  (one undo step). Renaming onto an existing strand merges the two. How many cards changed. */
  renameStrand(field: StrandKind, old: string, newName: string): number {
    const name = strip(newName);
    if (!strip(old) || !name) return 0;
    this.letGo.add(strandKey(field, old)); // the old name isn't kept as a saved strand
    const copies = this.state.cards.map(copyCard);
    const changed = new Set(renameValue(copies, field, old, name).map((c) => c.id));
    const oldKey = casefold(strip(old));
    let strandCards = 0; // strand cards renamed too
    const cards = copies.map((c, i) => {
      if (c.kind === KIND_STRAND && c.strand_kind === field && casefold(c.strand) === oldKey && c.strand !== name) {
        strandCards++;
        return makeCard({ ...c, strand: name, title: name });
      }
      return changed.has(c.id) ? makeCard({ ...c }) : this.state.cards[i]!;
    });
    const routes = this.state.routes.map((r) => ({ ...r, tags: [...r.tags], characters: [...r.characters], locations: [...r.locations] }));
    renameValue(routes as unknown as CardData[], field, old, name);
    const saved = { ...this.state.saved_values };
    if (saved[field]) saved[field] = renameInList(saved[field]!, old, name);
    // A renamed strand keeps its place in its groups (onto a strand already there: merged).
    const strand_groups = this.state.strand_groups.map((g) =>
      g.kind === field && groupHas(g, old) ? { ...g, members: renameInList(g.members, old, name) } : g);
    this.commit({ ...this.state, cards, routes, saved_values: saved, strands: this.renamedDetails(field, old, name),
      strand_groups });
    return changed.size + strandCards;
  }

  /** Carry a strand's details over to its new name; onto a strand with details of its own,
   *  merge them: both descriptions (the target's first), the target's picture (or the
   *  renamed one's), and the fields (the target's values kept). */
  private renamedDetails(kind: StrandKind, old: string, name: string): StrandInfo[] {
    const oldKey = strandKey(kind, old);
    const newKey = strandKey(kind, name);
    const moving = this.state.strands.find((s) => strandKey(s.kind, s.name) === oldKey);
    if (!moving) return [...this.state.strands];
    const rest = this.state.strands.filter((s) => s !== moving);
    const target = newKey !== oldKey ? rest.find((s) => strandKey(s.kind, s.name) === newKey) : undefined;
    if (!target) return [...rest, { ...moving, name }];
    const texts = [strip(target.description), strip(moving.description)].filter(Boolean);
    const merged: StrandInfo = {
      ...target, name, description: texts.join(MERGED_DESCRIPTIONS), picture: target.picture || moving.picture,
      fields: mergeFields(target.fields, moving.fields),
    };
    return rest.map((s) => (s === target ? merged : s));
  }

  /** Copy `source`'s field names (only `names`, if given) to `targets` of the same kind:
   *  one undo step. Returns [strands changed, fields added]. */
  applyStrandFields(kind: StrandKind, source: string, targets: Iterable<string>, names: Iterable<string> | null = null,
                    withValues = false): [number, number] {
    const info = this.strand(kind, source);
    if (!info?.fields.length) return [0, 0];
    const spelling = new Map(this.allValues(kind).map((v) => [casefold(v), v]));
    let strands = [...this.state.strands];
    let changed = 0;
    let added = 0;
    for (const t of new Set([...targets].map((x) => casefold(strip(x))))) {
      if (t === casefold(info.name) || !spelling.has(t)) continue;
      const at = strands.findIndex((x) => strandKey(x.kind, x.name) === strandKey(kind, t));
      const old = at >= 0 ? strands[at]! : makeStrandInfo({ kind, name: spelling.get(t)! });
      const fields = applyFields(info.fields, old.fields, names === null ? null : [...names], withValues);
      if (deepEqual(fields, old.fields)) continue;
      const next = { ...old, fields };
      strands = at >= 0 ? strands.map((x, i) => (i === at ? next : x)) : [...strands, next];
      changed++;
      added += fields.length - old.fields.length;
    }
    if (changed) this.commit({ ...this.state, strands });
    return [changed, added];
  }

  /** Strands nothing uses (no card, route or strand card), per field: [those without
   *  details (saved ones only), those with a description, picture or fields, or in a strand
   *  group]. */
  unusedStrands(): [Partial<Record<StrandKind, string[]>>, Partial<Record<StrandKind, string[]>>] {
    const plain: Partial<Record<StrandKind, string[]>> = {};
    const detailed: Partial<Record<StrandKind, string[]>> = {};
    for (const f of RENAMABLE_FIELDS) {
      const used = new Set([...this.strandUsage(f).keys(), ...this.strandCardCounts(f).keys()]);
      if (f === "status") for (const b of BUILTIN_STATUSES) used.add(casefold(b)); // built in: never unused
      const saved = new Set((this.state.saved_values[f] ?? []).map(casefold));
      const grouped = new Set(this.state.strand_groups.filter((g) => g.kind === f).flatMap((g) => g.members.map(casefold)));
      for (const name of this.allValues(f)) {
        const key = casefold(name);
        if (used.has(key)) continue;
        if (this.strand(f, name) || grouped.has(key)) (detailed[f] ??= []).push(name);
        else if (saved.has(key)) (plain[f] ??= []).push(name);
      }
    }
    return [plain, detailed];
  }

  /** How many cards and arrows use each colour, not counting the card `exclude`. */
  colorUsage(exclude: string | null = null): Map<string, number> {
    const counts = new Map<string, number>();
    const add = (c: string) => counts.set(c.toLowerCase(), (counts.get(c.toLowerCase()) ?? 0) + 1);
    for (const c of this.state.cards) if (c.id !== exclude) add(c.color);
    for (const e of this.state.connections) if (e.color) add(e.color);
    return counts;
  }

  /** Saved strands nothing uses, per field, plus custom colours nothing uses (under
   *  COLORS_KEY). Strands with details only with `withDetails`. */
  unusedSaved(withDetails = false): Record<string, string[]> {
    const [plain, detailed] = this.unusedStrands();
    const out: Record<string, string[]> = { ...plain } as Record<string, string[]>;
    if (withDetails) for (const [f, names] of Object.entries(detailed)) out[f] = [...(out[f] ?? []), ...names!];
    const used = this.colorUsage();
    const spare = this.state.custom_colors.filter((c) => !used.has(c.toLowerCase()));
    if (spare.length) out[COLORS_KEY] = spare;
    return out;
  }

  /** Remove saved strands (their details too) and, under COLORS_KEY, custom colours:
   *  one undo step. How many went. */
  removeSaved(values: Record<string, string[]>): number {
    let removed = 0;
    const colors = new Set((values[COLORS_KEY] ?? []).map((c) => c.toLowerCase()));
    const custom = this.state.custom_colors.filter((c) => !colors.has(c.toLowerCase()));
    removed += this.state.custom_colors.length - custom.length;
    const saved = { ...this.state.saved_values };
    let strands = [...this.state.strands];
    let groups = [...this.state.strand_groups];
    for (const [f, gone] of Object.entries(values) as [StrandKind, string[]][]) {
      if (!(RENAMABLE_FIELDS as readonly string[]).includes(f)) continue;
      const keys = new Set(gone.map((v) => casefold(v)));
      const before = saved[f] ?? [];
      const after = before.filter((v) => !keys.has(casefold(v)));
      const goneKeys = new Set(before.filter((v) => keys.has(casefold(v))).map(casefold));
      strands = strands.filter((x) => {
        if (x.kind === f && keys.has(casefold(x.name))) {
          goneKeys.add(casefold(x.name));
          return false;
        }
        return true;
      });
      groups = groups.map((g) => {
        if (g.kind !== f) return g;
        const kept = g.members.filter((m) => !keys.has(casefold(m)));
        if (kept.length === g.members.length) return g;
        for (const m of g.members) if (keys.has(casefold(m))) goneKeys.add(casefold(m));
        return { ...g, members: kept };
      });
      removed += goneKeys.size;
      for (const k of goneKeys) this.letGo.add(`${f}\u0000${k}`);
      if (after.length) saved[f] = after;
      else delete saved[f];
    }
    if (removed) this.commit({ ...this.state, custom_colors: custom, saved_values: saved, strands, strand_groups: groups });
    return removed;
  }

  /** Add strands (and custom colours) without making cards, with their details from
   *  `details`. Strands the board already has are skipped. How many were added. */
  importStrands(values: Record<string, string[]>, colors: readonly string[] = [], details: readonly StrandInfo[] = []): number {
    let added = 0;
    const saved = { ...this.state.saved_values };
    const strands = [...this.state.strands];
    const info = new Map(details.map((d) => [strandKey(d.kind, d.name), d]));
    for (const [f, fresh0] of Object.entries(values) as [StrandKind, string[]][]) {
      if (!(RENAMABLE_FIELDS as readonly string[]).includes(f)) continue;
      const have = new Set(this.allValues(f).map(casefold));
      const fresh = cleanList(fresh0).filter((v) => !have.has(casefold(v)));
      if (!fresh.length) continue;
      saved[f] = [...(saved[f] ?? []), ...fresh];
      added += fresh.length;
      for (const v of fresh) {
        const d = info.get(strandKey(f, v));
        if (d && !strandIsBlank(d)) strands.push({ ...d, name: v });
      }
    }
    const presets = new Set<string>(CARD_COLORS);
    const custom = [...this.state.custom_colors];
    for (const raw of colors) {
      const c = strip(raw).toLowerCase();
      if (c && !presets.has(c) && !custom.includes(c)) {
        custom.push(c);
        added++;
      }
    }
    if (added) this.commit({ ...this.state, saved_values: saved, strands, custom_colors: custom });
    return added;
  }

  /** What dropping a strand at (x, y) would do: ["card", id] adds it to a standard card,
   *  ["group", id] puts a strand card in a group, ["new", null] on the blank board; null:
   *  refused (over a strand card, whose strand is fixed). */
  strandDropTarget(x: number, y: number): ["card" | "group" | "new", string | null] | null {
    let card: CardBox | null = null;
    for (const b of this.boxes.values()) {
      if (!b.visible || b.isGroup) continue;
      if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) card = b; // the last drawn is on top
    }
    if (card) return card.isStrand ? null : ["card", card.card.id];
    const group = this.groupAt(x, y);
    return group ? ["group", group] : ["new", null];
  }

  /** Drop a strand at (x, y), as one undo step: on a standard card it joins the card's
   *  tags, characters or locations (a status replaces the card's); on a group or the blank
   *  board it becomes a strand card there. Returns [changed, a notice to show or ""]. */
  dropStrand(kind: StrandKind, name0: string, x: number, y: number, snap = false): [boolean, string] {
    const name = strip(name0);
    const target = this.strandDropTarget(x, y);
    if (!name || !target) return [false, ""];
    const [what, id] = target;
    if (what !== "card") {
      this.addStrandCard(kind, name, x, y, snap, id ?? undefined);
      return [true, ""];
    }
    const card = this.card(id!)!;
    const title = card.title || "Untitled";
    if (kind === "status") {
      const old = card.status;
      if (casefold(old) === casefold(name)) return [false, `“${title}” already has the status ${old}`];
      this.updateCard(card.id, { status: name });
      return [true, old ? `“${title}”: status ${old} → ${name}` : ""];
    }
    if (card[kind].some((v) => casefold(v) === casefold(name))) return [false, `“${title}” already has ${name}`];
    this.updateCard(card.id, { [kind]: [...card[kind], name] });
    return [true, ""];
  }

  // ----- strand groups (heddle/scene_strands.py) -------------------------------------------

  /** A strand group by kind and name (ignoring case), if the board has it. */
  strandGroup(kind: string, name: string): StrandGroup | undefined {
    const key = strandKey(kind, strip(name));
    return this.state.strand_groups.find((g) => strandGroupKey(g) === key);
  }

  /** A field's strand groups, alphabetically (as the panels list them). */
  groupsOf(kind: StrandKind): StrandGroup[] {
    return sortedBy(this.state.strand_groups.filter((g) => g.kind === kind), (g) => casefold(g.name));
  }

  /** The strand groups `strand` is in, alphabetically. */
  groupsWith(kind: StrandKind, strand: string): StrandGroup[] {
    return this.groupsOf(kind).filter((g) => groupHas(g, strand));
  }

  /** `names` in the board's spelling where it has them, duplicates dropped. */
  private spelled(kind: StrandKind, names: Iterable<string>): string[] {
    const spelling = new Map(this.allValues(kind).map((v) => [casefold(v), v]));
    return cleanList([...names].map((n) => spelling.get(casefold(strip(n))) ?? n));
  }

  /** Make a strand group (one undo step). Null if the name is blank or taken in its kind. */
  createStrandGroup(kind: StrandKind, name: string, members: Iterable<string> = []): StrandGroup | null {
    const group = makeStrandGroup({ kind, name, members: this.spelled(kind, members) });
    if (!group.kind || !group.name || this.strandGroup(kind, group.name)) return null;
    this.commit({ ...this.state, strand_groups: [...this.state.strand_groups, group] });
    return group;
  }

  /** Rename a strand group, or replace its strands or description (one undo step). Strands it
   *  loses stay on the board as saved strands. False if nothing changed, it's missing, or the
   *  new name is blank or taken. */
  updateStrandGroup(kind: StrandKind, name: string, change: { name?: string; members?: Iterable<string>; description?: string }): boolean {
    const group = this.strandGroup(kind, name);
    if (!group) return false;
    const next = makeStrandGroup({
      kind, name: change.name ?? group.name,
      members: change.members === undefined ? group.members : this.spelled(kind, change.members),
      description: change.description ?? group.description,
    });
    const other = this.strandGroup(kind, next.name);
    if (!next.name || (other && other !== group) || deepEqual(next, group)) return false;
    this.commit({ ...this.state, strand_groups: this.state.strand_groups.map((g) => (g === group ? next : g)) });
    return true;
  }

  /** Put strands in a strand group (one undo step); how many weren't in it already. */
  addToStrandGroup(kind: StrandKind, name: string, strands: Iterable<string>): number {
    const group = this.strandGroup(kind, name);
    if (!group) return 0;
    const fresh = this.spelled(kind, strands).filter((s) => !groupHas(group, s));
    if (fresh.length) this.updateStrandGroup(kind, name, { members: [...group.members, ...fresh] });
    return fresh.length;
  }

  /** Take strands out of a strand group (one undo step); how many were in it. */
  removeFromStrandGroup(kind: StrandKind, name: string, strands: Iterable<string>): number {
    const group = this.strandGroup(kind, name);
    if (!group) return 0;
    const keys = new Set([...strands].map((s) => casefold(strip(s))));
    const kept = group.members.filter((m) => !keys.has(casefold(m)));
    if (kept.length !== group.members.length) this.updateStrandGroup(kind, name, { members: kept });
    return group.members.length - kept.length;
  }

  /** Forget a strand group (one undo step). Its strands stay on the board. */
  deleteStrandGroup(kind: StrandKind, name: string): boolean {
    const group = this.strandGroup(kind, name);
    if (!group) return false;
    this.commit({ ...this.state, strand_groups: this.state.strand_groups.filter((g) => g !== group) });
    return true;
  }

  /** The strand groups that can be added to cards, by field: tags, characters and locations
   *  (a card has one status, so a group of statuses is only for filtering). Maps keep the
   *  names in order whatever they look like ("2024"). */
  strandGroupChoices(): Partial<Record<ListField, Map<string, string[]>>> {
    const out: Partial<Record<ListField, Map<string, string[]>>> = {};
    for (const f of BULK_LIST_FIELDS) {
      const groups = this.groupsOf(f);
      if (groups.length) out[f] = new Map(groups.map((g) => [g.name, [...g.members]]));
    }
    return out;
  }

  /** Add strands to cards' tags, characters or locations, as one undo step (strand cards have
   *  none of their own and are skipped). `what` names them in the notice. Returns [cards
   *  changed, a notice to show]. */
  addStrandsToCards(ids: Iterable<string>, kind: StrandKind, names: Iterable<string>, what = ""): [number, string] {
    if (!(BULK_LIST_FIELDS as readonly string[]).includes(kind)) return [0, ""];
    const list = this.spelled(kind, names);
    const targets = [...ids].filter((id) => this.card(id) && this.card(id)!.kind !== KIND_STRAND);
    const label = what || list.join(", ");
    if (!targets.length) return [0, ""];
    if (!list.length) return [0, `${label[0]!.toUpperCase()}${label.slice(1)} has no strands yet`];
    const n = this.bulkEdit(targets, { add: { [kind]: list } });
    if (n) return [n, `Added ${label} to ${n} card${n === 1 ? "" : "s"}`];
    return [0, `${targets.length === 1 ? "That card" : "Those cards"} already had ${label}`];
  }

  /** Add every strand in a strand group to cards (one undo step). [cards changed, notice]. */
  addStrandGroupToCards(ids: Iterable<string>, kind: StrandKind, name: string): [number, string] {
    const group = this.strandGroup(kind, name);
    if (!group) return [0, ""];
    return this.addStrandsToCards(ids, kind, group.members, `the strand group “${group.name}”`);
  }

  /** The card a strand group dropped at (x, y) would join: only a standard card takes one. */
  strandGroupDropTarget(kind: StrandKind, x: number, y: number): string | null {
    if (!(BULK_LIST_FIELDS as readonly string[]).includes(kind)) return null;
    const target = this.strandDropTarget(x, y);
    return target?.[0] === "card" ? target[1] : null;
  }

  /** Drop a strand group at (x, y): on a standard card its strands join the card's (one undo
   *  step). `members` come with the drag. Returns [changed, a notice to show]. */
  dropStrandGroup(kind: StrandKind, name: string, members: Iterable<string>, x: number, y: number): [boolean, string] {
    const id = this.strandGroupDropTarget(kind, x, y);
    if (!id) return [false, ""];
    const [n, notice] = this.addStrandsToCards([id], kind, members, `the strand group “${name}”`);
    return [n > 0, notice];
  }

  /** A card standing for a strand, centred on (x, y), in `group` if given: one undo step. */
  addStrandCard(kind: StrandKind, name: string, x: number, y: number, snap = false, group?: string): CardData {
    let [cx, cy] = [x - CARD_WIDTH / 2, y - 20];
    if (snap) [cx, cy] = [snapped(cx), snapped(cy)];
    const card = makeCard({
      kind: KIND_STRAND, strand_kind: kind, strand: name, x: cx, y: cy, parent: group ?? "",
      color: CARD_COLORS[this.state.cards.length % CARD_COLORS.length]!,
    });
    this.selected = new Set([card.id]);
    this.selectedArrows.clear();
    this.commit({ ...this.state, cards: [...this.state.cards, card] });
    return card;
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

  // ----- story tools: highlights, threads, outside the story, routes -----------------------

  /** Light up some cards and arrows and fade the rest (on top of any filter). Groups
   *  holding a lit card are lit too. Esc or clearHighlight() ends it. */
  setHighlight(cards: Iterable<string>, arrows: Iterable<string> = [], focus: string | null = null,
               label = "", owner = ""): void {
    this.applyHighlight(cards, arrows, focus, label, owner);
    this.notify();
  }

  private applyHighlight(cards: Iterable<string>, arrows: Iterable<string>, focus: string | null,
                         label: string, owner: string): void {
    if (owner !== "thread") this.thread = null;
    const ids = new Set([...cards].filter((id) => this.structure.byId.has(id)));
    this.highlight = { cards: ids, arrows: new Set(arrows), focus, label: label || "Highlight", owner };
    this.lit = new Set([...ids, ...this.storyGraph().containersOf(ids)]);
  }

  clearHighlight(): void {
    if (!this.highlight) return;
    this.dropHighlight();
    this.notify();
  }

  private dropHighlight(): void {
    this.highlight = null;
    this.thread = null;
    this.lit = new Set();
  }

  /** The highlight's owner ("" if none is showing). */
  get highlightOwner(): string {
    return this.highlight?.owner ?? "";
  }

  /** After every change: a thread is renumbered for the board as it now is; another
   *  highlight keeps showing for the cards that still exist (and ends when none do); the
   *  story tools' own highlights end when the story tools are turned off. */
  private refreshHighlight(): void {
    const h = this.highlight;
    if (!h) return;
    if (STORY_OWNERS.has(h.owner) && !this.state.display.story_tools) {
      this.dropHighlight();
    } else if (h.owner === "thread" && this.thread) {
      if (!this.threadHighlight(this.thread.name)) this.dropHighlight();
    } else {
      const ids = [...h.cards].filter((id) => this.structure.byId.has(id));
      const focus = h.focus !== null && this.structure.byId.has(h.focus) ? h.focus : null;
      if (!ids.length) this.dropHighlight();
      else this.applyHighlight(ids, h.arrows, focus, h.label, h.owner);
    }
  }

  /** Light up everything that can come before and/or after a card; for a group, before
   *  and after its contents. Returns the banner text. */
  highlightPaths(id: string, mode: PathMode = "both"): string {
    const label = this.pathsHighlight(id, mode);
    this.notify();
    return label;
  }

  private pathsHighlight(id: string, mode: PathMode): string {
    const graph = this.storyGraph();
    const before = mode !== "after" ? graph.upstream(id) : new Set<string>();
    const after = mode !== "before" ? graph.downstream(id) : new Set<string>();
    const inside = graph.contents(id);
    const ids = new Set([id, ...inside, ...before, ...after]);
    const edges = new Set([...graph.arrowsWithin(ids), ...graph.markersFor(ids)]);
    const title = titleLabels(this.state.cards).get(id) || this.card(id)?.title || "Untitled";
    const count = (set: Set<string>) => [...set].filter((i) => i !== id && !inside.has(i)).length;
    const parts = {
      both: `${count(before)} before, ${count(after)} after`, before: `${count(before)} before`, after: `${count(after)} after`,
    }[mode];
    const what = { both: "Paths through", before: "What leads to", after: "What follows" }[mode];
    const label = `${what} “${title}” · ${parts}`;
    this.applyHighlight(ids, edges, id, label, "paths");
    this.pathsMode = mode;
    return label;
  }

  /** H: the selected card's paths, or clear them if they're already showing. Returns a
   *  notice to show ("" if none). */
  togglePaths(): string {
    const one = this.selected.size === 1 ? [...this.selected][0]! : null;
    if (this.highlightOwner === "paths" && (one === null || this.highlight!.focus === one)) {
      this.clearHighlight();
      return "";
    }
    if (one === null) return "Select one card to highlight its paths";
    this.highlightPaths(one);
    return "";
  }

  /** Shift+H: step the path highlight from before and after to only what leads here, only
   *  what follows, and round again. With no path highlight, start one on the selected card
   *  at "only what leads here" (H gives before and after). Returns a notice, or "". */
  cyclePathsMode(): string {
    const focus = this.highlightOwner === "paths" ? this.highlight!.focus : null;
    if (focus !== null && this.structure.byId.has(focus)) {
      this.highlightPaths(focus, PATH_MODES[(PATH_MODES.indexOf(this.pathsMode) + 1) % PATH_MODES.length]!);
      return "";
    }
    if (this.selected.size !== 1) return "Select one card to highlight its paths";
    this.highlightPaths([...this.selected][0]!, "before");
    return "";
  }

  /** "Highlight paths of selection": selecting one card lights up its paths; selecting
   *  anything else clears them. Runs as the selection changes (from notify). */
  private followSelection(): void {
    const on = this.state.display.follow_paths;
    const one = on && this.selected.size === 1 ? [...this.selected][0]! : "";
    const key = on ? one : null;
    if (key === this.followed) return;
    this.followed = key;
    if (!on) return;
    if (one) this.pathsHighlight(one, "both");
    else if (this.highlightOwner === "paths") this.dropHighlight();
  }

  /** Light up the cards featuring a character, numbered in story order and joined by a
   *  dashed line. Returns the banner text ("" if no card features them). */
  showThread(name: string): string {
    const label = this.threadHighlight(name);
    if (!label && this.highlightOwner === "thread") this.dropHighlight();
    this.notify();
    return label;
  }

  private threadHighlight(name: string): string {
    const graph = this.storyGraph();
    const ids = graph.featuring(name);
    if (!ids.length) return "";
    const key = casefold(strip(name));
    const display = this.card(ids[0]!)!.characters.find((c) => casefold(c) === key) ?? strip(name);
    const arrows = new Set<string>();
    for (let i = 1; i < ids.length; i++) for (const a of graph.stepArrows(ids[i - 1]!, ids[i]!)) arrows.add(a);
    const introduced = ids.filter((i) => (this.introductions.get(i) ?? []).some((n) => casefold(n) === key));
    let label = `Thread: ${display} · ${ids.length} ${ids.length === 1 ? "card" : "cards"}`;
    if (introduced.length) {
      const first = titleLabels(this.state.cards).get(introduced[0]!) || "Untitled";
      label += ` · introduced in “${first}”${introduced.length > 1 ? ` (+${introduced.length - 1} more)` : ""}`;
    }
    // The character's own strand cards light up too (they aren't steps of the thread).
    const strandCards = this.state.cards.filter((c) => c.kind === KIND_STRAND && c.strand_kind === "characters"
      && casefold(strip(c.strand)) === key).map((c) => c.id);
    this.applyHighlight([...ids, ...strandCards], arrows, null, label, "thread");
    this.thread = { name: display, ids };
    return label;
  }

  /** A card's number in the thread showing (0 if it isn't on it). */
  threadNumber(id: string): number {
    return this.thread ? this.thread.ids.indexOf(id) + 1 : 0;
  }

  /** O: leave the selected cards out of the story, or put them back if they're all out
   *  already (one undo step). Strand cards are always outside it, so they're skipped.
   *  Returns a notice, or "". */
  toggleOutside(ids: Iterable<string> = this.selected): string {
    const cards = [...ids].map((id) => this.card(id)).filter((c): c is CardData => !!c && c.kind !== KIND_STRAND);
    if (!cards.length) return "Select a card to leave it out of the story (or put it back)";
    const out = cards.some((c) => !c.outside_story);
    this.commit(this.replaceCards(new Map(cards.map((c) => [c.id, { outside_story: out }]))));
    return "";
  }

  /** Saved route fields, by routeKeyId(key). */
  routeMap(): Map<string, RouteData> {
    return new Map(this.state.routes.map((r) => [routeKeyId(r.key), r]));
  }

  routeData(key: readonly string[]): RouteData | null {
    const id = routeKeyId(key);
    return this.state.routes.find((r) => routeKeyId(r.key) === id) ?? null;
  }

  /** Store a route's fields (one undo step); blank fields forget the route. */
  setRouteData(data: RouteData): void {
    if (!data.key.length) return;
    const id = routeKeyId(data.key);
    const at = this.state.routes.findIndex((r) => routeKeyId(r.key) === id);
    if (routeIsBlank(data)) {
      if (at >= 0) this.commit({ ...this.state, routes: this.state.routes.filter((_, i) => i !== at) });
      return;
    }
    if (at >= 0 && deepEqual(this.state.routes[at], data)) return;
    const routes = [...this.state.routes];
    if (at >= 0) routes[at] = copyRoute(data);
    else routes.push(copyRoute(data));
    this.commit({ ...this.state, routes });
  }

  /** Forget a route's fields (one undo step). False if it had none. */
  deleteRouteData(key: readonly string[]): boolean {
    if (!this.routeData(key)) return false;
    const id = routeKeyId(key);
    this.commit({ ...this.state, routes: this.state.routes.filter((r) => routeKeyId(r.key) !== id) });
    return true;
  }
}
