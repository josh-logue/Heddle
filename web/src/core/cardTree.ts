// The Card List's rows (heddle/card_list.py): every card under its group, in story order,
// top to bottom or A–Z, optionally narrowed to cards matching a search (keeping the groups
// round them, so you can see where each one is). Pure: the panel draws the rows.

import { searchCards } from "./filters.ts";
import type { StoryGraph } from "./graph.ts";
import { KIND_GROUP, type CardData, type StrandInfo } from "./model.ts";
import { casefold, collapseSpaces, sortedBy, splitLines, strip } from "./pystr.ts";
import { naturalKey } from "./rank.ts";

export type CardListSort = "story" | "position" | "title";
export const SORTS: [CardListSort, string][] = [["story", "Story order"], ["position", "Top to bottom"], ["title", "A–Z"]];

export interface CardListRow {
  id: string;
  depth: number;
  card: CardData;
  /** For a group: how many cards it holds directly. */
  count: number;
  /** Greyed: dimmed by the filter, or a group listed only to show where a match is. */
  muted: boolean;
  /** Where a card the search found (other than by its title) matched: [field, snippet]. */
  found: [string, string] | null;
  dimmed: boolean;
}

export interface CardListOptions {
  sort: CardListSort;
  storyTools: boolean;
  /** Narrow to cards whose title contains this (or, with fullText, anything search finds). */
  needle: string;
  fullText: boolean;
  strandInfo: ReadonlyMap<string, StrandInfo>;
  /** Cards the filter dims, and whether to leave them out instead of greying them. */
  dimmed: ReadonlySet<string>;
  hideDimmed: boolean;
}

/** Ids to keep when narrowed to `matches`: the matches and the groups round them. */
export function narrowed(children: ReadonlyMap<string, readonly string[]>, matches: Iterable<string>): Set<string> {
  const parent = new Map<string, string>();
  for (const [p, kids] of children) for (const k of kids) parent.set(k, p);
  const keep = new Set<string>();
  for (let id of matches) {
    while (id && !keep.has(id)) {
      keep.add(id);
      id = parent.get(id) ?? "";
    }
  }
  return keep;
}

export function cardListRows(graph: StoryGraph, o: CardListOptions): CardListRow[] {
  const children = graph.outline(o.sort === "story" && o.storyTools);
  const cards = graph.cards;
  if (o.sort === "title") {
    for (const [p, kids] of children) children.set(p, sortedBy(kids, (i) => naturalKey(cards.get(i)?.title ?? "")));
  }
  const needle = casefold(collapseSpaces(o.needle));
  const found = new Map<string, [string, string] | null>();
  if (needle) {
    for (const [id, c] of cards) if (casefold(collapseSpaces(strip(c.title) || "Untitled")).includes(needle)) found.set(id, null);
    if (o.fullText) {
      for (const [id, label, snippet] of searchCards(cards.values(), needle, o.strandInfo)) if (!found.has(id)) found.set(id, [label, snippet]);
    }
  }
  const keep = needle ? narrowed(children, found.keys()) : null;
  const hide = o.hideDimmed && o.dimmed.size > 0;
  const rows: CardListRow[] = [];
  const seen = new Set<string>();
  const walk = (parent: string, depth: number): boolean => {
    let listed = false;
    for (const id of children.get(parent) ?? []) {
      const card = cards.get(id);
      if (!card || seen.has(id) || (keep !== null && !keep.has(id))) continue;
      seen.add(id);
      const at = rows.length;
      rows.push(null as unknown as CardListRow); // filled once we know whether anything inside stays
      const inner = walk(id, depth + 1);
      const dimmed = o.dimmed.has(id);
      if (hide && dimmed && !inner) {
        rows.splice(at); // a hidden card, or a dimmed group with nothing left in it
        continue;
      }
      rows[at] = {
        id, depth, card, count: (children.get(id) ?? []).length, dimmed,
        muted: dimmed || (keep !== null && !found.has(id)), found: found.get(id) ?? null,
      };
      listed = true;
    }
    return listed;
  };
  walk("", 0);
  return rows;
}

/** What a row says when pointed at: the description's first line, status, and so on. */
export function rowTip(row: CardListRow): string {
  const c = row.card;
  const lines: string[] = [];
  if (row.found) lines.push(`Found in ${row.found[0].toLowerCase()}: ${row.found[1]}`);
  const first = splitLines(c.description).map(strip).find(Boolean) ?? "";
  if (first && c.kind !== KIND_GROUP) lines.push(first.length <= 120 ? first : `${first.slice(0, 117)}…`);
  if (c.status) lines.push(`Status: ${c.status}`);
  if (c.outside_story) lines.push("Not part of the story");
  if (c.kind === KIND_GROUP && c.collapsed) lines.push("Collapsed on the board");
  if (row.dimmed) lines.push("Hidden by the filter");
  return lines.join("\n");
}

/** "N of M cards", or "N cards · K groups". */
export function cardListSummary(rows: readonly CardListRow[], cards: readonly CardData[]): string {
  const groups = rows.filter((r) => r.card.kind === KIND_GROUP).length;
  const shown = rows.length - groups;
  const total = cards.filter((c) => c.kind !== KIND_GROUP).length;
  if (!cards.length) return "No cards yet";
  if (shown !== total) return `${shown} of ${total} cards`;
  return `${shown} card${shown !== 1 ? "s" : ""}${groups ? ` · ${groups} group${groups !== 1 ? "s" : ""}` : ""}`;
}
