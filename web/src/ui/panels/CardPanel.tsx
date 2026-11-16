import { useEffect, useRef, useState } from "react";
import { BUILTIN_STATUSES, KIND_GROUP, KIND_STRAND, allValues, type CardData } from "../../core/model.ts";
import { casefold, strip } from "../../core/pystr.ts";
import type { BoardStore } from "../../board/store.ts";
import { TokenInput } from "../TokenInput.tsx";

/** What's typed is saved this long after you stop typing (heddle/card_panel.py). */
export const COMMIT_DELAY_MS = 700;

type Draft = Pick<CardData, "title" | "description" | "tags" | "characters" | "pov" | "locations" | "status" | "notes">;

const draftOf = (c: CardData): Draft => ({
  title: c.title, description: c.description, tags: c.tags, characters: c.characters, pov: c.pov,
  locations: c.locations, status: c.status, notes: c.notes,
});

/** The card as the panel's fields describe it, tidied as the editor dialog does. */
function tidy(card: CardData, d: Draft): Partial<CardData> {
  return {
    ...d, title: strip(d.title) || "Untitled",
    description: card.kind !== KIND_GROUP ? strip(d.description) : card.description, notes: strip(d.notes),
  };
}

interface Props {
  store: BoardStore;
  onEditCard: (id: string) => void;
  onEditSeveral: () => void;
}

/** The Card panel: edits the selected card in place, with no dialog and no OK. The editor
 *  dialog stays for what it doesn't do (type, colour, a group's members, several cards). */
export function CardPanel({ store, onEditCard, onEditSeveral }: Props) {
  const selected = [...store.selected];
  const id = selected.length === 1 ? selected[0]! : null;
  const card = id ? store.card(id) : undefined;
  if (!card) {
    return (
      <div className="panel">
        <h3>{selected.length > 1 ? `${selected.length} cards selected` : "No card selected"}</h3>
        <p className="muted">{selected.length > 1 ? "Edit their colour, tags, characters, locations and status together."
          : "Click a card to edit it here."}</p>
        {selected.length > 1 && <button type="button" onClick={onEditSeveral}>Edit {selected.length} cards…</button>}
      </div>
    );
  }
  if (card.kind === KIND_STRAND) {
    return (
      <div className="panel">
        <h3>{card.title || "Untitled"}</h3>
        <p className="muted">A strand card shows its strand: give it a description in the Strands panel.</p>
        <button type="button" onClick={() => onEditCard(card.id)}>Edit strand card…</button>
      </div>
    );
  }
  // A fresh form per card: what was typed for the last one is saved as it goes.
  return <CardForm key={card.id} store={store} card={card} onEditCard={onEditCard} />;
}

function CardForm({ store, card, onEditCard }: { store: BoardStore; card: CardData; onEditCard: (id: string) => void }) {
  // Once you type, the fields show what you typed, also after it's saved (so a title
  // cleared to nothing isn't replaced by "Untitled" under your cursor), until the card
  // changes some other way (an undo, the canvas): then they show the card as it is.
  const [draft, setDraft] = useState<{ values: Draft; saved: CardData | null } | null>(null);
  const pending = useRef<Draft | null>(null);
  const timer = useRef(0);
  const shown = draft && (draft.saved === null || draft.saved === card) ? draft.values : draftOf(card);
  const cardId = card.id;

  const commit = () => {
    clearTimeout(timer.current);
    const d = pending.current;
    pending.current = null;
    const now = store.card(cardId);
    if (!d || !now) return;
    store.updateCard(cardId, tidy(now, d));
    setDraft({ values: d, saved: store.card(cardId) ?? null });
  };
  const commitRef = useRef(commit);
  useEffect(() => {
    commitRef.current = commit;
  });
  // Leaving this card (another picked, the panel closed): keep what was typed.
  useEffect(() => () => {
    clearTimeout(timer.current);
    const d = pending.current;
    const now = store.card(cardId);
    if (d && now) store.updateCard(cardId, tidy(now, d));
  }, [store, cardId]);

  const edit = (changes: Partial<Draft>) => {
    const next = { ...shown, ...changes };
    // Removing the POV character's chip clears the POV, as in the editor.
    if (changes.characters && next.pov && !next.characters.some((c) => casefold(c) === casefold(next.pov))) next.pov = "";
    pending.current = next;
    setDraft({ values: next, saved: null });
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => commitRef.current(), COMMIT_DELAY_MS);
  };

  const board = store.board;
  const where = store.titleContext(card.id);
  const statuses = [...BUILTIN_STATUSES, ...allValues(board, "status").filter((s) => !BUILTIN_STATUSES.some((b) => casefold(b) === casefold(s)))];
  const povChoices = [...shown.characters, ...allValues(board, "characters").filter((c) => !shown.characters.some((x) => casefold(x) === casefold(c)))];
  return (
    <div className="panel card-panel" onBlur={(e) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node)) commit(); // leaving the panel saves
    }}>
      <h3>{card.kind === KIND_GROUP ? "Group" : "Card"}{where ? ` in “${where}”` : ""}</h3>
      <p className="muted small-note">Changes are saved as you pause typing (Ctrl+Z undoes).</p>
      <div className="stack">
        <label>Title<input type="text" value={shown.title} onChange={(e) => edit({ title: e.target.value })} /></label>
        {card.kind !== KIND_GROUP && (
          <label>Description
            <textarea rows={5} value={shown.description} placeholder="What happens…" onChange={(e) => edit({ description: e.target.value })} />
          </label>
        )}
        <TokenInput label="Tags" values={shown.tags} onChange={(tags) => edit({ tags })} suggestions={allValues(board, "tags")} noun="tag" />
        <TokenInput label="Characters" values={shown.characters} onChange={(characters) => edit({ characters })}
                    suggestions={allValues(board, "characters")} noun="character" />
        <label>POV
          <input type="text" list="panel-pov" value={shown.pov} placeholder="Whose point of view? (optional)" onChange={(e) => edit({ pov: e.target.value })} />
          <datalist id="panel-pov">{povChoices.map((c) => <option key={c} value={c} />)}</datalist>
        </label>
        <TokenInput label="Locations" values={shown.locations} onChange={(locations) => edit({ locations })}
                    suggestions={allValues(board, "locations")} noun="location" />
        <label>Status
          <input type="text" list="panel-status" value={shown.status} onChange={(e) => edit({ status: e.target.value })} />
          <datalist id="panel-status">{statuses.map((st) => <option key={st} value={st} />)}</datalist>
        </label>
        <label>Notes<textarea rows={3} value={shown.notes} onChange={(e) => edit({ notes: e.target.value })} /></label>
      </div>
      <button type="button" onClick={() => {
        commit();
        onEditCard(card.id);
      }} title={`Open the editor for colour, type and everything else${card.kind === KIND_GROUP ? ", and the group's cards" : ""}`}>
        {card.kind === KIND_GROUP ? "Edit group…" : "More…"}
      </button>
    </div>
  );
}
