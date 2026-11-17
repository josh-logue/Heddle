// One open board's saving: Save and Save As, autosave, drafts, backups and the check for
// changes made to its file elsewhere (heddle/main_window.py's _write, _autosave, _backup,
// _changed_on_disk and the recovery copies). No React here: App makes one per board, on
// the host's files, storage and locks (tests pass an in-memory host).

import type { BoardStore } from "../board/store.ts";
import type { Db } from "../platform/db.ts";
import { baseName, jsonName, type FileRef } from "../platform/files.ts";
import type { HostBackups, HostFiles } from "../platform/host.ts";
import {
  boardOpenElsewhere, cardCount, discardDraft, fileKey, lockBoard, lockDraft, writeDraft,
  type Backup, type Locks,
} from "../platform/safety.ts";

export const AUTOSAVE_MS = 60_000;
export const AUTOSAVE_RETRY_MS = [10_000, 30_000, 60_000]; // after a failed autosave; the last repeats
export const AUTOSAVE_BUSY_RETRY_MS = 5_000; // a dialog was open when autosave was due

export type ConflictChoice = "overwrite" | "save_as" | "cancel";

export interface SessionHost {
  /** A short message for the user. */
  notice(text: string): void;
  /** The board's file changed since it was opened or saved here: what now? */
  askConflict(name: string): Promise<ConflictChoice>;
  /** A dialog is open (perhaps a new card's editor, which cancelling removes): autosave waits. */
  busy(): boolean;
  autosaveOn(): boolean;
  /** The name, file or status changed (redraw the toolbar). */
  changed(): void;
}

/** What a session uses of the host (host.ts): its files, storage and locks. */
export interface SessionPlatform {
  files: Pick<HostFiles, "read" | "write" | "pickSave" | "download" | "same">;
  db: Db;
  locks: Locks;
  backups: HostBackups;
}

export interface SessionStart {
  name: string;
  handle: FileRef | null;
  /** The file's text as opened (null: no file yet). */
  text: string | null;
  /** Keep writing to this draft (a recovered one); else a fresh draft id. */
  draftId?: string;
}

const time = (ms: number) => new Date(ms).toTimeString().slice(0, 5);

export class BoardSession {
  name: string;
  handle: FileRef | null;
  /** What this tab last read from or wrote to the file (to spot changes made elsewhere). */
  diskText: string | null;
  readonly draftId: string;
  /** Shown beside the board's name: "Autosaved 14:05", "Draft kept 14:05"… */
  status = "";
  /** Autosave stopped after the user chose not to overwrite changes made elsewhere. */
  blocked = false;
  /** Did opening find this file already open in another tab? */
  openElsewhere = false;
  private key = "";
  private timer: ReturnType<typeof setTimeout> | 0 = 0;
  private failures = 0;
  private conflictPending = false;
  private backedUp = false; // this session has backed up its file once (the file as opened)
  private hasDraft = false;
  private releases: (() => void)[] = [];
  private readonly unsubscribe: () => void;
  private disposed = false;

  private readonly db: Db;
  private readonly locks: Locks;
  private readonly files: SessionPlatform["files"];
  private readonly backupStore: HostBackups;

  constructor(readonly store: BoardStore, start: SessionStart, platform: SessionPlatform, private readonly host: SessionHost,
              private readonly now: () => number = Date.now) {
    this.db = platform.db;
    this.locks = platform.locks;
    this.files = platform.files;
    this.backupStore = platform.backups;
    this.name = start.name;
    this.handle = start.handle;
    this.diskText = start.text;
    this.draftId = start.draftId ?? `${now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    this.hasDraft = !!start.draftId;
    this.unsubscribe = store.subscribe(() => {
      if (store.modified) this.schedule();
    });
  }

  /** Take the locks, learn the file's key, and see whether another tab has it open. */
  async start(): Promise<void> {
    this.releases.push(await lockDraft(this.locks, this.draftId));
    await this.identify();
  }

  private async identify(): Promise<void> {
    this.key = await fileKey(this.db, this.handle, this.name, this.now(), this.files.same);
    if (this.handle) {
      this.openElsewhere = await boardOpenElsewhere(this.locks, this.key);
      this.releases.push(await lockBoard(this.locks, this.key));
    }
  }

  /** The board's file key (backups are kept under it). */
  get fileKey(): string {
    return this.key;
  }

  /** Stop: the board is being replaced or the page closed. `discard` drops its draft
   *  (the user chose to throw the changes away, or there were none). */
  async dispose(discard: boolean): Promise<void> {
    this.disposed = true;
    this.cancelTimer();
    this.unsubscribe();
    if (discard) await this.dropDraft();
    for (const release of this.releases) release();
    this.releases = [];
  }

  // ----- saving ---------------------------------------------------------------------------

  /** Save (Ctrl+S): back to the file where the browser allows it, else Save As. */
  async save(as = false): Promise<boolean> {
    if (!as && this.handle) return this.writeInPlace(this.handle, false, false);
    const target = await this.files.pickSave(this.name);
    if (target === null) return false;
    const [text, state] = this.store.committedJson();
    if (target === "download") {
      await this.backup(this.diskText, false);
      this.files.download(text, jsonName(this.name));
      this.saved(text, state);
      this.host.notice(`Downloaded “${jsonName(this.name)}”. This browser can't save in place: each save downloads a new copy.`);
      return true;
    }
    const same = this.handle !== null && this.key && (await fileKey(this.db, target, baseName(target.name), this.now(), this.files.same)) === this.key;
    if (!same) {
      for (const release of this.releases.splice(1)) release(); // the old file's lock
      this.handle = target;
      this.name = baseName(target.name);
      this.diskText = null;
      this.backedUp = false;
      await this.identify();
    }
    return this.writeInPlace(target, false, false);
  }

  /** Write the board to its file, backing up what's there first. Refuses to silently
   *  overwrite changes made elsewhere: Save asks; autosave (`quiet`) asks once it's done. */
  private async writeInPlace(handle: FileRef, quiet: boolean, overwrite: boolean): Promise<boolean> {
    // Save may ask to read the file (a lapsed permission would read as nothing: no check
    // for changes made elsewhere, and no backup of them).
    const current = await this.files.read(handle, !quiet);
    const changed = this.diskText !== null && current !== null && current !== this.diskText;
    if (changed && !overwrite) {
      if (quiet) {
        if (!this.conflictPending) {
          this.conflictPending = true;
          setTimeout(() => void this.resolveConflict(), 0); // once this autosave has finished
        }
        return false;
      }
      const choice = await this.host.askConflict(this.name);
      if (choice === "save_as") return this.save(true);
      if (choice !== "overwrite") return false;
    }
    // The version about to be replaced; changes made elsewhere are always kept.
    await this.backup(current, changed);
    const [text, state] = this.store.committedJson();
    try {
      await this.files.write(handle, text, !quiet);
    } catch (e) {
      if (quiet) throw e; // autosave keeps a draft and tries again
      this.host.notice(e instanceof Error && e.message ? e.message : `Couldn't save “${this.name}”: ${String(e)}`);
      return false;
    }
    this.saved(text, state);
    this.status = quiet ? `Autosaved ${time(this.now())}` : `Saved ${time(this.now())}`;
    if (!quiet) this.host.notice(`Saved “${this.name}”.`);
    this.host.changed();
    return true;
  }

  private saved(text: string, state: ReturnType<BoardStore["committedJson"]>[1]): void {
    this.diskText = text;
    this.blocked = false;
    this.failures = 0;
    this.cancelTimer();
    this.store.markSaved(state);
    void this.dropDraft();
    if (this.handle) void fileKey(this.db, this.handle, this.name, this.now(), this.files.same); // to the top of Open Recent
  }

  private async backup(text: string | null, force: boolean): Promise<void> {
    if (text === null) return;
    try {
      await this.backupStore.make(this.backupTarget, text, this.now(), force || !this.backedUp);
      this.backedUp = true;
    } catch (e) { // a failed backup mustn't stop the save itself
      this.host.notice(`Couldn't back up “${this.name}”: ${String(e)}`);
    }
  }

  private async resolveConflict(): Promise<void> {
    this.conflictPending = false;
    const handle = this.handle;
    if (!handle || this.disposed) return;
    const current = await this.files.read(handle);
    if (current === null || current === this.diskText) { // resolved itself meanwhile
      this.schedule();
      return;
    }
    this.cancelTimer();
    const choice = await this.host.askConflict(this.name);
    if (choice === "overwrite") await this.writeInPlace(handle, false, true).catch(() => false);
    else if (choice === "save_as") await this.save(true).catch(() => false);
    else {
      this.blocked = true;
      this.status = "Autosave paused: the file changed elsewhere";
      this.host.notice("Autosave paused: the file changed on disk. Save (Ctrl+S) to choose what to do.");
      this.host.changed();
    }
  }

  // ----- autosave and drafts --------------------------------------------------------------

  /** Autosave a minute after a change (unless one is already due). */
  schedule(delay = AUTOSAVE_MS): void {
    if (this.disposed || this.timer || this.blocked || !this.host.autosaveOn()) return;
    this.timer = setTimeout(() => {
      this.timer = 0;
      void this.autosave();
    }, delay);
  }

  private cancelTimer(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = 0;
  }

  /** Autosave the board now: into its file where possible, else as a draft. */
  async autosave(): Promise<void> {
    this.cancelTimer();
    if (this.disposed || !this.store.modified || !this.host.autosaveOn() || this.blocked) return;
    if (this.host.busy()) {
      this.schedule(AUTOSAVE_BUSY_RETRY_MS);
      return;
    }
    if (this.handle) {
      try {
        if (await this.writeInPlace(this.handle, true, false)) return;
        if (this.conflictPending) return; // asked once the current step is done
      } catch (e) {
        // Often brief (the file busy); or this page may no longer write to it until a
        // click allows it again. Keep a draft meanwhile, and try again later.
        const delay = AUTOSAVE_RETRY_MS[Math.min(this.failures, AUTOSAVE_RETRY_MS.length - 1)]!;
        this.failures++;
        await this.keepDraft(`Couldn't autosave to the file (${e instanceof Error ? e.message : String(e)}): kept a draft`);
        this.schedule(delay);
        return;
      }
    }
    await this.keepDraft();
  }

  /** Keep the board's unsaved state as a draft (offered for recovery if the tab goes). */
  async keepDraft(status?: string): Promise<void> {
    if (this.disposed || !this.store.modified) return;
    const [text] = this.store.committedJson();
    try {
      await writeDraft(this.db, {
        id: this.draftId, name: this.name, text, at: this.now(), cards: cardCount(text) ?? 0, handle: this.handle,
        disk: this.diskText,
      });
    } catch {
      try { // a handle the browser can't store: keep the board without it
        await writeDraft(this.db, { id: this.draftId, name: this.name, text, at: this.now(), cards: cardCount(text) ?? 0 });
      } catch (e) {
        this.status = "Couldn't keep a draft";
        this.host.notice(`Couldn't keep a draft of “${this.name}” in browser storage: ${String(e)}`);
        this.host.changed();
        return;
      }
    }
    this.hasDraft = true;
    this.status = status ?? `Draft kept ${time(this.now())}`;
    this.host.changed();
  }

  private async dropDraft(): Promise<void> {
    if (!this.hasDraft) return;
    this.hasDraft = false;
    await discardDraft(this.db, this.draftId).catch(() => undefined);
  }

  // ----- backups --------------------------------------------------------------------------

  backups(): Promise<[string, Backup][]> {
    return this.backupStore.list(this.backupTarget);
  }

  private get backupTarget() {
    return { key: this.key, ref: this.handle, name: this.name };
  }
}
