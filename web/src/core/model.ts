// Plain data model for a board, plus JSON loading and saving: a port of heddle/model.py.
//
// Cards, arrows, routes and strands are plain mutable objects, built and cleaned by the
// make* functions (Python does this in each dataclass's __post_init__). Anything keyed
// by card id or by user text is a Map, never a plain object: objects list integer-like
// keys ("7", "2024") first, which would reorder year groups, strand names and ids.
//
// Left out on purpose (no file paths in a browser): picture_for_file, picture_from_file,
// strands_for_file, strands_from_file, save_board, load_board. Pictures are kept as
// written. Reading and writing files lives in platform/.

import { casefold, escapeRegExp, sortedBy, splitLines, strip } from "./pystr.ts";

export const APP_ID = "Heddle";
/** Kept as an alias: W0 named it APP_NAME. */
export const APP_NAME = APP_ID;
// The version history lives in heddle/model.py's comments.
export const FORMAT_VERSION = 12;
/** The largest row limit a group can have (steps per row when auto-arranging). */
export const ARRANGE_WRAP_MAX = 99;

export const ARROW_STYLES = ["solid", "dashed", "dotted"] as const;
export const ARROW_ROUTINGS = ["straight", "curved", "avoid"] as const;
export type ArrowStyle = (typeof ARROW_STYLES)[number];
export type ArrowRouting = (typeof ARROW_ROUTINGS)[number];

/** Per-board display options and their defaults (see heddle/model.py for each one). */
export const DISPLAY_DEFAULTS = {
  show_pov: true,
  show_characters: false,
  show_tags: true,
  show_introductions: true,
  show_group_count: true,
  show_shadows: true,
  show_no_description: true,
  show_description: true,
  compact_cards: false,
  show_handles: true,
  show_arrow_labels: true,
  show_grid: true,
  arrow_routing: "straight" as ArrowRouting,
  story_tools: true,
  follow_paths: false,
};
export type Display = typeof DISPLAY_DEFAULTS;
export type DisplayToggle = { [K in keyof Display]: Display[K] extends boolean ? K : never }[keyof Display];
/** The on/off options (everything but arrow_routing), in order. */
export const DISPLAY_TOGGLES = Object.keys(DISPLAY_DEFAULTS).filter(
  (k) => typeof DISPLAY_DEFAULTS[k as keyof Display] === "boolean",
) as DisplayToggle[];

export const KIND_CARD = "card";
export const KIND_GROUP = "group";
export const KIND_STRAND = "strand";
export type CardKind = typeof KIND_CARD | typeof KIND_GROUP | typeof KIND_STRAND;

export const LIST_FIELDS = ["tags", "characters", "locations"] as const;
export type ListField = (typeof LIST_FIELDS)[number];

export const CARD_COLORS = [
  "#4a7fc1", // blue
  "#d9822b", // orange
  "#3f9e6e", // green
  "#b8475b", // red
  "#7b5ea7", // purple
  "#2a9aa6", // teal
  "#c9a227", // mustard
  "#6b6b6b", // gray
] as const;
const DEFAULT_COLOR: string = CARD_COLORS[0];
export const COLOR_NAMES: ReadonlyMap<string, string> = new Map(
  CARD_COLORS.map((c, i) => [c, ["Blue", "Orange", "Green", "Red", "Purple", "Teal", "Mustard", "Gray"][i]!]),
);

function randomId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 12);
}

let idMaker: () => string = randomId;

/** A fresh card or arrow id: 12 hex digits, as the desktop app makes them. */
export function newId(): string {
  return idMaker();
}

/** Tests only: make ids predictably (null restores random ids). The shared fixtures
 *  number the ids the loader makes up ("new1", "new2", …). */
export function setIdMaker(maker: (() => string) | null): void {
  idMaker = maker ?? randomId;
}

// ----- coercion of values straight from a file ------------------------------------------

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

/** Strings pass through; numbers become text; anything else (null, lists…) is blank. */
export function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return pyNumberText(value);
  return "";
}

/** str() of a number as Python writes it, for the cases a board file can hold. */
function pyNumberText(n: number): string {
  if (Number.isNaN(n)) return "nan";
  if (!Number.isFinite(n)) return n > 0 ? "inf" : "-inf";
  // JSON can't tell 5 from 5.0 once parsed: whole numbers read as Python ints.
  return String(n);
}

/** A finite number, or 0 for anything else (null, strings, NaN, infinity, booleans). */
export function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** A row limit from the file: a whole number from 0 (no limit) to ARRANGE_WRAP_MAX. */
export function asWrap(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(ARRANGE_WRAP_MAX, Math.trunc(value)));
}

export function isHexColor(value: unknown): value is string {
  return typeof value === "string" && HEX_COLOR.test(strip(value));
}

function asColor(value: unknown): string {
  return isHexColor(value) ? strip(value).toLowerCase() : DEFAULT_COLOR;
}

/** Board display options: the defaults, overridden by any valid saved values. */
export function cleanDisplay(raw: unknown): Display {
  const out: Display = { ...DISPLAY_DEFAULTS };
  if (isRecord(raw)) {
    for (const key of DISPLAY_TOGGLES) {
      if (typeof raw[key] === "boolean") out[key] = raw[key] as boolean;
    }
    if ((ARROW_ROUTINGS as readonly unknown[]).includes(raw.arrow_routing)) {
      out.arrow_routing = raw.arrow_routing as ArrowRouting;
    }
  }
  return out;
}

/** Normalise a list field: accepts a list or a comma-separated string (v1 files), strips
 *  blanks, and drops case-insensitive duplicates keeping the first spelling. */
export function cleanList(values: unknown): string[] {
  let items: unknown[];
  if (typeof values === "string") items = values.split(",");
  else if (Array.isArray(values)) items = values;
  else return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of items) {
    if (typeof raw !== "string") continue;
    const v = strip(raw);
    const key = casefold(v);
    if (v && !seen.has(key)) {
      seen.add(key);
      out.push(v);
    }
  }
  return out;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The POV character is one of the characters, spelled one way. */
function fixPov(item: { pov: string; characters: string[] }): void {
  if (!item.pov) return;
  const key = casefold(item.pov);
  const match = item.characters.find((c) => casefold(c) === key);
  if (match === undefined) item.characters.push(item.pov);
  else item.pov = match;
}

// ----- cards -------------------------------------------------------------------------------

export interface CardData {
  id: string;
  title: string;
  description: string;
  color: string;
  tags: string[];
  characters: string[];
  pov: string;
  locations: string[];
  status: string;
  notes: string;
  x: number;
  y: number;
  kind: CardKind;
  parent: string;
  width: number;
  height: number;
  arrange_by_color: boolean;
  arrange_vertical: boolean;
  arrange_grid: boolean;
  arrange_wrap: number;
  outside_story: boolean;
  collapsed: boolean;
  strand_kind: string;
  strand: string;
}

/** The saved field order (Python's dataclass order), used when writing a file. */
export const CARD_FIELDS = [
  "id", "title", "description", "color", "tags", "characters", "pov", "locations", "status",
  "notes", "x", "y", "kind", "parent", "width", "height", "arrange_by_color",
  "arrange_vertical", "arrange_grid", "arrange_wrap", "outside_story", "collapsed",
  "strand_kind", "strand",
] as const satisfies readonly (keyof CardData)[];

/** A card from any values (e.g. straight from a damaged file), every field coerced to its
 *  proper type rather than failing later on screen. */
export function makeCard(raw: Record<string, unknown> = {}): CardData {
  const get = (k: string, fallback: unknown) => (k in raw ? raw[k] : fallback);
  const id = get("id", undefined);
  const kindRaw = get("kind", KIND_CARD);
  const kind: CardKind =
    kindRaw === KIND_CARD || kindRaw === KIND_GROUP || kindRaw === KIND_STRAND ? kindRaw : KIND_CARD;
  const card: CardData = {
    id: typeof id === "string" && strip(id) ? id : newId(),
    title: asText(get("title", "New card")),
    description: asText(get("description", "")),
    color: asColor(get("color", DEFAULT_COLOR)),
    tags: cleanList(get("tags", [])),
    characters: cleanList(get("characters", [])),
    pov: strip(asText(get("pov", ""))),
    locations: cleanList(get("locations", [])),
    status: asText(get("status", "")),
    notes: asText(get("notes", "")),
    x: asNumber(get("x", 0)),
    y: asNumber(get("y", 0)),
    kind,
    parent: asText(get("parent", "")),
    width: 0,
    height: 0,
    arrange_by_color: get("arrange_by_color", false) === true,
    arrange_vertical: get("arrange_vertical", false) === true,
    arrange_grid: get("arrange_grid", false) === true,
    arrange_wrap: asWrap(get("arrange_wrap", 0)),
    outside_story: get("outside_story", false) === true,
    collapsed: false,
    strand_kind: asText(get("strand_kind", "")),
    strand: strip(asText(get("strand", ""))),
  };
  fixPov(card);
  if (card.kind === KIND_STRAND) {
    if (!["tags", "characters", "locations", "status"].includes(card.strand_kind)) {
      card.strand_kind = "characters";
    }
    card.strand = card.strand || strip(card.title) || "Untitled";
    card.title = card.strand;
    // A strand card only names its strand: it has no text or values of its own.
    card.description = card.notes = card.status = card.pov = "";
    card.tags = [];
    card.characters = [];
    card.locations = [];
    card.outside_story = false;
  } else {
    card.strand_kind = card.strand = "";
  }
  card.collapsed = get("collapsed", false) === true && card.kind === KIND_GROUP;
  for (const name of ["width", "height"] as const) {
    const value = asNumber(get(name, 0));
    card[name] = value > 0 ? value : 0;
  }
  return card;
}

/** A copy with some fields changed, cleaned again (Python's dataclasses.replace). */
export function replaceCard(card: CardData, changes: Partial<CardData>): CardData {
  return makeCard({ ...copyCard(card), ...changes });
}

/** An independent copy (its lists aren't shared). */
export function copyCard(card: CardData): CardData {
  return { ...card, tags: [...card.tags], characters: [...card.characters], locations: [...card.locations] };
}

// ----- strands (values) --------------------------------------------------------------------

export const RENAMABLE_FIELDS = ["tags", "characters", "locations", "status"] as const;
export type StrandKind = (typeof RENAMABLE_FIELDS)[number];
export const BUILTIN_STATUSES = ["Idea", "Outline", "Draft", "Revised", "Final"] as const;
export const BULK_LIST_FIELDS = ["tags", "characters", "locations"] as const;

/** Anything holding values by field: cards, and routes. */
type HasValues = Pick<CardData, ListField | "status" | "pov">;

function fieldValues(item: HasValues, field: string): string[] {
  const value = (item as unknown as Record<string, unknown>)[field];
  return Array.isArray(value) ? (value as string[]) : [value as string];
}

/** The distinct values of a text field, compared case-insensitively:
 *  {casefolded key: [display spelling, number of cards using it]}, in first-seen order.
 *  The first spelling found on a card is shown; each card counts once per value; `extra`
 *  values are included with a count of 0 unless a card already uses them. */
export function countValues(
  cards: Iterable<HasValues>, field: string, extra: Iterable<string> = [],
): Map<string, [string, number]> {
  const found = new Map<string, [string, number]>();
  for (const card of cards) {
    const seen = new Set<string>();
    for (const raw of fieldValues(card, field)) {
      const v = strip(raw);
      const key = casefold(v);
      if (!v || seen.has(key)) continue;
      seen.add(key);
      const [spelling, n] = found.get(key) ?? [v, 0];
      found.set(key, [spelling, n + 1]);
    }
  }
  for (const raw of extra) {
    const v = strip(raw);
    if (v && !found.has(casefold(v))) found.set(casefold(v), [v, 0]);
  }
  return found;
}

/** All distinct values of a field across cards plus `extra`, sorted. */
export function boardValues(cards: Iterable<HasValues>, field: string, extra: Iterable<string> = []): string[] {
  const spellings = [...countValues(cards, field, extra).values()].map(([s]) => s);
  return sortedBy(spellings, casefold);
}

/** Replace every occurrence of `old` (case-insensitive) with `new` in one field, in
 *  place. If `new` already exists the two merge, spelled as `new`. Returns the cards
 *  that changed. */
export function renameValue(cards: CardData[], field: string, old: string, newName: string): CardData[] {
  if (!(RENAMABLE_FIELDS as readonly string[]).includes(field)) {
    throw new Error(`Field '${field}' cannot be renamed.`);
  }
  const oldKey = casefold(strip(old));
  const name = strip(newName);
  if (!oldKey || !name) return [];
  const targets = new Set([oldKey, casefold(name)]);
  const changed: CardData[] = [];
  for (const card of cards) {
    let touched = false;
    if (field === "status") {
      if (targets.has(casefold(strip(card.status))) && card.status !== name) {
        card.status = name;
        touched = true;
      }
    } else {
      const f = field as ListField;
      const value = card[f];
      const updated = cleanList(value.map((v) => (targets.has(casefold(v)) ? name : v)));
      if (!listsEqual(updated, value)) {
        card[f] = updated;
        touched = true;
      }
    }
    // The POV is one of the card's characters, so it's renamed along with them.
    if (field === "characters" && targets.has(casefold(card.pov)) && card.pov !== name) {
      card.pov = name;
      touched = true;
    }
    if (touched) changed.push(card);
  }
  return changed;
}

function listsEqual(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

// ----- arrows --------------------------------------------------------------------------

export interface ConnectionData {
  source: string;
  target: string;
  label: string;
  id: string;
  style: ArrowStyle;
  color: string; // "#rrggbb", or "" for the theme's arrow color
}

export const CONNECTION_FIELDS = ["source", "target", "label", "id", "style", "color"] as const;

/** An arrow from any values. `source` and `target` are required (an arrow without them
 *  is too damaged to load); everything else is coerced. */
export function makeConnection(raw: Record<string, unknown>): ConnectionData {
  if (!("source" in raw) || !("target" in raw)) throw new TypeError("An arrow needs a source and a target.");
  const id = raw.id;
  const style = raw.style;
  return {
    source: asText(raw.source),
    target: asText(raw.target),
    label: asText("label" in raw ? raw.label : ""),
    id: typeof id === "string" && strip(id) ? id : newId(),
    style: (ARROW_STYLES as readonly unknown[]).includes(style) ? (style as ArrowStyle) : "solid",
    color: isHexColor(raw.color) ? asColor(raw.color) : "",
  };
}

// ----- routes --------------------------------------------------------------------------

/** Fields given to one route through the story. `key` names the route: its stops' card
 *  ids in order, a loop's ids sorted and joined by "+" (see graph.Route.key). */
export interface RouteData {
  key: string[];
  name: string;
  tags: string[];
  characters: string[];
  pov: string;
  locations: string[];
  status: string;
  notes: string;
  inherit: boolean;
}

export const ROUTE_FIELDS = [
  "key", "name", "tags", "characters", "pov", "locations", "status", "notes", "inherit",
] as const;

export function makeRoute(raw: Record<string, unknown> = {}): RouteData {
  const key = Array.isArray(raw.key) ? raw.key : [];
  const route: RouteData = {
    key: key.filter((k): k is string => typeof k === "string" && strip(k) !== "").map(strip),
    name: asText(raw.name ?? ""),
    tags: cleanList(raw.tags),
    characters: cleanList(raw.characters),
    pov: strip(asText(raw.pov ?? "")),
    locations: cleanList(raw.locations),
    status: asText(raw.status ?? ""),
    notes: asText(raw.notes ?? ""),
    inherit: raw.inherit === true,
  };
  fixPov(route);
  return route;
}

/** Nothing set: such a route isn't saved. */
export function routeIsBlank(r: RouteData): boolean {
  return !(strip(r.name) || r.tags.length || r.characters.length || r.pov || r.locations.length
    || strip(r.status) || strip(r.notes) || r.inherit);
}

/** An independent copy (its lists aren't shared). */
export function copyRoute(r: RouteData): RouteData {
  return { ...r, key: [...r.key], tags: [...r.tags], characters: [...r.characters], locations: [...r.locations] };
}

/** A route key as a single string, for use as a Map key (keys are tuples in Python). */
export function routeKeyId(key: readonly string[]): string {
  return JSON.stringify(key);
}

/** Saved route fields: well-formed, not blank, one per route (the first wins). */
export function cleanRoutes(raw: unknown): RouteData[] {
  const out: RouteData[] = [];
  const seen = new Set<string>();
  for (const entry of Array.isArray(raw) ? raw : []) {
    if (!isRecord(entry)) continue;
    const route = makeRoute(entry);
    const id = routeKeyId(route.key);
    if (route.key.length && !seen.has(id) && !routeIsBlank(route)) {
      seen.add(id);
      out.push(route);
    }
  }
  return out;
}

// ----- strand details ------------------------------------------------------------------

export type StrandField = readonly [name: string, value: string];

/** Text for a strand field's name or value: one line, trimmed. */
function oneLine(value: unknown): string {
  return strip(splitLines(asText(value)).join(" "));
}

/** A strand's custom fields as ordered [name, value] pairs. Accepts the saved form
 *  ({"name", "value"} objects) or pairs. Nameless entries are dropped and a name used
 *  twice (ignoring case) keeps its first entry. */
export function cleanFields(raw: unknown): StrandField[] {
  const out: StrandField[] = [];
  const seen = new Set<string>();
  for (const entry of Array.isArray(raw) ? raw : []) {
    let name: unknown;
    let value: unknown;
    if (isRecord(entry)) {
      name = entry.name;
      value = entry.value;
    } else if (Array.isArray(entry) && entry.length === 2) {
      [name, value] = entry;
    } else {
      continue;
    }
    const n = oneLine(name);
    if (n && !seen.has(casefold(n))) {
      seen.add(casefold(n));
      out.push([n, oneLine(value)]);
    }
  }
  return out;
}

/** The fields of a strand renamed onto `target`'s strand: the target's fields in its
 *  order with its values kept (an empty one takes the other's), then the fields only
 *  the renamed strand had. */
export function mergeFields(target: readonly StrandField[], moving: readonly StrandField[]): StrandField[] {
  const theirs = new Map(moving.map(([n, v]) => [casefold(n), v]));
  const merged: StrandField[] = target.map(([n, v]) => [n, v || (theirs.get(casefold(n)) ?? "")]);
  const have = new Set(target.map(([n]) => casefold(n)));
  for (const [n, v] of moving) if (!have.has(casefold(n))) merged.push([n, v]);
  return merged;
}

/** `target`'s fields after applying `source`'s to it: the source fields it lacks
 *  (ignoring case) are added at the end in the source's order, empty unless
 *  `withValues`. Existing fields keep their place and values, except that `withValues`
 *  fills an empty one. `names` limits which source fields are applied. */
export function applyFields(
  source: readonly StrandField[], target: readonly StrandField[],
  names: Iterable<string> | null = null, withValues = false,
): StrandField[] {
  const wanted = names === null ? null : new Set([...names].map((n) => casefold(strip(n))));
  const picked = source.filter(([n]) => wanted === null || wanted.has(casefold(n)));
  const given = new Map(picked.map(([n, v]) => [casefold(n), v]));
  const out: StrandField[] = target.map(([n, v]) =>
    withValues ? [n, v || (given.get(casefold(n)) ?? "")] : [n, v]);
  const have = new Set(target.map(([n]) => casefold(n)));
  for (const [n, v] of picked) if (!have.has(casefold(n))) out.push([n, withValues ? v : ""]);
  return out;
}

/** A strand's own details (Strands panel). `picture` is kept exactly as the file has it. */
export interface StrandInfo {
  kind: StrandKind | "";
  name: string;
  description: string;
  picture: string;
  fields: StrandField[];
}

export function makeStrandInfo(raw: Record<string, unknown> = {}): StrandInfo {
  const kind = "kind" in raw ? raw.kind : "tags";
  return {
    kind: (RENAMABLE_FIELDS as readonly unknown[]).includes(kind) ? (kind as StrandKind) : "",
    name: strip(asText(raw.name ?? "")),
    description: asText(raw.description ?? ""),
    picture: strip(asText(raw.picture ?? "")),
    fields: cleanFields(raw.fields),
  };
}

/** (kind, casefolded name), joined into one string for use as a Map key. */
export function strandKey(kind: string, name: string): string {
  return `${kind}\u0000${casefold(name)}`;
}

export function strandInfoKey(s: StrandInfo): string {
  return strandKey(s.kind, s.name);
}

export function strandIsBlank(s: StrandInfo): boolean {
  // Field names alone count: applying fields to a strand must survive a save.
  return !(strip(s.description) || s.picture || s.fields.length);
}

export function strandToDict(s: StrandInfo): Record<string, unknown> {
  return {
    kind: s.kind, name: s.name, description: s.description, picture: s.picture,
    fields: s.fields.map(([name, value]) => ({ name, value })),
  };
}

/** Saved strand details: well-formed, not blank, one per strand (the first wins). */
export function cleanStrands(raw: unknown): StrandInfo[] {
  const out: StrandInfo[] = [];
  const seen = new Set<string>();
  for (const entry of Array.isArray(raw) ? raw : []) {
    if (!isRecord(entry)) continue;
    const info = makeStrandInfo(entry);
    const key = strandInfoKey(info);
    if (info.kind && info.name && !strandIsBlank(info) && !seen.has(key)) {
      seen.add(key);
      out.push(info);
    }
  }
  return out;
}

// ----- the board -----------------------------------------------------------------------

export type SavedValues = Partial<Record<StrandKind, string[]>>;

export interface BoardData {
  cards: CardData[];
  connections: ConnectionData[];
  custom_colors: string[];
  saved_values: SavedValues;
  display: Display;
  routes: RouteData[];
  strands: StrandInfo[];
  /** The format version the board was read from (not saved). */
  source_version: number;
  /** What loading had to repair, in words: shown once on opening, never saved. */
  load_notes: string[];
}

export function makeBoard(parts: Partial<BoardData> = {}): BoardData {
  return {
    cards: parts.cards ?? [],
    connections: parts.connections ?? [],
    custom_colors: parts.custom_colors ?? [],
    saved_values: parts.saved_values ?? {},
    display: parts.display ?? { ...DISPLAY_DEFAULTS },
    routes: parts.routes ?? [],
    strands: parts.strands ?? [],
    source_version: parts.source_version ?? FORMAT_VERSION,
    load_notes: parts.load_notes ?? [],
  };
}

/** Every value of a field on this board: used on cards, by routes, or saved. */
export function allValues(board: BoardData, field: StrandKind): string[] {
  const extra = [...(board.saved_values[field] ?? [])];
  for (const [spelling] of countValues(board.routes, field).values()) extra.push(spelling);
  for (const s of board.strands) if (s.kind === field) extra.push(s.name);
  return boardValues(board.cards, field, extra);
}

export function fromNewerVersion(board: BoardData): boolean {
  return board.source_version > FORMAT_VERSION;
}

function pick<T extends object>(item: T, names: readonly (keyof T)[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const n of names) {
    const v = item[n];
    out[n as string] = Array.isArray(v) ? [...v] : v;
  }
  return out;
}

/** The board as saved, with keys in the same order as the desktop app writes them. */
export function boardToDict(board: BoardData): Record<string, unknown> {
  const saved: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(board.saved_values)) if (v && v.length) saved[k] = [...v];
  return {
    app: APP_ID,
    version: FORMAT_VERSION,
    custom_colors: [...board.custom_colors],
    saved_values: saved,
    display: cleanDisplay(board.display),
    cards: board.cards.map((c) => pick(c, CARD_FIELDS)),
    connections: board.connections.map((c) => pick(c, CONNECTION_FIELDS)),
    routes: board.routes.filter((r) => r.key.length && !routeIsBlank(r)).map((r) => pick(r, ROUTE_FIELDS)),
    strands: board.strands.filter((s) => s.kind && s.name && !strandIsBlank(s)).map(strandToDict),
  };
}

/** The board as file text: two-space indents, non-ASCII written as is. */
export function boardToJson(board: BoardData): string {
  return JSON.stringify(boardToDict(board), null, 2);
}

export class NotABoardError extends Error {
  constructor() {
    super("This file is not a Heddle board.");
    this.name = "NotABoardError";
  }
}

/** A board from parsed JSON. One damaged entry never makes the whole board unopenable: it
 *  is skipped, and `load_notes` says so. */
export function boardFromDict(raw: unknown): BoardData {
  if (!isRecord(raw) || !Array.isArray(raw.cards)) throw new NotABoardError();
  const notes: string[] = [];
  const rawCards = raw.cards as unknown[];
  const cards = buildAll(rawCards, makeCard);
  let renewed = renewDuplicateIds(cards); // duplicates would leave orphaned cards
  note(notes, rawCards.length - cards.length, "damaged card", "skipped");
  note(notes, renewed, "card", "given a new id (the id was used twice)");
  const rawConns = Array.isArray(raw.connections) ? (raw.connections as unknown[]) : [];
  const conns = buildAll(rawConns, makeConnection);
  // Arrows are keyed by id in the story tools: a reused id hid one of them.
  renewed = renewDuplicateIds(conns);
  note(notes, rawConns.length - conns.length, "damaged arrow", "skipped");
  note(notes, renewed, "arrow", "given a new id (the id was used twice)");
  let customs: string[];
  if (Array.isArray(raw.custom_colors)) {
    customs = raw.custom_colors.filter(
      (c): c is string => typeof c === "string" && HEX_COLOR.test(strip(c)));
  } else {
    customs = cards.map((c) => c.color); // older file: recover non-preset colors in use
  }
  const version = typeof raw.version === "number" && Number.isInteger(raw.version) ? raw.version : 1;
  return makeBoard({
    cards, connections: conns, custom_colors: dedupeColors(customs),
    saved_values: cleanSavedValues(raw.saved_values), display: cleanDisplay(raw.display),
    routes: cleanRoutes(raw.routes), strands: cleanStrands(raw.strands),
    source_version: version, load_notes: notes,
  });
}

/** A board from file text. Throws a SyntaxError for text that isn't JSON. */
export function boardFromJson(text: string): BoardData {
  return boardFromDict(JSON.parse(text));
}

export function cleanSavedValues(raw: unknown): SavedValues {
  if (!isRecord(raw)) return {};
  const out: SavedValues = {};
  for (const f of RENAMABLE_FIELDS) {
    const v = cleanList(raw[f]);
    if (v.length) out[f] = v;
  }
  return out;
}

/** Rename (case-insensitive) within a plain value list, merging duplicates. */
export function renameInList(values: readonly string[], old: string, newName: string): string[] {
  const targets = new Set([casefold(strip(old)), casefold(strip(newName))]);
  return cleanList(values.map((v) => (targets.has(casefold(v)) ? strip(newName) : v)));
}

function dedupeColors(colors: readonly string[]): string[] {
  const presets = new Set<string>(CARD_COLORS);
  const out: string[] = [];
  for (const raw of colors) {
    const c = strip(raw).toLowerCase();
    if (c && !presets.has(c) && !out.includes(c)) out.push(c);
  }
  return out;
}

/** Build each entry, leaving out the ones too damaged to build. */
function buildAll<T>(entries: readonly unknown[], build: (raw: Record<string, unknown>) => T): T[] {
  const out: T[] = [];
  for (const entry of entries) {
    if (!isRecord(entry)) continue;
    try {
      out.push(build(entry));
    } catch {
      continue;
    }
  }
  return out;
}

function renewDuplicateIds(items: { id: string }[]): number {
  const seen = new Set<string>();
  let renewed = 0;
  for (const item of items) {
    if (seen.has(item.id)) {
      item.id = newId();
      renewed++;
    }
    seen.add(item.id);
  }
  return renewed;
}

function note(notes: string[], count: number, thing: string, what: string): void {
  if (count) notes.push(`${count} ${thing}${count !== 1 ? "s" : ""} ${what}`);
}

// ----- replace -------------------------------------------------------------------------

export const REPLACE_FIELDS = [["title", "Titles"], ["description", "Descriptions"], ["notes", "Notes"]] as const;
export type TextField = "title" | "description" | "notes";

function replacePattern(find: string, matchCase: boolean): RegExp | null {
  if (!find) return null;
  return new RegExp(escapeRegExp(find), matchCase ? "gu" : "giu");
}

/** Strand cards are named by their strand, and groups have no description of their own. */
export function replaceable(card: CardData, field: string): boolean {
  if (card.kind === KIND_STRAND) return false;
  return !(card.kind === KIND_GROUP && field === "description");
}

/** [matches, cards with a match] that replaceText would change. */
export function countReplacements(
  cards: Iterable<CardData>, find: string, fields: readonly TextField[], matchCase = false,
): [number, number] {
  const pattern = replacePattern(find, matchCase);
  if (pattern === null) return [0, 0];
  let total = 0;
  let touched = 0;
  for (const card of cards) {
    let n = 0;
    for (const f of fields) if (replaceable(card, f)) n += (card[f].match(pattern) ?? []).length;
    total += n;
    if (n) touched++;
  }
  return [total, touched];
}

/** Replace `find` with `replacement` in the given text fields of each card, in place
 *  (ignoring case unless `matchCase`). Returns the cards that changed. */
export function replaceText(
  cards: Iterable<CardData>, find: string, replacement: string, fields: readonly TextField[],
  matchCase = false,
): CardData[] {
  const pattern = replacePattern(find, matchCase);
  if (pattern === null) return [];
  const changed: CardData[] = [];
  for (const card of cards) {
    const before = fields.map((f) => card[f]);
    for (const f of fields) {
      if (replaceable(card, f)) card[f] = card[f].replace(pattern, () => replacement);
    }
    if (fields.some((f, i) => card[f] !== before[i])) changed.push(card);
  }
  return changed;
}

/** Each card's title as lists show it: "Warden · East Ward" when another card has the same
 *  title (ignoring case), so the two can be told apart, else the bare title. */
export function titleLabels(cards: Iterable<CardData>): Map<string, string> {
  const list = [...cards];
  const byId = new Map(list.map((c) => [c.id, c]));
  const counts = new Map<string, number>();
  for (const c of list) {
    const key = casefold(strip(c.title));
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const out = new Map<string, string>();
  for (const c of list) {
    let title = strip(c.title) || "Untitled";
    const parent = byId.get(c.parent);
    if (counts.get(casefold(strip(c.title)))! > 1 && parent !== undefined) {
      title += ` · ${strip(parent.title) || "Untitled"}`;
    }
    out.set(c.id, title);
  }
  return out;
}

export interface BulkEdit {
  color?: string | null;
  addTags?: Iterable<string>;
  removeTags?: Iterable<string>;
  status?: string | null;
  add?: Partial<Record<ListField, Iterable<string>>>;
  remove?: Partial<Record<ListField, Iterable<string>>>;
}

/** Edit several cards at once, in place. Unset means "leave as is": color and status
 *  replace; tags, characters and locations are removed then added, matched
 *  case-insensitively. Removing a card's POV character clears its POV. Strand cards only
 *  take the color. Returns the cards that changed. */
export function applyBulkEdit(cards: CardData[], edit: BulkEdit = {}): CardData[] {
  const { color = null, status = null } = edit;
  const add = new Map<ListField, string[]>();
  const remove = new Map<ListField, string[]>();
  for (const f of BULK_LIST_FIELDS) {
    add.set(f, [...(edit.add?.[f] ?? [])]);
    remove.set(f, [...(edit.remove?.[f] ?? [])]);
  }
  add.get("tags")!.push(...(edit.addTags ?? []));
  remove.get("tags")!.push(...(edit.removeTags ?? []));
  const adding = new Map(BULK_LIST_FIELDS.map((f) => [f, cleanList(add.get(f))]));
  const removing = new Map(BULK_LIST_FIELDS.map((f) => [
    f, new Set(remove.get(f)!.filter((v) => strip(v)).map((v) => casefold(strip(v)))),
  ]));
  const snapshot = (c: CardData) => JSON.stringify([c.color, c.tags, c.characters, c.locations, c.status, c.pov]);
  const changed: CardData[] = [];
  for (const card of cards) {
    const before = snapshot(card);
    if (color !== null) card.color = color;
    if (card.kind !== KIND_STRAND) {
      for (const f of BULK_LIST_FIELDS) {
        const rm = removing.get(f)!;
        const ad = adding.get(f)!;
        if (rm.size || ad.length) card[f] = cleanList([...card[f].filter((v) => !rm.has(casefold(v))), ...ad]);
      }
      if (card.pov && removing.get("characters")!.has(casefold(card.pov))) card.pov = "";
      if (status !== null) card.status = strip(status);
    }
    if (snapshot(card) !== before) changed.push(card);
  }
  return changed;
}

export const CLIPBOARD_MIME = "application/x-heddle-fragment";

/** Copy of a board fragment with fresh ids, ready to paste: groups keep their own cards,
 *  arrows keep their (re-mapped) ends, arrows to cards outside the fragment are dropped.
 *  A card whose group isn't in the fragment stays in that group only if its id is in
 *  `keepParents`. */
export function cloneFragment(fragment: BoardData, keepParents: ReadonlySet<string> = new Set()): BoardData {
  const idMap = new Map(fragment.cards.map((c) => [c.id, newId()]));
  const cards = fragment.cards.map((c) => {
    const parent = idMap.get(c.parent) ?? (keepParents.has(c.parent) ? c.parent : "");
    return replaceCard(c, { id: idMap.get(c.id)!, parent });
  });
  const conns = fragment.connections
    .filter((e) => idMap.has(e.source) && idMap.has(e.target))
    .map((e) => ({ ...e, source: idMap.get(e.source)!, target: idMap.get(e.target)!, id: newId() }));
  return makeBoard({ cards, connections: conns, custom_colors: [...fragment.custom_colors] });
}
