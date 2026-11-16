import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { SORTS, cardListRows, cardListSummary, rowTip, type CardListSort } from "../../core/cardTree.ts";
import { KIND_GROUP, KIND_STRAND } from "../../core/model.ts";
import { STRAND_MARKS } from "../../board/metrics.ts";
import type { BoardStore } from "../../board/store.ts";
import { readJson, writeJson } from "../../platform/settings.ts";
import { strandInfoMap } from "../Tools.tsx";

const FOLDED = "⊞"; // a group collapsed on the board (as on its title bar)

interface Options {
  sort: CardListSort;
  hideDimmed: boolean;
  status: boolean;
  fullText: boolean;
}
const DEFAULTS: Options = { sort: "story", hideDimmed: false, status: false, fullText: false };

interface Props {
  store: BoardStore;
  /** Show cards picked in the list; `unfold` (Enter, double-click) opens collapsed groups
   *  to reach them and hands the keyboard to the board. */
  onShow: (ids: string[], unfold: boolean) => void;
}

/** The Card List (heddle/card_list.py): every card as a tree following the groups. Picking a
 *  row selects the card and brings it into view; selecting on the board picks its rows. */
export function CardListPanel({ store, onShow }: Props) {
  const [opts, setOpts] = useState<Options>(() => ({ ...DEFAULTS, ...readJson<Partial<Options>>("cardList", {}) }));
  const [needle, setNeedle] = useState("");
  const [closed, setClosed] = useState<Set<string>>(new Set()); // groups folded in the list, not the board
  const list = useRef<HTMLUListElement>(null);
  const setOpt = (o: Partial<Options>) => {
    const next = { ...opts, ...o };
    setOpts(next);
    writeJson("cardList", next);
  };
  const version = store.version;
  const filterOn = store.filterActive;
  const rows = useMemo(() => cardListRows(store.storyGraph(), {
    sort: opts.sort, storyTools: store.state.display.story_tools, needle, fullText: opts.fullText,
    strandInfo: strandInfoMap(store), dimmed: filterOn ? store.dimmed : new Set(), hideDimmed: opts.hideDimmed,
  }), [store, version, opts, needle, filterOn]); // eslint-disable-line react-hooks/exhaustive-deps

  // Rows under a group folded in the list are left out.
  const shown = useMemo(() => {
    const out: typeof rows = [];
    let skipBelow = Infinity;
    for (const r of rows) {
      if (r.depth > skipBelow) continue;
      skipBelow = Infinity;
      out.push(r);
      if (closed.has(r.id) && !needle) skipBelow = r.depth;
    }
    return out;
  }, [rows, closed, needle]);

  const selected = store.selected;
  const firstSelected = shown.findIndex((r) => selected.has(r.id));
  useEffect(() => { // keep the canvas's selection in view in the list
    if (firstSelected >= 0) list.current?.children[firstSelected]?.scrollIntoView({ block: "nearest" });
  }, [firstSelected]);

  const key = (e: KeyboardEvent<HTMLUListElement>) => {
    const at = Math.max(0, firstSelected);
    const step = { ArrowDown: 1, ArrowUp: -1, PageDown: 10, PageUp: -10 }[e.key];
    if (step) {
      e.preventDefault();
      const next = shown[Math.max(0, Math.min(shown.length - 1, at + step))];
      if (next) onShow([next.id], false);
    } else if (e.key === "Enter" && shown[at]) {
      e.preventDefault();
      onShow([shown[at]!.id], true);
    } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && shown[at]?.card.kind === KIND_GROUP) {
      e.preventDefault();
      const next = new Set(closed);
      if (e.key === "ArrowLeft") next.add(shown[at]!.id);
      else next.delete(shown[at]!.id);
      setClosed(next);
    }
  };

  return (
    <div className="panel card-list">
      <div className="row">
        <input type="search" className="wide-input" value={needle} aria-label="Find a card"
               placeholder={opts.fullText ? "Find a card" : "Find a card by title"}
               title={`Narrow the list to cards whose ${opts.fullText ? "title, description, notes or strands contain" : "title contains"} this (Esc clears it)`}
               onChange={(e) => setNeedle(e.target.value)}
               onKeyDown={(e) => {
                 if (e.key === "Escape") setNeedle("");
                 if ((e.key === "ArrowDown" || e.key === "Enter") && shown[0]) {
                   e.preventDefault();
                   onShow([shown[0].id], e.key === "Enter");
                   list.current?.focus();
                 }
               }} />
      </div>
      <div className="row between">
        <select value={opts.sort} aria-label="Order" onChange={(e) => setOpt({ sort: e.target.value as CardListSort })}
                title="Story order follows the arrows (top to bottom while story tools are off); cards stay in their groups whichever you pick">
          {SORTS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <span className="muted">{cardListSummary(rows, store.state.cards)}</span>
      </div>
      <div className="row wrap small-options">
        <label title="Show each card's status beside its title"><input type="checkbox" checked={opts.status} onChange={(e) => setOpt({ status: e.target.checked })} /> Status</label>
        <label title="Find cards by description, notes and strands too, not just titles"><input type="checkbox" checked={opts.fullText} onChange={(e) => setOpt({ fullText: e.target.checked })} /> Search all text</label>
        {filterOn && (
          <label title="Leave out the cards the filter fades (greyed otherwise)">
            <input type="checkbox" checked={opts.hideDimmed} onChange={(e) => setOpt({ hideDimmed: e.target.checked })} /> Hide filtered-out cards
          </label>
        )}
      </div>
      <ul className="tree-list" ref={list} role="tree" aria-label="Cards" tabIndex={0} onKeyDown={key}>
        {shown.map((r) => {
          const c = r.card;
          let title = c.title.trim() || "Untitled";
          if (c.kind === KIND_STRAND) title = `${STRAND_MARKS[c.strand_kind] ?? "•"} ${title}`;
          const group = c.kind === KIND_GROUP;
          return (
            <li key={r.id} role="treeitem" aria-selected={selected.has(r.id)} aria-expanded={group ? !closed.has(r.id) : undefined}
                className={[selected.has(r.id) ? "current" : "", r.muted ? "muted-row" : "", c.outside_story ? "outside" : ""].join(" ")}
                style={{ paddingLeft: 6 + r.depth * 14 }} title={rowTip(r) || undefined}
                onClick={(e) => {
                  onShow([r.id], false);
                  e.currentTarget.parentElement?.focus(); // the arrow keys carry on in the list
                }}
                onDoubleClick={() => onShow([r.id], true)}>
              {group ? (
                <button type="button" className="twisty" aria-label={closed.has(r.id) ? "Expand in the list" : "Collapse in the list"}
                        onClick={(e) => {
                          e.stopPropagation();
                          const next = new Set(closed);
                          if (closed.has(r.id)) next.delete(r.id);
                          else next.add(r.id);
                          setClosed(next);
                        }}>{closed.has(r.id) ? "▸" : "▾"}</button>
              ) : <span className="twisty" />}
              <span className="dot" style={{ background: c.color }} />
              <span className={group ? "row-title group" : "row-title"}>
                {group && c.collapsed ? `${FOLDED} ` : ""}{title}{group ? ` · ${r.count}` : ""}
              </span>
              {opts.status && !group && c.status && <span className="muted row-status">{c.status}</span>}
            </li>
          );
        })}
        {!shown.length && <li className="muted">{needle ? "No card matches." : "No cards yet."}</li>}
      </ul>
    </div>
  );
}
