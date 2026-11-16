import { useRef, useState } from "react";
import {
  ARROW_STYLES, BUILTIN_STATUSES, CARD_COLORS, COLOR_NAMES, allValues, cleanList,
  type ArrowStyle, type CardData, type CardKind, type ConnectionData,
} from "../core/model.ts";
import { casefold } from "../core/pystr.ts";
import type { BoardStore } from "../board/store.ts";
import { Dialog } from "./Dialog.tsx";
import { TokenInput } from "./TokenInput.tsx";

const STRAND_KINDS = [["characters", "Character"], ["locations", "Location"], ["tags", "Tag"], ["status", "Status"]] as const;

function Swatches({ value, onChange, custom, allowNone }: {
  value: string | null; onChange: (c: string) => void; custom: readonly string[]; allowNone?: boolean;
}) {
  const colors = [...CARD_COLORS, ...custom.filter((c) => !(CARD_COLORS as readonly string[]).includes(c))];
  const own = value !== null && value !== "" && !colors.includes(value);
  return (
    <div className="swatches" role="radiogroup">
      {allowNone && (
        <button type="button" role="radio" aria-checked={value === ""} className="swatch none"
                title="The theme's arrow colour" onClick={() => onChange("")}>∅</button>
      )}
      {[...colors, ...(own ? [value!] : [])].map((c) => (
        <button key={c} type="button" role="radio" aria-checked={c === value} className="swatch"
                style={{ background: c }} title={COLOR_NAMES.get(c) ?? c} aria-label={COLOR_NAMES.get(c) ?? c}
                onClick={() => onChange(c)} />
      ))}
      <label className="swatch custom" title="Custom colour…">
        +
        <input type="color" value={value || "#4a7fc1"} aria-label="Custom colour"
               onChange={(e) => onChange(e.target.value.toLowerCase())} />
      </label>
    </div>
  );
}

interface CardEditorProps {
  store: BoardStore;
  id: string;
  isNew: boolean;
  onClose: () => void;
}

/** Edit a card, group or strand card (heddle/dialogs.py CardDialog). The parts that
 *  belong to later stages (a group's member list and arrange options) aren't here yet. */
export function CardEditor({ store, id, isNew, onClose }: CardEditorProps) {
  const card = store.card(id)!;
  const [kind, setKind] = useState<CardKind>(card.kind);
  const [title, setTitle] = useState(card.title);
  const [description, setDescription] = useState(card.description);
  const [color, setColor] = useState(card.color);
  const [tags, setTags] = useState(card.tags);
  const [characters, setCharacters] = useState(card.characters);
  const [pov, setPov] = useState(card.pov);
  const [locations, setLocations] = useState(card.locations);
  const [status, setStatus] = useState(card.status);
  const [notes, setNotes] = useState(card.notes);
  const [outside, setOutside] = useState(card.outside_story);
  const [strandKind, setStrandKind] = useState(card.strand_kind || "characters");
  const [strand, setStrand] = useState(card.strand);
  const pending = useRef<Record<string, string>>({}).current;
  const board = store.board;
  const suggest = (f: "tags" | "characters" | "locations" | "status") => allValues(board, f);
  const statuses = [...BUILTIN_STATUSES, ...suggest("status").filter((s) => !BUILTIN_STATUSES.some((b) => casefold(b) === casefold(s)))];
  const povChoices = [...characters, ...suggest("characters").filter((c) => !characters.some((x) => casefold(x) === casefold(c)))];

  const ok = () => {
    // Anything still typed in a chip box is added, as pressing OK does on the desktop.
    const withPending = (values: string[], key: string) => cleanList([...values, pending[key] ?? ""]);
    const chars = withPending(characters, "characters");
    const data: Partial<CardData> = {
      kind, title, description, color, tags: withPending(tags, "tags"), characters: chars,
      // Removing the POV character's chip clears the POV.
      pov: pov && !chars.some((c) => casefold(c) === casefold(pov)) && characters.some((c) => casefold(c) === casefold(pov)) ? "" : pov,
      locations: withPending(locations, "locations"), status, notes, outside_story: outside,
      strand_kind: kind === "strand" ? strandKind : "", strand: kind === "strand" ? strand : "",
    };
    store.updateCard(id, data);
    onClose();
  };
  const cancel = () => {
    if (isNew) store.discardNew(id);
    onClose();
  };
  const name = kind === "group" ? "group" : kind === "strand" ? "strand card" : "card";

  return (
    <Dialog title={`${isNew ? "New" : "Edit"} ${name}`} onOk={ok} onCancel={cancel} wide>
      <div className="field">
        <span className="label">Type</span>
        <div className="radios" role="radiogroup" aria-label="Type">
          {([["card", "Card", "A single scene or story beat"], ["group", "Group", "A container that other cards sit on top of"],
            ["strand", "Strand", "Stands for a character, location, tag or status"]] as const).map(([k, label, tip]) => (
            <label key={k} title={tip}><input type="radio" name="kind" checked={kind === k} onChange={() => setKind(k)} /> {label}</label>
          ))}
        </div>
      </div>
      {kind === "strand" ? (
        <div className="field">
          <label htmlFor="strand-name">Strand</label>
          <div className="row">
            <select value={strandKind} onChange={(e) => setStrandKind(e.target.value)} aria-label="Strand kind">
              {STRAND_KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
            <input id="strand-name" type="text" list="strand-names" value={strand} placeholder="Pick one, or type a new one"
                   onChange={(e) => setStrand(e.target.value)} />
            <datalist id="strand-names">
              {suggest(strandKind as "tags").map((s) => <option key={s} value={s} />)}
            </datalist>
          </div>
        </div>
      ) : (
        <>
          <div className="field">
            <label htmlFor="card-title">Title</label>
            <input id="card-title" type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <TokenInput label="Tags" values={tags} onChange={setTags} suggestions={suggest("tags")} noun="tag"
                      placeholder="Type a tag (e.g. Act 1, Subplot B) and press Enter" onPending={(t) => (pending.tags = t)} />
        </>
      )}
      <div className="field">
        <span className="label">Color</span>
        <Swatches value={color} onChange={setColor} custom={store.state.custom_colors} />
      </div>
      {kind === "card" && (
        <div className="field">
          <label htmlFor="card-desc">Description</label>
          <textarea id="card-desc" rows={5} value={description} placeholder="What happens in this scene or beat?"
                    onChange={(e) => setDescription(e.target.value)} />
        </div>
      )}
      {kind !== "strand" && store.state.display.story_tools && (
        <div className="field">
          <span className="label">Story</span>
          <label title="Leave it out of story checks, routes, character introductions and threads (a group: with everything in it)">
            <input type="checkbox" checked={outside} onChange={(e) => setOutside(e.target.checked)} /> Not part of the story
          </label>
        </div>
      )}
      {kind !== "strand" && (
        <fieldset className="details">
          <legend>Details (hidden on the card until you click its ▸)</legend>
          <TokenInput label="Characters" values={characters} onChange={setCharacters} suggestions={suggest("characters")}
                      noun="character" onPending={(t) => (pending.characters = t)} />
          <div className="field">
            <label htmlFor="card-pov">POV</label>
            <input id="card-pov" type="text" list="pov-choices" value={pov} placeholder="Whose point of view? (optional)"
                   title="The point-of-view character. They're added to Characters if they aren't there already."
                   onChange={(e) => setPov(e.target.value)} />
            <datalist id="pov-choices">{povChoices.map((c) => <option key={c} value={c} />)}</datalist>
          </div>
          <TokenInput label="Locations" values={locations} onChange={setLocations} suggestions={suggest("locations")}
                      noun="location" onPending={(t) => (pending.locations = t)} />
          <div className="field">
            <label htmlFor="card-status">Status</label>
            <input id="card-status" type="text" list="status-choices" value={status} onChange={(e) => setStatus(e.target.value)} />
            <datalist id="status-choices">{statuses.map((s) => <option key={s} value={s} />)}</datalist>
          </div>
          <div className="field">
            <label htmlFor="card-notes">Notes</label>
            <textarea id="card-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </fieldset>
      )}
    </Dialog>
  );
}

interface ArrowEditorProps {
  store: BoardStore;
  ids: string[];
  onClose: () => void;
}

/** Edit one arrow's label, line and colour, or several arrows' line and colour
 *  (heddle/arrow_dialog.py). Anything left unset stays as it is on each arrow. */
export function ArrowEditor({ store, ids, onClose }: ArrowEditorProps) {
  const conns = store.state.connections.filter((c) => ids.includes(c.id));
  const single = conns.length === 1;
  const same = <K extends keyof ConnectionData>(k: K) => (conns.every((c) => c[k] === conns[0]![k]) ? conns[0]![k] : null);
  const [label, setLabel] = useState(conns[0]?.label ?? "");
  const [style, setStyle] = useState<ArrowStyle | null>(same("style"));
  const [color, setColor] = useState<string | null>(same("color"));
  if (!conns.length) return null;
  const ok = () => {
    store.updateArrows(ids, {
      ...(single ? { label } : {}), ...(style !== null ? { style } : {}), ...(color !== null ? { color } : {}),
    });
    onClose();
  };
  return (
    <Dialog title={single ? "Edit arrow" : `Edit ${conns.length} arrows`} onOk={ok} onCancel={onClose}>
      {single && (
        <div className="field">
          <label htmlFor="arrow-label">Label</label>
          <input id="arrow-label" type="text" value={label} placeholder="Shown on the arrow (optional)" onChange={(e) => setLabel(e.target.value)} />
        </div>
      )}
      <div className="field">
        <span className="label">Line</span>
        <div className="radios" role="radiogroup" aria-label="Line">
          {ARROW_STYLES.map((s) => (
            <label key={s}><input type="radio" name="style" checked={style === s} onChange={() => setStyle(s)} /> {s[0]!.toUpperCase() + s.slice(1)}</label>
          ))}
        </div>
      </div>
      <div className="field">
        <span className="label">Color</span>
        <Swatches value={color} onChange={setColor} custom={store.state.custom_colors} allowNone />
      </div>
      {!single && <p className="muted">Anything you leave unset stays as it is on each arrow.</p>}
    </Dialog>
  );
}
