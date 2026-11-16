// Ranking titles for Go to Card, and sorting titles as people expect: from
// heddle/go_to_card.py (rank) and heddle/card_list.py (natural_key).

import { casefold, collapseSpaces, compareKeys, strip, type SortKey } from "./pystr.ts";

/** How well a title matches: 0 starts with it, 1 a word starts with it, 2 contains it,
 *  null not at all. `needle` is casefolded with single spaces. */
export function rank(title: string, needle: string): number | null {
  const t = casefold(collapseSpaces(title));
  if (t.startsWith(needle)) return 0;
  if (` ${t}`.replace(/[-(]/g, " ").includes(` ${needle}`)) return 1;
  return t.includes(needle) ? 2 : null;
}

/** Sorts titles ignoring case, with "Card 2" before "Card 10". */
export function naturalKey(text: string): SortKey {
  return casefold(strip(text)).split(/(\d+)/).filter((part) => part)
    .map((part) => (/^\d+$/.test(part) ? [0, Number(part), ""] : [1, 0, part]));
}

export const compareNatural = (a: string, b: string) => compareKeys(naturalKey(a), naturalKey(b));
