// Arrow geometry: a port of heddle/edge_item.py (straight, curved and "avoid cards"
// routing, first/last-card marker arrows, reverse pairs, labels) and of the scene's rule
// that arrows into a collapsed group meet its folded frame, merged and marked ×N.
//
// QPainterPath has no browser equivalent, so paths are kept as line and cubic segments,
// measured and sampled by flattening the curves.

import type { ConnectionData, Display } from "../core/model.ts";
import { collapseSpaces } from "../core/pystr.ts";
import {
  HEADER_HEIGHT, PORT_RADIUS, anchorRect, bodyRect, hasPort, type CardBox, type Rect, type Structure,
} from "./metrics.ts";
import { elide, lineHeight, type TextMeasurer } from "./text.ts";

export const ARROW_LEN = 13;
export const ARROW_HALF_W = 6.5;
export const REVERSE_OFFSET = 9;
export const MAX_LABEL_WIDTH = 160;
export const LOD_OVERVIEW = 0.3;
export const CURVE_MIN_PULL = 40;
export const AVOID_MARGIN = 14;
export const AVOID_SAMPLES = 32;
export const DASH_PATTERNS: Record<string, number[]> = { dashed: [4, 3], dotted: [0.01, 2.4] };

export type Point = readonly [number, number];
export type Segment = { kind: "L"; to: Point } | { kind: "C"; c1: Point; c2: Point; to: Point };

export class Path {
  readonly segments: Segment[] = [];
  private flat: Point[] | null = null;

  constructor(readonly start: Point) {}

  lineTo(p: Point): this {
    this.segments.push({ kind: "L", to: p });
    this.flat = null;
    return this;
  }

  cubicTo(c1: Point, c2: Point, to: Point): this {
    this.segments.push({ kind: "C", c1, c2, to });
    this.flat = null;
    return this;
  }

  /** The path as a polyline (curves cut into short straight pieces). */
  points(): Point[] {
    if (this.flat) return this.flat;
    const out: Point[] = [this.start];
    let p = this.start;
    for (const s of this.segments) {
      if (s.kind === "L") out.push(s.to);
      else {
        for (let k = 1; k <= 24; k++) out.push(bezier(p, s.c1, s.c2, s.to, k / 24));
      }
      p = s.to;
    }
    return (this.flat = out);
  }

  length(): number {
    const pts = this.points();
    let total = 0;
    for (let i = 1; i < pts.length; i++) total += dist(pts[i - 1]!, pts[i]!);
    return total;
  }

  /** The point `along` the way along the path (0 to its length). */
  pointAtLength(along: number): Point {
    const pts = this.points();
    let left = Math.max(0, along);
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1]!;
      const b = pts[i]!;
      const d = dist(a, b);
      if (left <= d || i === pts.length - 1) {
        const t = d ? Math.min(1, left / d) : 0;
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      }
      left -= d;
    }
    return pts[pts.length - 1]!;
  }

  /** The point at a share (0 to 1) of the way along, by length. */
  pointAtPercent(t: number): Point {
    return this.pointAtLength(t * this.length());
  }

  bounds(): Rect {
    const pts = this.points();
    let l = Infinity, tp = Infinity, r = -Infinity, b = -Infinity;
    for (const [x, y] of pts) {
      l = Math.min(l, x);
      tp = Math.min(tp, y);
      r = Math.max(r, x);
      b = Math.max(b, y);
    }
    return { x: l, y: tp, w: r - l, h: b - tp };
  }
}

function bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: number): Point {
  const u = 1 - t;
  const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
  return [a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]];
}

const dist = (a: Point, b: Point) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const center = (r: Rect): Point => [r.x + r.w / 2, r.y + r.h / 2];
const contains = (r: Rect, [x, y]: Point) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
const intersects = (a: Rect, b: Rect) => a.x <= b.x + b.w && b.x <= a.x + a.w && a.y <= b.y + b.h && b.y <= a.y + a.h;
const grow = (r: Rect, d: number): Rect => ({ x: r.x - d, y: r.y - d, w: r.w + 2 * d, h: r.h + 2 * d });

/** Where a ray from p (inside rect) in direction (ux, uy) leaves the rect. */
function exitPoint(rect: Rect, p: Point, ux: number, uy: number): Point {
  const ts: number[] = [];
  if (ux > 1e-9) ts.push((rect.x + rect.w - p[0]) / ux);
  else if (ux < -1e-9) ts.push((rect.x - p[0]) / ux);
  if (uy > 1e-9) ts.push((rect.y + rect.h - p[1]) / uy);
  else if (uy < -1e-9) ts.push((rect.y - p[1]) / uy);
  const t = ts.length ? Math.min(...ts) : 0;
  return [p[0] + ux * t, p[1] + uy * t];
}

/** An arrow as drawn. */
export interface ArrowShape {
  conn: ConnectionData;
  /** The card or collapsed group at each end, as drawn. */
  from: string;
  to: string;
  /** Ends where the arrowhead begins. */
  path: Path;
  head: [Point, Point, Point];
  label: Rect | null;
  labelText: string;
  /** Shown on hover: the label in full when it's shortened or hidden. */
  tooltip: string;
  /** Arrows drawn as this one because they meet the same collapsed groups (0: just it). */
  merged: number;
}

type Routed = [path: Path, tip: Point, dir: Point, mid: Point];

export interface RouteContext {
  boxes: ReadonlyMap<string, CardBox>;
  structure: Structure;
  display: Display;
  m: TextMeasurer;
  /** Pairs "source\0target" that have an arrow, for reverse-pair offsets. */
  pairs: ReadonlySet<string>;
  /** Visible plain cards, for "avoid cards" routing. */
  obstacles: readonly CardBox[];
}

/** Every arrow to draw. Those whose ends fold into the same collapsed group are hidden;
 *  those meeting the same collapsed groups are drawn once, marked ×N. */
export function routeArrows(connections: readonly ConnectionData[], boxes: ReadonlyMap<string, CardBox>,
                            structure: Structure, display: Display, m: TextMeasurer): ArrowShape[] {
  const seen = new Set<string>();
  const live: ConnectionData[] = [];
  for (const c of connections) {
    const key = `${c.source}\u0000${c.target}`;
    if (!boxes.has(c.source) || !boxes.has(c.target) || c.source === c.target || seen.has(key)) continue;
    seen.add(key);
    live.push(c);
  }
  const ctx: RouteContext = {
    boxes, structure, display, m, pairs: seen,
    obstacles: [...boxes.values()].filter((b) => b.visible && !b.isGroup),
  };
  const byEnds = new Map<string, ConnectionData[]>();
  for (const c of live) {
    const a = structure.visibleEnd(c.source);
    const b = structure.visibleEnd(c.target);
    if (a === b) continue;
    const key = `${a}\u0000${b}`;
    const list = byEnds.get(key);
    if (list) list.push(c);
    else byEnds.set(key, [c]);
  }
  const out: ArrowShape[] = [];
  for (const [key, list] of byEnds) {
    const [a, b] = key.split("\u0000") as [string, string];
    const shape = routeArrow(list[0]!, a, b, list.length > 1 ? list.length : 0, ctx);
    if (shape) out.push(shape);
  }
  return out;
}

function routeArrow(conn: ConnectionData, a: string, b: string, merged: number, ctx: RouteContext): ArrowShape | null {
  const { boxes, display } = ctx;
  const ends = a === conn.source && b === conn.target ? boundaryEnds(conn, ctx) : null;
  let routed: Routed | null = null;
  if (ends) {
    routed = straightBetween(ends[0], ends[1]);
  } else {
    if (display.arrow_routing !== "straight") routed = curve(conn, a, b, display.arrow_routing === "avoid", ctx);
    routed ??= straight(conn, a, b, ctx);
  }
  if (!routed) return null;
  const [path, tip, [ux, uy]] = routed;
  let mid = routed[3];
  if (!ends) mid = labelCentre(path, boxes.get(a)!, display, mid);
  const base: Point = [tip[0] - ux * ARROW_LEN, tip[1] - uy * ARROW_LEN];
  const perp: Point = [-uy * ARROW_HALF_W, ux * ARROW_HALF_W];
  const head: [Point, Point, Point] = [tip, [base[0] + perp[0], base[1] + perp[1]], [base[0] - perp[0], base[1] - perp[1]]];

  const [full, text] = labelTexts(conn, merged, display, ctx.m);
  let label: Rect | null = null;
  if (text) {
    const w = ctx.m.width(text, "edge") + 12;
    const h = lineHeight(ctx.m, "edge") + 4;
    label = { x: mid[0] - w / 2, y: mid[1] - h / 2, w, h };
  }
  return { conn, from: a, to: b, path, head, label, labelText: text, tooltip: full !== text ? full : "", merged };
}

/** [the label on one line, the label as drawn: shortened, or "" when labels are hidden]. */
export function labelTexts(conn: ConnectionData, merged: number, display: Display, m: TextMeasurer): [string, string] {
  const label = collapseSpaces(conn.label);
  if (merged > 1) return [`${merged} arrows into or out of a collapsed group`, `×${merged}`];
  if (!label || !display.show_arrow_labels) return [label, ""];
  return [label, elide(m, label, "edge", MAX_LABEL_WIDTH)];
}

/** Halfway along the part of the arrow you can see: past the source's handle, if the
 *  arrow leaves from it. */
function labelCentre(path: Path, from: CardBox, display: Display, mid: Point): Point {
  const length = path.length();
  const start = path.start;
  const anchor = anchorRect(from);
  const covered = hasPort(from, display) && Math.abs(start[0] - (anchor.x + anchor.w)) < 1 ? PORT_RADIUS : 0;
  if (length <= covered) return mid;
  return path.pointAtLength((covered + length) / 2);
}

function straightBetween(start: Point, tip: Point): Routed | null {
  const dx = tip[0] - start[0];
  const dy = tip[1] - start[1];
  const length = Math.hypot(dx, dy);
  if (length <= ARROW_LEN) return null;
  const ux = dx / length;
  const uy = dy / length;
  const path = new Path(start).lineTo([tip[0] - ux * ARROW_LEN, tip[1] - uy * ARROW_LEN]);
  return [path, tip, [ux, uy], [(start[0] + tip[0]) / 2, (start[1] + tip[1]) / 2]];
}

const hasReverse = (conn: ConnectionData, ctx: RouteContext) => ctx.pairs.has(`${conn.target}\u0000${conn.source}`);

/** Centre to centre, cut off at both cards' edges. */
function straight(conn: ConnectionData, a: string, b: string, ctx: RouteContext): Routed | null {
  const s = anchorRect(ctx.boxes.get(a)!);
  const t = anchorRect(ctx.boxes.get(b)!);
  let sc = center(s);
  let tc = center(t);
  const dx = tc[0] - sc[0];
  const dy = tc[1] - sc[1];
  const length = Math.hypot(dx, dy);
  if (length < 1e-6) return null;
  const ux = dx / length;
  const uy = dy / length;
  if (hasReverse(conn, ctx)) {
    const off: Point = [-uy * REVERSE_OFFSET, ux * REVERSE_OFFSET];
    sc = [sc[0] + off[0], sc[1] + off[1]];
    tc = [tc[0] + off[0], tc[1] + off[1]];
  }
  const start = exitPoint(s, sc, ux, uy);
  const tip = exitPoint(t, tc, -ux, -uy);
  const span = (tip[0] - start[0]) * ux + (tip[1] - start[1]) * uy;
  if (span <= ARROW_LEN) return null; // cards overlap
  return straightBetween(start, tip);
}

/** For an arrow between a group and a card inside it: [start, tip] across the gap
 *  between the card and the nearest side of the frame's inner area. */
function boundaryEnds(conn: ConnectionData, ctx: RouteContext): [Point, Point] | null {
  const { structure, boxes } = ctx;
  let groupId: string;
  let cardId: string;
  let inward: boolean;
  if (structure.isInside(conn.target, conn.source)) [groupId, cardId, inward] = [conn.source, conn.target, true];
  else if (structure.isInside(conn.source, conn.target)) [groupId, cardId, inward] = [conn.target, conn.source, false];
  else return null;
  const group = boxes.get(groupId)!;
  const body = bodyRect(group);
  const r = anchorRect(boxes.get(cardId)!);
  const cx = Math.min(Math.max(r.x + r.w / 2, body.x), body.x + body.w);
  // Side arrows run along the card's title bar, clear of ordinary arrows.
  const cy = Math.min(Math.max(r.y + HEADER_HEIGHT / 2, body.y), body.y + body.h);
  const spans: Record<string, [Point, Point]> = {
    left: [[body.x, cy], [r.x, cy]],
    right: [[body.x + body.w, cy], [r.x + r.w, cy]],
    top: [[cx, body.y], [cx, r.y]],
    bottom: [[cx, body.y + body.h], [cx, r.y + r.h]],
  };
  const vertical = group.card.arrange_vertical;
  const preferred = inward ? (vertical ? "top" : "left") : (vertical ? "bottom" : "right");
  const others = (structure.members.get(groupId) ?? [])
    .filter((id) => id !== cardId && !structure.isInside(cardId, id)).map((id) => anchorRect(boxes.get(id)!));
  const length = (side: string) => {
    const [p, q] = spans[side]!;
    return Math.abs(p[0] - q[0]) + Math.abs(p[1] - q[1]);
  };
  const clear = (side: string) => {
    const [p, q] = spans[side]!;
    const lane = grow({ x: Math.min(p[0], q[0]), y: Math.min(p[1], q[1]), w: Math.abs(p[0] - q[0]), h: Math.abs(p[1] - q[1]) }, 1);
    return !others.some((o) => intersects(o, lane));
  };
  const opposite = { left: "right", right: "left", top: "bottom", bottom: "top" }[preferred]!;
  const sides = Object.keys(spans).filter((k) => k !== preferred && k !== opposite)
    .map((k, i) => ({ k, i })).sort((p, q) => length(p.k) - length(q.k) || p.i - q.i).map(({ k }) => k);
  const order = [preferred, ...sides, opposite];
  const side = order.find(clear) ?? preferred;
  const [border, edge] = spans[side]!;
  return inward ? [border, edge] : [edge, border];
}

/** A smooth S-curve between the facing sides of the two cards, leaving and arriving square
 *  to them. With `avoid`, a curve that would cross other cards is bent around them. Null
 *  when the cards are too close to curve between. */
function curve(conn: ConnectionData, a: string, b: string, avoid: boolean, ctx: RouteContext): Routed | null {
  const s = anchorRect(ctx.boxes.get(a)!);
  const t = anchorRect(ctx.boxes.get(b)!);
  const gapX = Math.max(t.x - (s.x + s.w), s.x - (t.x + t.w));
  const gapY = Math.max(t.y - (s.y + s.h), s.y - (t.y + t.h));
  if (Math.max(gapX, gapY) <= ARROW_LEN + 4) return null;
  const horizontal = gapX >= gapY;
  // (along, across) coordinates, so one routine serves both directions.
  const loc = (p: Point): Point => (horizontal ? p : [p[1], p[0]]);
  const out = (al: number, ac: number): Point => (horizontal ? [al, ac] : [ac, al]);
  const [sLo, sHi] = horizontal ? [s.x, s.x + s.w] : [s.y, s.y + s.h];
  const [tLo, tHi] = horizontal ? [t.x, t.x + t.w] : [t.y, t.y + t.h];
  const sc = loc(center(s));
  const tc = loc(center(t));
  const sign = tc[0] > sc[0] ? 1 : -1;
  const off = hasReverse(conn, ctx) ? REVERSE_OFFSET * sign * (horizontal ? 1 : -1) : 0;
  const a0 = sign > 0 ? sHi : sLo;
  const c0 = sc[1] + off;
  const tipA = sign > 0 ? tLo : tHi;
  const c3 = tc[1] + off;
  const a3 = tipA - sign * ARROW_LEN;

  const build = (lane: [number, number, number] | null = null): Path => {
    const path = new Path(out(a0, c0));
    if (lane === null) {
      const pull = Math.max(Math.abs(a3 - a0) * 0.5, CURVE_MIN_PULL);
      return path.cubicTo(out(a0 + sign * pull, c0), out(a3 - sign * pull, c3), out(a3, c3));
    }
    const [via, w1, w2] = lane;
    const p1 = Math.abs(w1 - a0) * 0.5;
    const p2 = Math.abs(a3 - w2) * 0.5;
    path.cubicTo(out(a0 + sign * p1, c0), out(w1 - sign * p1, via), out(w1, via));
    path.lineTo(out(w2, via));
    return path.cubicTo(out(w2 + sign * p2, via), out(a3 - sign * p2, c3), out(a3, c3));
  };

  const lanes = (blocked: Rect[]): [number, number, number][] => {
    const corners = [...blocked.map((r) => loc([r.x, r.y])), ...blocked.map((r) => loc([r.x + r.w, r.y + r.h]))];
    const along = corners.map((p) => p[0]);
    const across = corners.map((p) => p[1]);
    const loA = Math.min(...along) - AVOID_MARGIN;
    const hiA = Math.max(...along) + AVOID_MARGIN;
    const [first, last] = sign > 0 ? [loA, hiA] : [hiA, loA];
    const ease = CURVE_MIN_PULL / 2;
    let w1 = sign > 0 ? Math.max(first, a0 + ease) : Math.min(first, a0 - ease);
    let w2 = sign > 0 ? Math.min(last, a3 - ease) : Math.max(last, a3 + ease);
    if ((w2 - w1) * sign < 0) w1 = w2 = (a0 + a3) / 2;
    const home = (c0 + c3) / 2;
    const sides = [Math.min(...across) - AVOID_MARGIN, Math.max(...across) + AVOID_MARGIN];
    const sorted = sides.map((v, i) => ({ v, i })).sort((p, q) => Math.abs(p.v - home) - Math.abs(q.v - home) || p.i - q.i);
    return sorted.map(({ v }) => [v, w1, w2]);
  };

  let path = build();
  if (avoid) {
    let blocked = cardsInTheWay(path, conn, a, b, ctx);
    for (let round = 0; round < 3 && blocked.length; round++) {
      const tried: Rect[][] = [];
      let found = false;
      for (const lane of lanes(blocked)) {
        const candidate = build(lane);
        const hits = cardsInTheWay(candidate, conn, a, b, ctx);
        if (!hits.length) {
          path = candidate;
          blocked = [];
          found = true;
          break;
        }
        tried.push(hits);
      }
      if (found) break;
      const extra = tried[0]!.filter((r) => !blocked.some((x) => sameRect(x, r)));
      if (!extra.length) break; // no clear way round: keep the plain curve
      blocked = [...blocked, ...extra];
    }
  }
  const tip = out(tipA, c3);
  return [path, tip, out(sign, 0), path.pointAtPercent(0.5)];
}

const sameRect = (p: Rect, q: Rect) => p.x === q.x && p.y === q.y && p.w === q.w && p.h === q.h;

/** Cards (not groups, not this arrow's own ends) that the path runs through. */
function cardsInTheWay(path: Path, conn: ConnectionData, a: string, b: string, ctx: RouteContext): Rect[] {
  const ends = new Set([conn.source, conn.target, a, b]);
  const area = grow(path.bounds(), 1);
  const rects = ctx.obstacles.filter((o) => !ends.has(o.card.id))
    .map((o) => anchorRect(o)).filter((r) => intersects(r, area)).map((r) => grow(r, 4));
  if (!rects.length) return [];
  const points = Array.from({ length: AVOID_SAMPLES + 1 }, (_, k) => path.pointAtPercent(k / AVOID_SAMPLES));
  return rects.filter((r) => points.some((p) => contains(r, p)));
}

/** Does a point lie on an arrow (within `tolerance` of its line, head or label)? */
export function hitArrow(shape: ArrowShape, p: Point, tolerance: number): boolean {
  if (shape.label && contains(grow(shape.label, 0), p)) return true;
  if (dist(shape.head[0], p) <= ARROW_LEN + tolerance) return true;
  const pts = shape.path.points();
  for (let i = 1; i < pts.length; i++) if (segmentDistance(pts[i - 1]!, pts[i]!, p) <= tolerance) return true;
  return false;
}

function segmentDistance(a: Point, b: Point, p: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2)) : 0;
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

export const geometry = { contains, intersects, grow, center };
