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
}

/** Several values as removable chips, plus a box to type more (heddle/token_input.py).
 *  Enter or a comma adds what's typed; an existing spelling on the board is reused;
 *  Backspace in an empty box removes the last chip. */
export function TokenInput({ label, values, onChange, suggestions, noun, placeholder, onPending }: Props) {
  const [text, setText] = useState("");
  const listId = useId();
  const inputId = useId();

  const add = (raw: string) => {
    const typed = raw.trim();
    if (!typed) return;
    const known = suggestions.find((s) => casefold(s) === casefold(typed));
    onChange(cleanList([...values, known ?? typed]));
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
                 else {
                   setText(v);
                   onPending?.(v);
                 }
               }}
               onKeyDown={key} onBlur={() => onPending?.(text)} />
        <datalist id={listId}>
          {suggestions.filter((s) => !have.has(casefold(s))).map((s) => <option key={s} value={s} />)}
        </datalist>
      </div>
    </div>
  );
}
