// Card and group sizes and what's drawn where on them: the layout half of
// heddle/card_item.py (CardItem._relayout), plus the parts of heddle/scene.py that decide
// group membership, nesting depth and what a collapsed group hides.
//
// Pure: text is measured through an injected TextMeasurer. Groups are fitted around
// their cards deepest first, so a nested group's frame is known before its parent's.

import {
  DISPLAY_DEFAULTS, KIND_GROUP, KIND_STRAND, strandKey, type CardData, type Display, type StrandInfo,
} from "../core/model.ts";
import { casefold, strip } from "../core/pystr.ts";
import { elide, elideLines, lineHeight, wrapLines, type FontKey, type TextMeasurer } from "./text.ts";

export const CARD_WIDTH = 230;
export const HEADER_HEIGHT = 32;
export const PAD = 10;
export const CORNER = 8;
export const PORT_RADIUS = 7;
export const LOD_TEXT = 0.5;
export const LOD_TITLE = 0.3;
export const TOGGLE_SIZE = 18;
export const BADGE_SIZE = 18;
export const FOLD_SIZE = 16;
export const MAX_DESC_LINES = 6;
export const DIMMED_OPACITY = 0.2;
export const GROUP_PAD = 22;
export const GROUP_MIN_WIDTH = 300;
export const GROUP_EMPTY_HEIGHT = 120;
export const GROUP_MIN_BODY = 60;
export const RESIZE_GRIP = 16;

export const STRAND_MARKS: Record<string, string> = { characters: "☺", locations: "⌂", tags: "#", status: "◑" };
export const STRAND_KIND_NAMES: Record<string, string> = {
  characters: "Character", locations: "Location", tags: "Tag", status: "Status",
};
const DETAIL_FIELDS = [
  ["characters", "Characters"], ["pov", "POV"], ["locations", "Locations"], ["status", "Status"], ["notes", "Notes"],
] as const;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Text drawn on a card, in the card's own coordinates, top-aligned, one entry per line. */
export interface Block extends Rect {
  lines: string[];
  font: FontKey;
  role: "text" | "muted";
}

export interface Pill extends Rect {
  text: string;
}

/** Everything the renderer and hit testing need about one card or group. */
export interface CardBox extends Rect {
  card: CardData;
  isGroup: boolean;
  isStrand: boolean;
  /** Plain cards: height with details hidden (arrows meet this part: see anchorRect). */
  closedH: number;
  /** Height of the header panel: the title bar, or for groups title, tags and details. */
  headerH: number;
  blocks: Block[];
  tagPills: Pill[];
  charPills: Pill[];
  /** The dashed line above the details, if drawn. */
  detailsTop: number | null;
  detailsVisible: boolean;
  memberCount: number;
  /** Characters this card introduces (★), when the board shows them. */
  introduces: string[];
  /** Shown on hover: a cut-off or hidden description, or what a strand card stands for. */
  tooltip: string;
  /** Groups around it (0 for a top-level card). */
  depth: number;
  /** False when folded away inside a collapsed group. */
  visible: boolean;
  /** Groups: where the group's saved x and y belong after fitting round its cards (the
   *  frame as it looks with details hidden), less any make-room push. */
  anchorX: number;
  anchorY: number;
}

export interface LayoutInput {
  cards: readonly CardData[];
  display?: Display;
  /** {card id: characters it introduces} (empty when story tools are off). */
  introductions?: ReadonlyMap<string, readonly string[]>;
  /** Cards whose details are showing. */
  details?: ReadonlySet<string>;
  strands?: readonly StrandInfo[];
  /** Cards moved aside (not saved) to make room for open details: {id: [dx, dy]}. */
  shift?: ReadonlyMap<string, readonly [number, number]>;
}

/** The board's group structure, cleaned as the desktop app cleans it when loading:
 *  a parent that's missing, isn't a group, or leads round in a loop is dropped. */
export class Structure {
  readonly byId = new Map<string, CardData>();
  readonly parentOf = new Map<string, string>();
  readonly members = new Map<string, string[]>();
  readonly depth = new Map<string, number>();

  constructor(cards: readonly CardData[]) {
    for (const c of cards) this.byId.set(c.id, c);
    for (const c of cards) {
      const p = this.byId.get(c.parent);
      if (c.parent && p && p.kind === KIND_GROUP && p.id !== c.id) this.parentOf.set(c.id, c.parent);
    }
    for (const c of cards) {
      const seen = new Set([c.id]);
      let p = this.parentOf.get(c.id);
      while (p !== undefined) {
        if (seen.has(p)) {
          this.parentOf.delete(c.id);
          break;
        }
        seen.add(p);
        p = this.parentOf.get(p);
      }
    }
    for (const c of cards) {
      const p = this.parentOf.get(c.id);
      if (p !== undefined) {
        const list = this.members.get(p);
        if (list) list.push(c.id);
        else this.members.set(p, [c.id]);
      }
    }
    for (const c of cards) {
      let d = 0;
      for (let p = this.parentOf.get(c.id); p !== undefined; p = this.parentOf.get(p)) d++;
      this.depth.set(c.id, d);
    }
  }

  /** Groups around a card, nearest first. */
  *ancestors(id: string): Generator<string> {
    for (let p = this.parentOf.get(id); p !== undefined; p = this.parentOf.get(p)) yield p;
  }

  /** What stands for a card on the canvas: itself, or the outermost collapsed group it's
   *  inside (whose folded frame its arrows meet). */
  visibleEnd(id: string): string {
    let shown = id;
    for (const a of this.ancestors(id)) if (this.byId.get(a)!.collapsed) shown = a;
    return shown;
  }

  /** Is `id` inside group `groupId`, at any depth? */
  isInside(id: string, groupId: string): boolean {
    for (const a of this.ancestors(id)) if (a === groupId) return true;
    return false;
  }

  /** Every card and group inside a group, at any depth. */
  descendants(groupId: string): string[] {
    const out: string[] = [];
    const stack = [groupId];
    while (stack.length) for (const m of this.members.get(stack.pop()!) ?? []) {
      out.push(m);
      stack.push(m);
    }
    return out;
  }
}

/** Lays out cards and fits groups: all of them, or one card and the groups around it. */
export class Layouter {
  private readonly ctx: Ctx;
  /** Plain cards laid out before, by card object (cards are replaced, never changed). */
  private readonly cache = new WeakMap<CardData, { details: boolean; sx: number; sy: number; box: CardBox }>();

  constructor(input: LayoutInput, m: TextMeasurer, public structure = new Structure(input.cards)) {
    this.ctx = {
      m, display: input.display ?? DISPLAY_DEFAULTS,
      strands: new Map((input.strands ?? []).map((s) => [strandKey(s.kind, s.name), s])),
      introductions: input.introductions ?? new Map(), details: input.details ?? new Set(),
      shift: input.shift ?? new Map(),
    };
  }

  /** Every card, then every group from the deepest out; returned in board order. */
  all(cards: readonly CardData[]): Map<string, CardBox> {
    const { structure } = this;
    const boxes = new Map<string, CardBox>();
    const order = cards.map((c, i) => ({ c, i }));
    const groups = order.filter(({ c }) => c.kind === KIND_GROUP)
      .sort((a, b) => structure.depth.get(b.c.id)! - structure.depth.get(a.c.id)! || a.i - b.i);
    for (const { c } of order) if (c.kind !== KIND_GROUP) boxes.set(c.id, this.plain(c, boxes));
    for (const { c } of groups) boxes.set(c.id, layoutCard(c, this.ctx, structure, boxes));
    const out = new Map<string, CardBox>();
    for (const c of cards) {
      const box = boxes.get(c.id)!;
      box.visible = structure.visibleEnd(c.id) === c.id;
      out.set(c.id, box);
    }
    return out;
  }

  /** A plain or strand card: from the cache when nothing it depends on has changed. */
  private plain(c: CardData, boxes: Map<string, CardBox>): CardBox {
    const details = this.ctx.details.has(c.id);
    const [sx, sy] = this.ctx.shift.get(c.id) ?? [0, 0];
    const hit = this.cache.get(c);
    if (hit && hit.details === details && hit.sx === sx && hit.sy === sy && !hit.box.introduces.length
        && !(this.ctx.introductions.get(c.id)?.length)) {
      return { ...hit.box, x: c.x + sx, y: c.y + sy };
    }
    const box = layoutCard(c, this.ctx, this.structure, boxes);
    this.cache.set(c, { details, sx, sy, box: { ...box } });
    return box;
  }

  /** Lay out one card again (its text or details changed), then refit the groups around
   *  it, nearest first. `boxes` is updated in place. */
  update(id: string, boxes: Map<string, CardBox>): void {
    for (const cid of [id, ...this.structure.ancestors(id)]) {
      const old = boxes.get(cid);
      if (!old) continue;
      const box = layoutCard(old.card, this.ctx, this.structure, boxes);
      box.visible = old.visible;
      boxes.set(cid, box);
    }
  }
}

/** Lay out every card and fit every group. */
export function layoutBoard(input: LayoutInput, m: TextMeasurer, structure = new Structure(input.cards)): Map<string, CardBox> {
  return new Layouter(input, m, structure).all(input.cards);
}

interface Ctx {
  m: TextMeasurer;
  display: Display;
  strands: Map<string, StrandInfo>;
  introductions: ReadonlyMap<string, readonly string[]>;
  details: ReadonlySet<string>;
  shift: ReadonlyMap<string, readonly [number, number]>;
}

function textBlock(m: TextMeasurer, x: number, y: number, w: number, text: string, font: FontKey,
                   role: Block["role"]): Block {
  const lines = wrapLines(m, text, font, w);
  return { x, y, w, h: lines.length * lineHeight(m, font), lines, font, role };
}

/** Rounded pills for values, wrapping onto new rows; returns them and the y below. */
function layoutPills(m: TextMeasurer, values: readonly string[], y0: number, inner: number): [Pill[], number] {
  if (!values.length) return [[], y0];
  const pillH = lineHeight(m, "small") + 4;
  const pills: Pill[] = [];
  let x = PAD;
  let y = y0;
  for (const value of values) {
    const text = elide(m, value, "small", inner - 12);
    const w = m.width(text, "small") + 12;
    if (x > PAD && x + w > PAD + inner) {
      x = PAD;
      y += pillH + 4;
    }
    pills.push({ x, y, w, h: pillH, text });
    x += w + 4;
  }
  return [pills, y + pillH + 6];
}

function layoutCard(c: CardData, ctx: Ctx, structure: Structure, done: Map<string, CardBox>): CardBox {
  const { m, display } = ctx;
  const group = c.kind === KIND_GROUP;
  const members = group ? structure.members.get(c.id) ?? [] : [];
  let bbox: { l: number; t: number; r: number; b: number } | null = null;
  for (const id of members) {
    const r = done.get(id);
    if (!r) continue; // (only in a nesting loop, which Structure has already broken)
    bbox = bbox === null ? { l: r.x, t: r.y, r: r.x + r.w, b: r.y + r.h }
      : { l: Math.min(bbox.l, r.x), t: Math.min(bbox.t, r.y), r: Math.max(bbox.r, r.x + r.w), b: Math.max(bbox.b, r.y + r.h) };
  }
  const manual = group && c.width > 0 && c.height > 0;
  const [dx, dy] = ctx.shift.get(c.id) ?? [0, 0];
  const cx = c.x + dx;
  const cy = c.y + dy;
  let left = cx;
  let width: number;
  if (manual) {
    let right = left + c.width;
    if (bbox) {
      left = Math.min(left, bbox.l - GROUP_PAD);
      right = Math.max(right, bbox.r + GROUP_PAD);
    }
    width = Math.max(right - left, GROUP_MIN_WIDTH);
  } else if (group) {
    width = bbox ? Math.max(GROUP_MIN_WIDTH, bbox.r - bbox.l + 2 * GROUP_PAD) : GROUP_MIN_WIDTH;
    if (bbox) left = bbox.l - GROUP_PAD;
  } else {
    width = CARD_WIDTH;
  }
  const inner = width - 2 * PAD;
  const detailsVisible = ctx.details.has(c.id);
  const introduces = display.show_introductions ? [...(ctx.introductions.get(c.id) ?? [])] : [];
  const box: CardBox = {
    card: c, isGroup: group, isStrand: c.kind === KIND_STRAND, x: left, y: cy, w: width, h: 0, closedH: 0,
    headerH: HEADER_HEIGHT, blocks: [], tagPills: [], charPills: [], detailsTop: null, detailsVisible,
    memberCount: members.length, introduces, tooltip: "", depth: structure.depth.get(c.id) ?? 0, visible: true,
    anchorX: c.x, anchorY: c.y,
  };
  if (box.isStrand) {
    layoutStrand(box, ctx, inner);
    return box;
  }
  const blocks = box.blocks;
  let y = HEADER_HEIGHT + PAD;
  [box.tagPills, y] = layoutPills(m, display.show_tags ? c.tags : [], y, inner);

  const pov = display.show_pov ? c.pov : "";
  if (pov) {
    const labelW = m.width("POV", "label") + 1;
    const lineH = lineHeight(m, "small");
    const dy = m.ascent("small") - m.ascent("label"); // line the label up with the name
    blocks.push({ x: PAD, y: y + dy, w: labelW, h: lineHeight(m, "label"), lines: ["POV"], font: "label", role: "muted" });
    const nameX = PAD + labelW + 6;
    const name = elide(m, pov, "small", PAD + inner - nameX);
    blocks.push({ x: nameX, y, w: PAD + inner - nameX, h: lineH, lines: [name], font: "small", role: "text" });
    y += lineH + 6;
  }
  const faceCharacters = display.show_characters
    ? c.characters.filter((ch) => !(pov && casefold(ch) === casefold(pov))) : [];
  [box.charPills, y] = layoutPills(m, faceCharacters, y, inner);
  const hasFace = Boolean(box.tagPills.length || pov || box.charPills.length);
  let titleOnly = false;

  const desc = strip(c.description);
  if (group) {
    // (groups have no description of their own)
  } else if (!display.show_description) {
    // Descriptions hidden: pointing at the card shows it.
    box.tooltip = desc;
    if (hasFace) y += PAD - 6;
    else if (display.compact_cards) {
      y = HEADER_HEIGHT;
      titleOnly = true;
    } else y += lineHeight(m, "body") + PAD;
  } else if (!desc && !display.show_no_description) {
    if (hasFace) y += PAD - 6;
    else y += lineHeight(m, "placeholder") + PAD;
  } else {
    const font: FontKey = desc ? "body" : "placeholder";
    const [lines, truncated] = elideLines(m, desc || "No description", font, inner, MAX_DESC_LINES);
    if (truncated) box.tooltip = desc; // hovering a cut-off description shows all of it
    const h = lines.length * lineHeight(m, font);
    blocks.push({ x: PAD, y, w: inner, h, lines, font, role: desc ? "text" : "muted" });
    y += h + PAD;
  }

  const yWithoutDetails = (box.closedH = y);
  if (detailsVisible) {
    if (titleOnly) {
      y += PAD;
    } else {
      box.detailsTop = !group || hasFace ? y - PAD / 2 : null;
      y += box.detailsTop !== null ? PAD / 2 : 0;
    }
    const labelH = lineHeight(m, "label");
    let shown = false;
    const field = (label: string, value: string) => {
      shown = true;
      blocks.push({ x: PAD, y, w: inner, h: labelH, lines: [label], font: "label", role: "muted" });
      y += labelH + 1;
      const b = textBlock(m, PAD, y, inner, value, "small", "text");
      blocks.push(b);
      y += b.h + 6;
    };
    for (const [key, label] of DETAIL_FIELDS) {
      const raw = c[key];
      const value = Array.isArray(raw) ? raw.join(", ") : strip(raw);
      if (value) field(label.toUpperCase(), value);
    }
    if (introduces.length) field("INTRODUCES ★", introduces.join(", "));
    if (!shown) {
      blocks.push(textBlock(m, PAD, y, inner, "No details yet.", "smallItalic", "muted"));
      y += lineHeight(m, "smallItalic") + 6;
    }
    y += PAD - 6;
  }

  if (group) {
    const hdr = (box.headerH = hasFace || detailsVisible ? y : HEADER_HEIGHT);
    const hdr0 = hasFace ? yWithoutDetails : HEADER_HEIGHT;
    let bodyTop: number;
    let bottom: number;
    if (manual) {
      bodyTop = cy + hdr0;
      bottom = cy + c.height;
      if (bbox) {
        bodyTop = Math.min(bodyTop, bbox.t - GROUP_PAD);
        bottom = Math.max(bottom, bbox.b + GROUP_PAD);
      }
      bottom = Math.max(bottom, bodyTop + GROUP_MIN_BODY);
    } else if (bbox) {
      bodyTop = bbox.t - GROUP_PAD;
      bottom = bbox.b + GROUP_PAD;
    } else {
      bodyTop = cy + hdr0;
      bottom = bodyTop + GROUP_EMPTY_HEIGHT;
    }
    const top = bodyTop - hdr; // extra header (shown details) grows upward
    box.y = top;
    if (!manual && bbox) {
      box.anchorX = left - dx; // the anchor follows the cards' top-left corners
      box.anchorY = bodyTop - hdr0 - dy;
    }
    box.h = c.collapsed ? hdr : bottom - top;
    box.closedH = box.h;
  } else {
    box.h = y;
  }
  return box;
}

/** A strand card is its title bar (the strand's name); its details show the strand's
 *  description, then its fields that have a value. */
function layoutStrand(box: CardBox, ctx: Ctx, inner: number): void {
  const { m } = ctx;
  const c = box.card;
  box.tooltip = `${STRAND_KIND_NAMES[c.strand_kind] ?? "Strand"}: ${c.strand}`;
  let y = (box.closedH = HEADER_HEIGHT);
  if (box.detailsVisible) {
    y += PAD;
    const info = ctx.strands.get(strandKey(c.strand_kind, c.strand));
    const desc = info ? strip(info.description) : "";
    const fields = info ? info.fields.filter(([, v]) => v).map(([n, v]) => `${n}: ${v}`) : [];
    let texts: [string, FontKey, Block["role"]][] = [
      ...(desc ? [[desc, "small", "text"] as [string, FontKey, Block["role"]]] : []),
      ...fields.map((line) => [line, "small", "text"] as [string, FontKey, Block["role"]]),
    ];
    if (!texts.length) texts = [["No description yet.", "smallItalic", "muted"]];
    texts.forEach(([text, font, role], n) => {
      if (n) y += n === 1 && desc ? PAD / 2 : 2;
      const b = textBlock(m, PAD, y, inner, text, font, role);
      box.blocks.push(b);
      y += b.h;
    });
    y += PAD;
  }
  box.headerH = HEADER_HEIGHT;
  box.h = y;
}

/** Where arrows meet a card: the card as it looks with details hidden, so showing details
 *  doesn't move its arrows. Groups: the whole frame. */
export function anchorRect(b: CardBox): Rect {
  return b.isGroup ? { x: b.x, y: b.y, w: b.w, h: b.h } : { x: b.x, y: b.y, w: b.w, h: Math.min(b.closedH, b.h) };
}

/** A group's frame below its header panel: where its cards sit. */
export function bodyRect(b: CardBox): Rect {
  return { x: b.x, y: b.y + b.headerH, w: b.w, h: b.h - b.headerH };
}

/** Only plain and strand cards get a connection handle, and only when the board shows them. */
export function hasPort(b: CardBox, display: Display): boolean {
  return !b.isGroup && display.show_handles;
}

export function portCenter(b: CardBox): [number, number] {
  const y = b.isGroup ? HEADER_HEIGHT / 2 : Math.min(b.closedH, b.h) / 2;
  return [b.x + b.w, b.y + y];
}

/** A group's collapse / expand button, at the left of its title bar (card coordinates). */
export function foldRect(): Rect {
  return { x: PAD - 4, y: (HEADER_HEIGHT - FOLD_SIZE) / 2, w: FOLD_SIZE, h: FOLD_SIZE };
}

/** The ▸ that shows and hides details, at the right of the title bar (card coordinates). */
export function toggleRect(b: CardBox): Rect {
  return { x: b.w - PAD - TOGGLE_SIZE + 4, y: (HEADER_HEIGHT - TOGGLE_SIZE) / 2, w: TOGGLE_SIZE, h: TOGGLE_SIZE };
}

/** Drawing order: groups (outermost first), then cards; each in board order. Folded-away
 *  cards are left out. Arrows go between the two. */
export function paintOrder(boxes: ReadonlyMap<string, CardBox>): { groups: CardBox[]; cards: CardBox[] } {
  const all = [...boxes.values()].filter((b) => b.visible);
  const groups = all.filter((b) => b.isGroup).map((b, i) => ({ b, i }))
    .sort((p, q) => Math.min(p.b.depth, 30) - Math.min(q.b.depth, 30) || p.i - q.i).map(({ b }) => b);
  return { groups, cards: all.filter((b) => !b.isGroup) };
}

/** The extent of every visible card, or null for an empty board. */
export function boardExtent(boxes: ReadonlyMap<string, CardBox>): Rect | null {
  let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
  for (const x of boxes.values()) {
    if (!x.visible) continue;
    l = Math.min(l, x.x);
    t = Math.min(t, x.y);
    r = Math.max(r, x.x + x.w);
    b = Math.max(b, x.y + x.h);
  }
  return l === Infinity ? null : { x: l, y: t, w: r - l, h: b - t };
}

export function titleOf(c: CardData): string {
  return c.title || "Untitled";
}

