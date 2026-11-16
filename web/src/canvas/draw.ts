// Drawing the board on a Canvas 2D context: the paint() methods of heddle/card_item.py and
// heddle/edge_item.py, and the scene's grid (BoardScene.drawBackground). Coordinates are
// scene units; the camera's transform is applied once.

import type { Display } from "../core/model.ts";
import {
  CORNER, HEADER_HEIGHT, LOD_TEXT, LOD_TITLE, PAD, PORT_RADIUS, STRAND_MARKS, TOGGLE_SIZE,
  foldRect, hasPort, paintOrder, portCenter, toggleRect, type CardBox, type Rect,
} from "../board/metrics.ts";
import { DASH_PATTERNS, LOD_OVERVIEW, type ArrowShape } from "../board/routing.ts";
import { cssFont, elide, lineHeight, type FontKey, type TextMeasurer } from "../board/text.ts";
import type { BoardStore } from "../board/store.ts";
import type { Camera } from "./camera.ts";
import { darker, lighter, readableText, withAlpha, type Theme } from "./theme.ts";

export const GRID = 25;
export const MAJOR_EVERY = 5;

/** What the pointer is over, for hover effects. */
export interface Hover {
  card?: string;
  part?: "port" | "toggle" | "fold" | "body";
  arrow?: string;
}

export interface DrawState {
  store: BoardStore;
  camera: Camera;
  theme: Theme;
  m: TextMeasurer;
  hover: Hover;
  dpr: number;
  /** Cards being dragged (drawn on top), if any. */
  lifted?: ReadonlySet<string>;
  /** A card or group a drag would drop onto or into, outlined. */
  dropTarget?: string;
  /** Where a new card would go (dropping a handle on empty canvas). */
  ghost?: { rect: Rect; color: string };
}

export function drawBoard(ctx: CanvasRenderingContext2D, s: DrawState): void {
  const { camera, theme, dpr } = s;
  const display = s.store.state.display;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = theme.canvasBg;
  ctx.fillRect(0, 0, camera.width, camera.height);
  const k = camera.scale * dpr;
  ctx.setTransform(k, 0, 0, k, -camera.ox * k, -camera.oy * k);
  const view = camera.visible();
  if (display.show_grid) drawGrid(ctx, view, camera.scale, theme);

  const lod = camera.scale;
  const { groups, cards } = paintOrder(s.store.boxes);
  // What's being dragged is drawn above everything else until it's dropped.
  const lifted = s.lifted;
  const below = lifted ? cards.filter((c) => !lifted.has(c.card.id)) : cards;
  const above = lifted ? cards.filter((c) => lifted.has(c.card.id)) : [];
  const onScreen = (b: Rect) => overlaps(b, view, 12);
  for (const g of groups) if (onScreen(g)) drawCard(ctx, g, s, display, lod);
  for (const a of s.store.arrows) if (overlaps(a.path.bounds(), view, 40)) drawArrow(ctx, a, s, lod);
  for (const c of below) if (onScreen(c)) drawCard(ctx, c, s, display, lod);
  for (const c of above) if (onScreen(c)) drawCard(ctx, c, s, display, lod);
  if (s.ghost) {
    const { rect: r, color } = s.ghost;
    const path = roundRect(r.x, r.y, r.w, r.h, CORNER);
    ctx.fillStyle = withAlpha(color, 40);
    ctx.fill(path);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 3]);
    ctx.stroke(path);
    ctx.setLineDash([]);
  }
}

function overlaps(r: Rect, v: Rect, margin: number): boolean {
  return r.x - margin <= v.x + v.w && v.x <= r.x + r.w + margin && r.y - margin <= v.y + v.h && v.y <= r.y + r.h + margin;
}

function drawGrid(ctx: CanvasRenderingContext2D, view: Rect, scale: number, t: Theme): void {
  const step = scale >= 0.5 ? GRID : GRID * MAJOR_EVERY;
  const minor = new Path2D();
  const major = new Path2D();
  for (let x = Math.floor(view.x / step) * step; x < view.x + view.w; x += step) {
    const p = Math.round(x / GRID) % MAJOR_EVERY === 0 ? major : minor;
    p.moveTo(x, view.y);
    p.lineTo(x, view.y + view.h);
  }
  for (let y = Math.floor(view.y / step) * step; y < view.y + view.h; y += step) {
    const p = Math.round(y / GRID) % MAJOR_EVERY === 0 ? major : minor;
    p.moveTo(view.x, y);
    p.lineTo(view.x + view.w, y);
  }
  ctx.lineWidth = 1 / scale; // one screen pixel
  ctx.strokeStyle = t.gridMinor;
  ctx.stroke(minor);
  ctx.strokeStyle = t.gridMajor;
  ctx.stroke(major);
}

function roundRect(x: number, y: number, w: number, h: number, r: number): Path2D {
  const p = new Path2D();
  p.roundRect(x, y, w, h, r);
  return p;
}

/** Text lines, top-aligned in a block, each clipped to the block's width. */
function drawLines(ctx: CanvasRenderingContext2D, m: TextMeasurer, x: number, y: number, lines: readonly string[],
                   font: FontKey): void {
  ctx.font = cssFont(font);
  const lh = lineHeight(m, font);
  const ascent = m.ascent(font);
  lines.forEach((line, i) => ctx.fillText(line, x, y + i * lh + ascent));
}

/** One line, vertically centred in `r` (Qt's AlignVCenter), left, right or centred. */
function drawCentred(ctx: CanvasRenderingContext2D, m: TextMeasurer, r: Rect, text: string, font: FontKey,
                     align: CanvasTextAlign = "left"): void {
  ctx.font = cssFont(font);
  ctx.textAlign = align;
  const x = align === "left" ? r.x : align === "right" ? r.x + r.w : r.x + r.w / 2;
  ctx.fillText(text, x, r.y + (r.h - lineHeight(m, font)) / 2 + m.ascent(font));
  ctx.textAlign = "left";
}

function drawCard(ctx: CanvasRenderingContext2D, b: CardBox, s: DrawState, display: Display, lod: number): void {
  const t = s.theme;
  const { m } = s;
  const showText = lod >= LOD_TEXT;
  const color = b.card.color;
  if (lod < LOD_TITLE) {
    drawOverview(ctx, b, t, lod, s.store.selected.has(b.card.id));
    return;
  }
  ctx.save();
  ctx.translate(b.x, b.y);
  const path = roundRect(0, 0, b.w, b.h, CORNER);
  const hover = s.hover.card === b.card.id ? s.hover.part : undefined;

  if (b.isGroup) {
    ctx.fillStyle = t.canvasBg; // opaque base (hides the grid), then a wash of the colour
    ctx.fill(path);
    ctx.fillStyle = withAlpha(color, t.dark ? 45 : 30);
    ctx.fill(path);
    if (b.headerH > HEADER_HEIGHT) { // solid panel behind tags and details
      ctx.save();
      ctx.clip(path);
      ctx.fillStyle = t.cardBg;
      ctx.fillRect(0, 0, b.w, b.headerH);
      ctx.strokeStyle = withAlpha(color, 120);
      ctx.lineWidth = 1;
      line(ctx, 0, b.headerH, b.w, b.headerH);
      ctx.restore();
    }
    if (b.memberCount === 0 && showText && !b.card.collapsed) {
      ctx.fillStyle = t.cardMuted;
      drawCentred(ctx, m, { x: PAD, y: b.headerH, w: b.w - 2 * PAD, h: b.h - b.headerH }, "Empty group", "smallItalic", "center");
    }
  } else {
    if (display.show_shadows) {
      ctx.fillStyle = t.cardShadow;
      ctx.save();
      ctx.translate(2, 3);
      ctx.fill(path);
      ctx.restore();
    }
    ctx.fillStyle = t.cardBg;
    ctx.fill(path);
  }

  ctx.save();
  ctx.clip(path);
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, b.w, HEADER_HEIGHT);
  ctx.restore();

  drawHeader(ctx, b, s, display, showText, hover);

  for (const [pills, outlined] of [[b.tagPills, false], [b.charPills, true]] as const) {
    for (const p of pills) {
      const r = p.h / 2;
      if (outlined) { // characters: outlined, so they read apart from tags
        ctx.strokeStyle = withAlpha(color, t.dark ? 200 : 170);
        ctx.lineWidth = 1;
        ctx.stroke(roundRect(p.x + 0.5, p.y + 0.5, p.w - 1, p.h - 1, r));
      } else {
        ctx.fillStyle = withAlpha(color, t.dark ? 80 : 50);
        ctx.fill(roundRect(p.x, p.y, p.w, p.h, r));
      }
      if (showText) {
        ctx.fillStyle = t.cardText;
        drawCentred(ctx, m, p, p.text, "small", "center");
      }
    }
  }

  if (b.detailsTop !== null) {
    ctx.strokeStyle = t.cardBorder;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 2]);
    line(ctx, PAD, b.detailsTop, b.w - PAD, b.detailsTop);
    ctx.setLineDash([]);
  }

  if (showText) {
    for (const blk of b.blocks) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(blk.x, blk.y, blk.w, blk.h + 1);
      ctx.clip();
      ctx.fillStyle = blk.role === "text" ? t.cardText : t.cardMuted;
      drawLines(ctx, m, blk.x, blk.y, blk.lines, blk.font);
      ctx.restore();
    }
  }

  // Outline: selected, a drop target, a group, or plain; dashed for a card left out of
  // the story tools.
  let width = 1;
  let stroke = t.cardBorder;
  let dashed = false;
  if (s.store.selected.has(b.card.id)) {
    stroke = t.selected;
    width = 2.5;
  } else if (s.dropTarget === b.card.id) {
    stroke = t.dark ? lighter(color, 130) : darker(color, 115);
    width = 2.5;
    dashed = true;
  } else if (b.isGroup) {
    stroke = withAlpha(color, 170);
    width = 1.5;
  }
  ctx.strokeStyle = stroke;
  ctx.lineWidth = width;
  if (dashed || (b.card.outside_story && display.story_tools && !s.store.selected.has(b.card.id))) {
    ctx.setLineDash([4 * width, 2 * width]);
  }
  ctx.stroke(path);
  ctx.setLineDash([]);

  if (hasPort(b, display)) {
    const [px, py] = portCenter(b);
    const radius = PORT_RADIUS + (hover === "port" ? 2 : 0);
    ctx.beginPath();
    ctx.arc(px - b.x, py - b.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = darker(color, 110);
    ctx.fill();
    ctx.strokeStyle = t.portRing;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.restore();
}

function line(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number): void {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

/** Far zoomed out: plain blocks (body plus coloured header), no text. */
function drawOverview(ctx: CanvasRenderingContext2D, b: CardBox, t: Theme, lod: number, selected: boolean): void {
  const color = b.card.color;
  if (b.isGroup) {
    ctx.fillStyle = t.canvasBg;
    ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.fillStyle = withAlpha(color, t.dark ? 45 : 30);
    ctx.fillRect(b.x, b.y, b.w, b.h);
  } else {
    ctx.fillStyle = t.cardBg;
    ctx.fillRect(b.x, b.y, b.w, b.h);
  }
  ctx.fillStyle = color;
  ctx.fillRect(b.x, b.y, b.w, HEADER_HEIGHT);
  if (b.isGroup || selected) {
    ctx.strokeStyle = selected ? t.selected : color;
    ctx.lineWidth = 1 / lod;
    ctx.strokeRect(b.x, b.y, b.w, b.h);
  }
}

function drawHeader(ctx: CanvasRenderingContext2D, b: CardBox, s: DrawState, display: Display, showCount: boolean,
                    hover: Hover["part"]): void {
  const { m } = s;
  const color = b.card.color;
  const fg = readableText(color);
  let right = b.w - 2.5 * PAD - TOGGLE_SIZE;
  const collapsed = b.isGroup && b.card.collapsed;
  if (b.isGroup && showCount && (display.show_group_count || collapsed)) {
    const count = `${b.memberCount} card${b.memberCount !== 1 ? "s" : ""}`;
    const w = m.width(count, "small") + 8;
    ctx.fillStyle = withAlpha(fg, 190);
    drawCentred(ctx, m, { x: right - w, y: 0, w, h: HEADER_HEIGHT }, count, "small", "right");
    right -= w + 6;
  }
  if (b.introduces.length) { // ★: this card introduces a character
    const w = m.width("★", "title") + 4;
    ctx.fillStyle = fg;
    drawCentred(ctx, m, { x: right - w, y: 0, w, h: HEADER_HEIGHT }, "★", "title", "right");
    right -= w + 2;
  }
  let left = PAD;
  if (b.isGroup) {
    drawFold(ctx, fg, collapsed, hover === "fold");
    left += 16 + 2;
  }
  if (b.isStrand) {
    const mark = STRAND_MARKS[b.card.strand_kind] ?? "•";
    const w = m.width(mark, "title") + 6;
    ctx.fillStyle = fg;
    drawCentred(ctx, m, { x: left, y: 0, w, h: HEADER_HEIGHT }, mark, "title");
    left += w;
  }
  const title = elide(m, b.card.title || "Untitled", "title", right - left);
  ctx.fillStyle = fg;
  drawCentred(ctx, m, { x: left, y: 0, w: right - left, h: HEADER_HEIGHT }, title, "title");
  drawToggle(ctx, b, fg, hover === "toggle");
}

/** A small boxed − (collapse) or + (expand) at the left of a group's title. */
function drawFold(ctx: CanvasRenderingContext2D, fg: string, collapsed: boolean, hot: boolean): void {
  const f = foldRect();
  const r = { x: f.x + 2, y: f.y + 2, w: f.w - 4, h: f.h - 4 };
  ctx.strokeStyle = withAlpha(fg, hot ? 255 : 170);
  ctx.lineWidth = 1.3;
  ctx.stroke(roundRect(r.x, r.y, r.w, r.h, 2.5));
  const cx = r.x + r.w / 2;
  const cy = r.y + r.h / 2;
  const arm = r.w * 0.28;
  line(ctx, cx - arm, cy, cx + arm, cy);
  if (collapsed) line(ctx, cx, cy - arm, cx, cy + arm);
}

/** ▸ (details hidden) or ▾ (showing) at the right of the title bar. */
function drawToggle(ctx: CanvasRenderingContext2D, b: CardBox, fg: string, hot: boolean): void {
  const r = toggleRect(b);
  if (hot) {
    ctx.fillStyle = withAlpha(fg, 45);
    ctx.beginPath();
    ctx.ellipse(r.x + r.w / 2, r.y + r.h / 2, r.w / 2, r.h / 2, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  const { x, y, w: sz } = r;
  const pts = b.detailsVisible
    ? [[x + sz * 0.25, y + sz * 0.36], [x + sz * 0.75, y + sz * 0.36], [x + sz * 0.5, y + sz * 0.7]]
    : [[x + sz * 0.36, y + sz * 0.25], [x + sz * 0.36, y + sz * 0.75], [x + sz * 0.7, y + sz * 0.5]];
  ctx.fillStyle = fg;
  ctx.beginPath();
  ctx.moveTo(pts[0]![0]!, pts[0]![1]!);
  ctx.lineTo(pts[1]![0]!, pts[1]![1]!);
  ctx.lineTo(pts[2]![0]!, pts[2]![1]!);
  ctx.closePath();
  ctx.fill();
}

function arrowColor(a: ArrowShape, t: Theme, hover: boolean): string {
  const own = a.conn.color || null;
  if (hover) return own ? (t.dark ? lighter(own, 135) : darker(own, 135)) : t.edgeHover;
  return own ?? t.edgeLine;
}

function tracePath(ctx: CanvasRenderingContext2D, a: ArrowShape): void {
  const p = a.path;
  ctx.beginPath();
  ctx.moveTo(p.start[0], p.start[1]);
  for (const seg of p.segments) {
    if (seg.kind === "L") ctx.lineTo(seg.to[0], seg.to[1]);
    else ctx.bezierCurveTo(seg.c1[0], seg.c1[1], seg.c2[0], seg.c2[1], seg.to[0], seg.to[1]);
  }
}

function drawArrow(ctx: CanvasRenderingContext2D, a: ArrowShape, s: DrawState, lod: number): void {
  const t = s.theme;
  const selected = s.store.selectedArrows.has(a.conn.id);
  const color = selected ? t.selected : arrowColor(a, t, s.hover.arrow === a.conn.id);
  if (lod < LOD_OVERVIEW) { // far zoomed out: a plain 1px line
    tracePath(ctx, a);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1 / lod;
    ctx.stroke();
    return;
  }
  const width = selected ? 3 : 2.2;
  tracePath(ctx, a);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  const dash = DASH_PATTERNS[a.conn.style];
  ctx.setLineDash(dash ? dash.map((d) => d * width) : []);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.lineCap = "butt";
  const [p, q, r] = a.head;
  ctx.beginPath();
  ctx.moveTo(p[0], p[1]);
  ctx.lineTo(q[0], q[1]);
  ctx.lineTo(r[0], r[1]);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();

  if (a.label) {
    const l = a.label;
    const box = roundRect(l.x, l.y, l.w, l.h, 4);
    ctx.fillStyle = t.edgeLabelBg;
    ctx.fill(box);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.stroke(box);
    if (lod >= LOD_TEXT) {
      ctx.fillStyle = t.edgeText;
      drawCentred(ctx, s.m, l, a.labelText, "edge", "center");
    }
  }
}
