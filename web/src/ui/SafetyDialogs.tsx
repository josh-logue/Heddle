import { useState } from "react";
import { describeTime, type Backup } from "../platform/safety.ts";
import { Dialog } from "./Dialog.tsx";

/** Pick one of a board's backups to restore (heddle/backup_dialog.py). */
export function RestoreDialog({ name, backups, onClose, onRestore }: {
  name: string; backups: [string, Backup][]; onClose: () => void; onRestore: (b: Backup) => void;
}) {
  const [pick, setPick] = useState(0);
  const chosen = backups[pick]?.[1];
  return (
    <Dialog title="Restore from backup" okLabel="Restore" onCancel={onClose} onOk={() => chosen && onRestore(chosen)}>
      <p>
        Earlier versions of <strong>{name}</strong>, newest first. Restoring replaces what's on the canvas; you can
        undo it, and nothing is written to the file until you save.
      </p>
      <ul className="pick-list backup-list" role="listbox" aria-label="Backups" tabIndex={0}
          onKeyDown={(e) => {
            const step = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
            if (!step) return;
            e.preventDefault();
            setPick(Math.max(0, Math.min(backups.length - 1, pick + step)));
          }}>
        {backups.map(([key, b], i) => (
          <li key={key} role="option" aria-selected={i === pick} className={i === pick ? "current" : ""}
              onClick={() => setPick(i)} onDoubleClick={() => onRestore(b)}>
            {describeTime(b.at)} <span className="muted">· {b.cards === null ? "unreadable" : `${b.cards} card${b.cards === 1 ? "" : "s"}`}</span>
          </li>
        ))}
      </ul>
      <p className="muted small-note">
        Backups are kept in this browser's storage: the first time you save over a board each session, then at most
        every 5 minutes, 20 per board. The browser may clear them if it runs short of space.
      </p>
    </Dialog>
  );
}
