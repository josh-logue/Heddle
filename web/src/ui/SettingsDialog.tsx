import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import { OPTIONS, getOption, setOption, type OptionKey } from "../platform/settings.ts";
import { clearErrors, describeError, errorEntries, errorReport, logError } from "../platform/errorLog.ts";
import { Dialog } from "./Dialog.tsx";

/** Copy text to the clipboard; false if the browser wouldn't. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** The error log's line in Settings: how many, copy, clear. */
function ErrorLogRow() {
  const [count, setCount] = useState(() => errorEntries().length);
  const [copied, setCopied] = useState("");
  return (
    <fieldset className="details">
      <legend>Error log</legend>
      <p className="muted small-note">
        {count ? `${count} unexpected error${count === 1 ? "" : "s"} logged in this browser.` : "No errors logged."} The log
        stays in this browser; nothing is sent anywhere.
      </p>
      <div className="row">
        <button type="button" onClick={async () => setCopied(await copyText(errorReport()) ? "Copied." : "The browser wouldn't copy it.")}>
          Copy error report
        </button>
        <button type="button" disabled={!count} onClick={() => {
          clearErrors();
          setCount(0);
          setCopied("");
        }}>Clear log</button>
        <span className="muted" role="status">{copied}</span>
      </div>
    </fieldset>
  );
}

/** Settings (heddle/settings_dialog.py): one checkbox per option, by section. Kept per
 *  browser, not with the board. */
export function SettingsDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (values: Record<OptionKey, boolean>) => void }) {
  const keys = Object.keys(OPTIONS) as OptionKey[];
  const [values, setValues] = useState(() => Object.fromEntries(keys.map((k) => [k, getOption(k)])) as Record<OptionKey, boolean>);
  const sections = [...new Set(keys.map((k) => OPTIONS[k][1]))];
  return (
    <Dialog title="Settings" onCancel={onClose} onOk={() => {
      for (const k of keys) setOption(k, values[k]);
      onSaved(values);
    }}>
      {sections.map((section) => (
        <fieldset key={section} className="details">
          <legend>{section}</legend>
          {keys.filter((k) => OPTIONS[k][1] === section).map((k) => (
            <label key={k} className="block-check" title={OPTIONS[k][3]}>
              <input type="checkbox" checked={values[k]} onChange={(e) => setValues({ ...values, [k]: e.target.checked })} /> {OPTIONS[k][2]}
            </label>
          ))}
        </fieldset>
      ))}
      <ErrorLogRow />
    </Dialog>
  );
}

/** "Something went wrong": the page is still running; suggests keeping a copy of the board. */
export function ErrorDialog({ summary, onClose }: { summary: string; onClose: () => void }) {
  const [copied, setCopied] = useState("");
  return (
    <Dialog title="Something went wrong" okLabel="Close" onOk={onClose} onCancel={onClose} single>
      <p>
        Heddle hit an unexpected error. It's still running, but to be safe, consider saving a copy of your board
        (File → Save as…) and checking it.
      </p>
      <p className="muted error-summary">{summary}</p>
      <div className="row">
        <button type="button" onClick={async () => setCopied(await copyText(errorReport()) ? "Copied: paste it into a bug report." : "The browser wouldn't copy it.")}>
          Copy error report
        </button>
        <span className="muted" role="status">{copied}</span>
      </div>
      <p className="muted small-note">The details are kept in this browser's error log (Edit → Settings). Nothing is sent anywhere.</p>
    </Dialog>
  );
}

/** A crash while drawing the interface: logged, and a page that says so instead of a
 *  blank one. Unsaved changes may still be in a draft (offered after reloading). */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  override state = { error: null as string | null };

  static getDerivedStateFromError(e: unknown) {
    return { error: describeError(e) };
  }

  override componentDidCatch(e: unknown) {
    logError(describeError(e));
  }

  override render() {
    if (this.state.error === null) return this.props.children;
    return <CrashPage summary={this.state.error.split("\n")[0] ?? ""} />;
  }
}

function CrashPage({ summary }: { summary: string }) {
  const [copied, setCopied] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  return (
    <section className="welcome crash" role="alert">
      <h1 ref={heading} tabIndex={-1}>Something went wrong</h1>
      <p>
        Heddle hit an error it couldn't recover from. Reload the page: a board with unsaved changes is usually offered
        back from its last draft.
      </p>
      <p className="muted error-summary">{summary}</p>
      <div className="welcome-actions">
        <button type="button" className="primary" onClick={() => location.reload()}>Reload</button>
        <button type="button" onClick={async () => setCopied(await copyText(errorReport()) ? "Copied." : "The browser wouldn't copy it.")}>
          Copy error report
        </button>
        <span className="muted" role="status">{copied}</span>
      </div>
    </section>
  );
}
