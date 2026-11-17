import { useEffect, useRef, useState, type MouseEvent } from "react";
import {
  BUILTIN_STATUSES, BULK_LIST_FIELDS, KIND_STRAND, RENAMABLE_FIELDS, groupHas, makeStrandInfo,
  type StrandField, type StrandGroup, type StrandKind,
} from "../../core/model.ts";
import { casefold } from "../../core/pystr.ts";
import type { BoardStore } from "../../board/store.ts";
import { SEPARATOR, type MenuItem } from "../../canvas/menus.ts";

import {
  STRAND_GROUP_MIME, STRAND_MIME, strandDragging, strandGroupDragging, type StrandGroupDrag,
} from "../../canvas/controller.ts";
const COMMIT_DELAY_MS = 700;
export const KIND_LABELS: Record<StrandKind, string> = { tags: "Tags", characters: "Characters", locations: "Locations", status: "Statuses" };
export const KIND_ONE: Record<StrandKind, string> = { tags: "tag", characters: "character", locations: "location", status: "status" };
export const KIND_PLURAL: Record<StrandKind, string> = { tags: "tags", characters: "characters", locations: "locations", status: "statuses" };

/** "1 character", "3 statuses". */
export function strandsText(n: number, kind: StrandKind): string {
  return `${n} ${n === 1 ? KIND_ONE[kind] : KIND_PLURAL[kind]}`;
}
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
  /** A strand's picture ready to show, or null where it can't be (a browser; a missing file). */
  picture(picture: string): Promise<string | null>;
  /** Show a right-click menu. */
  menu(items: MenuItem[], x: number, y: number): void;
  /** Ask for a new strand group's name (starting with the picked strands of its kind);
   *  `created` gets it once made. */
  newGroup(kind: StrandKind, picked: Partial<Record<StrandKind, string[]>>, created: (kind: StrandKind, name: string) => void): void;
  /** Ask for a strand group's new name; `renamed` gets it once renamed. */
  renameGroup(kind: StrandKind, name: string, renamed: (name: string) => void): void;
  notice(text: string): void;
}

type Picked = { kind: StrandKind; key: string; group?: boolean } | null;
const pickId = (kind: string, key: string) => `${kind}\u0000${key}`;

/** The Strands panel (heddle/strands_panel.py): every strand on the board, how much each is
 *  used, and each one's description (also shown on its strand cards) and custom fields.
 *  A strand dragged onto the board joins a card, or becomes a strand card. Pictures are kept
 *  in the file but shown only by the desktop app.
 *
 *  Strand groups come first in their kind's section, with their strands under them; strands
 *  in no strand group follow, and one in two is listed under both. Ctrl+click (⌘ on a Mac)
 *  picks several strands, to start a strand group with or add to one together. */
export function StrandsPanel({ store, act }: { store: BoardStore; act: StrandActions }) {
  const [find, setFind] = useState("");
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<Picked>(null);
  const [picks, setPicks] = useState<Set<string>>(new Set()); // the strands picked (pickId)
  const needle = casefold(find.trim());
  const [plain, detailed] = store.unusedStrands();
  const anyUnused = Object.keys(plain).length + Object.keys(detailed).length > 0;
  const name = picked && !picked.group ? store.allValues(picked.kind).find((v) => casefold(v) === picked.key) : undefined;
  const group = picked?.group ? store.groupsOf(picked.kind).find((g) => casefold(g.name) === picked.key) : undefined;

  const toggleFold = (key: string) => {
    const next = new Set(folded);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setFolded(next);
  };
  /** The picked strands, by kind, each once. */
  const pickedStrands = (): Partial<Record<StrandKind, string[]>> => {
    const out: Partial<Record<StrandKind, string[]>> = {};
    for (const kind of RENAMABLE_FIELDS) {
      const names = store.allValues(kind).filter((n) => picks.has(pickId(kind, casefold(n))));
      if (names.length) out[kind] = names;
    }
    return out;
  };
  const pickStrand = (kind: StrandKind, n: string, more: boolean) => {
    const id = pickId(kind, casefold(n));
    const next = more ? new Set(picks) : new Set<string>();
    if (more && next.has(id) && next.size > 1) next.delete(id);
    else next.add(id);
    setPicks(next);
    setPicked({ kind, key: casefold(n) });
  };
  const showGroup = (kind: StrandKind, gname: string) => {
    setPicks(new Set());
    setPicked({ kind, key: casefold(gname), group: true });
  };
  const newGroup = (kind: StrandKind, from: Partial<Record<StrandKind, string[]>>) =>
    act.newGroup(kind, from, (k, n) => showGroup(k, n));
  const menuAt = (e: MouseEvent, items: MenuItem[]) => {
    e.preventDefault();
    e.stopPropagation();
    act.menu(items, e.clientX, e.clientY);
  };

  /** A strand's right-click menu: Add to Strand Group ▸, and Remove from its strand group. */
  const strandMenu = (kind: StrandKind, n: string, inGroup: string | null): MenuItem[] => {
    const chosen = picks.has(pickId(kind, casefold(n))) ? pickedStrands()[kind] ?? [n] : [n];
    const what = chosen.length === 1 ? chosen[0]! : strandsText(chosen.length, kind);
    const groups = store.groupsOf(kind);
    const items: MenuItem[] = [{
      label: `Add ${what} to Strand Group`,
      submenu: [
        ...groups.map((g) => ({
          label: g.name, disabled: chosen.every((c) => groupHas(g, c)),
          action: () => store.addToStrandGroup(kind, g.name, chosen),
        })),
        ...(groups.length ? [SEPARATOR] : []),
        { label: "New Strand Group…", action: () => newGroup(kind, { [kind]: chosen }) },
      ],
    }];
    if (inGroup) items.push({ label: `Remove from “${inGroup}”`, action: () => store.removeFromStrandGroup(kind, inGroup, chosen) });
    return items;
  };

  return (
    <div className="panel strands-panel">
      <input type="search" className="wide-input" placeholder="Find a strand" aria-label="Find a strand" value={find}
             onChange={(e) => setFind(e.target.value)} />
      <div className="strand-tree" title="Drag a strand onto a card to add it to the card, or onto a group or a blank spot for a strand card. Drag a strand group onto a card to add all its strands">
        {RENAMABLE_FIELDS.map((kind) => {
          const usage = store.strandUsage(kind);
          const cardsFor = store.strandCardCounts(kind);
          const names = store.allValues(kind);
          const byKey = new Map(names.map((n) => [casefold(n), n]));
          const groups = store.groupsOf(kind);
          const grouped = new Set(groups.flatMap((g) => g.members.map(casefold)).filter((k) => byKey.has(k)));
          const open = !folded.has(kind);
          const matches = (n: string) => !needle || casefold(n).includes(needle);

          const strandRow = (n: string, inGroup: string | null) => {
            const key = casefold(n);
            const [cards, routes] = usage.get(key) ?? [0, 0];
            const sc = cardsFor.get(key) ?? 0;
            const has = store.strand(kind, n) !== undefined;
            const unused = !(cards || routes || sc);
            const current = !picked?.group && picked?.kind === kind && picked.key === key;
            const chosen = picks.has(pickId(kind, key));
            return (
              <li key={`${inGroup ?? ""}/${n}`} role="option" aria-selected={chosen || current} draggable
                  className={`${current ? "current" : ""} ${chosen && !current ? "chosen" : ""} ${unused ? "unused" : ""} ${inGroup !== null ? "member" : ""}`}
                  onClick={(e) => pickStrand(kind, n, e.ctrlKey || e.metaKey)}
                  onContextMenu={(e) => menuAt(e, strandMenu(kind, n, inGroup))}
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
          };

          return (
            <section key={kind}>
              <button type="button" className="fold" aria-expanded={open} onClick={() => toggleFold(kind)}
                      onContextMenu={(e) => menuAt(e, [{ label: `New ${KIND_ONE[kind][0]!.toUpperCase()}${KIND_ONE[kind].slice(1)} Strand Group…`,
                        action: () => newGroup(kind, {}) }])}>
                {open ? "▾" : "▸"} <strong>{KIND_LABELS[kind]}</strong> <span className="muted">({names.length})</span></button>
              {open && (
                <ul role="listbox" aria-label={KIND_LABELS[kind]} aria-multiselectable>
                  {groups.flatMap((g) => {
                    const members = g.members.filter((m) => byKey.has(casefold(m))).map((m) => byKey.get(casefold(m))!);
                    const nameHit = !!needle && casefold(g.name).includes(needle);
                    const shown = nameHit || !needle ? members : members.filter(matches);
                    if (needle && !nameHit && !shown.length) return [];
                    const fold = `${kind}/${casefold(g.name)}`;
                    const gOpen = !folded.has(fold);
                    const current = picked?.group && picked.kind === kind && picked.key === casefold(g.name);
                    const draggable = (BULK_LIST_FIELDS as readonly string[]).includes(kind) && g.members.length > 0;
                    return [
                      <li key={`group:${g.name}`} role="option" aria-selected={!!current} aria-label={`Strand group ${g.name}`}
                          className={`strand-group ${current ? "current" : ""}`} draggable={draggable}
                          title={`Strand group: ${strandsText(g.members.length, kind)}`}
                          onClick={() => showGroup(kind, g.name)}
                          onContextMenu={(e) => menuAt(e, [
                            { label: "Rename Strand Group…", action: () => act.renameGroup(kind, g.name, (n) => showGroup(kind, n)) },
                            { label: "Delete Strand Group", action: () => deleteGroup(store, act, kind, g.name, () => setPicked(null)) },
                          ])}
                          onDragStart={(e) => {
                            if (!draggable) return e.preventDefault();
                            const payload: StrandGroupDrag = { kind, name: g.name, members: [...g.members] };
                            e.dataTransfer.setData(STRAND_GROUP_MIME, JSON.stringify(payload));
                            e.dataTransfer.setData("text/plain", g.name);
                            e.dataTransfer.effectAllowed = "copy";
                            strandGroupDragging.current = payload;
                          }}
                          onDragEnd={() => (strandGroupDragging.current = null)}>
                        <span>
                          <button type="button" className="fold inline" aria-expanded={gOpen} aria-label={gOpen ? `Fold ${g.name}` : `Unfold ${g.name}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    toggleFold(fold);
                                  }}>{gOpen ? "▾" : "▸"}</button> <strong>{g.name}</strong>
                        </span>
                        <span className="muted">({g.members.length})</span>
                      </li>,
                      ...(gOpen ? shown.map((m) => strandRow(m, g.name)) : []),
                      ...(gOpen && !g.members.length && !needle
                        ? [<li key={`empty:${g.name}`} className="muted member"><em>Empty: tick strands in its member list below</em></li>] : []),
                    ];
                  })}
                  {!names.length && <li className="muted"><em>No {KIND_LABELS[kind].toLowerCase()} yet</em></li>}
                  {names.filter((n) => !grouped.has(casefold(n)) && matches(n)).map((n) => strandRow(n, null))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      <div className="row between">
        <button type="button" onClick={() => newGroup(picked?.kind ?? "characters", pickedStrands())}
                title="Make a strand group (e.g. a family of characters) to filter by or add to cards together. Picked strands start in it (Ctrl+click picks several)">
          New strand group…</button>
        <button type="button" disabled={!anyUnused} onClick={act.removeUnused}
                title="Pick strands nothing on the board uses and take them off it">Remove unused…</button>
      </div>
      {group
        ? <GroupDetails key={`group:${picked!.kind}:${picked!.key}`} store={store} group={group} act={act}
                        onRenamed={(n) => showGroup(group.kind as StrandKind, n)} onDeleted={() => setPicked(null)} />
        : picked && name !== undefined
          ? <StrandDetails key={`${picked.kind}:${picked.key}`} store={store} kind={picked.kind} name={name} act={act} />
          : <p className="muted">Pick a strand above to see where it's used and give it a description and fields.</p>}
    </div>
  );
}

function deleteGroup(store: BoardStore, act: StrandActions, kind: StrandKind, name: string, done: () => void) {
  if (store.deleteStrandGroup(kind, name)) act.notice(`Deleted the strand group “${name}”: its strands stay on the board`);
  done();
}

/** The cards (not strand cards) that have any of `names`. */
function cardsWithAny(store: BoardStore, kind: StrandKind, names: readonly string[]): string[] {
  const ids = new Set(names.flatMap((n) => store.cardsWith(kind, n)));
  return store.state.cards.filter((c) => ids.has(c.id) && c.kind !== KIND_STRAND).map((c) => c.id);
}

/** A picked strand group: how much its strands are used, actions, its description and the
 *  member checklist (every strand of its kind; ticking one puts it in). */
function GroupDetails({ store, group, act, onRenamed, onDeleted }: {
  store: BoardStore; group: StrandGroup; act: StrandActions; onRenamed: (name: string) => void; onDeleted: () => void;
}) {
  const kind = group.kind as StrandKind;
  const [text, setText] = useState<string | null>(null); // typed, not saved yet
  const [find, setFind] = useState("");
  const timer = useRef(0);
  const pending = useRef<string | null>(null);
  const nameRef = useRef(group.name);
  useEffect(() => {
    nameRef.current = group.name;
  });
  const commit = () => {
    clearTimeout(timer.current);
    if (pending.current === null) return;
    const d = pending.current;
    pending.current = null;
    store.updateStrandGroup(kind, nameRef.current, { description: d });
    setText(null);
  };
  const commitRef = useRef(commit);
  useEffect(() => {
    commitRef.current = commit;
  });
  useEffect(() => () => { // leaving this strand group keeps what was typed
    clearTimeout(timer.current);
    if (pending.current !== null) store.updateStrandGroup(kind, nameRef.current, { description: pending.current });
  }, [store, kind]);

  const cards = cardsWithAny(store, kind, group.members);
  const needle = casefold(find.trim());
  const strands = store.allValues(kind);
  return (
    <div className="strand-details">
      <h3>{group.name} <span className="muted">· {KIND_ONE[kind]} strand group</span></h3>
      <p className="muted small-note">
        {strandsText(group.members.length, kind)} · {cards.length ? `${cards.length} card${cards.length === 1 ? "" : "s"}` : "on no cards"}</p>
      <div className="row wrap">
        <button type="button" onClick={() => act.renameGroup(kind, group.name, onRenamed)}
                title="Rename the strand group (its strands keep their names)">Rename…</button>
        <button type="button" disabled={!cards.length} onClick={() => act.selectCards(cards)}
                title="Select the cards that have any of its strands">Select cards</button>
        <button type="button" onClick={() => deleteGroup(store, act, kind, group.name, onDeleted)}
                title="Forget the strand group. Its strands stay on the board and on their cards (undo with Ctrl+Z)">Delete strand group</button>
      </div>
      <label className="block">Description
        <textarea rows={3} value={text ?? group.description} placeholder="Description…" onBlur={commit}
                  onChange={(e) => {
                    pending.current = e.target.value;
                    setText(e.target.value);
                    clearTimeout(timer.current);
                    timer.current = window.setTimeout(() => commitRef.current(), COMMIT_DELAY_MS);
                  }} />
      </label>
      <div className="fields">
        <strong>Members ({group.members.length})</strong>
        <input type="search" className="wide-input" placeholder="Find a strand" aria-label="Find a member" value={find}
               onChange={(e) => setFind(e.target.value)} />
        <ul className="member-list" aria-label="Members" title="Tick a strand to put it in the strand group">
          {strands.filter((n) => !needle || casefold(n).includes(needle)).map((n) => (
            <li key={n}>
              <label>
                <input type="checkbox" checked={groupHas(group, n)} onChange={(e) => {
                  if (e.target.checked) store.addToStrandGroup(kind, group.name, [n]);
                  else store.removeFromStrandGroup(kind, group.name, [n]);
                }} /> {n}
              </label>
            </li>
          ))}
        </ul>
      </div>
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
  const inGroups = store.groupsWith(kind, name).map((g) => g.name);

  return (
    <div className="strand-details">
      <h3>{name} <span className="muted">· {KIND_ONE[kind]}</span></h3>
      <p className="muted small-note">{usageText(usage[0], usage[1], sc, kind === "status" && BUILTIN.has(casefold(name)))}</p>
      {inGroups.length > 0 && (
        <p className="muted small-note">{inGroups.length === 1 ? "In strand group " : "In strand groups "}{inGroups.join(", ")}</p>
      )}
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
      {info?.picture && <StrandPicture picture={info.picture} load={act.picture} />}
      {info && (
        <button type="button" onClick={() => store.setStrandInfo(makeStrandInfo({ kind, name }))}>Clear details</button>
      )}
    </div>
  );
}

/** The strand's picture where the host can show it (the desktop app); else its path. */
function StrandPicture({ picture, load }: { picture: string; load: (picture: string) => Promise<string | null> }) {
  const [shown, setShown] = useState<{ picture: string; url: string | null } | null>(null);
  useEffect(() => {
    let live = true;
    void load(picture).then((url) => live && setShown({ picture, url }), () => live && setShown({ picture, url: null }));
    return () => {
      live = false;
    };
  }, [picture, load]);
  const url = shown?.picture === picture ? shown.url : null;
  return url
    ? <figure className="strand-picture"><img src={url} alt={`Picture: ${picture}`} title={picture} /></figure>
    : <p className="muted small-note" title={picture}>Picture: {picture} (shown in the desktop app)</p>;
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
