import { useState } from "react";
import { RENAMABLE_FIELDS, countValues, type StrandField, type StrandKind } from "../core/model.ts";
import { casefold, sortedBy } from "../core/pystr.ts";
import { COLORS_KEY, type BoardStore } from "../board/store.ts";
import { Dialog } from "./Dialog.tsx";
import { KIND_LABELS, KIND_ONE, KIND_PLURAL, strandsText } from "./panels/StrandsPanel.tsx";

const FIELD_LABELS: Record<StrandKind, string> = { tags: "Tag", characters: "Character", locations: "Location", status: "Status" };

/** Rename a strand everywhere (heddle/rename_dialog.py). OK asks to confirm, saying how many
 *  cards change and whether it merges into a strand of the new name. */
export function RenameStrand({ store, kind: kind0, value, onConfirm, onClose }: {
  store: BoardStore; kind: StrandKind; value: string;
  onConfirm: (kind: StrandKind, old: string, name: string, message: string) => void; onClose: () => void;
}) {
  const [kind, setKind] = useState<StrandKind>(kind0);
  // Every strand of the kind with how many cards use it (saved and detailed ones too).
  const values = (k: StrandKind) => sortedBy(
    [...countValues(store.state.cards, k, store.allValues(k)).values()], ([v]) => casefold(v));
  const list = values(kind);
  const [old, setOld] = useState(() => list.find(([v]) => casefold(v) === casefold(value))?.[0] ?? list[0]?.[0] ?? "");
  const [name, setName] = useState(old);
  const count = list.find(([v]) => v === old)?.[1] ?? 0;
  const merge = casefold(name.trim()) !== casefold(old) ? list.find(([v]) => casefold(v) === casefold(name.trim()))?.[0] : undefined;
  const ok = () => {
    const n = name.trim();
    if (!old || !n || n === old) return;
    const effect = count ? `This changes ${count} card${count === 1 ? "" : "s"}.` : "No card uses this strand yet.";
    const message = `Rename “${old}” to “${n}”?\n\n${effect}${merge ? `\n\n“${merge}” already exists, so the two will be merged into one entry.` : ""}`;
    onConfirm(kind, old, n, message);
  };
  return (
    <Dialog title="Rename strand" okLabel="Rename…" onOk={ok} onCancel={onClose}>
      <div className="field"><label htmlFor="rn-kind">Rename a</label>
        <select id="rn-kind" value={kind} onChange={(e) => {
          const k = e.target.value as StrandKind;
          setKind(k);
          const first = values(k)[0]?.[0] ?? "";
          setOld(first);
          setName(first);
        }}>
          {RENAMABLE_FIELDS.map((k) => <option key={k} value={k}>{FIELD_LABELS[k]}</option>)}
        </select></div>
      <div className="field"><label htmlFor="rn-old">Current name</label>
        <select id="rn-old" value={old} disabled={!list.length} onChange={(e) => {
          setOld(e.target.value);
          setName(e.target.value);
        }}>
          {list.map(([v, n]) => <option key={v} value={v}>{n ? `${v}   (${n})` : `${v}   (unused)`}</option>)}
        </select></div>
      <div className="field"><label htmlFor="rn-new">New name</label>
        <input id="rn-new" type="text" value={name} placeholder="New name" onChange={(e) => setName(e.target.value)} /></div>
      {!list.length && <p className="muted">No card has a {FIELD_LABELS[kind].toLowerCase()} yet.</p>}
    </Dialog>
  );
}

const CATEGORY_LABELS: Record<string, string> = { ...KIND_LABELS, [COLORS_KEY]: "Custom colors" };
const CATEGORY_ORDER = [...RENAMABLE_FIELDS, COLORS_KEY];

/** A checklist of strands (and custom colours) by kind, all ticked to start with
 *  (heddle/values_dialog.py): for importing strands, and removing unused ones. `extra`
 *  lists more under a checkbox (unused strands that have details), marked ✎. */
export function StrandChecklist({ title, intro, values, okLabel, extra, extraLabel, onOk, onClose }: {
  title: string; intro: string; values: Record<string, string[]>; okLabel: string;
  extra?: Record<string, string[]>; extraLabel?: string; onOk: (chosen: Record<string, string[]>) => void; onClose: () => void;
}) {
  const [withExtra, setWithExtra] = useState(false);
  const [unticked, setUnticked] = useState<Set<string>>(new Set());
  const keyOf = (cat: string, v: string) => `${cat}\u0001${v}`;
  const shown = CATEGORY_ORDER.map((cat) => {
    const plain = values[cat] ?? [];
    const more = withExtra ? (extra?.[cat] ?? []).filter((v) => !plain.includes(v)) : [];
    return [cat, plain, more] as const;
  }).filter(([, plain, more]) => plain.length + more.length);
  const all = shown.flatMap(([cat, plain, more]) => [...plain, ...more].map((v) => keyOf(cat, v)));
  const chosen = () => {
    const out: Record<string, string[]> = {};
    for (const [cat, plain, more] of shown) {
      const picked = [...plain, ...more].filter((v) => !unticked.has(keyOf(cat, v)));
      if (picked.length) out[cat] = picked;
    }
    return out;
  };
  const n = all.filter((k) => !unticked.has(k)).length;
  const extraCount = Object.values(extra ?? {}).reduce((t, v) => t + v.length, 0);
  return (
    <Dialog title={title} okLabel={okLabel} onOk={() => n && onOk(chosen())} onCancel={onClose}>
      <p>{intro}</p>
      <div className="checklist">
        {shown.map(([cat, plain, more]) => (
          <section key={cat}>
            <label className="cat"><input type="checkbox" checked={[...plain, ...more].every((v) => !unticked.has(keyOf(cat, v)))}
                                          onChange={(e) => {
                                            const next = new Set(unticked);
                                            for (const v of [...plain, ...more]) {
                                              if (e.target.checked) next.delete(keyOf(cat, v));
                                              else next.add(keyOf(cat, v));
                                            }
                                            setUnticked(next);
                                          }} /> <strong>{CATEGORY_LABELS[cat]}</strong> <span className="muted">({plain.length + more.length})</span></label>
            <ul>
              {[...plain, ...more].map((v) => (
                <li key={v}>
                  <label title={more.includes(v) ? "Has a description, picture or fields, which will be removed too" : undefined}>
                    <input type="checkbox" checked={!unticked.has(keyOf(cat, v))} onChange={(e) => {
                      const next = new Set(unticked);
                      if (e.target.checked) next.delete(keyOf(cat, v));
                      else next.add(keyOf(cat, v));
                      setUnticked(next);
                    }} />
                    {cat === COLORS_KEY && <span className="dot" style={{ background: v }} />} {v}{more.includes(v) ? "  ✎" : ""}
                  </label>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      {extraCount > 0 && extraLabel && (
        <label><input type="checkbox" checked={withExtra} onChange={(e) => setWithExtra(e.target.checked)} /> {extraLabel}</label>
      )}
      <div className="row between">
        <span>
          <button type="button" onClick={() => setUnticked(new Set())}>Check all</button>{" "}
          <button type="button" onClick={() => setUnticked(new Set(all))}>Uncheck all</button>
        </span>
        <span className="muted">{n} of {all.length} selected</span>
      </div>
    </Dialog>
  );
}

/** Copy one strand's field names to other strands of the same kind (Strands panel → Apply
 *  to…; heddle/apply_fields_dialog.py). */
export function ApplyFields({ kind, source, fields, others, onOk, onClose }: {
  kind: StrandKind; source: string; fields: StrandField[]; others: string[];
  onOk: (targets: string[], names: string[], withValues: boolean) => void; onClose: () => void;
}) {
  const [names, setNames] = useState(new Set(fields.map(([n]) => n)));
  const [targets, setTargets] = useState<Set<string>>(new Set());
  const [find, setFind] = useState("");
  const [withValues, setWithValues] = useState(false);
  const plural = KIND_LABELS[kind].toLowerCase();
  const allOn = others.length > 0 && others.every((o) => targets.has(o));
  return (
    <Dialog title={`Apply fields from “${source}”`} okLabel="Apply" onOk={() => {
      if (names.size && targets.size) onOk([...targets], [...names], withValues);
    }} onCancel={onClose}>
      <p>Adds the ticked fields to the ticked {plural}, empty unless you tick “Also copy the values”. Fields a {KIND_ONE[kind]} already
        has keep their values, and nothing is removed.</p>
      <strong>Fields</strong>
      <div className="stack tight scroll-box">
        {fields.map(([n, v]) => (
          <label key={n} title={v ? `${n}: ${v}` : undefined}><input type="checkbox" checked={names.has(n)} onChange={(e) => {
            const next = new Set(names);
            if (e.target.checked) next.add(n);
            else next.delete(n);
            setNames(next);
          }} /> {n}</label>
        ))}
      </div>
      <strong>To these {plural}</strong>
      <div className="stack tight">
        <label><input type="checkbox" checked={allOn} disabled={!others.length}
                      onChange={() => setTargets(allOn ? new Set() : new Set(others))} /> All {plural} ({others.length})</label>
        <input type="search" className="wide-input" placeholder={`Find ${KIND_ONE[kind]}`} value={find} aria-label={`Find ${KIND_ONE[kind]}`}
               onChange={(e) => setFind(e.target.value)} />
        <div className="stack tight scroll-box tall">
          {others.filter((o) => casefold(o).includes(casefold(find.trim()))).map((o) => (
            <label key={o}><input type="checkbox" checked={targets.has(o)} onChange={(e) => {
              const next = new Set(targets);
              if (e.target.checked) next.add(o);
              else next.delete(o);
              setTargets(next);
            }} /> {o}</label>
          ))}
        </div>
        <label><input type="checkbox" checked={withValues} onChange={(e) => setWithValues(e.target.checked)} /> Also copy the values (only into empty fields)</label>
      </div>
    </Dialog>
  );
}


/** Name a strand group (heddle/strand_group_dialog.py): a new one, starting with the picked
 *  strands of the kind chosen (`picked`), or a renamed one (`name`, the kind fixed). OK stays
 *  off while the name is blank or the kind already has a strand group by that name. */
export function StrandGroupDialog({ store, kind: kind0, name: name0 = "", picked, onOk, onClose }: {
  store: BoardStore; kind: StrandKind; name?: string; picked?: Partial<Record<StrandKind, string[]>>;
  onOk: (kind: StrandKind, name: string, members: string[]) => void; onClose: () => void;
}) {
  const renaming = picked === undefined;
  const [kind, setKind] = useState<StrandKind>(kind0);
  const [name, setName] = useState(name0);
  const clean = name.split(/\s+/).filter(Boolean).join(" ");
  const taken = !!clean && casefold(clean) !== casefold(name0.trim()) && !!store.strandGroup(kind, clean);
  const members = picked?.[kind] ?? [];
  const ok = () => {
    if (clean && !taken) onOk(kind, clean, members);
  };
  return (
    <Dialog title={renaming ? "Rename Strand Group" : "New Strand Group"} okLabel={renaming ? "Rename" : "Create"} onOk={ok} onCancel={onClose}>
      <div className="field"><label htmlFor="sg-name">Name</label>
        <input id="sg-name" type="text" value={name} placeholder="e.g. Family, Act 1 tags, The Wards"
               onChange={(e) => setName(e.target.value)} /></div>
      <div className="field"><label htmlFor="sg-kind">Kind</label>
        <select id="sg-kind" value={kind} disabled={renaming} onChange={(e) => setKind(e.target.value as StrandKind)}
                title={renaming ? "A strand group's kind can't change" : "A strand group holds strands of one kind"}>
          {RENAMABLE_FIELDS.map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
        </select></div>
      {!renaming && (
        <p className="muted small-note">{members.length ? `It starts with the ${strandsText(members.length, kind)} you picked.`
          : `It starts empty. Tick ${KIND_PLURAL[kind]} in its member list, or right-click one and choose Add to Strand Group.`}</p>
      )}
      {taken && <p role="alert">There's already a {KIND_ONE[kind]} strand group called “{clean}”.</p>}
    </Dialog>
  );
}
