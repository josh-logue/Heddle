import { useId, useState, type KeyboardEvent } from "react";
import { cleanList } from "../core/model.ts";
import { casefold } from "../core/pystr.ts";

interface Props {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  suggestions: readonly string[];
  /** "tag", "character"…: for the placeholder and the remove buttons. */
  noun: string;
  placeholder?: string;
  /** The text still typed in the box, so OK can add it (as the desktop does by default). */
  onPending?: (text: string) => void;
  /** Strand groups ({name: strands}): offered after the strands (see groupLabel); picking one
   *  adds all its strands. Typing a group's bare name still adds a strand by that name. */
  groups?: ReadonlyMap<string, readonly string[]>;
}

/** How a strand group is offered among a box's suggestions: "Family · strand group (3)". */
export function groupLabel(name: string, members: readonly string[]): string {
  return `${name} · strand group (${members.length})`;
}

/** Several values as removable chips, plus a box to type more (heddle/token_input.py).
 *  Enter or a comma adds what's typed; an existing spelling on the board is reused;
 *  Backspace in an empty box removes the last chip. */
export function TokenInput({ label, values, onChange, suggestions, noun, placeholder, onPending, groups }: Props) {
  const [text, setText] = useState("");
  const listId = useId();
  const inputId = useId();
  const labels = new Map([...(groups ?? new Map<string, readonly string[]>())]
    .filter(([, members]) => members.length).map(([name, members]) => [groupLabel(name, members), members]));
  const spell = (typed: string) => suggestions.find((s) => casefold(s) === casefold(typed)) ?? typed;

  const add = (raw: string) => {
    const typed = raw.trim();
    if (!typed) return;
    const members = labels.get(typed); // a strand group's suggestion: all its strands
    onChange(cleanList([...values, ...(members ? members.map((m) => spell(m)) : [spell(typed)])]));
    setText("");
    onPending?.("");
  };

  const key = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      if (text.trim()) {
        e.preventDefault(); // (Enter on an empty box submits the dialog)
        add(text);
      } else if (e.key === ",") {
        e.preventDefault();
      }
    } else if (e.key === "Backspace" && !text && values.length) {
      onChange(values.slice(0, -1));
    }
  };

  const have = new Set(values.map(casefold));
  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      <div className="tokens">
        {values.map((v) => (
          <span className="chip" key={v}>
            {v}
            <button type="button" aria-label={`Remove ${noun} ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>×</button>
          </span>
        ))}
        <input id={inputId} type="text" list={listId} value={text} placeholder={values.length ? "" : placeholder ?? `Add a ${noun}`}
               onChange={(e) => {
                 const v = e.target.value;
                 if (v.endsWith(",")) add(v.slice(0, -1));
                 else if (labels.has(v)) add(v); // picked from the list: no one types a group's label
                 else {
                   setText(v);
                   onPending?.(v);
                 }
               }}
               onKeyDown={key} onBlur={() => onPending?.(text)} />
        <datalist id={listId}>
          {suggestions.filter((s) => !have.has(casefold(s))).map((s) => <option key={s} value={s} />)}
          {/* Strand groups follow the strands, while they'd still add something. */}
          {[...labels].filter(([, members]) => members.some((m) => !have.has(casefold(m))))
            .map(([l]) => <option key={`group:${l}`} value={l} />)}
        </datalist>
      </div>
    </div>
  );
}
