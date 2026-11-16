// The board as the viewer shows it: card layout, arrows, introductions, and the two
// things you can change while viewing: folding groups and showing details. Pure: no DOM.
// W3 replaces this with the editable board store.
//
// Showing a card's details pushes what it would cover out of the way, and hiding them
// moves those cards back (heddle/scene_room.py). Those moves are never saved: they're
// kept as offsets beside the board's own positions.

import { StoryGraph } from "../core/graph.ts";
import { V_GAP } from "../core/layout.ts";
import { KIND_GROUP, type BoardData } from "../core/model.ts";
import { Layouter, Structure, type CardBox, type Rect } from "./metrics.ts";
import { routeArrows, type ArrowShape } from "./routing.ts";
import type { TextMeasurer } from "./text.ts";

/** Gap left when pushing neighbours out of the way. */
export const PUSH_GAP = V_GAP;

type Move = [id: string, dx: number, dy: number];

/** Qt's QRectF.intersects: rectangles that only touch don't count. */
const intersects = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const rectOf = (b: CardBox): Rect => ({ x: b.x, y: b.y, w: b.w, h: b.h });

export class BoardViewer {
  readonly structure: Structure;
  boxes!: Map<string, CardBox>;
  arrows!: ArrowShape[];
  readonly details = new Set<string>();
  /** How far each card has been pushed aside for open details. */
  private readonly shift = new Map<string, [number, number]>();
  /** {card whose details are open: the pushes that made room for them}. */
  private readonly loans = new Map<string, Move[]>();
  private readonly layouter: Layouter;
  /** Bumped on every change, so the canvas and minimap know to redraw. */
  version = 0;

  constructor(readonly board: BoardData, private readonly m: TextMeasurer) {
    this.structure = new Structure(board.cards);
    const introductions = board.display.story_tools
      ? new StoryGraph(board.cards, board.connections).introductions() : new Map<string, string[]>();
    this.layouter = new Layouter({
      cards: board.cards, display: board.display, introductions, details: this.details,
      strands: board.strands, shift: this.shift,
    }, m, this.structure);
    this.relayout();
  }

  /** Lay out every card and route every arrow again. */
  relayout(): void {
    this.boxes = this.layouter.all(this.board.cards);
    this.reroute();
  }

  private reroute(): void {
    this.arrows = routeArrows(this.board.connections, this.boxes, this.structure, this.board.display, this.m);
    this.version++;
  }

  /** Fold a group to its title bar, or unfold it. (Not saved: the viewer can't save yet.) */
  setCollapsed(groupId: string, collapsed: boolean): void {
    this.collapse([groupId], collapsed);
  }

  /** Fold or unfold every group. */
  setAllCollapsed(collapsed: boolean): void {
    this.collapse(this.board.cards.filter((c) => c.kind === KIND_GROUP).map((c) => c.id), collapsed);
  }

  /** Unfolding pushes neighbours aside, as on the desktop (and they stay there). */
  private collapse(ids: string[], collapsed: boolean): void {
    const groups = ids.map((id) => this.structure.byId.get(id)!)
      .filter((c) => c?.kind === KIND_GROUP && c.collapsed !== collapsed);
    if (!groups.length) return;
    const before = new Map<string, Rect>();
    for (const g of groups) {
      for (const id of [g.id, ...this.structure.ancestors(g.id)]) before.set(id, rectOf(this.boxes.get(id)!));
    }
    for (const g of groups) g.collapsed = collapsed;
    this.boxes = this.layouter.all(this.board.cards);
    if (!collapsed) for (const g of groups) this.makeRoom(g.id, before, []);
    this.reroute();
  }

  /** `grown` has grown right or down from its frame in `before`: push its neighbours the
   *  same way, then do the same for each group around it that grew as a result. */
  private makeRoom(grown: string, before: ReadonlyMap<string, Rect>, moves: Move[]): void {
    for (let level: string | undefined = grown; level !== undefined; level = this.structure.parentOf.get(level)) {
      this.pushAside(level, before.get(level)!, moves);
      const parent = this.structure.parentOf.get(level);
      if (parent !== undefined) this.layouter.update(parent, this.boxes);
    }
  }

  get anyCollapsed(): boolean {
    return this.board.cards.some((c) => c.kind === KIND_GROUP && c.collapsed);
  }

  toggleDetails(cardId: string): void {
    this.showDetails(cardId, !this.details.has(cardId));
    this.reroute();
  }

  /** Show or hide every card's details: cards top to bottom (each pushes what's below it
   *  before that opens in turn), then groups deepest first; hiding in reverse. */
  setAllDetails(visible: boolean): void {
    const cards = this.board.cards.filter((c) => c.kind !== KIND_GROUP).map((c) => this.boxes.get(c.id)!)
      .map((b, i) => ({ b, i })).sort((p, q) => p.b.y - q.b.y || p.b.x - q.b.x || p.i - q.i).map(({ b }) => b.card.id);
    const groups = this.board.cards.filter((c) => c.kind === KIND_GROUP).map((c, i) => ({ id: c.id, i }))
      .sort((p, q) => this.structure.depth.get(q.id)! - this.structure.depth.get(p.id)! || p.i - q.i).map(({ id }) => id);
    const order = [...cards, ...groups];
    for (const id of visible ? order : order.reverse()) this.showDetails(id, visible);
    this.reroute();
  }

  private showDetails(id: string, visible: boolean): void {
    if (visible === this.details.has(id)) return;
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

  /** Details closed: move back what opening them pushed (latest push first). */
  private giveBack(id: string): void {
    const moves = this.loans.get(id) ?? [];
    this.loans.delete(id);
    const touched = new Set<string>();
    for (const [mid, dx, dy] of [...moves].reverse()) {
      this.moveBy(mid, -dx, -dy);
      const parent = this.structure.parentOf.get(mid);
      if (parent !== undefined) touched.add(parent);
    }
    for (const g of touched) this.layouter.update(g, this.boxes);
  }

  /** Move a card, or a group with everything inside it. */
  private moveBy(id: string, dx: number, dy: number): void {
    for (const x of [id, ...(this.boxes.get(id)?.isGroup ? this.structure.descendants(id) : [])]) {
      const [sx, sy] = this.shift.get(x) ?? [0, 0];
      this.shift.set(x, [sx + dx, sy + dy]);
      const box = this.boxes.get(x);
      if (box) {
        box.x += dx;
        box.y += dy;
      }
    }
  }

  /** Move the cards and groups beside `grown` (same group) that its frame now covers out
   *  of the way: right if they were right of its old frame, down if below it (the
   *  shorter move if both), leaving the usual gap. Whatever a moved card then covers
   *  moves on in turn. Cards that already overlapped the old frame stay put. */
  private pushAside(grown: string, old: Rect, moves: Move[]): void {
    const parent = this.structure.parentOf.get(grown);
    const siblings = this.board.cards.filter((c) => c.id !== grown && this.structure.parentOf.get(c.id) === parent)
      .map((c) => c.id);
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
        this.moveBy(s, dx, dy);
        moves.push([s, dx, dy]);
        movers.push([s, r, rectOf(this.boxes.get(s)!)]);
      }
    }
  }
}
