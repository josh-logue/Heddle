import { useEffect, useRef, useState } from "react";
import { BUILTIN_STATUSES, RENAMABLE_FIELDS, makeStrandInfo, type StrandField, type StrandKind } from "../../core/model.ts";
import { casefold } from "../../core/pystr.ts";
import type { BoardStore } from "../../board/store.ts";

import { STRAND_MIME, strandDragging } from "../../canvas/controller.ts";
const COMMIT_DELAY_MS = 700;
export const KIND_LABELS: Record<StrandKind, string> = { tags: "Tags", characters: "Characters", locations: "Locations", status: "Statuses" };
export const KIND_ONE: Record<StrandKind, string> = { tags: "tag", characters: "character", locations: "location", status: "status" };
const NEW_FIELD_NAME = "Field";
const BUILTIN = new Set(BUILTIN_STATUSES.map((s) => casefold(s)));

export function usageText(cards: number, routes: number, strandCards = 0, builtin = false): string {
  const bits: string[] = [];
  if (cards) bits.push(`${cards} card${cards === 1 ? "" : "s"}`);
  if (routes) bits.push(`${routes} route${routes === 1 ? "" : "s"}`);
  if (strandCards) bits.push(`${strandCards} strand card${strandCards === 1 ? "" : "s"}`);
  return bits.join(" · ") || (builtin ? "built-in" : "unused");
}

export interface StrandActions {
  rename(kind: StrandKind, name: string): void;
  removeUnused(): void;
  applyFields(kind: StrandKind, name: string): void;
  selectCards(ids: string[]): void;
  addToBoard(kind: StrandKind, name: string): void;
}

type Picked = { kind: StrandKind; key: string } | null;

/** The Strands panel (heddle/strands_panel.py): every strand on the board, how much each is
 *  used, and each one's description (also shown on its strand cards) and custom fields.
 *  A strand dragged onto the board joins a card, or becomes a strand card. Pictures are kept
 *  in the file but shown only by the desktop app. */
export function StrandsPanel({ store, act }: { store: BoardStore; act: StrandActions }) {
  const [find, setFind] = useState("");
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<Picked>(null);
  const needle = casefold(find.trim());
  const [plain, detailed] = store.unusedStrands();
  const anyUnused = Object.keys(plain).length + Object.keys(detailed).length > 0;
  const name = picked ? store.allValues(picked.kind).find((v) => casefold(v) === picked.key) : undefined;

  return (
    <div className="panel strands-panel">
      <input type="search" className="wide-input" placeholder="Find a strand" aria-label="Find a strand" value={find}
             onChange={(e) => setFind(e.target.value)} />
      <div className="strand-tree" title="Drag a strand onto a card to add it to the card, or onto a group or a blank spot for a strand card">
        {RENAMABLE_FIELDS.map((kind) => {
          const usage = store.strandUsage(kind);
          const cardsFor = store.strandCardCounts(kind);
          const names = store.allValues(kind);
          const open = !folded.has(kind);
          return (
            <section key={kind}>
              <button type="button" className="fold" aria-expanded={open} onClick={() => {
                const next = new Set(folded);
                if (open) next.add(kind);
                else next.delete(kind);
                setFolded(next);
              }}>{open ? "▾" : "▸"} <strong>{KIND_LABELS[kind]}</strong> <span className="muted">({names.length})</span></button>
              {open && (
                <ul role="listbox" aria-label={KIND_LABELS[kind]}>
                  {!names.length && <li className="muted"><em>No {KIND_LABELS[kind].toLowerCase()} yet</em></li>}
                  {names.filter((n) => !needle || casefold(n).includes(needle)).map((n) => {
                    const key = casefold(n);
                    const [cards, routes] = usage.get(key) ?? [0, 0];
                    const sc = cardsFor.get(key) ?? 0;
                    const has = store.strand(kind, n) !== undefined;
                    const unused = !(cards || routes || sc);
                    const current = picked?.kind === kind && picked.key === key;
                    return (
                      <li key={n} role="option" aria-selected={current} draggable className={`${current ? "current" : ""} ${unused ? "unused" : ""}`}
                          onClick={() => setPicked({ kind, key })}
                          onDragStart={(e) => {
                            e.dataTransfer.setData(STRAND_MIME, JSON.stringify({ kind, name: n }));
                            e.dataTransfer.setData("text/plain", n);
                            e.dataTransfer.effectAllowed = "copy";
                            strandDragging.current = { kind, name: n };
                          }}
                          onDragEnd={() => (strandDragging.current = null)}
                          title={has ? "Has a description or fields" : undefined}>
                        <span>{n}{has ? " ✎" : ""}</span>
                        <span className="muted">{usageText(cards, routes, sc, kind === "status" && BUILTIN.has(key))}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      <div className="row end">
        <button type="button" disabled={!anyUnused} onClick={act.removeUnused}
                title="Pick strands nothing on the board uses and take them off it">Remove unused…</button>
      </div>
      {picked && name !== undefined
        ? <StrandDetails key={`${picked.kind}:${picked.key}`} store={store} kind={picked.kind} name={name} act={act} />
        : <p className="muted">Pick a strand above to see where it's used and give it a description and fields.</p>}
    </div>
  );
}

function StrandDetails({ store, kind, name, act }: { store: BoardStore; kind: StrandKind; name: string; act: StrandActions }) {
  const info = store.strand(kind, name);
  const [text, setText] = useState<string | null>(null); // typed, not saved yet
  const timer = useRef(0);
  const pending = useRef<string | null>(null);
  const description = text ?? info?.description ?? "";
  const fields: StrandField[] = info?.fields ?? [];

  /** Store the strand's details with `patch` applied (one undo step; cleaned as on loading). */
  const save = (patch: { description?: string; fields?: StrandField[] }) => {
    const now = store.strand(kind, name);
    store.setStrandInfo(makeStrandInfo({
      kind, name, description: patch.description ?? now?.description ?? "", picture: now?.picture ?? "",
      fields: patch.fields ?? now?.fields ?? [],
    }));
  };
  const commit = () => {
    clearTimeout(timer.current);
    if (pending.current === null) return;
    const d = pending.current;
    pending.current = null;
    save({ description: d });
    setText(null);
  };
  const commitRef = useRef(commit);
  useEffect(() => {
    commitRef.current = commit;
  });
  useEffect(() => () => { // leaving this strand keeps what was typed
    clearTimeout(timer.current);
    if (pending.current !== null) {
      const now = store.strand(kind, name);
      store.setStrandInfo(makeStrandInfo({ kind, name, description: pending.current, picture: now?.picture ?? "", fields: now?.fields ?? [] }));
    }
  }, [store, kind, name]);

  const setFields = (next: StrandField[]) => save({ fields: next });
  const uniqueName = () => {
    const taken = new Set(fields.map(([n]) => casefold(n)));
    let n = NEW_FIELD_NAME;
    for (let k = 2; taken.has(casefold(n)); k++) n = `${NEW_FIELD_NAME} ${k}`;
    return n;
  };
  const cards = store.cardsWith(kind, name);
  const usage = store.strandUsage(kind).get(casefold(name)) ?? [0, 0];
  const sc = store.strandCardCounts(kind).get(casefold(name)) ?? 0;

  return (
    <div className="strand-details">
      <h3>{name} <span className="muted">· {KIND_ONE[kind]}</span></h3>
      <p className="muted small-note">{usageText(usage[0], usage[1], sc, kind === "status" && BUILTIN.has(casefold(name)))}</p>
      <div className="row wrap">
        <button type="button" onClick={() => act.rename(kind, name)} title="Rename it on every card (merging with a strand of the new name)">Rename…</button>
        <button type="button" disabled={!cards.length} onClick={() => act.selectCards(cards)}>Select cards</button>
        {kind === "characters" && store.state.display.story_tools && (
          <button type="button" disabled={!usage[0]} onClick={() => store.showThread(name)}
                  title="Light up every card featuring this character, in story order">Show thread</button>
        )}
        <button type="button" onClick={() => act.addToBoard(kind, name)} title="Add a strand card for it to the middle of the board">Add to board</button>
      </div>
      <label className="block">Description
        <textarea rows={5} value={description} placeholder="Description…" onBlur={commit}
                  onChange={(e) => {
                    pending.current = e.target.value;
                    setText(e.target.value);
                    clearTimeout(timer.current);
                    timer.current = window.setTimeout(() => commitRef.current(), COMMIT_DELAY_MS);
                  }} />
      </label>
      <div className="fields">
        <div className="row between"><strong>Fields</strong>
          <span>
            <button type="button" onClick={() => setFields([...fields, [uniqueName(), ""]])}>Add field</button>
            <button type="button" disabled={!fields.length} onClick={() => act.applyFields(kind, name)}
                    title="Copy these field names to other strands of the same kind">Apply to…</button>
          </span>
        </div>
        {!fields.length && <p className="muted small-note">No fields yet. Add your own, such as age or biome.</p>}
        {fields.map(([n, v], i) => (
          <FieldRow key={`${i}:${n}`} name={n} value={v} first={i === 0} last={i === fields.length - 1}
                    onChange={(nn, nv) => {
                      // A name another field already has (ignoring case) isn't taken.
                      if (fields.some(([o], j) => j !== i && casefold(o) === casefold(nn.trim()))) return false;
                      setFields(fields.map((f, j) => (j === i ? [nn.trim() || n, nv] : f)));
                      return true;
                    }}
                    onRemove={() => setFields(fields.filter((_, j) => j !== i))}
                    onMove={(d) => {
                      const next = [...fields];
                      [next[i], next[i + d]] = [next[i + d]!, next[i]!];
                      setFields(next);
                    }} />
        ))}
      </div>
      {info?.picture && <p className="muted small-note" title={info.picture}>Picture: {info.picture} (shown in the desktop app)</p>}
      {info && (
        <button type="button" onClick={() => store.setStrandInfo(makeStrandInfo({ kind, name }))}>Clear details</button>
      )}
    </div>
  );
}

function FieldRow({ name, value, first, last, onChange, onRemove, onMove }: {
  name: string; value: string; first: boolean; last: boolean;
  onChange: (name: string, value: string) => boolean; onRemove: () => void; onMove: (d: 1 | -1) => void;
}) {
  const [n, setN] = useState(name);
  const [v, setV] = useState(value);
  const done = () => {
    if (n === name && v === value) return;
    if (!onChange(n, v)) setN(name); // that name's taken: back to the old one
  };
  return (
    <div className="field-row">
      <input type="text" value={n} aria-label="Field name" onChange={(e) => setN(e.target.value)} onBlur={done}
             onKeyDown={(e) => e.key === "Enter" && done()} />
      <input type="text" value={v} aria-label={`${name} value`} onChange={(e) => setV(e.target.value)} onBlur={done}
             onKeyDown={(e) => e.key === "Enter" && done()} />
      <button type="button" className="icon" disabled={first} aria-label="Move up" onClick={() => onMove(-1)}>▲</button>
      <button type="button" className="icon" disabled={last} aria-label="Move down" onClick={() => onMove(1)}>▼</button>
      <button type="button" className="icon" aria-label={`Remove ${name}`} onClick={onRemove}>×</button>
    </div>
  );
}
