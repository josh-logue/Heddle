// Auto-arrange for a group's cards: a port of heddle/layout.py, whose docstring describes
// the layout (chains in rows, branches stacked, loose cards in a block, colour lanes,
// room for arrow labels, row limits). Sizes come in as input, so results can be compared
// exactly with the desktop app's.

import { longestPathLayers } from "./graph.ts";
import { sortedBy } from "./pystr.ts";

export const H_GAP = 70;
export const V_GAP = 30;
export const ROW_GAP = 50;
export const SAME_SIZE = 30;
export const LABEL_MARGIN = 48;

export interface Node {
  id: string;
  w: number;
  h: number;
  /** Current position, used only to keep a stable, familiar order. */
  x: number;
  y: number;
  /** Lane key when arranging by color. */
  color: string;
  /** A nested group (kept apart from plain cards when unconnected). */
  group: boolean;
}

export function makeNode(id: string, w: number, h: number, extra: Partial<Node> = {}): Node {
  return { id, w, h, x: 0, y: 0, color: "", group: false, ...extra };
}

export type Positions = Map<string, [number, number]>;
/** Arrow label sizes keyed "source\0target": [width, height]. */
export type LabelSizes = ReadonlyMap<string, readonly [number, number]>;

export const edgeKey = (s: string, t: string) => `${s}\u0000${t}`;

export interface ArrangeOptions {
  byColor?: boolean;
  vertical?: boolean;
  grid?: boolean;
  labels?: LabelSizes | null;
  wrap?: number;
}

/** {node id: [x, y]} top-left positions relative to (0, 0). See heddle/layout.arrange. */
export function arrange(nodes: readonly Node[], edges: readonly (readonly [string, string])[],
                        opts: ArrangeOptions = {}): Positions {
  const { byColor = false, vertical = false, grid = false, wrap = 0 } = opts;
  const labels = opts.labels ?? new Map();
  const rank = readingRank(nodes); // on the board as it is, whichever way it's laid out
  if (vertical) {
    // Lay out the transposed problem horizontally, then swap the axes back.
    const flipped = nodes.map((n) => ({ ...n, w: n.h, h: n.w, x: n.y, y: n.x }));
    const room = new Map([...labels].map(([k, [, h]]) => [k, h]));
    const placed = arrangeH(flipped, edges, byColor, grid, rank, room, wrap);
    return new Map([...placed].map(([i, [x, y]]) => [i, [y, x]]));
  }
  const room = new Map([...labels].map(([k, [w]]) => [k, w]));
  return arrangeH(nodes, edges, byColor, grid, rank, room, wrap);
}

/** Each node's place in reading order, as you'd read the board by eye: in lines from
 *  top to bottom, each line left to right. Nodes share a line when they overlap
 *  vertically by at least half the smaller height (of the node, or of the line so far). */
export function readingRank(nodes: readonly Node[]): Map<string, number> {
  const lines: { top: number; bottom: number; members: Node[] }[] = [];
  for (const n of sortedBy(nodes, (n) => [n.y, n.x])) {
    const top = n.y;
    const bottom = n.y + n.h;
    const line = lines[lines.length - 1];
    if (line) {
      const overlap = Math.min(line.bottom, bottom) - Math.max(line.top, top);
      if (overlap >= 0.5 * Math.min(n.h, line.bottom - line.top) && overlap > 0) {
        line.top = Math.min(line.top, top);
        line.bottom = Math.max(line.bottom, bottom);
        line.members.push(n);
        continue;
      }
    }
    lines.push({ top, bottom, members: [n] });
  }
  const order = lines.flatMap((l) => sortedBy(l.members, (n) => [n.x, n.y]).map((n) => n.id));
  return new Map(order.map((i, k) => [i, k]));
}

function arrangeH(nodes: readonly Node[], edges: readonly (readonly [string, string])[], byColor: boolean,
                  grid: boolean, rankIn: Map<string, number>, room: Map<string, number>, wrap: number): Positions {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const succ = new Map<string, string[]>(nodes.map((n) => [n.id, []]));
  // Neighbours in the order the arrows were given (a Set keeps insertion order).
  const adj = new Map<string, Set<string>>(nodes.map((n) => [n.id, new Set()]));
  for (const [s, t] of edges) {
    if (byId.has(s) && byId.has(t) && s !== t && !succ.get(s)!.includes(t)) {
      succ.get(s)!.push(t);
      adj.get(s)!.add(t);
      adj.get(t)!.add(s);
    }
  }

  let components: string[][] = [];
  const seen = new Set<string>();
  for (const n of sortedBy(nodes, (n) => [n.y, n.x])) {
    if (seen.has(n.id)) continue;
    seen.add(n.id);
    const stack = [n.id];
    const comp: string[] = [];
    while (stack.length) {
      const u = stack.pop()!;
      comp.push(u);
      for (const v of adj.get(u)!) {
        if (!seen.has(v)) {
          seen.add(v);
          stack.push(v);
        }
      }
    }
    components.push(comp);
  }
  components = sortedBy(components, (comp) => Math.min(...comp.map((i) => rankIn.get(i)!)));

  const loose = sortedBy(components.filter((c) => c.length === 1).map((c) => c[0]!), (i) => rankIn.get(i)!);
  const chains = components.filter((c) => c.length > 1);

  const positions: Positions = new Map();
  let rowTop = 0;
  for (const comp of chains) {
    const layer = longestPathLayers(comp, succ, (i) => [byId.get(i)!.x, byId.get(i)!.y]);
    const rank = orderInLayers(comp, layer, succ, byId);
    const gaps = stepGaps(comp, layer, succ, room);
    const steps = sortedBy(new Set(layer.values()), (k) => k);
    if (byColor) {
      const lanes = laneOrder(comp, layer, byId);
      for (const row of rows(steps, wrap)) {
        const inRow = new Set(row);
        const part = comp.filter((i) => inRow.has(layer.get(i)!));
        rowTop += placeColorLanes(part, layer, rank, byId, positions, rowTop, gaps, lanes) + ROW_GAP;
      }
      continue;
    }
    const columns = new Map<number, string[]>();
    for (const i of sortedBy(comp, (i) => rank.get(i)!)) pushTo(columns, layer.get(i)!, i);
    const colW = new Map<number, number>();
    const colH = new Map<number, number>();
    for (const [k, ids] of columns) {
      colW.set(k, Math.max(...ids.map((i) => byId.get(i)!.w)));
      colH.set(k, sum(ids.map((i) => byId.get(i)!.h)) + V_GAP * (ids.length - 1));
    }
    for (const row of rows(sortedBy(columns.keys(), (k) => k), wrap)) {
      const rowH = Math.max(...row.map((k) => colH.get(k)!));
      let x = 0;
      for (const k of row) {
        let y = rowTop + (rowH - colH.get(k)!) / 2;
        for (const i of columns.get(k)!) {
          positions.set(i, [x, y]);
          y += byId.get(i)!.h + V_GAP;
        }
        x += colW.get(k)! + (gaps.get(k) ?? H_GAP);
      }
      rowTop += rowH + ROW_GAP;
    }
  }
  if (loose.length) placeLoose(loose, byId, positions, rowTop, grid, byColor, wrap);
  return positions;
}

/** Python's sum(): left to right, so float results match exactly. */
function sum(values: readonly number[]): number {
  let total = 0;
  for (const v of values) total += v;
  return total;
}

/** The chain's steps split into rows of `wrap` (all in one row when wrap is 0). */
function rows(steps: readonly number[], wrap: number): number[][] {
  if (wrap <= 0) return [[...steps]];
  const out: number[][] = [];
  for (let k = 0; k < steps.length; k += wrap) out.push(steps.slice(k, k + wrap));
  return out;
}

/** How many unconnected cards go in a row: all of them, a roughly square number with
 *  grid, and never more than the row limit. */
function perRow(n: number, grid: boolean, wrap: number): number {
  const count = grid ? Math.ceil(Math.sqrt(n)) : n;
  return wrap > 0 ? Math.min(count, wrap) : count;
}

/** Unconnected cards: one row (or a grid) below the chains, wrapping after `wrap`
 *  cards. With byColor, each color gets its own block, in order of first appearance. */
function placeLoose(ids: readonly string[], byId: Map<string, Node>, positions: Positions, top: number,
                    grid: boolean, byColor: boolean, wrap: number): void {
  const groups = new Map<string, string[]>();
  for (const i of ids) pushTo(groups, byColor ? byId.get(i)!.color : "", i);
  let y = top;
  for (const group of groups.values()) {
    const isGroup = (i: string) => byId.get(i)!.group;
    const mixed = group.some(isGroup) && !group.every(isGroup);
    y += (mixed ? placeMixed : placeBlock)(group, byId, positions, y, grid, wrap) + V_GAP;
  }
}

type Placed = [Map<string, [number, number]>, number, number];

/** Unconnected groups and plain cards together: the groups in a row, the cards under the
 *  groups from some k on (the earliest k giving the smallest block, give or take a
 *  SAME_SIZE-deep strip). Returns the block's height. See heddle/layout._place_mixed. */
function placeMixed(ids: readonly string[], byId: Map<string, Node>, positions: Positions, top: number,
                    grid: boolean, wrap: number): number {
  const groups = ids.filter((i) => byId.get(i)!.group);
  const cards = ids.filter((i) => !byId.get(i)!.group);
  const xs: number[] = [];
  let x = 0;
  for (const i of groups) {
    xs.push(x);
    x += byId.get(i)!.w + V_GAP;
  }
  const rowEnd = x - V_GAP;
  const per = perRow(cards.length, grid, wrap);
  const widest = Math.max(...cards.map((i) => byId.get(i)!.w));
  const tallest = Math.max(...groups.map((i) => byId.get(i)!.h));

  const cardsFrom = (k: number): Placed | null => {
    const left = xs[k]!;
    if (rowEnd - left < widest) return null; // too narrow for some card
    let y = top + Math.max(...groups.slice(k).map((i) => byId.get(i)!.h)) + V_GAP;
    const placed = new Map<string, [number, number]>();
    let cx = left;
    let rowH = 0;
    let inRow = 0;
    for (const i of cards) {
      const n = byId.get(i)!;
      if (inRow && (cx + n.w > rowEnd || inRow >= per)) {
        cx = left;
        y = y + rowH + V_GAP;
        rowH = 0;
        inRow = 0;
      }
      placed.set(i, [cx, y]);
      cx += n.w + V_GAP;
      rowH = Math.max(rowH, n.h);
      inRow++;
    }
    const right = Math.max(...[...placed].map(([i, [px]]) => px + byId.get(i)!.w));
    const bottom = Math.max(...[...placed].map(([i, [, py]]) => py + byId.get(i)!.h));
    return [placed, Math.max(rowEnd, right), Math.max(bottom, top + tallest) - top];
  };

  let options: [number, Placed][] = [];
  for (let k = 0; k < groups.length; k++) {
    const o = cardsFrom(k);
    if (o !== null) options.push([k, o]);
  }
  if (!options.length) options = [[0, cardsAfter(groups, cards, byId, xs, top)]];
  const smallest = Math.min(...options.map(([, o]) => o[1] * o[2]));
  const slack = SAME_SIZE * Math.max(...options.map(([, o]) => o[1]));
  const [, [placed, , height]] = options.find(([, o]) => o[1] * o[2] <= smallest + slack)!;
  groups.forEach((i, k) => positions.set(i, [xs[k]!, top]));
  for (const [i, p] of placed) positions.set(i, p);
  return height;
}

/** Fallback (a card wider than the whole groups' row): the cards in a row under it. */
function cardsAfter(groups: readonly string[], cards: readonly string[], byId: Map<string, Node>,
                    xs: readonly number[], top: number): Placed {
  const y = top + Math.max(...groups.map((i) => byId.get(i)!.h)) + V_GAP;
  const placed = new Map<string, [number, number]>();
  let x = 0;
  for (const i of cards) {
    placed.set(i, [x, y]);
    x += byId.get(i)!.w + V_GAP;
  }
  const width = Math.max(xs[xs.length - 1]! + byId.get(groups[groups.length - 1]!)!.w, x - V_GAP);
  return [placed, width, y + Math.max(...cards.map((i) => byId.get(i)!.h)) - top];
}

/** Lay ids out in rows (all in one row unless grid or a row limit), aligned in columns;
 *  returns the block's height. */
function placeBlock(ids: readonly string[], byId: Map<string, Node>, positions: Positions, top: number,
                    grid: boolean, wrap: number): number {
  const cols = perRow(ids.length, grid, wrap);
  const blockRows: string[][] = [];
  for (let k = 0; k < ids.length; k += cols) blockRows.push(ids.slice(k, k + cols));
  const colW: number[] = [];
  for (let c = 0; c < cols; c++) {
    colW.push(Math.max(...blockRows.filter((r) => c < r.length).map((r) => byId.get(r[c]!)!.w)));
  }
  let y = top;
  for (const row of blockRows) {
    let x = 0;
    row.forEach((i, c) => {
      positions.set(i, [x, y]);
      x += colW[c]! + V_GAP;
    });
    y += Math.max(...row.map((i) => byId.get(i)!.h)) + V_GAP;
  }
  return y - V_GAP - top;
}

/** Order the cards within each step column to reduce crossed arrows: start from the
 *  current top-to-bottom order, then sweep forward and backward sorting by the average
 *  position of each card's neighbours (barycentre). A new order is kept only if it
 *  strictly reduces crossings. Returns each card's index within its column. */
function orderInLayers(comp: readonly string[], layer: Map<string, number>, succ: Map<string, string[]>,
                       byId: Map<string, Node>, sweeps = 4): Map<string, number> {
  const members = new Set(comp);
  const nbrs = new Map<string, Set<string>>(comp.map((i) => [i, new Set()]));
  const edges: [string, string][] = [];
  for (const u of comp) {
    for (const v of succ.get(u)!) {
      if (members.has(v) && v !== u && layer.get(u) !== layer.get(v)) {
        nbrs.get(u)!.add(v);
        nbrs.get(v)!.add(u);
        edges.push(layer.get(u)! < layer.get(v)! ? [u, v] : [v, u]);
      }
    }
  }
  const columns = new Map<number, string[]>();
  for (const i of sortedBy(comp, (i) => [byId.get(i)!.y, byId.get(i)!.x])) pushTo(columns, layer.get(i)!, i);
  const keys = sortedBy(columns.keys(), (k) => k);
  const pos = new Map<string, number>();
  for (const col of columns.values()) col.forEach((i, k) => pos.set(i, k));

  const crossings = (): number => {
    // Two arrows between the same pair of columns cross when their ends are in opposite
    // order on the two sides.
    const byPair = new Map<string, [number, number][]>();
    for (const [a, b] of edges) pushTo(byPair, `${layer.get(a)},${layer.get(b)}`, [pos.get(a)!, pos.get(b)!]);
    let total = 0;
    for (const ends of byPair.values()) {
      for (let k = 0; k < ends.length; k++) {
        const [a1, b1] = ends[k]!;
        for (let m = k + 1; m < ends.length; m++) {
          const [a2, b2] = ends[m]!;
          if ((a1 - a2) * (b1 - b2) < 0) total++;
        }
      }
    }
    return total;
  };

  let best = new Map(pos);
  let bestCrossings = crossings();
  for (let sweep = 0; sweep < (bestCrossings ? sweeps : 0); sweep++) {
    const forward = sweep % 2 === 0;
    for (const colKey of forward ? keys.slice(1) : keys.slice(0, -1).reverse()) {
      const col = columns.get(colKey)!;
      const barycentre = (i: string): number => {
        const ref = [...nbrs.get(i)!].filter((n) => (forward ? layer.get(n)! < colKey : layer.get(n)! > colKey))
          .map((n) => pos.get(n)!);
        return ref.length ? sum(ref) / ref.length : pos.get(i)!;
      };
      const order = new Map(col.map((i) => [i, [barycentre(i), pos.get(i)!] as const]));
      const sortedCol = sortedBy(col, (i) => order.get(i)!);
      col.splice(0, col.length, ...sortedCol);
      col.forEach((i, k) => pos.set(i, k));
    }
    const c = crossings();
    if (c < bestCrossings) {
      best = new Map(pos);
      bestCrossings = c;
    }
    if (bestCrossings === 0) break;
  }
  return best;
}

/** {step k: gap after it} where an arrow between steps k and k + 1 has a label that
 *  needs more than the usual H_GAP (with LABEL_MARGIN around it). */
function stepGaps(comp: readonly string[], layer: Map<string, number>, succ: Map<string, string[]>,
                  room: Map<string, number>): Map<number, number> {
  const gaps = new Map<number, number>();
  for (const s of comp) {
    for (const t of succ.get(s)!) {
      const need = room.get(edgeKey(s, t)) ?? 0;
      const ls = layer.get(s)!;
      const lt = layer.get(t) ?? ls;
      const a = Math.min(ls, lt);
      const b = Math.max(ls, lt);
      if (need > 0 && b - a === 1) gaps.set(a, Math.max(gaps.get(a) ?? H_GAP, need + LABEL_MARGIN));
    }
  }
  return gaps;
}

/** A chain's colors in order of first appearance along it: its lanes, top to bottom. */
function laneOrder(comp: readonly string[], layer: Map<string, number>, byId: Map<string, Node>): string[] {
  const firstSeen = new Map<string, [number, number]>();
  for (const i of comp) {
    const key: [number, number] = [layer.get(i)!, byId.get(i)!.y];
    const c = byId.get(i)!.color;
    const old = firstSeen.get(c);
    if (old === undefined || key[0] < old[0] || (key[0] === old[0] && key[1] < old[1])) firstSeen.set(c, key);
  }
  return sortedBy(firstSeen.keys(), (c) => firstSeen.get(c)!);
}

/** Place (one row of) a chain with a lane per color, in the chain's lane order, so a
 *  color keeps its place on every row; a lane with no cards in this row takes no room.
 *  Returns the row's height. */
function placeColorLanes(comp: readonly string[], layer: Map<string, number>, rank: Map<string, number>,
                         byId: Map<string, Node>, positions: Positions, top: number,
                         gaps: Map<number, number>, allLanes: readonly string[]): number {
  const lanes = allLanes.filter((c) => comp.some((i) => byId.get(i)!.color === c));
  const laneOf = new Map(lanes.map((c, n) => [c, n]));
  const cells = new Map<string, { lane: number; col: number; ids: string[] }>();
  for (const i of sortedBy(comp, (i) => rank.get(i)!)) {
    const lane = laneOf.get(byId.get(i)!.color)!;
    const col = layer.get(i)!;
    const k = `${lane},${col}`;
    const cell = cells.get(k);
    if (cell) cell.ids.push(i);
    else cells.set(k, { lane, col, ids: [i] });
  }
  const cellH = (ids: string[]) => sum(ids.map((i) => byId.get(i)!.h)) + V_GAP * (ids.length - 1);
  const colW = new Map<number, number>();
  const laneH = new Map<number, number>();
  for (const { lane, col, ids } of cells.values()) {
    colW.set(col, Math.max(colW.get(col) ?? 0, Math.max(...ids.map((i) => byId.get(i)!.w))));
    laneH.set(lane, Math.max(laneH.get(lane) ?? 0, cellH(ids)));
  }
  const colX = new Map<number, number>();
  let x = 0;
  for (const col of sortedBy(colW.keys(), (k) => k)) {
    colX.set(col, x);
    x += colW.get(col)! + (gaps.get(col) ?? H_GAP);
  }
  const laneY = new Map<number, number>();
  let y = top;
  for (let lane = 0; lane < lanes.length; lane++) {
    laneY.set(lane, y);
    y += laneH.get(lane)! + V_GAP;
  }
  for (const { lane, col, ids } of cells.values()) {
    let cy = laneY.get(lane)!; // top-aligned so a lane reads as a clean row
    for (const i of ids) {
      positions.set(i, [colX.get(col)!, cy]);
      cy += byId.get(i)!.h + V_GAP;
    }
  }
  return y - V_GAP - top;
}

function pushTo<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}
