// Drafts, backups, recent files and the board session's saving (autosave, conflicts,
// backups before overwriting). Ported in spirit from tests/test_backups.py,
// tests/test_recovery.py and the autosave tests of the desktop window.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { boardFromDict } from "../src/core/model.ts";
import { BoardStore } from "../src/board/store.ts";
import { fakeMeasurer } from "../src/board/text.ts";
import { MemoryDb } from "../src/platform/db.ts";
import type { FileRef } from "../src/platform/files.ts";
import {
  BACKUP_INTERVAL_MS, MemoryLocks, cardCount, dbBackups, describeTime, discardDraft, fileKey, listBackups, lockDraft, makeBackup,
  orphanDrafts, recentFiles, writeDraft,
} from "../src/platform/safety.ts";
import {
  AUTOSAVE_BUSY_RETRY_MS, AUTOSAVE_MS, BoardSession, type ConflictChoice, type SessionHost, type SessionPlatform,
} from "../src/ui/session.ts";

const MIN = 60_000;
const T0 = Date.UTC(2026, 10, 16, 9, 0, 0);

describe("backups", () => {
  it("keeps the first, then at most one every 5 minutes unless forced, newest first", async () => {
    const db = new MemoryDb();
    expect(await makeBackup(db, "f", "Tracks", '{"cards":[{}]}', T0)).not.toBeNull();
    expect(await makeBackup(db, "f", "Tracks", '{"cards":[]}', T0 + MIN)).toBeNull();
    expect(await makeBackup(db, "f", "Tracks", '{"cards":[{},{}]}', T0 + MIN, true)).not.toBeNull();
    expect(await makeBackup(db, "f", "Tracks", '{"cards":[{},{},{}]}', T0 + BACKUP_INTERVAL_MS + MIN)).not.toBeNull();
    const list = await listBackups(db, "f");
    expect(list.map(([, b]) => b.cards)).toEqual([3, 2, 1]);
    expect(await listBackups(db, "other")).toEqual([]);
  });

  it("keeps the newest 20 per board, and skips empty text", async () => {
    const db = new MemoryDb();
    for (let i = 0; i < 25; i++) await makeBackup(db, "f", "B", `{"cards":[],"n":${i}}`, T0 + i * 10 * MIN);
    await makeBackup(db, "g", "C", '{"cards":[]}', T0);
    const list = await listBackups(db, "f");
    expect(list.length).toBe(20);
    expect(list[0]![1].text).toContain('"n":24');
    expect(list.at(-1)![1].text).toContain('"n":5');
    expect((await listBackups(db, "g")).length).toBe(1);
    expect(await makeBackup(db, "h", "D", "  ", T0)).toBeNull();
  });

  it("counts cards, and describes times as the desktop does", () => {
    expect(cardCount('{"cards":[1,2]}')).toBe(2);
    expect(cardCount("not json")).toBeNull();
    const now = new Date(2026, 10, 16, 15, 0, 0).getTime();
    expect(describeTime(new Date(2026, 10, 16, 14, 5, 22).getTime(), now)).toBe("Today, 14:05:22");
    expect(describeTime(new Date(2026, 10, 15, 9, 1, 2).getTime(), now)).toBe("Yesterday, 09:01:02");
    expect(describeTime(new Date(2026, 10, 2, 9, 1, 2).getTime(), now)).toBe("Mon 02 Nov 2026, 09:01:02");
  });
});

describe("drafts and recovery", () => {
  it("offers only drafts whose tab has gone, newest first", async () => {
    const db = new MemoryDb();
    const locks = new MemoryLocks();
    const draft = (id: string, at: number) => writeDraft(db, { id, name: id, text: "{}", at, cards: 0 });
    await draft("old", T0);
    await draft("new", T0 + MIN);
    await draft("open", T0 + 2 * MIN);
    const release = await lockDraft(locks, "open");
    expect((await orphanDrafts(db, locks)).map((d) => d.id)).toEqual(["new", "old"]);
    release();
    expect((await orphanDrafts(db, locks)).map((d) => d.id)).toEqual(["open", "new", "old"]);
    await discardDraft(db, "new");
    expect((await orphanDrafts(db, locks)).map((d) => d.id)).toEqual(["open", "old"]);
  });
});

/** A file the session can read and write, which "someone else" can change too. */
type SessionFiles = SessionPlatform["files"];
class FakeFiles implements SessionFiles {
  readonly contents = new Map<FileRef, string>();
  writes = 0;
  denied = false;
  picks: (FileRef | null | "download")[] = [];
  downloads: [string, string][] = [];
  /** Runs while a write is under way. */
  during: (() => void) | null = null;
  handle(name: string, text: string | null = null): FileRef {
    const h: FileRef = { name };
    if (text !== null) this.contents.set(h, text);
    return h;
  }
  async read(h: FileRef) {
    return this.contents.get(h) ?? null;
  }
  async write(h: FileRef, text: string, ask: boolean) {
    if (this.denied && !ask) throw new Error("not allowed");
    this.writes++;
    this.during?.();
    this.contents.set(h, text);
  }
  async pickSave() {
    return this.picks.shift() ?? null;
  }
  async same(a: FileRef, b: FileRef) {
    return a === b;
  }
  download(text: string, name: string) {
    this.downloads.push([name, text]);
  }
}

describe("the board session", () => {
  const m = fakeMeasurer();
  let db: MemoryDb;
  let locks: MemoryLocks;
  let files: FakeFiles;
  let clock: number;
  let answers: ConflictChoice[];
  let notices: string[];
  let busy: boolean;
  const host: SessionHost = {
    notice: (t) => notices.push(t), askConflict: async () => answers.shift() ?? "cancel",
    busy: () => busy, autosaveOn: () => true, changed: () => {},
  };
  beforeEach(() => {
    vi.useFakeTimers();
    db = new MemoryDb();
    locks = new MemoryLocks();
    files = new FakeFiles();
    clock = T0;
    answers = [];
    notices = [];
    busy = false;
  });
  afterEach(() => vi.useRealTimers());

  const ORIGINAL = '{"cards":[{"id":"a","title":"Rowan"}]}';
  async function open(withFile = true) {
    const store = new BoardStore(boardFromDict(JSON.parse(ORIGINAL)), m);
    const handle = withFile ? files.handle("Tracks.json", ORIGINAL) : null;
    const s = new BoardSession(store, { name: "Tracks", handle, text: withFile ? ORIGINAL : null }, { db, locks, files, backups: dbBackups(async () => db) }, host, () => clock);
    await s.start();
    return { store, s, handle };
  }
  const tick = async (ms: number) => {
    clock += ms;
    await vi.advanceTimersByTimeAsync(ms);
    await vi.advanceTimersByTimeAsync(5); // and what that set off straight after (a 0 ms timer counts as 1)
  };

  it("autosaves a minute after a change, backing up the file as opened first", async () => {
    const { store, s, handle } = await open();
    store.updateCard("a", { title: "Mabel" });
    await tick(AUTOSAVE_MS - 1000);
    expect(files.writes).toBe(0);
    await tick(1000);
    expect(files.writes).toBe(1);
    expect(files.contents.get(handle!)).toContain("Mabel");
    expect(store.modified).toBe(false);
    expect(s.status).toMatch(/^Autosaved /);
    const backups = await listBackups(db, s.fileKey);
    expect(backups.map(([, b]) => b.text)).toEqual([ORIGINAL]);
  });

  it("waits while a dialog is open", async () => {
    const { store } = await open();
    store.updateCard("a", { title: "Mabel" });
    busy = true;
    await tick(AUTOSAVE_MS);
    expect(files.writes).toBe(0);
    busy = false;
    await tick(AUTOSAVE_BUSY_RETRY_MS);
    expect(files.writes).toBe(1);
  });

  it("never overwrites changes made elsewhere without asking; cancelling pauses autosave", async () => {
    const { store, s, handle } = await open();
    files.contents.set(handle!, '{"cards":[],"theirs":1}');
    store.updateCard("a", { title: "Mabel" });
    answers = ["cancel"];
    await tick(AUTOSAVE_MS);
    expect(files.contents.get(handle!)).toContain("theirs");
    expect(s.blocked).toBe(true);
    expect(await orphanDrafts(db, new MemoryLocks())).toEqual([]); // asking isn't failing: no draft
    expect(notices.at(-1)).toContain("Autosave paused");
    store.updateCard("a", { title: "Greta" });
    await tick(AUTOSAVE_MS * 2);
    expect(files.writes).toBe(0); // paused until a save decides
    answers = ["overwrite"];
    expect(await s.save()).toBe(true);
    expect(files.contents.get(handle!)).toContain("Greta");
    const kept = (await listBackups(db, s.fileKey)).map(([, b]) => b.text);
    expect(kept[0]).toContain("theirs"); // their version is backed up before overwriting
    expect(s.blocked).toBe(false);
  });

  it("autosave's question can overwrite or save elsewhere", async () => {
    const { store, handle } = await open();
    files.contents.set(handle!, '{"cards":[],"theirs":1}');
    store.updateCard("a", { title: "Mabel" });
    answers = ["save_as"];
    const other = files.handle("Copy.json");
    files.picks = [other];
    await tick(AUTOSAVE_MS);
    expect(files.contents.get(handle!)).toContain("theirs");
    expect(files.contents.get(other)).toContain("Mabel");
  });

  it("keeps a draft when the file can't be written, and tries again", async () => {
    const { store, s } = await open();
    files.denied = true;
    store.updateCard("a", { title: "Mabel" });
    await tick(AUTOSAVE_MS);
    expect(files.writes).toBe(0);
    expect(s.status).toContain("kept a draft");
    expect((await orphanDrafts(db, new MemoryLocks())).map((d) => d.text)).toEqual([expect.stringContaining("Mabel")]);
    files.denied = false;
    await tick(10_000);
    expect(files.writes).toBe(1);
    expect(await orphanDrafts(db, new MemoryLocks())).toEqual([]); // saved: the draft goes
  });

  it("an untitled board autosaves a draft only, and stays unsaved", async () => {
    const { store, s } = await open(false);
    store.updateCard("a", { title: "Mabel" });
    await tick(AUTOSAVE_MS);
    expect(store.modified).toBe(true);
    expect(s.status).toMatch(/^Draft kept /);
    expect(await orphanDrafts(db, locks)).toEqual([]); // locked: its tab is open
    await s.dispose(false); // the tab closes
    expect((await orphanDrafts(db, locks)).map((d) => d.name)).toEqual(["Tracks"]);
  });

  it("discarding the board drops its draft", async () => {
    const { store, s } = await open(false);
    store.updateCard("a", { title: "Mabel" });
    await s.keepDraft();
    await s.dispose(true);
    expect(await orphanDrafts(db, locks)).toEqual([]);
  });

  it("Save As downloads where the browser can't save in place, backing up the version opened", async () => {
    const { store, s } = await open(false);
    s.diskText = ORIGINAL;
    store.updateCard("a", { title: "Mabel" });
    files.picks = ["download"];
    expect(await s.save()).toBe(true);
    expect(files.downloads.map(([n]) => n)).toEqual(["Tracks.json"]);
    expect(store.modified).toBe(false);
    expect((await listBackups(db, "name:Tracks")).length).toBe(1);
  });

  it("Save As to another file follows that file from then on", async () => {
    const { store, s, handle } = await open();
    const other = files.handle("Other.json");
    files.picks = [other];
    store.updateCard("a", { title: "Mabel" });
    expect(await s.save(true)).toBe(true);
    expect(s.name).toBe("Other");
    expect(s.handle).toBe(other);
    expect(files.contents.get(handle!)).toBe(ORIGINAL);
    store.updateCard("a", { title: "Greta" });
    expect(await s.save()).toBe(true);
    expect(files.contents.get(other)).toContain("Greta");
  });

  it("marks saved what was written, not a change made while writing", async () => {
    const { store, s } = await open();
    store.updateCard("a", { title: "Mabel" });
    files.during = () => store.updateCard("a", { title: "Greta" }); // while the file is being written
    await s.save();
    expect(files.contents.get(s.handle!)).toContain("Mabel");
    expect(store.modified).toBe(true);
  });

  it("spots a file already open in another tab, and records recent files", async () => {
    const first = await open();
    const store = new BoardStore(boardFromDict(JSON.parse(ORIGINAL)), m);
    const again = new BoardSession(store, { name: "Tracks", handle: first.handle, text: ORIGINAL }, { db, locks, files, backups: dbBackups(async () => db) }, host, () => clock);
    await again.start(); // (an exclusive board lock would wait here forever)
    expect(first.s.openElsewhere).toBe(false);
    expect(again.openElsewhere).toBe(true);
    expect(again.fileKey).toBe(first.s.fileKey);
    expect((await recentFiles(db)).map((e) => e.name)).toEqual(["Tracks"]);
    expect(await fileKey(db, null, "Loose", clock)).toBe("name:Loose");
  });
});
