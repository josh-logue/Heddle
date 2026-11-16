// The story as a graph: what comes before or after what. A port of heddle/graph.py,
// whose docstring explains how groups stand for their contents (entry and exit cards,
// first and last-card marker arrows).
//
// Everything keyed by card id is a Map and keeps Python's dict order, since several
// answers (nodes, arrow order ties, routes) depend on the order cards were listed in.

import { KIND_GROUP, KIND_STRAND, type CardData, type ConnectionData } from "./model.ts";
import { casefold, maxBy, minBy, sortedBy, sortedStrings, strip, type SortKey } from "./pystr.ts";

type Succ = ReadonlyMap<string, readonly string[]>;

/** Step number for each node of a connected component: the length of the longest arrow
 *  path reaching it, after dropping back-edges (found by DFS, so cycles are tolerated).
 *  `orderKey` makes the result stable: DFS starts from sources first, in that order.
 *  Used by auto-arrange and by arrowOrder(). */
export function longestPathLayers(
  comp: readonly string[], succ: Succ, orderKey: (id: string) => SortKey,
): Map<string, number> {
  const members = new Set(comp);
  const order = sortedBy(comp, orderKey);
  const indeg = new Map(comp.map((i) => [i, 0]));
  for (const u of comp) {
    for (const v of succ.get(u) ?? []) if (members.has(v)) indeg.set(v, indeg.get(v)! + 1);
  }

  const dag = new Map<string, string[]>(comp.map((i) => [i, []]));
  const state = new Map<string, 1 | 2>(); // 1 = on stack, 2 = done
  const roots = [...order.filter((i) => indeg.get(i) === 0), ...order]; // sources first
  for (const root of roots) {
    if (state.has(root)) continue;
    state.set(root, 1);
    const stack: [string, number][] = [[root, 0]];
    while (stack.length) {
      const top = stack[stack.length - 1]!;
      const [u, k] = top;
      const next = succ.get(u) ?? [];
      if (k >= next.length) {
        state.set(u, 2);
        stack.pop();
        continue;
      }
      top[1] = k + 1;
      const v = next[k]!;
      if (!members.has(v) || state.get(v) === 1) continue; // outside, or a back-edge
      dag.get(u)!.push(v);
      if (!state.has(v)) {
        state.set(v, 1);
        stack.push([v, 0]);
      }
    }
  }

  const remaining = new Map(comp.map((i) => [i, 0]));
  for (const u of comp) for (const v of dag.get(u)!) remaining.set(v, remaining.get(v)! + 1);
  const layer = new Map(comp.map((i) => [i, 0]));
  const queue = order.filter((i) => remaining.get(i) === 0);
  for (let q = 0; q < queue.length; q++) {
    const u = queue[q]!;
    for (const v of dag.get(u)!) {
      layer.set(v, Math.max(layer.get(v)!, layer.get(u)! + 1));
      remaining.set(v, remaining.get(v)! - 1);
      if (remaining.get(v) === 0) queue.push(v);
    }
  }
  return layer;
}

export interface PathCount {
  /** Distinct start-to-end routes (each cycle walked at most once). Exact up to 2^53. */
  count: number;
  /** If true, looping round a cycle allows more. */
  has_cycles: boolean;
}

/** Joins a loop's card ids (sorted) into one stop of a route key. */
export const LOOP_JOIN = "+";

/** One way through the story from a start to an end. Each stop is a single card, or a
 *  loop's cards in story order (a loop is one stop, as when counting). */
export class Route {
  private keyCache: string[] | null = null;

  constructor(readonly stops: readonly (readonly string[])[]) {}

  /** Identifies the route across edits: a stop's card id, or a loop's ids sorted and
   *  joined with LOOP_JOIN. */
  get key(): string[] {
    if (this.keyCache === null) {
      this.keyCache = this.stops.map((s) => (s.length === 1 ? s[0]! : sortedStrings(s).join(LOOP_JOIN)));
    }
    return this.keyCache;
  }

  get cards(): string[] {
    return this.stops.flat();
  }

  get hasLoop(): boolean {
    return this.stops.some((s) => s.length > 1);
  }
}

const pairKey = (a: string, b: string) => `${a}\u0000${b}`;

export class StoryGraph {
  readonly cards: Map<string, CardData>;
  readonly members = new Map<string, string[]>();
  /** Cards outside the story, everything inside such a group, strand cards, and groups
   *  holding nothing but outside cards. */
  readonly outside = new Set<string>();
  /** Arrows between cards that both exist and are in the story, without duplicates or
   *  self-loops: {arrow id: [source, target]}. */
  readonly arrows = new Map<string, readonly [string, string]>();
  readonly firstMarks = new Map<string, string[]>();
  readonly lastMarks = new Map<string, string[]>();
  readonly boundaryArrows = new Set<string>();
  /** Each arrow's flow ends: cards it leaves from and cards it arrives at. */
  readonly arrowEnds = new Map<string, readonly [readonly string[], readonly string[]]>();
  readonly succ = new Map<string, string[]>();
  readonly pred = new Map<string, string[]>();

  private readonly orderCache = new Map<string, readonly string[]>();
  private readonly entriesCache = new Map<string, string[]>();
  private readonly exitsCache = new Map<string, string[]>();
  private readonly stepArrowsMap = new Map<string, string[]>();
  private routeCache: RouteParts | null = null;

  constructor(cards: Iterable<CardData>, connections: Iterable<ConnectionData>) {
    this.cards = new Map();
    for (const c of cards) this.cards.set(c.id, c);
    for (const c of this.cards.values()) {
      const p = c.parent;
      if (p && p !== c.id && this.cards.get(p)?.kind === KIND_GROUP) {
        const list = this.members.get(p);
        if (list) list.push(c.id);
        else this.members.set(p, [c.id]);
      }
    }
    for (const [cid, c] of this.cards) {
      if (c.outside_story || c.kind === KIND_STRAND) {
        this.outside.add(cid);
        for (const i of this.contents(cid)) this.outside.add(i);
      }
    }
    let changed = true;
    while (changed) {
      changed = false;
      for (const [gid, members] of this.members) {
        if (!this.outside.has(gid) && members.length && members.every((m) => this.outside.has(m))) {
          this.outside.add(gid);
          changed = true;
        }
      }
    }
    const seenPairs = new Set<string>();
    for (const conn of connections) {
      const { source: s, target: t } = conn;
      const pair = pairKey(s, t);
      if (this.cards.has(s) && this.cards.has(t) && !this.outside.has(s) && !this.outside.has(t)
          && s !== t && !seenPairs.has(pair)) {
        seenPairs.add(pair);
        this.arrows.set(conn.id, [s, t]);
      }
    }
    for (const [cid, [s, t]] of this.arrows) {
      if (this.isInside(t, s)) {
        pushTo(this.firstMarks, s, t);
        this.boundaryArrows.add(cid);
      } else if (this.isInside(s, t)) {
        pushTo(this.lastMarks, t, s);
        this.boundaryArrows.add(cid);
      }
    }
    for (const i of this.nodes()) {
      this.succ.set(i, []);
      this.pred.set(i, []);
    }
    for (const [cid, [s, t]] of this.arrows) {
      if (this.boundaryArrows.has(cid)) {
        // A marker, not a step: it lights up along with the card it marks.
        const inner = t !== s && this.isInside(t, s) ? this.entryCards(t) : this.exitCards(s);
        this.arrowEnds.set(cid, [inner, inner]);
        continue;
      }
      const froms = this.exitCards(s);
      const tos = this.entryCards(t);
      this.arrowEnds.set(cid, [froms, tos]);
      for (const a of froms) {
        for (const b of tos) {
          if (a === b) continue;
          pushTo(this.stepArrowsMap, pairKey(a, b), cid);
          const next = this.succ.get(a)!;
          if (!next.includes(b)) {
            next.push(b);
            this.pred.get(b)!.push(a);
          }
        }
      }
    }
  }

  // ----- structure ---------------------------------------------------------------------

  /** A group with cards in it: it stands for its contents rather than being a stop. */
  isContainer(cardId: string): boolean {
    return (this.members.get(cardId)?.length ?? 0) > 0;
  }

  /** The stops a story passes through: cards, plus empty groups. */
  nodes(): string[] {
    return [...this.cards.keys()].filter((i) => !this.isContainer(i));
  }

  /** Every card and group inside a group, at any depth. */
  contents(groupId: string): Set<string> {
    const out = new Set<string>();
    const stack = [groupId];
    while (stack.length) {
      for (const m of this.members.get(stack.pop()!) ?? []) {
        if (!out.has(m)) {
          out.add(m);
          stack.push(m);
        }
      }
    }
    return out;
  }

  /** Groups holding any of `ids`, at any depth. */
  containersOf(ids: Iterable<string>): Set<string> {
    const out = new Set<string>();
    for (const i of ids) {
      const seen = new Set([i]);
      let p = this.cards.get(i)?.parent ?? "";
      while (p && this.cards.has(p) && !seen.has(p)) {
        seen.add(p);
        out.add(p);
        p = this.cards.get(p)!.parent;
      }
    }
    return out;
  }

  /** Is cardId inside groupId, at any depth? */
  isInside(cardId: string, groupId: string): boolean {
    let cur = this.cards.get(cardId)?.parent ?? "";
    const seen = new Set([cardId]);
    while (cur && this.cards.has(cur) && !seen.has(cur)) {
      if (cur === groupId) return true;
      seen.add(cur);
      cur = this.cards.get(cur)!.parent;
    }
    return false;
  }

  /** The cards a group's first-card arrows point to (empty: none marked). */
  firstCards(groupId: string): string[] {
    return [...(this.firstMarks.get(groupId) ?? [])];
  }

  /** The cards with last-card arrows to the group (empty: none marked). */
  lastCards(groupId: string): string[] {
    return [...(this.lastMarks.get(groupId) ?? [])];
  }

  /** The member of `groupId` that is `cardId` or holds it; null if outside. */
  private directMember(cardId: string, groupId: string): string | null {
    let cur = cardId;
    const seen = new Set<string>();
    while (cur && this.cards.has(cur) && !seen.has(cur)) {
      seen.add(cur);
      if (this.cards.get(cur)!.parent === groupId) return cur;
      cur = this.cards.get(cur)!.parent;
    }
    return null;
  }

  /** The group's marked first (entries) / last (exits) cards if it has any; otherwise
   *  the members with no arrow from (entries) / to (exits) another member, the arrows of
   *  nested groups counting for the nested group. */
  private boundary(groupId: string, entries: boolean): string[] {
    const marked = (entries ? this.firstMarks : this.lastMarks).get(groupId);
    if (marked?.length) return [...marked];
    // Cards outside the story are never a group's first or last cards.
    const members = (this.members.get(groupId) ?? []).filter((m) => !this.outside.has(m));
    const linked = new Set<string>();
    for (const [cid, [s, t]] of this.arrows) {
      if (this.boundaryArrows.has(cid)) continue;
      const ms = this.directMember(s, groupId);
      const mt = this.directMember(t, groupId);
      if (ms !== null && mt !== null && ms !== mt) linked.add(entries ? mt : ms);
    }
    const out = members.filter((m) => !linked.has(m));
    if (!out.length && members.length) {
      // Every member is led to (from) by another: the group is one big loop. Enter at
      // its top-left card and leave from its bottom-right one.
      out.push((entries ? minBy : maxBy)(members, (i) => this.position(i)));
    }
    return out;
  }

  private expand(cardId: string, entries: boolean, cache: Map<string, string[]>,
                 guard: ReadonlySet<string> = new Set()): string[] {
    if (!this.isContainer(cardId) || guard.has(cardId)) {
      return this.isContainer(cardId) ? [] : [cardId];
    }
    const hit = cache.get(cardId);
    if (hit) return hit;
    const out: string[] = [];
    const inner = new Set(guard).add(cardId);
    for (const m of this.boundary(cardId, entries)) {
      for (const c of this.expand(m, entries, cache, inner)) if (!out.includes(c)) out.push(c);
    }
    cache.set(cardId, out);
    return out;
  }

  /** Where an arrow into this card or group arrives (itself, if it's a stop). */
  entryCards(cardId: string): string[] {
    return this.expand(cardId, true, this.entriesCache);
  }

  /** Where an arrow out of this card or group leaves from (itself, if a stop). */
  exitCards(cardId: string): string[] {
    return this.expand(cardId, false, this.exitsCache);
  }

  // ----- reachability ------------------------------------------------------------------

  private walk(seeds: Iterable<string>, adj: Succ): Set<string> {
    const out = new Set<string>();
    const queue = [...seeds];
    for (let q = 0; q < queue.length; q++) {
      for (const v of adj.get(queue[q]!) ?? []) {
        if (!out.has(v)) {
          out.add(v);
          queue.push(v);
        }
      }
    }
    return out;
  }

  /** Every stop that can come after this card (or after a group's contents). The card
   *  itself is included only if a cycle leads back to it. */
  downstream(cardId: string): Set<string> {
    return this.walk(this.exitCards(cardId), this.succ);
  }

  /** Every stop that can come before this card (or before a group's contents). */
  upstream(cardId: string): Set<string> {
    return this.walk(this.entryCards(cardId), this.pred);
  }

  /** Arrows (connection ids) linking two of `ids`: one of the cards an arrow leaves from
   *  and one it arrives at must both be in the set. */
  arrowsWithin(ids: Iterable<string>): Set<string> {
    const set = new Set(ids);
    const out = new Set<string>();
    for (const [cid, [froms, tos]] of this.arrowEnds) {
      if (froms.some((i) => set.has(i)) && tos.some((i) => set.has(i))) out.add(cid);
    }
    return out;
  }

  // ----- characters --------------------------------------------------------------------

  private rankMap(): Map<string, number> {
    return new Map(this.arrowOrder().map((i, n) => [i, n]));
  }

  /** Stops whose characters include `name` (ignoring case), in story order. */
  featuring(name: string): string[] {
    const k = casefold(strip(name));
    const rank = this.rankMap();
    const found = this.nodes().filter((i) => !this.outside.has(i)
      && this.cards.get(i)!.characters.some((c) => casefold(c) === k));
    return sortedBy(found, (i) => rank.get(i)!);
  }

  /** {card id: characters that card introduces}. A card introduces a character when it
   *  features them and no card on any route leading to it does. Branches each get their
   *  own introduction; a card reached again round a loop doesn't count. Only cards on
   *  arrow chains take part. */
  introductions(): Map<string, string[]> {
    // Each loop is one step, so "featured somewhere before" passes forward along the
    // arrows in one pass, for every character at once as bits of a bigint.
    const linked = this.nodes().filter((i) => this.succ.get(i)!.length || this.pred.get(i)!.length);
    const comps = this.stronglyConnected();
    const compOf = new Map<string, number>();
    comps.forEach((comp, n) => comp.forEach((i) => compOf.set(i, n)));
    const bit = new Map<string, bigint>();
    const featured: bigint[] = comps.map(() => 0n);
    for (const i of linked) {
      for (const name of this.cards.get(i)!.characters) {
        const key = casefold(name);
        if (!bit.has(key)) bit.set(key, BigInt(bit.size));
        featured[compOf.get(i)!]! |= 1n << bit.get(key)!;
      }
    }
    const nextSteps: Set<number>[] = comps.map(() => new Set());
    const waiting: number[] = comps.map(() => 0);
    for (const [u, vs] of this.succ) {
      for (const v of vs) {
        const a = compOf.get(u)!;
        const b = compOf.get(v)!;
        if (a !== b && !nextSteps[a]!.has(b)) {
          nextSteps[a]!.add(b);
          waiting[b]!++;
        }
      }
    }
    const before: bigint[] = comps.map(() => 0n);
    const queue: number[] = [];
    for (let n = 0; n < comps.length; n++) if (waiting[n] === 0) queue.push(n);
    for (let q = 0; q < queue.length; q++) {
      const a = queue[q]!;
      const carry = before[a]! | featured[a]!;
      for (const b of nextSteps[a]!) {
        before[b]! |= carry;
        if (--waiting[b]! === 0) queue.push(b);
      }
    }

    const rank = this.rankMap();
    const claimed = new Set<string>(); // "loop:bit" already introduced
    const out = new Map<string, string[]>();
    for (const i of sortedBy(linked, (i) => rank.get(i)!)) {
      const n = compOf.get(i)!;
      for (const name of this.cards.get(i)!.characters) {
        const b = bit.get(casefold(name))!;
        if ((before[n]! >> b) & 1n) continue; // featured on a step leading here
        if (comps[n]!.length > 1) {
          const tag = `${n}:${b}`;
          if (claimed.has(tag)) continue; // an earlier card on this loop has them
          claimed.add(tag);
        }
        pushTo(out, i, name);
      }
    }
    // Each card lists its introductions in its own character order.
    for (const [c, names] of out) {
      const chars = this.cards.get(c)!.characters;
      const order = new Map(chars.map((n, k) => [casefold(n), k]));
      out.set(c, sortedBy(names, (n) => order.get(casefold(n)) ?? order.size));
    }
    return out;
  }

  /** The arrows (connection ids) that make the step from stop a to stop b. */
  stepArrows(a: string, b: string): string[] {
    return [...(this.stepArrowsMap.get(pairKey(a, b)) ?? [])];
  }

  /** First/last-card arrows marking any of these cards. */
  markersFor(ids: Iterable<string>): Set<string> {
    const set = new Set(ids);
    const out = new Set<string>();
    for (const cid of this.boundaryArrows) {
      if (this.arrowEnds.get(cid)![0].some((i) => set.has(i))) out.add(cid);
    }
    return out;
  }

  // ----- order -------------------------------------------------------------------------

  position(i: string): [number, number] {
    const c = this.cards.get(i)!;
    return [c.y, c.x];
  }

  /** Connected chains among `ids` (default: every stop), ignoring arrow direction, in
   *  reading order of their top-left card. */
  components(ids: Iterable<string> | null = null): string[][] {
    const wanted = ids === null ? null : new Set(ids);
    const pool = new Set(this.nodes().filter((i) => wanted === null || wanted.has(i)));
    const comps: string[][] = [];
    const seen = new Set<string>();
    for (const start of sortedBy(pool, (i) => this.position(i))) {
      if (seen.has(start)) continue;
      seen.add(start);
      const comp: string[] = [];
      const stack = [start];
      while (stack.length) {
        const u = stack.pop()!;
        comp.push(u);
        for (const v of [...this.succ.get(u)!, ...this.pred.get(u)!]) {
          if (pool.has(v) && !seen.has(v)) {
            seen.add(v);
            stack.push(v);
          }
        }
      }
      comps.push(comp);
    }
    return comps;
  }

  /** Stops in story order: chain by chain (in reading order), and within a chain by step
   *  along the arrows, then top-to-bottom, left-to-right for cards at the same step.
   *  Cards without arrows follow reading order. Cached: the graph never changes. */
  arrowOrder(ids: Iterable<string> | null = null): string[] {
    const list = ids === null ? null : [...ids];
    const key = list === null ? "" : "\u0001" + sortedStrings(new Set(list)).join("\u0000");
    const cached = this.orderCache.get(key);
    if (cached) return [...cached];
    const out: string[] = [];
    for (const comp of this.components(list)) {
      const members = new Set(comp);
      const sub = new Map(comp.map((u) => [u, this.succ.get(u)!.filter((v) => members.has(v))]));
      const layer = longestPathLayers(comp, sub, (i) => [this.cards.get(i)!.x, this.cards.get(i)!.y]);
      out.push(...sortedBy(comp, (i) => [layer.get(i)!, ...this.position(i)]));
    }
    this.orderCache.set(key, out);
    return [...out];
  }

  /** Every card, strand cards included, under the group it sits in ("" for the board
   *  itself), as the Outline export and the Card List show them. With `byStory`,
   *  siblings come in story order; otherwise in reading order of their top-left corners. */
  outline(byStory = true): Map<string, string[]> {
    const children = new Map<string, string[]>();
    for (const [cid, c] of this.cards) {
      const parent = this.cards.has(c.parent) && c.parent !== cid ? c.parent : "";
      pushTo(children, parent, cid);
    }
    let key: (cid: string) => SortKey;
    if (byStory) {
      const rank = this.rankMap();
      const unranked = rank.size;
      key = (cid) => {
        const ranks = [cid, ...this.contents(cid)].filter((i) => rank.has(i)).map((i) => rank.get(i)!);
        return [ranks.length ? Math.min(...ranks) : unranked, ...this.position(cid)];
      };
    } else {
      key = (cid) => this.position(cid);
    }
    for (const [parent, kids] of children) children.set(parent, sortedBy(kids, key));
    return children;
  }

  // ----- cycles and paths --------------------------------------------------------------

  /** Stops and arrows-between-them, limited to `ids` (default: everything). */
  private restricted(ids: Iterable<string> | null): [string[], Map<string, string[]>] {
    if (ids === null) return [this.nodes(), this.succ];
    const pool = new Set([...ids].filter((i) => this.succ.has(i)));
    const nodes = this.nodes().filter((i) => pool.has(i));
    return [nodes, new Map(nodes.map((u) => [u, this.succ.get(u)!.filter((v) => pool.has(v))]))];
  }

  /** Tarjan's algorithm, iteratively. Every stop (of `ids`, default all) is in exactly
   *  one component; only arrows between those stops count. */
  stronglyConnected(ids: Iterable<string> | null = null): string[][] {
    const [nodes, succ] = this.restricted(ids);
    const index = new Map<string, number>();
    const low = new Map<string, number>();
    const onStack = new Set<string>();
    const stack: string[] = [];
    const comps: string[][] = [];
    let counter = 0;
    for (const root of nodes) {
      if (index.has(root)) continue;
      const work: [string, number][] = [[root, 0]];
      index.set(root, counter);
      low.set(root, counter);
      counter++;
      stack.push(root);
      onStack.add(root);
      while (work.length) {
        const top = work[work.length - 1]!;
        const [u, k] = top;
        const next = succ.get(u)!;
        if (k < next.length) {
          top[1] = k + 1;
          const v = next[k]!;
          if (!index.has(v)) {
            index.set(v, counter);
            low.set(v, counter);
            counter++;
            stack.push(v);
            onStack.add(v);
            work.push([v, 0]);
          } else if (onStack.has(v)) {
            low.set(u, Math.min(low.get(u)!, index.get(v)!));
          }
          continue;
        }
        work.pop();
        if (work.length) {
          const parent = work[work.length - 1]![0];
          low.set(parent, Math.min(low.get(parent)!, low.get(u)!));
        }
        if (low.get(u) === index.get(u)) {
          const comp: string[] = [];
          for (;;) {
            const w = stack.pop()!;
            onStack.delete(w);
            comp.push(w);
            if (w === u) break;
          }
          comps.push(comp);
        }
      }
    }
    return comps;
  }

  /** Groups of stops that loop back on each other, each in story order. */
  cycles(ids: Iterable<string> | null = null): string[][] {
    const rank = this.rankMap();
    const loops = this.stronglyConnected(ids).filter((c) => c.length > 1)
      .map((c) => sortedBy(c, (i) => rank.get(i)!));
    return sortedBy(loops, (c) => rank.get(c[0]!)!);
  }

  /** The stops with each loop squashed into one. */
  private condensation(ids: Iterable<string> | null = null): Condensation {
    const list = ids === null ? null : [...ids];
    const comps = this.stronglyConnected(list);
    const [, succ] = this.restricted(list);
    const compOf = new Map<string, number>();
    comps.forEach((c, n) => c.forEach((i) => compOf.set(i, n)));
    // Successors in ascending component order, as Python iterates a set of small ints.
    const csuccSets: Set<number>[] = comps.map(() => new Set());
    const indeg: number[] = comps.map(() => 0);
    for (const [u, vs] of succ) {
      for (const v of vs) {
        const a = compOf.get(u)!;
        const b = compOf.get(v)!;
        if (a !== b && !csuccSets[a]!.has(b)) {
          csuccSets[a]!.add(b);
          indeg[b]!++;
        }
      }
    }
    const csucc = csuccSets.map((s) => [...s].sort((x, y) => x - y));
    const linked = new Set<number>();
    csucc.forEach((next, n) => {
      if (next.length) linked.add(n);
      next.forEach((b) => linked.add(b));
    });
    return { comps, csucc, indeg, linked };
  }

  /** How many distinct routes lead from a start to an end (within `ids`, if given).
   *  Each cycle counts as a single stop; has_cycles says if any exist. */
  countPaths(ids: Iterable<string> | null = null): PathCount {
    const { comps, csucc, indeg, linked } = this.condensation(ids);
    const deg = [...indeg];
    const ways = csucc.map((_, n) => (deg[n] === 0 && linked.has(n) ? 1 : 0));
    const queue: number[] = [];
    for (let n = 0; n < csucc.length; n++) if (deg[n] === 0) queue.push(n);
    let total = 0;
    for (let q = 0; q < queue.length; q++) {
      const a = queue[q]!;
      if (!csucc[a]!.length && linked.has(a)) total += ways[a]!; // an end
      for (const b of csucc[a]!) {
        ways[b]! += ways[a]!;
        if (--deg[b]! === 0) queue.push(b);
      }
    }
    return { count: total, has_cycles: comps.some((c) => c.length > 1) };
  }

  // ----- listing routes ----------------------------------------------------------------

  private routeParts(): RouteParts {
    if (this.routeCache === null) {
      const { comps, csucc, indeg, linked } = this.condensation();
      const rank = this.rankMap();
      const stops = comps.map((c) => sortedBy(c, (i) => rank.get(i) ?? 0));
      const keys = stops.map((s) => (s.length === 1 ? s[0]! : sortedStrings(s).join(LOOP_JOIN)));
      this.routeCache = { stops, keys, csucc, indeg, linked };
    }
    return this.routeCache;
  }

  /** Every route from a start to an end, in reading order (the same routes countPaths
   *  counts), stopping after `limit` if given. Walked without recursion. */
  routes(limit: number | null = null): Route[] {
    const { stops, csucc, indeg, linked } = this.routeParts();
    const pos = (n: number) => this.position(stops[n]![0]!);
    const nexts = csucc.map((next) => sortedBy(next, pos));
    const sources = sortedBy(
      csucc.map((_, n) => n).filter((n) => indeg[n] === 0 && linked.has(n)), pos);
    const out: Route[] = [];
    for (const src of sources) {
      const path = [src];
      const stack: [number, number][] = [[src, 0]];
      while (stack.length) {
        const top = stack[stack.length - 1]!;
        const [node, i] = top;
        if (!nexts[node]!.length) {
          out.push(new Route(path.map((n) => stops[n]!)));
          if (limit !== null && out.length >= limit) return out;
        }
        if (i < nexts[node]!.length) {
          top[1] = i + 1;
          const child = nexts[node]![i]!;
          path.push(child);
          stack.push([child, 0]);
        } else {
          stack.pop();
          path.pop();
        }
      }
    }
    return out;
  }

  /** The route with this key, if it's still a complete start-to-end route. */
  routeForKey(key: readonly string[]): Route | null {
    const { stops, keys, csucc, indeg, linked } = this.routeParts();
    const index = new Map(keys.map((k, n) => [k, n]));
    const comps = key.map((k) => index.get(k));
    if (!comps.length || comps.some((c) => c === undefined)) return null;
    const ids = comps as number[];
    const first = ids[0]!;
    const last = ids[ids.length - 1]!;
    if (indeg[first] !== 0 || csucc[last]!.length || !linked.has(first) || !linked.has(last)) return null;
    for (let k = 0; k + 1 < ids.length; k++) if (!csucc[ids[k]!]!.includes(ids[k + 1]!)) return null;
    return new Route(ids.map((n) => stops[n]!));
  }

  /** The arrows a route walks: each step between stops, the arrows inside its loops, and
   *  the first/last-card markers of the groups it passes through. */
  routeArrows(route: Route): Set<string> {
    const out = new Set<string>();
    for (let k = 0; k + 1 < route.stops.length; k++) {
      for (const u of route.stops[k]!) {
        for (const v of route.stops[k + 1]!) for (const a of this.stepArrows(u, v)) out.add(a);
      }
    }
    for (const stop of route.stops) if (stop.length > 1) for (const a of this.arrowsWithin(stop)) out.add(a);
    for (const a of this.markersFor(route.cards)) out.add(a);
    return out;
  }
}

interface Condensation {
  comps: string[][];
  csucc: number[][];
  indeg: number[];
  linked: Set<number>;
}

interface RouteParts {
  stops: string[][];
  keys: string[];
  csucc: number[][];
  indeg: number[];
  linked: Set<number>;
}

function pushTo<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

