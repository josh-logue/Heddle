import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { searchCards } from "../core/filters.ts";
import {
  BUILTIN_STATUSES, BULK_LIST_FIELDS, CARD_COLORS, COLOR_NAMES, DISPLAY_DEFAULTS, KIND_GROUP, KIND_STRAND,
  REPLACE_FIELDS, boardValues, countReplacements, strandKey, titleLabels, type Display, type TextField,
} from "../core/model.ts";
import { casefold, collapseSpaces, sortedBy } from "../core/pystr.ts";
import { naturalKey, rank } from "../core/rank.ts";
import { STRAND_MARKS } from "../board/metrics.ts";
import type { BoardStore } from "../board/store.ts";
import { Dialog } from "./Dialog.tsx";
import { TokenInput } from "./TokenInput.tsx";

/** {strandKey: StrandInfo}, for searching strands' descriptions and fields. */
export const strandInfoMap = (store: BoardStore) => new Map(store.state.strands.map((s) => [strandKey(s.kind, s.name), s]));

// ----- Go to Card -------------------------------------------------------------------------------

const MAX_ROWS = 200;

/** Go to Card (heddle/go_to_card.py): type part of a title and jump to the card. Titles
 *  starting with it come first, then a word starting with it, then containing it, then
 *  cards found by their description, notes or strands. */
export function GoToCard({ store, onGo, onClose }: { store: BoardStore; onGo: (id: string) => void; onClose: () => void }) {
  const [text, setText] = useState("");
  const [current, setCurrent] = useState(0);
  const list = useRef<HTMLUListElement>(null);
  const cards = store.state.cards;
  const labels = useMemo(() => titleLabels(cards), [cards]);
  const found = useMemo(() => {
    const needle = casefold(collapseSpaces(text));
    const rows: { key: unknown[]; id: string; where: string }[] = [];
    if (!needle) {
      for (const c of cards) rows.push({ key: [naturalKey(c.title)], id: c.id, where: "" });
    } else {
      for (const c of cards) {
        const r = rank(c.title.trim() || "Untitled", needle);
        if (r !== null) rows.push({ key: [r, naturalKey(c.title)], id: c.id, where: "" });
      }
      const titled = new Set(rows.map((r) => r.id));
      for (const [id, label, snippet] of searchCards(cards, needle, strandInfoMap(store))) {
        if (!titled.has(id)) rows.push({ key: [3, naturalKey(store.card(id)!.title)], id, where: `${label}: ${snippet}` });
      }
    }
    return sortedBy(rows, (r) => r.key as never);
  }, [cards, text, store]);
  const shown = found.slice(0, MAX_ROWS);
  const pick = Math.min(current, Math.max(0, shown.length - 1));

  useEffect(() => {
    list.current?.children[pick]?.scrollIntoView({ block: "nearest" });
  }, [pick]);

  const go = (i = pick) => {
    const row = shown[i];
    if (row) onGo(row.id);
  };
  const key = (e: KeyboardEvent) => {
    const step = { ArrowDown: 1, ArrowUp: -1, PageDown: 10, PageUp: -10 }[e.key];
    if (step) {
      e.preventDefault();
      setCurrent(Math.max(0, Math.min(shown.length - 1, pick + step)));
    }
  };
  const more = found.length - MAX_ROWS;
  return (
    <Dialog title="Go to Card" okLabel="Go" onOk={() => go()} onCancel={onClose}>
      <input type="text" className="wide-input" placeholder="Type part of a card's title" value={text} aria-label="Card title"
             onChange={(e) => {
               setText(e.target.value);
               setCurrent(0);
             }} onKeyDown={key} />
      <ul className="pick-list" ref={list} role="listbox" aria-label="Cards">
        {shown.map((row, i) => {
          const c = store.card(row.id)!;
          let label = labels.get(c.id) ?? (c.title.trim() || "Untitled");
          if (c.kind === KIND_STRAND) label = `${STRAND_MARKS[c.strand_kind] ?? "•"} ${label}`;
          else if (c.kind === KIND_GROUP) label += "  (group)";
          return (
            <li key={row.id} role="option" aria-selected={i === pick} className={i === pick ? "current" : ""}
                onClick={() => setCurrent(i)} onDoubleClick={() => go(i)} title={row.where || undefined}>
              <span className="dot" style={{ background: c.color }} />
              <span>{label}</span>
              {row.where && <span className="muted"> — {row.where}</span>}
            </li>
          );
        })}
      </ul>
      <p className="muted small-note">
        {!found.length ? "No card matches" : `${found.length} card${found.length !== 1 ? "s" : ""}`
          + (more > 0 ? ` (first ${MAX_ROWS} shown: type more to narrow)` : "") + " · Enter goes to it, Esc closes"}
      </p>
    </Dialog>
  );
}

// ----- Replace ------------------------------------------------------------------------------------

/** Replace (heddle/replace_dialog.py): find and replace text in cards' titles, descriptions
 *  and notes, as one undo step. Strand names aren't touched here. */
export function Replace({ store, onDone, onClose }: { store: BoardStore; onDone: (changed: number) => void; onClose: () => void }) {
  const selected = [...store.selected];
  const [find, setFind] = useState("");
  const [replacement, setReplacement] = useState("");
  const [fields, setFields] = useState<Set<TextField>>(new Set(REPLACE_FIELDS.map(([f]) => f)));
  const [matchCase, setMatchCase] = useState(false);
  const [onlySelected, setOnlySelected] = useState(selected.length > 1);
  const useSelected = onlySelected && selected.length > 0;
  const cards = useSelected ? store.state.cards.filter((c) => selected.includes(c.id)) : store.state.cards;
  const [total, touched] = countReplacements(cards, find, [...fields], matchCase);
  const ok = () => {
    if (!total) return;
    onDone(store.replaceInCards(find, replacement, [...fields], matchCase, useSelected ? selected : null));
  };
  return (
    <Dialog title="Replace" okLabel="Replace all" onOk={ok} onCancel={onClose}>
      <div className="field"><label htmlFor="r-find">Find</label>
        <input id="r-find" type="text" value={find} placeholder="Text to find" onChange={(e) => setFind(e.target.value)} /></div>
      <div className="field"><label htmlFor="r-with">Replace with</label>
        <input id="r-with" type="text" value={replacement} placeholder="Replace with (empty removes it)" onChange={(e) => setReplacement(e.target.value)} /></div>
      <div className="field"><span className="label">Look in</span>
        <div className="radios">
          {REPLACE_FIELDS.map(([f, label]) => (
            <label key={f}><input type="checkbox" checked={fields.has(f)} onChange={(e) => {
              const next = new Set(fields);
              if (e.target.checked) next.add(f);
              else next.delete(f);
              setFields(next);
            }} /> {label}</label>
          ))}
        </div>
      </div>
      <div className="field"><span />
        <div className="stack tight">
          <label><input type="checkbox" checked={matchCase} onChange={(e) => setMatchCase(e.target.checked)} /> Match case</label>
          <label><input type="checkbox" disabled={!selected.length} checked={useSelected} onChange={(e) => setOnlySelected(e.target.checked)} />
            {" "}Selected cards only ({selected.length})</label>
        </div>
      </div>
      <p className="muted" role="status">
        {!find ? "" : total ? `${total} match${total !== 1 ? "es" : ""} in ${touched} card${touched !== 1 ? "s" : ""} (one undo step)` : "No matches"}
      </p>
      <p className="muted small-note">To rename a tag, character, location or status everywhere, use Edit → Rename strand… (Ctrl+R).</p>
    </Dialog>
  );
}

// ----- Edit several cards -----------------------------------------------------------------------

const KEEP = "\u0001keep";
const SINGULAR: Record<string, string> = { tags: "tag", characters: "character", locations: "location" };

/** Edit several selected cards at once (heddle/multi_edit.py): colour, tags, characters
 *  and locations (add / remove) and status. Everything starts as "no change". */
export function MultiEdit({ store, onDone, onClose }: { store: BoardStore; onDone: (changed: number) => void; onClose: () => void }) {
  const ids = [...store.selected];
  const cards = store.state.cards.filter((c) => ids.includes(c.id));
  const [color, setColor] = useState<string | null>(null);
  const [add, setAdd] = useState<Record<string, string[]>>({ tags: [], characters: [], locations: [] });
  const [remove, setRemove] = useState<Record<string, string[]>>({ tags: [], characters: [], locations: [] });
  const [status, setStatus] = useState(KEEP);
  const pending = useRef<Record<string, string>>({}).current;
  const colours = [...CARD_COLORS, ...store.state.custom_colors.filter((c) => !(CARD_COLORS as readonly string[]).includes(c))];
  const statuses = [...BUILTIN_STATUSES, ...store.allValues("status").filter((s) => !BUILTIN_STATUSES.some((b) => casefold(b) === casefold(s)))];
  const ok = () => {
    const withPending = (values: string[], key: string) => (pending[key]?.trim() ? [...values, pending[key]!] : values);
    const edit = {
      color, status: status === KEEP ? null : status,
      add: Object.fromEntries(BULK_LIST_FIELDS.map((f) => [f, withPending(add[f]!, `add-${f}`)])),
      remove: Object.fromEntries(BULK_LIST_FIELDS.map((f) => [f, withPending(remove[f]!, `remove-${f}`)])),
    };
    onDone(store.bulkEdit(ids, edit));
  };
  return (
    <Dialog title={`Edit ${ids.length} cards`} okLabel={`Apply to ${ids.length} cards`} onOk={ok} onCancel={onClose} wide>
      <p>Changes apply to all <strong>{ids.length}</strong> selected cards. Anything left as it is stays different on each card.</p>
      <div className="field"><span className="label">Color</span>
        <div className="swatches" role="radiogroup">
          <button type="button" role="radio" aria-checked={color === null} className="swatch none" title="Keep each card's colour"
                  onClick={() => setColor(null)}>–</button>
          {colours.map((c) => (
            <button key={c} type="button" role="radio" aria-checked={c === color} className="swatch" style={{ background: c }}
                    title={COLOR_NAMES.get(c) ?? c} aria-label={COLOR_NAMES.get(c) ?? c} onClick={() => setColor(c)} />
          ))}
        </div>
      </div>
      {BULK_LIST_FIELDS.map((f) => (
        <div key={f}>
          <TokenInput label={`Add ${f}`} values={add[f]!} onChange={(v) => setAdd({ ...add, [f]: v })} suggestions={store.allValues(f)}
                      noun={SINGULAR[f]!} placeholder={`${f[0]!.toUpperCase()}${f.slice(1)} to add to every card`}
                      onPending={(t) => (pending[`add-${f}`] = t)} />
          <TokenInput label={`Remove ${f}`} values={remove[f]!} onChange={(v) => setRemove({ ...remove, [f]: v })}
                      suggestions={boardValues(cards, f)} noun={SINGULAR[f]!} placeholder={`${f[0]!.toUpperCase()}${f.slice(1)} to remove from every card`}
                      onPending={(t) => (pending[`remove-${f}`] = t)} />
        </div>
      ))}
      <div className="field"><label htmlFor="m-status">Status</label>
        <select id="m-status" value={status} onChange={(e) => setStatus(e.target.value)}
                title="Keep each card's status, set one for all, or clear it">
          <option value={KEEP}>(keep each card's status)</option>
          <option value="">(no status)</option>
          {statuses.map((st) => <option key={st} value={st}>{st}</option>)}
        </select>
      </div>
    </Dialog>
  );
}

// ----- Board Options ----------------------------------------------------------------------------

type Toggle = Exclude<keyof Display, "arrow_routing">;
export const SECTIONS: [string, [Toggle, string, string][]][] = [
  ["Card face", [
    ["show_tags", "Tags", "Tag pills on each card (tags still work in filters when hidden)"],
    ["show_pov", "POV", "Each card's point-of-view character"],
    ["show_characters", "Characters", "Each card's characters as pills"],
    ["show_introductions", "★ introductions", "A ★ on cards that introduce a character, and an Introduces line in their details"],
    ["show_group_count", "Group card count", "\"N cards\" in each group's title bar"],
    ["show_shadows", "Card shadows", "A drop shadow under each card"],
    ["show_description", "Descriptions", "Each card's description on its face. Hidden, point at a card to read it"],
    ["show_no_description", "“No description”", "The words on cards that have no description. Hidden, a card with nothing else on its face keeps the space blank; one showing tags, POV or characters closes it up"],
    ["compact_cards", "Compact cards", "While descriptions are hidden: a card with nothing else on its face is just its title bar, instead of keeping a blank line"],
  ]],
  ["Canvas and arrows", [
    ["show_handles", "Connection handles", "The ● handle for dragging out arrows. Hidden, arrows are still made with right-click → Connect to…"],
    ["show_arrow_labels", "Arrow labels", "Label text on arrows (hidden: shown when you point at one)"],
    ["show_grid", "Grid", "The background grid (snapping to it works either way)"],
  ]],
  ["Story", [
    ["story_tools", "Story tools", "★ introductions, the Introduces filter, Story Checks, Routes, the Path Reader and character threads. Turn off for a board that just sorts things into groups."],
    ["follow_paths", "Highlight paths of selection", "Selecting a card lights up its paths"],
  ]],
];
const ROUTINGS = [["straight", "Straight"], ["curved", "Curved"], ["avoid", "Curved, avoiding cards"]] as const;

/** Board Options (heddle/board_options.py): every display option of this board, saved with
 *  it; OK applies the changes as one undo step. */
export function BoardOptions({ store, onClose }: { store: BoardStore; onClose: () => void }) {
  const [values, setValues] = useState<Display>({ ...DISPLAY_DEFAULTS, ...store.state.display });
  return (
    <Dialog title="Board Options" onOk={() => {
      store.setDisplay(values);
      onClose();
    }} onCancel={onClose}>
      <p className="muted">These are saved with this board.</p>
      {SECTIONS.map(([title, options]) => (
        <fieldset key={title} className="details">
          <legend>{title}</legend>
          <div className="stack tight">
            {options.map(([key, label, tip]) => (
              <label key={key} title={tip}>
                <input type="checkbox" checked={values[key]}
                       // "No description" only matters while descriptions show, Compact cards only while hidden.
                       disabled={(key === "show_no_description" && !values.show_description) || (key === "compact_cards" && values.show_description)}
                       onChange={(e) => setValues({ ...values, [key]: e.target.checked })} /> {label}
              </label>
            ))}
            {title === "Canvas and arrows" && (
              <label>Arrows{" "}
                <select value={values.arrow_routing} onChange={(e) => setValues({ ...values, arrow_routing: e.target.value as Display["arrow_routing"] })}>
                  {ROUTINGS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </label>
            )}
          </div>
        </fieldset>
      ))}
    </Dialog>
  );
}
