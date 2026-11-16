// Card filtering (option collection and matching) and search: a port of
// heddle/filters.py.
//
// Values are compared case-insensitively. Within a category, checked values are OR'd;
// across categories they are AND'd. List categories can be set to "match all". An empty
// field is NONE_KEY, so "cards with no status" can be filtered too. Computed categories
// (introductions) come in as `extras`: {category: {card id: values}}.

import { COLOR_NAMES, countValues, type CardData, type StrandInfo } from "./model.ts";
import { casefold, codePoints, collapseSpaces, sortedBy, strip } from "./pystr.ts";

export interface FilterCounts {
  cards_shown: number;
  cards_total: number;
  groups_shown: number;
  groups_total: number;
}

function count(shown: number | null, total: number, noun: string): string {
  const word = total === 1 ? noun : noun + "s";
  return shown === null ? `${total} ${word}` : `${shown} of ${total} ${word}`;
}

/** '2 of 17 cards, 1 of 5 groups' (filtered) or '17 cards, 5 groups' (not). Groups are
 *  left out on a board without any. */
export function describeCounts(counts: FilterCounts, filtered = true): string {
  const parts = [count(filtered ? counts.cards_shown : null, counts.cards_total, "card")];
  if (counts.groups_total) {
    parts.push(count(filtered ? counts.groups_shown : null, counts.groups_total, "group"));
  }
  return parts.join(", ");
}

export const CATEGORIES = ["tags", "color", "characters", "pov", "introduces", "locations", "status"] as const;
export type Category = (typeof CATEGORIES)[number];
export const LABELS: Record<Category, string> = {
  tags: "Tags", color: "Color", characters: "Characters", pov: "POV",
  introduces: "Introduces", locations: "Locations", status: "Status",
};
export const MATCH_ALL_CATEGORIES: readonly Category[] = ["tags", "characters", "introduces", "locations"];
export const COMPUTED: readonly Category[] = ["introduces"];
/** {category: {card id: values}} for categories worked out from the arrows. */
export type Extras = ReadonlyMap<string, ReadonlyMap<string, readonly string[]>>;
export const NONE_KEY = "";
export const NONE_LABEL = "(none)";

/** [key, display text, number of cards]. */
export type Option = readonly [key: string, label: string, count: number];

function rawValues(card: CardData, category: Category, extras: Extras | null = null): string[] {
  if (category === "color") return [strip(card.color).toLowerCase()];
  if (COMPUTED.includes(category)) {
    return [...(extras?.get(category)?.get(card.id) ?? [])].filter((v) => strip(v));
  }
  const value = card[category as Exclude<Category, "color" | "introduces">];
  if (Array.isArray(value)) return value.map(strip).filter((v) => v);
  const v = strip(value);
  return v ? [v] : [];
}

function keyOf(category: Category, raw: string): string {
  return category === "color" ? raw : casefold(raw);
}

export function cardKeys(card: CardData, category: Category, extras: Extras | null = null): Set<string> {
  const keys = new Set(rawValues(card, category, extras).map((v) => keyOf(category, v)));
  return keys.size ? keys : new Set([NONE_KEY]);
}

export function displayFor(category: Category, raw: string): string {
  return category === "color" ? (COLOR_NAMES.get(raw) ?? raw) : raw;
}

/** Distinct values per category, with card counts, sorted alphabetically, "(none)" last.
 *  Text fields use model.countValues (first spelling shown). */
export function collectOptions(cardsIn: Iterable<CardData>, extras: Extras | null = null): Map<Category, Option[]> {
  const cards = [...cardsIn];
  const result = new Map<Category, Option[]>();
  for (const cat of CATEGORIES) {
    let counted: Map<string, [string, number]>;
    if (cat === "color" || COMPUTED.includes(cat)) {
      counted = new Map();
      for (const card of cards) {
        const seen = new Set<string>();
        for (const raw of rawValues(card, cat, extras)) {
          const key = keyOf(cat, raw);
          if (seen.has(key)) continue;
          seen.add(key);
          const [name, n] = counted.get(key) ?? [displayFor(cat, raw), 0];
          counted.set(key, [name, n + 1]);
        }
      }
    } else {
      counted = countValues(cards, cat);
    }
    const options: Option[] = sortedBy(
      [...counted].map(([k, [name, n]]) => [k, name, n] as const), (o) => casefold(o[1]));
    const empty = cards.filter((card) => !rawValues(card, cat, extras).length).length;
    if (empty) options.push([NONE_KEY, NONE_LABEL, empty]);
    result.set(cat, options);
  }
  return result;
}

export const SEARCH_FIELDS = [["title", "Title"], ["description", "Description"], ["notes", "Notes"]] as const;
export const SEARCH_STRANDS = [
  ["tags", "Tag"], ["characters", "Character"], ["locations", "Location"], ["status", "Status"],
] as const;
export const SNIPPET_CHARS = 30;

/** Python's text.find() on code points: the index of `needle` in `hay`, or -1. */
function findCodePoint(hay: string, needle: string): number {
  const at = hay.indexOf(needle);
  return at < 0 ? -1 : codePoints(hay.slice(0, at)).length;
}

function snippet(textIn: string, needle: string): string | null {
  const text = codePoints(collapseSpaces(textIn)); // line breaks flattened
  // Found in the case-folded text, then cut from the original (as Python does).
  const at = findCodePoint(casefold(text.join("")), needle);
  if (at < 0) return null;
  const start = Math.max(0, at - SNIPPET_CHARS);
  const end = Math.min(text.length, at + codePoints(needle).length + SNIPPET_CHARS);
  return (start ? "…" : "") + text.slice(start, end).join("") + (end < text.length ? "…" : "");
}

/** [kind, name] of every strand the card has, or that a strand card stands for. */
function cardStrands(card: CardData): [string, string][] {
  if (card.kind === "strand") {
    return card.strand_kind && card.strand ? [[card.strand_kind, card.strand]] : [];
  }
  const out: [string, string][] = [];
  for (const kind of ["tags", "characters", "locations"] as const) for (const v of card[kind]) out.push([kind, v]);
  if (card.status) out.push(["status", card.status]);
  return out;
}

/** Cards whose text or strands contain `query` (ignoring case), in the order given:
 *  [card id, field label, snippet around the first match]. Text first (title,
 *  description, notes), then the card's strands, then the descriptions of its strands
 *  (`strandInfo`: {strandKey(kind, name): StrandInfo}), then their field values. */
export function searchCards(
  cards: Iterable<CardData>, query: string, strandInfo: ReadonlyMap<string, StrandInfo> | null = null,
): [string, string, string][] {
  const needle = casefold(collapseSpaces(query));
  if (!needle) return [];
  const labels = new Map<string, string>(SEARCH_STRANDS);
  const found: [string, string, string][] = [];
  for (const card of cards) {
    let hit: [string, string] | null = null;
    for (const [name, label] of SEARCH_FIELDS) {
      const s = snippet(card[name], needle);
      if (s !== null) {
        hit = [label, s];
        break;
      }
    }
    const strands = cardStrands(card);
    if (hit === null) {
      const m = strands.find(([, name]) => casefold(name).includes(needle));
      if (m) hit = [labels.get(m[0]) ?? "Strand", m[1]];
    }
    if (hit === null && strandInfo && strandInfo.size) {
      const infos: [string, StrandInfo][] = [];
      for (const [kind, name] of strands) {
        const info = strandInfo.get(`${kind}\u0000${casefold(name)}`);
        if (info !== undefined) infos.push([name, info]);
      }
      for (const [name, info] of infos) {
        const s = snippet(info.description, needle);
        if (s !== null) {
          hit = [`${name}’s description`, s];
          break;
        }
      }
      // Then the strands' field values (never the field names).
      outer: for (const [name, info] of hit === null ? infos : []) {
        for (const [field, value] of info.fields) {
          const s = snippet(value, needle);
          if (s !== null) {
            hit = [`${name}’s ${field}`, s];
            break outer;
          }
        }
      }
    }
    if (hit !== null) found.push([card.id, ...hit]);
  }
  return found;
}

/** Whether `card` passes the filter. `matchAll` names the categories where a card needs
 *  every ticked entry; only MATCH_ALL_CATEGORIES take part. */
export function matches(
  card: CardData, selection: ReadonlyMap<string, ReadonlySet<string>>,
  matchAll: Iterable<string> = [], extras: Extras | null = null,
): boolean {
  if (card.kind === "strand") return strandCardMatches(card, selection);
  const all = new Set([...matchAll].filter((c) => (MATCH_ALL_CATEGORIES as readonly string[]).includes(c)));
  for (const [cat, selected] of selection) {
    if (!selected.size) continue;
    const keys = cardKeys(card, cat as Category, extras);
    if (all.has(cat)) {
      for (const k of selected) if (!keys.has(k)) return false;
    } else if (![...keys].some((k) => selected.has(k))) {
      return false;
    }
  }
  return true;
}

/** A strand card stays lit when its own strand is ticked (a character also under POV or
 *  Introduces), or its colour is; other categories don't apply to it. */
function strandCardMatches(card: CardData, selection: ReadonlyMap<string, ReadonlySet<string>>): boolean {
  const active = new Set([...selection].filter(([, s]) => s.size).map(([c]) => c));
  if (!active.size) return true;
  const key = casefold(card.strand);
  const cats = [card.strand_kind, ...(card.strand_kind === "characters" ? ["pov", "introduces"] : [])];
  if (cats.some((c) => selection.get(c)?.has(key))) return true;
  return active.has("color") && selection.get("color")!.has(card.color.toLowerCase());
}
