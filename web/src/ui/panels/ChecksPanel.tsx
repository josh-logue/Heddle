import { useEffect, useMemo, useState } from "react";
import { DEFAULT_ENDING_WORD, KINDS, WARNING, runChecks, summary } from "../../core/checks.ts";
import { KIND_GROUP, titleLabels } from "../../core/model.ts";
import { casefold, strip } from "../../core/pystr.ts";
import type { BoardStore } from "../../board/store.ts";
import { readJson, writeJson } from "../../platform/settings.ts";
import { graphOf, useSettled } from "./useSettled.ts";

export const OWNER = "checks"; // marks the board's highlight as this panel's
const RECHECK_DELAY_MS = 300; // re-run this long after the board settles

interface Props {
  store: BoardStore;
  /** Select some cards and bring them into view. */
  onShow: (ids: string[]) => void;
}

/** Story Checks (heddle/checks_panel.py): dead ends, extra starts, loops, loose cards,
 *  starts, endings and the number of routes. Clicking a result finds its cards. */
export function ChecksPanel({ store, onShow }: Props) {
  const state = useSettled(store.state, RECHECK_DELAY_MS);
  const [scope, setScope] = useState<string | null>(null);
  const [word, setWord] = useState(() => readJson<string>("endingWord", DEFAULT_ENDING_WORD));
  const [typed, setTyped] = useState(word);
  const [closed, setClosed] = useState<Set<string>>(() => new Set(["start", "ending"])); // the plain lists start folded

  const groups = useMemo(() => {
    const labels = titleLabels(state.cards); // groups with the same name name their parent
    return state.cards.filter((c) => c.kind === KIND_GROUP)
      .sort((a, b) => (casefold(a.title) < casefold(b.title) ? -1 : casefold(a.title) > casefold(b.title) ? 1 : 0))
      .map((g) => [g.id, `Group: ${labels.get(g.id) ?? "Untitled"}`] as const);
  }, [state]);
  const current = scope !== null && groups.some(([id]) => id === scope) ? scope : null;
  const report = useMemo(() => runChecks(graphOf(store, state), current, word), [store, state, current, word]);

  // Leaving the panel takes its highlight away.
  useEffect(() => () => {
    if (store.highlightOwner === OWNER) store.clearHighlight();
  }, [store]);

  const commitWord = () => {
    const w = strip(typed) || DEFAULT_ENDING_WORD;
    setWord(w);
    writeJson("endingWord", w);
  };

  const pick = (kind: string, ids: readonly string[], text: string) => {
    const found = ids.filter((id) => store.card(id));
    if (!found.length) return;
    const arrows = kind === "cycle" ? store.storyGraph().arrowsWithin(found) : [];
    store.setHighlight(found, arrows, found.length === 1 ? found[0]! : null, `Check: ${text}`, OWNER);
    onShow(found);
  };

  return (
    <div className="panel checks-panel">
      <div className="field-row">
        <label htmlFor="checks-scope">Check</label>
        <select id="checks-scope" value={current ?? ""} title="Check the whole board, or just the cards in one group"
                onChange={(e) => setScope(e.target.value || null)}>
          <option value="">Whole board</option>
          {groups.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      <div className="field-row">
        <label htmlFor="checks-ending">Endings are tagged</label>
        <input id="checks-ending" type="text" value={typed} placeholder={DEFAULT_ENDING_WORD}
               title="Cards with this tag or status are endings, so they aren't reported as dead ends"
               onChange={(e) => setTyped(e.target.value)} onBlur={commitWord}
               onKeyDown={(e) => { if (e.key === "Enter") commitWord(); }} />
      </div>
      <p className="panel-summary"><strong>{summary(report)}</strong></p>
      <ul className="checks-tree" aria-label="Story check results">
        {[...KINDS].map(([kind, [title, severity]]) => {
          const found = report.ofKind(kind);
          if (!found.length) return null;
          const open = !closed.has(kind);
          const heading = `${title} (${found.length})`;
          return (
            <li key={kind}>
              <div className="checks-heading">
                <button type="button" className="icon fold" aria-expanded={open} aria-label={open ? `Fold ${title}` : `Unfold ${title}`}
                        onClick={() => {
                          const next = new Set(closed);
                          if (open) next.add(kind);
                          else next.delete(kind);
                          setClosed(next);
                        }}>{open ? "▾" : "▸"}</button>
                <button type="button" className="row-button strong" onClick={() => pick(kind, found.flatMap((f) => f.cards), heading)}>
                  {severity === WARNING ? "⚠" : "•"}  {heading}
                </button>
              </div>
              {open && (
                <ul>
                  {found.map((f, i) => (
                    <li key={i}>
                      <button type="button" className="row-button" title={f.message} onClick={() => pick(kind, f.cards, f.message)}>{f.message}</button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      <p className="muted small-note">Click a result to find its cards. Mark a deliberate ending with the tag or status above so it isn't counted as a dead end.</p>
    </div>
  );
}
