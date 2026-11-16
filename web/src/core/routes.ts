// Routes through the story, as the Routes panel shows them: a port of heddle/routes.py.
//
// A route is a walk from a start to an end (graph.Route); its fields are kept on the
// board as RouteData under the route's key. With "inherit card strands" on, a route also
// shows every strand its cards have, live, listed apart from its own.

import { LOOP_JOIN, type Route, type StoryGraph } from "./graph.ts";
import { cleanList, routeKeyId, type CardData, type RouteData } from "./model.ts";
import { casefold, strip } from "./pystr.ts";

export const INHERITED_FIELDS = [
  ["tags", "Tags"], ["characters", "Characters"], ["pov", "POV"], ["locations", "Locations"], ["status", "Status"],
] as const;
export type InheritedField = (typeof INHERITED_FIELDS)[number][0];
export const MAX_LISTED = 300;
export const COMPACT_LOOP_OVER = 4;
export const LOOP_PREVIEW = 3;

type Cards = ReadonlyMap<string, CardData>;
type Labels = ReadonlyMap<string, string> | null;
type Stops = readonly (readonly string[])[] | null;

export function cardTitle(card: CardData | undefined): string {
  if (card === undefined) return "(deleted card)";
  return strip(card.title) || "Untitled";
}

function titleOf(cards: Cards, i: string, labels: Labels): string {
  if (labels !== null && labels.has(i) && cards.has(i)) return labels.get(i)!;
  return cardTitle(cards.get(i));
}

/** The card ids a route key part stands for (a loop's ids are joined). */
export function stopIds(keyPart: string): string[] {
  return keyPart.split(LOOP_JOIN);
}

export function keyCards(key: readonly string[]): string[] {
  return key.flatMap(stopIds);
}

function stopLists(key: readonly string[], stops: Stops = null): string[][] {
  return stops !== null ? stops.map((s) => [...s]) : key.map(stopIds);
}

/** 'First card → Last card' (or a single card's title). */
export function defaultTitle(key: readonly string[], cards: Cards, stops: Stops = null, labels: Labels = null): string {
  const lists = stopLists(key, stops);
  const first = lists.length ? titleOf(cards, lists[0]![0]!, labels) : "Empty route";
  if (lists.length < 2) return first;
  return `${first} → ${titleOf(cards, lists[lists.length - 1]![0]!, labels)}`;
}

export function routeTitle(
  key: readonly string[], cards: Cards, data: RouteData | null, stops: Stops = null, labels: Labels = null,
): string {
  if (data !== null && strip(data.name)) return strip(data.name);
  return defaultTitle(key, cards, stops, labels);
}

/** One line per stop: a card's title, or a loop's titles marked ↻. A loop of more than
 *  COMPACT_LOOP_OVER cards is summarised ("↻ Loop of 12 cards: A, B, C …"). */
export function stepsText(key: readonly string[], cards: Cards, stops: Stops = null, labels: Labels = null): string[] {
  return stopLists(key, stops).map((ids) => {
    if (ids.length === 1) return titleOf(cards, ids[0]!, labels);
    if (ids.length <= COMPACT_LOOP_OVER) return "↻ " + ids.map((i) => titleOf(cards, i, labels)).join(", ");
    const names = ids.slice(0, LOOP_PREVIEW).map((i) => titleOf(cards, i, labels)).join(", ");
    return `↻ Loop of ${ids.length} cards: ${names} …`;
  });
}

/** Every card of each loop that stepsText summarises, one line per loop. */
export function loopDetails(key: readonly string[], cards: Cards, stops: Stops = null, labels: Labels = null): string[] {
  return stopLists(key, stops).filter((ids) => ids.length > COMPACT_LOOP_OVER)
    .map((ids) => `Loop of ${ids.length} cards: ` + ids.map((i) => titleOf(cards, i, labels)).join(", "));
}

/** Everything the filter box looks through, case-folded. */
export function searchText(key: readonly string[], cards: Cards, data: RouteData | null, labels: Labels = null): string {
  const hay = [routeTitle(key, cards, data, null, labels), ...keyCards(key).map((i) => titleOf(cards, i, labels))];
  if (data !== null) hay.push(data.notes);
  for (const view of mergedFields(data, keyCards(key), cards).values()) hay.push(...view.own, ...view.inherited);
  return casefold(hay.join("\n"));
}

/** Every value the route's cards have, per field, in route order, without
 *  case-insensitive repeats. */
export function inheritedValues(cardIds: Iterable<string>, cards: Cards): Map<InheritedField, string[]> {
  const present = [...cardIds].filter((i) => cards.has(i)).map((i) => cards.get(i)!);
  const out = new Map<InheritedField, string[]>();
  for (const [name] of INHERITED_FIELDS) {
    const values: string[] = [];
    for (const card of present) {
      const v = card[name];
      if (Array.isArray(v)) values.push(...v);
      else values.push(v);
    }
    out.set(name, cleanList(values));
  }
  return out;
}

export interface FieldView {
  own: string[];
  inherited: string[];
}

export function mergedFields(data: RouteData | null, cardIds: Iterable<string>, cards: Cards): Map<InheritedField, FieldView> {
  const out = new Map<InheritedField, FieldView>();
  const inherit = data !== null && data.inherit;
  const fromCards = inherit ? inheritedValues(cardIds, cards) : new Map<InheritedField, string[]>();
  for (const [name] of INHERITED_FIELDS) {
    const raw = data === null ? [] : data[name];
    const own = Array.isArray(raw) ? [...raw] : strip(raw) ? [raw] : [];
    const have = new Set(own.map(casefold));
    const extra = (fromCards.get(name) ?? []).filter((v) => !have.has(casefold(v)));
    out.set(name, { own, inherited: extra });
  }
  return out;
}

/** Does a filter text appear in the route's name, card titles, notes or any value it
 *  shows (own or inherited)? */
export function matches(text: string, key: readonly string[], cards: Cards, data: RouteData | null): boolean {
  const needle = casefold(strip(text));
  return !needle || searchText(key, cards, data).includes(needle);
}

export interface RouteListing {
  routes: Route[];
  total: number;
  missing: RouteData[];
}

export function isTruncated(listing: RouteListing): boolean {
  return listing.routes.length < listing.total;
}

/** The routes to list: the first `limit` in reading order, plus any route with saved
 *  fields that's still complete; and the saved fields whose route is gone. `saved` is
 *  keyed by routeKeyId(key). */
export function listRoutes(graph: StoryGraph, saved: ReadonlyMap<string, RouteData>, limit = MAX_LISTED): RouteListing {
  const routes = graph.routes(limit);
  const total = graph.countPaths().count;
  const listed = new Set(routes.map((r) => routeKeyId(r.key)));
  const missing: RouteData[] = [];
  for (const [id, data] of saved) {
    if (listed.has(id)) continue;
    const route = graph.routeForKey(data.key);
    if (route === null) {
      missing.push(data);
    } else {
      routes.push(route);
      listed.add(id);
    }
  }
  return { routes, total, missing };
}
