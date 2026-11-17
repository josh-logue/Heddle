import { useEffect, useMemo, useState } from "react";
import {
  CATEGORIES, LABELS, MATCH_ALL_CATEGORIES, NONE_KEY, cardKeys, collectOptions, describeCounts, type Category, type Option,
} from "../../core/filters.ts";
import { KIND_STRAND, type StrandKind } from "../../core/model.ts";
import { casefold } from "../../core/pystr.ts";
import type { BoardStore } from "../../board/store.ts";
import { readJson, writeJson } from "../../platform/settings.ts";
import type { MenuItem } from "../../canvas/menus.ts";

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

/** A value's right-click menu (heddle/filter_panel._context_menu): POV and Introduces
 *  values are characters, so they show threads too. */
function valueMenu(store: BoardStore, cat: string, value: string): MenuItem[] {
  const field = ["characters", "pov", "introduces"].includes(cat) ? "characters" : cat;
  const items: MenuItem[] = [];
  if (field === "characters" && store.state.display.story_tools) {
    items.push({ label: `Show thread of “${value}”`, action: () => store.showThread(value) });
  }
  return items;
}

/** The Filter panel (heddle/filter_panel.py): every value on the board as a checkbox, per
 *  category; cards that don't match fade out. Ticked values in one category match any of
 *  them (or, switched to "match all", every one); separate categories must all match. */
/** The kind of strand group each category lists: POV and Introduces are characters. */
const GROUP_KINDS: Partial<Record<Category, StrandKind>> = {
  tags: "tags", characters: "characters", pov: "characters", introduces: "characters", locations: "locations", status: "status",
};

export function FilterPanel({ store, onMenu }: {
  store: BoardStore;
  /** A value's right-click menu: a character's (POV, introduction's) thread, a rename. */
  onMenu?: (items: MenuItem[], x: number, y: number) => void;
}) {
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const story = store.state.display.story_tools;
  const state = store.state; // (the options change only with the board, not the selection)
  const options = useMemo(
    () => collectOptions(store.state.cards.filter((c) => c.kind !== KIND_STRAND), store.filterExtras()),
    [store, state], // eslint-disable-line react-hooks/exhaustive-deps
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

  /** Tick or untick values: one (a strand) or several (a strand group's strands). */
  const toggle = (cat: string, key: string | readonly string[], on: boolean) => {
    const next = new Map([...selection].map(([c, k]) => [c, new Set(k)]));
    const keys = next.get(cat) ?? new Set<string>();
    for (const k of typeof key === "string" ? [key] : key) {
      if (on) keys.add(k);
      else keys.delete(k);
    }
    next.set(cat, keys);
    store.setFilter(next, matchAll);
  };
  const cards = store.state.cards.filter((c) => c.kind !== KIND_STRAND);
  const extras = store.filterExtras();
  /** A category's strand groups with the strands cards use there (others have nothing to
   *  show), and how many cards have any of them. Character groups also list under POV and
   *  Introduces. */
  const groupsFor = (cat: Category, opts: readonly Option[]) => {
    const kind = GROUP_KINDS[cat];
    if (!kind) return [];
    const have = new Map(opts.map((o) => [o[0], o]));
    return store.groupsOf(kind).flatMap((g) => {
      const members = g.members.map((m) => have.get(casefold(m))).filter((o): o is Option => !!o);
      if (!members.length) return [];
      const keys = new Set(members.map(([k]) => k));
      const n = cards.filter((c) => [...cardKeys(c, cat, extras)].some((k) => keys.has(k))).length;
      return [{ name: g.name, members, keys: [...keys], n }];
    });
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
  const groupsInAll = MATCH_ALL_CATEGORIES.some((c) => matchAll.has(c) && GROUP_KINDS[c] && store.groupsOf(GROUP_KINDS[c]!).length);
  const hint = !alls.length
    ? "Ticked entries in one category match any of them; separate categories must all match."
    : `Cards need every ticked entry in ${alls.length === 1 ? alls[0] : `${alls.slice(0, -1).join(", ")} and ${alls.at(-1)}`}, and any ticked entry elsewhere; separate categories must all match.`
      + (groupsInAll ? " A ticked strand group there needs every strand in it." : "");

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
                  {(() => {
                    const entry = ([key, label, count]: Option, group?: string) => (
                      <li key={`${group ?? ""}/${key}`} className={group !== undefined ? "member" : undefined} onContextMenu={(e) => {
                        const items = key === NONE_KEY || !onMenu ? [] : valueMenu(store, cat, label);
                        if (!items.length) return;
                        e.preventDefault();
                        onMenu!(items, e.clientX, e.clientY);
                      }}>
                        <label>
                          <input type="checkbox" checked={selection.get(cat)?.has(key) ?? false}
                                 onChange={(e) => toggle(cat, key, e.target.checked)} />
                          {cat === "color" && <span className="dot" style={{ background: key }} />}
                          <span className={key === NONE_KEY ? "none" : ""}>{label}</span>
                          <span className="muted">({count})</span>
                        </label>
                      </li>
                    );
                    const groups = groupsFor(cat, opts);
                    const grouped = new Set(groups.flatMap((g) => g.keys));
                    const ticked = selection.get(cat) ?? new Set<string>();
                    return [
                      ...groups.flatMap((g) => {
                        const fold = `${cat}/${casefold(g.name)}`;
                        const gOpen = !folded.has(fold);
                        const n = g.keys.filter((k) => ticked.has(k)).length;
                        return [
                          <li key={`group:${g.name}`} className="strand-group"
                              title={`Strand group: ticking it ticks all ${g.keys.length} of its strands on cards (${g.n} card${g.n === 1 ? "" : "s"} have one)`}>
                            <button type="button" className="fold inline" aria-expanded={gOpen} aria-label={gOpen ? `Fold ${g.name}` : `Unfold ${g.name}`}
                                    onClick={() => {
                                      const next = new Set(folded);
                                      if (gOpen) next.add(fold);
                                      else next.delete(fold);
                                      setFolded(next);
                                    }}>{gOpen ? "▾" : "▸"}</button>
                            <label>
                              {/* Partly ticked when only some of its strands are; a click ticks them all. */}
                              <input type="checkbox" aria-label={`Strand group ${g.name}`} checked={n === g.keys.length}
                                     ref={(el) => { if (el) el.indeterminate = n > 0 && n < g.keys.length; }}
                                     onChange={() => toggle(cat, g.keys, n < g.keys.length)} />
                              <strong>{g.name}</strong>
                              <span className="muted">({g.n})</span>
                            </label>
                          </li>,
                          ...(gOpen ? g.members.map((o) => entry(o, g.name)) : []),
                        ];
                      }),
                      ...opts.filter(([k]) => !grouped.has(k)).map((o) => entry(o)),
                    ];
                  })()}
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
