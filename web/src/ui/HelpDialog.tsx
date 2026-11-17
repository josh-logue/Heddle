import { useMemo, useState } from "react";
import controls from "../controls.md?raw";
import { inlineRuns, parseControls } from "../core/helpText.ts";
import { casefold } from "../core/pystr.ts";
import { getHost } from "../platform/host.ts";
import { Dialog } from "./Dialog.tsx";

function Rich({ text }: { text: string }) {
  return <>{inlineRuns(text).map(([t, k], i) => (k === "b" ? <strong key={i}>{t}</strong> : k === "i" ? <em key={i}>{t}</em> : t))}</>;
}

/** Help (F1): the controls from src/controls.md, with a box to find one. */
export function HelpDialog({ onClose }: { onClose: () => void }) {
  const sections = useMemo(() => parseControls(controls, getHost().kind), []); // (the desktop's or the browser's)
  const [find, setFind] = useState("");
  const needle = casefold(find.trim());
  const shown = sections
    .map(([title, entries]) => [title, needle ? entries.filter(([a, h]) => casefold(`${a} ${h}`).includes(needle)) : entries] as const)
    .filter(([, entries]) => entries.length);
  return (
    <Dialog title="Heddle controls" okLabel="Close" onOk={onClose} onCancel={onClose} single wide>
      <input type="text" className="wide-input help-find" placeholder="Find a control (e.g. thread, export, Ctrl+P)" aria-label="Find a control"
             value={find} onChange={(e) => setFind(e.target.value)} />
      <div className="help-body">
        {shown.map(([title, entries]) => (
          <section key={title}>
            <h3>{title}</h3>
            <dl>
              {entries.map(([action, how]) => (
                <div key={action} className="help-entry">
                  <dt>{action}</dt>
                  <dd><Rich text={how} /></dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        {!shown.length && <p className="muted">Nothing matches “{find}”.</p>}
      </div>
    </Dialog>
  );
}
