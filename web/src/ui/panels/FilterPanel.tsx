import { useEffect, useMemo, useState } from "react";
import {
  CATEGORIES, LABELS, MATCH_ALL_CATEGORIES, NONE_KEY, collectOptions, describeCounts, type Category,
} from "../../core/filters.ts";
import { KIND_STRAND } from "../../core/model.ts";
import type { BoardStore } from "../../board/store.ts";
import { readJson, writeJson } from "../../platform/settings.ts";

const NOUNS: Record<string, string> = { tags: "tags", characters: "characters", introduces: "introductions", locations: "locations" };

/** The "match all" categories are remembered per browser, as the desktop does per machine. */
export function loadMatchAll(): Set<string> {
  const raw = readJson<string[]>("filterMatchAll", []);
  return new Set(Array.isArray(raw) ? raw.filter((c) => (MATCH_ALL_CATEGORIES as readonly string[]).includes(c)) : []);
}

/** "all tags, all characters": the "all" categories where it changes the result (2+ ticked). */
export function matchNote(store: BoardStore): string {
  return MATCH_ALL_CATEGORIES.filter((c) => store.filter.matchAll.has(c) && (store.filter.selection.get(c)?.size ?? 0) > 1)
    .map((c) => `all ${NOUNS[c]}`).join(", ");
}

/** The Filter panel (heddle/filter_panel.py): every value on the board as a checkbox, per
 *  category; cards that don't match fade out. Ticked values in one category match any of
 *  them (or, switched to "match all", every one); separate categories must all match. */
export function FilterPanel({ store }: { store: BoardStore }) {
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const story = store.state.display.story_tools;
  const version = store.version;
  const options = useMemo(
    () => collectOptions(store.state.cards.filter((c) => c.kind !== KIND_STRAND), store.filterExtras()),
    [store, version], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const { selection, matchAll } = store.filter;
  const categories = CATEGORIES.filter((c) => c !== "introduces" || story);

  // Values no card has any more (renamed, removed) drop out of the ticks.
  useEffect(() => {
    let changed = false;
    const next = new Map<string, Set<string>>();
    for (const [cat, keys] of selection) {
      const have = new Set((categories.includes(cat as Category) ? options.get(cat as Category) ?? [] : []).map(([k]) => k));
      const kept = new Set([...keys].filter((k) => have.has(k)));
      if (kept.size !== keys.size) changed = true;
      if (kept.size) next.set(cat, kept);
    }
    if (changed) store.setFilter(next, matchAll);
  });

  const toggle = (cat: string, key: string, on: boolean) => {
    const next = new Map([...selection].map(([c, k]) => [c, new Set(k)]));
    const keys = next.get(cat) ?? new Set<string>();
    if (on) keys.add(key);
    else keys.delete(key);
    next.set(cat, keys);
    store.setFilter(next, matchAll);
  };
  const setAll = (cat: string, on: boolean) => {
    const next = new Set(matchAll);
    if (on) next.add(cat);
    else next.delete(cat);
    writeJson("filterMatchAll", [...next]);
    store.setFilter(selection, next);
  };
  const active = store.filterActive;
  const alls = MATCH_ALL_CATEGORIES.filter((c) => matchAll.has(c)).map((c) => NOUNS[c]!);
  const hint = !alls.length
    ? "Ticked entries in one category match any of them; separate categories must all match."
    : `Cards need every ticked entry in ${alls.length === 1 ? alls[0] : `${alls.slice(0, -1).join(", ")} and ${alls.at(-1)}`}, and any ticked entry elsewhere; separate categories must all match.`;

  return (
    <div className="panel filter-panel">
      <div className="row between">
        <span>{active ? `Showing ${describeCounts(store.filterCounts)}` : `${describeCounts(store.filterCounts, false)} · no filter`}</span>
        <button type="button" disabled={!active} onClick={() => store.setFilter(new Map(), matchAll)}>Clear</button>
      </div>
      <div className="filter-tree">
        {categories.map((cat) => {
          const opts = options.get(cat) ?? [];
          const n = selection.get(cat)?.size ?? 0;
          const open = !folded.has(cat);
          return (
            <section key={cat} className="filter-cat">
              <div className="filter-head">
                <button type="button" className="fold" aria-expanded={open} onClick={() => {
                  const next = new Set(folded);
                  if (open) next.add(cat);
                  else next.delete(cat);
                  setFolded(next);
                }}>{open ? "▾" : "▸"} <strong>{LABELS[cat]}</strong>{n ? <span className="muted"> · {n} selected</span> : null}</button>
                {opts.length > 0 && (MATCH_ALL_CATEGORIES as readonly string[]).includes(cat) && (
                  <button type="button" className={matchAll.has(cat) ? "mode on" : "mode"} aria-pressed={matchAll.has(cat)}
                          title={matchAll.has(cat) ? `Showing only cards with every ticked ${NOUNS[cat]!.slice(0, -1)}: click to show cards with any of them`
                            : `Showing cards with any ticked ${NOUNS[cat]!.slice(0, -1)}: click to show only cards with all of them`}
                          onClick={() => setAll(cat, !matchAll.has(cat))}>{matchAll.has(cat) ? "match all" : "match any"}</button>
                )}
              </div>
              {open && (
                <ul>
                  {!opts.length && <li className="muted"><em>No cards yet</em></li>}
                  {opts.map(([key, label, count]) => (
                    <li key={key}>
                      <label>
                        <input type="checkbox" checked={selection.get(cat)?.has(key) ?? false}
                               onChange={(e) => toggle(cat, key, e.target.checked)} />
                        {cat === "color" && <span className="dot" style={{ background: key }} />}
                        <span className={key === NONE_KEY ? "none" : ""}>{label}</span>
                        <span className="muted">({count})</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      <p className="muted small-note">{hint}</p>
    </div>
  );
}
