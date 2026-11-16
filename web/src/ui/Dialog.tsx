import { useEffect, useRef, type FormEvent, type ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
  onOk: () => void;
  onCancel: () => void;
  okLabel?: string;
  wide?: boolean;
}

/** A modal dialog (the browser's <dialog>): Enter in a one-line box is OK, Esc cancels. */
export function Dialog({ title, children, onOk, onCancel, okLabel = "OK", wide }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current!;
    d.showModal();
    // Focus the first text box, with its text selected (as the desktop's title box).
    const first = d.querySelector<HTMLInputElement | HTMLTextAreaElement>("input[type=text], textarea");
    first?.focus();
    first?.select();
    return () => d.close();
  }, []);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onOk();
  };
  return (
    <dialog ref={ref} className={wide ? "dialog wide" : "dialog"} aria-label={title}
            onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <form method="dialog" onSubmit={submit}>
        <h2>{title}</h2>
        <div className="dialog-body">{children}</div>
        <div className="dialog-buttons">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="submit" className="primary">{okLabel}</button>
        </div>
      </form>
    </dialog>
  );
}

/** Ask a yes/no question. */
export function Confirm({ message, okLabel, onAnswer }: { message: string; okLabel: string; onAnswer: (yes: boolean) => void }) {
  return (
    <Dialog title="Heddle" okLabel={okLabel} onOk={() => onAnswer(true)} onCancel={() => onAnswer(false)}>
      {message.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}
    </Dialog>
  );
}
