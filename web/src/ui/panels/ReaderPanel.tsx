import { useEffect, useReducer, useRef, type KeyboardEvent } from "react";
import { MAX_CHOICE_KEYS, type PathReader } from "../../board/reader.ts";
import { casefold } from "../../core/pystr.ts";

interface Props {
  reader: PathReader;
  /** Take the keyboard when the panel opens (Read from here). */
  autoFocus?: boolean;
}

/** The Path Reader (heddle/path_reader.py): one card at a time, with a button per way on.
 *  → / Space / Enter: next · 1–9: pick a branch · ← / Backspace: back. */
export function ReaderPanel({ reader, autoFocus }: Props) {
  const [, redraw] = useReducer((n: number) => n + 1, 0);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => reader.subscribe(redraw), [reader]);
  useEffect(() => {
    if (autoFocus) root.current?.focus({ preventScroll: true });
  }, [autoFocus, reader.version]);

  const key = (e: KeyboardEvent) => {
    let done = false;
    if (["ArrowRight", " ", "Enter"].includes(e.key)) done = reader.next();
    else if (e.key === "ArrowLeft" || e.key === "Backspace") done = reader.back();
    else if (/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) done = reader.choose(Number(e.key) - 1);
    if (done || e.key === " ") e.preventDefault(); // (Space never scrolls the panel)
  };

  const store = reader.store;
  if (!reader.reading) {
    return (
      <div className="panel reader-panel" ref={root} tabIndex={-1}>
        <h3 className="reader-title">Not reading</h3>
        <p>Right-click a card → <i>Read from here</i> (or select it and press Ctrl+Shift+R) to walk through the story from it.</p>
      </div>
    );
  }
  const route = reader.route;
  const options = reader.choices();
  const visited = new Set(route);
  const card = route.length ? store.card(route[route.length - 1]!) : undefined;
  const via = route.length ? reader.via[route.length - 1] : "";
  const meta: [string, string][] = [];
  if (card) {
    if (card.pov) meta.push(["POV", card.pov]);
    const others = card.characters.filter((c) => casefold(c) !== casefold(card.pov));
    if (others.length) meta.push(["Characters", others.join(", ")]);
    if (card.locations.length) meta.push(["Locations", card.locations.join(", ")]);
    if (card.status) meta.push(["Status", card.status]);
  }

  return (
    <div className="panel reader-panel" ref={root} tabIndex={0} data-uses-space onKeyDown={key} aria-label="Path Reader">
      <p className="muted reader-trail">{route.length ? route.map((id) => reader.title(id)).join(" → ") : `Reading “${reader.startTitle}”`}</p>
      <div className="reader-card">
        {via && <p className="reader-via"><i>via “{via}”</i></p>}
        <h3 className="reader-title">{card ? card.title || "Untitled" : reader.startTitle}</h3>
        {meta.length > 0 && (
          <p className="reader-meta">
            {meta.map(([k, v], i) => <span key={k}>{i > 0 && " · "}<strong>{k}</strong> {v}</span>)}
          </p>
        )}
        <p className="reader-body pre-wrap">
          {card ? card.description || "(no description)" : "This group has several first cards. Where do you want to begin?"}
        </p>
        {card?.notes && <p className="muted pre-wrap"><strong>Notes</strong><br />{card.notes}</p>}
      </div>
      <div className="reader-choices">
        {options.map((o, n) => {
          let text = reader.title(o.id);
          if (o.label) text = `“${o.label}” → ${text}`;
          else if (route.length) text = `→ ${text}`;
          if (visited.has(o.id)) text += "  (visited)";
          if (n < MAX_CHOICE_KEYS && options.length > 1) text = `${n + 1}.  ${text}`;
          return (
            <button key={o.id} type="button" className="reader-choice" tabIndex={-1} onClick={() => {
              reader.choose(n);
              root.current?.focus({ preventScroll: true });
            }}>{text}</button>
          );
        })}
      </div>
      {reader.endNote() && <p className="muted">{reader.endNote()}</p>}
      <div className="row reader-nav">
        <button type="button" tabIndex={-1} disabled={!reader.canGoBack} onClick={() => reader.back()}>← Back</button>
        <button type="button" tabIndex={-1} disabled={!reader.canGoBack} onClick={() => reader.restart()}>Restart</button>
        <span className="spacer" />
        <span className="muted">{route.length ? `Step ${route.length}` : ""}</span>
      </div>
      <p className="muted small-note">→ / Space: next · 1–9: pick a branch · ← / Backspace: back</p>
    </div>
  );
}
