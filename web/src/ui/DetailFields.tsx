// The fields cards and routes share: tags, characters, POV, locations, status and notes
// (heddle/details_form.py). The card editor and the route editor both use them, so the
// two behave the same.

import { useRef, useState, type ReactNode } from "react";
import { BUILTIN_STATUSES, cleanList } from "../core/model.ts";
import { casefold } from "../core/pystr.ts";
import type { BoardStore } from "../board/store.ts";
import { TokenInput } from "./TokenInput.tsx";
import { getOption } from "../platform/settings.ts";

export interface DetailValues {
  tags: string[];
  characters: string[];
  pov: string;
  locations: string[];
  status: string;
  notes: string;
}

export interface DetailFieldsState {
  tags: string[];
  setTags: (v: string[]) => void;
  /** Note what's still typed in a chip box (the tags box is the dialog's), added on OK. */
  setPending: (key: string, text: string) => void;
  /** Characters, POV, Locations, Status and Notes, in that order (the tags box goes
   *  wherever the dialog wants it). */
  fields: ReactNode;
  /** The fields as entered, with anything still typed in a chip box added, as pressing
   *  OK does on the desktop; removing the POV character's chip clears the POV. */
  values: () => DetailValues;
}

/** The shared fields, from `data` (a card or a route); `prefix` keeps element ids apart. */
export function useDetailFields(store: BoardStore, data: DetailValues, prefix: string): DetailFieldsState {
  const [tags, setTags] = useState(data.tags);
  const [characters, setCharacters] = useState(data.characters);
  const [pov, setPov] = useState(data.pov);
  const [locations, setLocations] = useState(data.locations);
  const [status, setStatus] = useState(data.status);
  const [notes, setNotes] = useState(data.notes);
  const pending = useRef<Record<string, string>>({}).current;
  const suggest = (f: "tags" | "characters" | "locations" | "status") => store.allValues(f);
  const statuses = [...BUILTIN_STATUSES, ...suggest("status").filter((s) => !BUILTIN_STATUSES.some((b) => casefold(b) === casefold(s)))];
  // POV offers this item's own characters first, then the rest of the board's.
  const povChoices = [...characters, ...suggest("characters").filter((c) => !characters.some((x) => casefold(x) === casefold(c)))];

  const values = (): DetailValues => {
    // Settings can turn this off: then only chips added with Enter count.
    const keep = getOption("commit_pending_entries");
    const withPending = (list: string[], key: string) => cleanList([...list, keep ? pending[key] ?? "" : ""]);
    const chars = withPending(characters, "characters");
    const dropped = pov && !chars.some((c) => casefold(c) === casefold(pov)) && characters.some((c) => casefold(c) === casefold(pov));
    return {
      tags: withPending(tags, "tags"), characters: chars, pov: dropped ? "" : pov,
      locations: withPending(locations, "locations"), status, notes,
    };
  };

  const fields = (
    <>
      <TokenInput label="Characters" values={characters} onChange={setCharacters} suggestions={suggest("characters")}
                  noun="character" onPending={(t) => (pending.characters = t)} />
      <div className="field">
        <label htmlFor={`${prefix}-pov`}>POV</label>
        <input id={`${prefix}-pov`} type="text" list={`${prefix}-pov-choices`} value={pov} placeholder="Whose point of view? (optional)"
               title="The point-of-view character. They're added to Characters if they aren't there already."
               onChange={(e) => setPov(e.target.value)} />
        <datalist id={`${prefix}-pov-choices`}>{povChoices.map((c) => <option key={c} value={c} />)}</datalist>
      </div>
      <TokenInput label="Locations" values={locations} onChange={setLocations} suggestions={suggest("locations")}
                  noun="location" onPending={(t) => (pending.locations = t)} />
      <div className="field">
        <label htmlFor={`${prefix}-status`}>Status</label>
        <input id={`${prefix}-status`} type="text" list={`${prefix}-status-choices`} value={status} onChange={(e) => setStatus(e.target.value)} />
        <datalist id={`${prefix}-status-choices`}>{statuses.map((s) => <option key={s} value={s} />)}</datalist>
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-notes`}>Notes</label>
        <textarea id={`${prefix}-notes`} rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
    </>
  );
  const setPending = (key: string, text: string) => {
    pending[key] = text;
  };
  return { tags, setTags, setPending, fields, values };
}
