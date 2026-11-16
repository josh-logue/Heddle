// The Path Reader's walk through the story (heddle/path_reader.py, without its widgets).
//
// Start it on a card ("Read from here"). It offers the next steps along the card's arrows:
// one way on, or a choice at a branch. Back retraces the route actually taken (not just
// any card that leads here). The route so far is highlighted on the board.

import { titleLabels } from "../core/model.ts";
import type { StoryGraph } from "../core/graph.ts";
import type { BoardStore } from "./store.ts";

export const OWNER = "reader"; // marks the board's highlight as the reader's own
export const MAX_CHOICE_KEYS = 9; // number keys 1-9 pick a branch

export interface Choice {
  id: string;
  /** The label of the arrow that leads there ("" if none). */
  label: string;
}

type Listener = () => void;

export class PathReader {
  /** Card ids, in the order read. */
  route: string[] = [];
  /** The label of the arrow that led to each step ("" if none). */
  via: string[] = [];
  /** Reading a group: its first cards, offered before step 1. */
  startChoices: string[] = [];
  startTitle = "";
  /** Bumped on every change, for the panel to redraw. */
  version = 0;
  private seen: unknown = null;
  private readonly listeners = new Set<Listener>();
  private readonly unsubscribe: () => void;

  constructor(readonly store: BoardStore, private readonly showCard: (id: string) => void = () => {}) {
    // The board changed: cut the route where it no longer holds.
    this.unsubscribe = store.subscribe(() => {
      if (store.state !== this.seen) this.refresh();
    });
    this.seen = store.state;
  }

  dispose(): void {
    this.unsubscribe();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  get reading(): boolean {
    return this.route.length > 0 || this.startChoices.length > 0;
  }

  private get graph(): StoryGraph {
    return this.store.storyGraph();
  }

  /** Begin reading at a card. A group starts at its first cards: one of them is picked
   *  up straight away, or the reader offers the choice. */
  start(id: string): void {
    const graph = this.graph;
    this.route = [];
    this.via = [];
    this.startChoices = [];
    if (graph.isContainer(id)) {
      const entries = this.ordered(graph.entryCards(id));
      if (entries.length === 1) {
        this.stepTo(entries[0]!, "");
        return;
      }
      this.startChoices = entries;
      this.startTitle = this.store.card(id)?.title || "Untitled";
      this.changed();
      return;
    }
    this.stepTo(id, "");
  }

  /** Each possible next step, in story order. */
  choices(): Choice[] {
    if (!this.route.length) return this.startChoices.map((id) => ({ id, label: "" }));
    const graph = this.graph;
    const current = this.route[this.route.length - 1]!;
    return this.ordered(graph.succ.get(current) ?? []).map((next) => {
      const labels = graph.stepArrows(current, next).map((a) => this.arrowLabel(a));
      return { id: next, label: labels.find((l) => l) ?? "" };
    });
  }

  choose(index: number): boolean {
    const options = this.choices();
    const pick = options[index];
    if (!pick) return false;
    this.stepTo(pick.id, pick.label);
    return true;
  }

  /** Follow the only way on; at a branch, use choose(). */
  next(): boolean {
    return this.choices().length === 1 && this.choose(0);
  }

  get canGoBack(): boolean {
    return this.route.length > 1 || (this.route.length > 0 && this.startChoices.length > 0);
  }

  back(): boolean {
    if (!this.canGoBack) return false;
    this.route.pop();
    this.via.pop();
    if (this.route.length) this.showCard(this.route[this.route.length - 1]!);
    this.changed();
    return true;
  }

  restart(): void {
    if (this.startChoices.length) {
      this.route = [];
      this.via = [];
      this.changed();
    } else if (this.route.length) {
      this.route = this.route.slice(0, 1);
      this.via = this.via.slice(0, 1);
      this.showCard(this.route[0]!);
      this.changed();
    }
  }

  /** Forget the route and take away the reader's highlight (if it's still showing). */
  stop(): void {
    if (!this.reading) return;
    this.route = [];
    this.via = [];
    this.startChoices = [];
    if (this.store.highlightOwner === OWNER) this.store.clearHighlight();
    this.changed(false);
  }

  /** The board changed: the route ends at the first step whose card is gone, or that the
   *  board no longer joins to the one before (its arrow was deleted or reversed). The
   *  route's highlight is redrawn only if it's still the one showing: another highlight,
   *  or one cleared with Esc, stays as it is. */
  refresh(): void {
    this.seen = this.store.state;
    if (!this.reading) return;
    const graph = this.graph;
    let keep = 0;
    while (keep < this.route.length && this.store.card(this.route[keep]!)) {
      if (keep && !(graph.succ.get(this.route[keep - 1]!) ?? []).includes(this.route[keep]!)) break;
      keep++;
    }
    this.route = this.route.slice(0, keep);
    this.via = this.via.slice(0, keep);
    this.startChoices = this.startChoices.filter((id) => this.store.card(id));
    this.changed(this.store.highlightOwner === OWNER);
  }

  /** As lists show it: a repeated title names its group. */
  title(id: string): string {
    const card = this.store.card(id);
    if (!card) return "?";
    return titleLabels(this.store.state.cards).get(id) || card.title || "Untitled";
  }

  /** Where the reading stands: the end, a branch, or nothing to say. */
  endNote(): string {
    const n = this.choices().length;
    if (!n) return "The end of this path: no arrows lead on from here.";
    if (n > 1 && this.route.length) return `The story branches here (${n} ways on).`;
    return "";
  }

  private arrowLabel(id: string): string {
    const conn = this.store.state.connections.find((c) => c.id === id);
    return conn ? conn.label.split(/\s+/).filter(Boolean).join(" ") : "";
  }

  private ordered(ids: Iterable<string>): string[] {
    const order = this.graph.arrowOrder();
    const rank = new Map(order.map((id, n) => [id, n]));
    return [...ids].sort((a, b) => (rank.get(a) ?? order.length) - (rank.get(b) ?? order.length));
  }

  private stepTo(id: string, label: string): void {
    this.route.push(id);
    this.via.push(label);
    this.showCard(id);
    this.changed();
  }

  private changed(rehighlight = true): void {
    if (rehighlight) this.highlightRoute();
    this.version++;
    for (const fn of this.listeners) fn();
  }

  private highlightRoute(): void {
    const graph = this.graph;
    const ids = new Set([...this.route, ...(this.route.length ? [] : this.startChoices)]);
    if (!ids.size) return;
    const arrows = new Set<string>();
    for (let i = 1; i < this.route.length; i++) for (const a of graph.stepArrows(this.route[i - 1]!, this.route[i]!)) arrows.add(a);
    for (const a of graph.markersFor(this.route)) arrows.add(a);
    const n = this.route.length;
    this.seen = this.store.state;
    this.store.setHighlight(ids, arrows, n ? this.route[n - 1]! : null, n ? `Reading a path · step ${n}` : "Reading a path", OWNER);
  }
}
