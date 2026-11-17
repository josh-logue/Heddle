// The platform seam (W9a): the app's platform-facing code runs on any Host. These run it
// on an in-memory, desktop-shaped host (tests/memoryHost.ts), the pattern for testing the
// desktop shell's host in W9b/W9c.
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CHANNELS } from "../src/platform/bridge.ts";
import { desktopHost } from "../src/platform/desktopHost.ts";
import { BoardStore } from "../src/board/store.ts";
import { fakeMeasurer } from "../src/board/text.ts";
import { laterDb } from "../src/platform/db.ts";
import { clearErrors, errorEntries, errorReport, logError } from "../src/platform/errorLog.ts";
import { FileGoneError, parseBoard, type FileRef } from "../src/platform/files.ts";
import { browserFiles } from "../src/platform/browser/files.ts";
import { BROWSER_KEYS, DESKTOP_KEYS, getHost, matchesKey, setHost, type Host } from "../src/platform/host.ts";
import { orphanDrafts, recentFiles } from "../src/platform/safety.ts";
import { getOption, readJson, readSetting, setOption, writeJson, writeSetting } from "../src/platform/settings.ts";
import { BoardSession, type SessionHost } from "../src/ui/session.ts";
import { MemoryHost, pathRef } from "./memoryHost.ts";
import { fakeBridge, type FakeBridge } from "./fakeBridge.ts";

const BOARD = '{"cards":[{"id":"a","title":"Rowan"}]}';
const T0 = Date.UTC(2026, 10, 16, 9, 0, 0);

describe("the app on a non-browser host", () => {
  let host: MemoryHost;
  beforeEach(() => {
    host = new MemoryHost();
    setHost(host);
  });

  it("keeps settings and remembered layout with the host (Node has no localStorage)", () => {
    expect(getHost()).toBe(host);
    expect(getOption("snap_to_grid")).toBe(false);
    setOption("snap_to_grid", true);
    writeSetting("theme", "dark");
    writeJson("panels", { open: ["filter"] });
    expect(host.settingsData.get("snap")).toBe("on");
    expect(readSetting("theme", "system", ["system", "light", "dark"])).toBe("dark");
    expect(readJson("panels", {})).toEqual({ open: ["filter"] });
    host.settingsData.set("panels", "{not json");
    expect(readJson("panels", { open: [] })).toEqual({ open: [] });
  });

  it("logs errors with the host, and reports them under the host's heading", () => {
    logError("Error: one", T0);
    expect(host.errorData).toEqual([{ at: T0, text: "Error: one" }]);
    expect(errorReport()).toMatch(/^Heddle \(test host\) error report\n\n===== 2026-11-16T09:00:00.000Z =====\nError: one/);
    clearErrors();
    expect(errorEntries()).toEqual([]);
  });

  // The same tests on the in-memory host and on the desktop host over a fake bridge.
  describe.each([
    ["the in-memory host", (mem: MemoryHost): Host => mem],
    ["the desktop host", (mem: MemoryHost): Host => desktopHost(fakeBridge(mem), mem, (p) => mem.onLeave(p))],
  ])("a board's saving, on %s", (_label, makeHost) => {
    const m = fakeMeasurer();
    let app: Host;
    let notices: string[];
    const page: SessionHost = {
      notice: (t) => notices.push(t), askConflict: async () => "cancel", busy: () => false, autosaveOn: () => true, changed: () => {},
    };
    let sessions: BoardSession[];
    beforeEach(() => {
      notices = [];
      sessions = [];
      app = makeHost(host);
      setHost(app);
    });
    afterEach(async () => {
      for (const s of sessions) await s.dispose(false);
    });

    /** What App does on File → Open: the host picks and reads, the app parses. */
    async function open(path: string, now = () => T0) {
      host.opens.push(path);
      const picked = (await app.files.pickBoard())!;
      const opened = parseBoard(picked.text, picked.fileName, picked.ref);
      const store = new BoardStore(opened.board, m);
      const s = new BoardSession(store, { name: opened.name, handle: opened.handle, text: opened.text ?? null },
        { db: laterDb(app.storage()), locks: app.locks, files: app.files, backups: app.backups }, page, now);
      sessions.push(s);
      await s.start();
      return { store, s };
    }

    it("opens, autosaves in place with a backup first, and remembers the file", async () => {
      host.disk.set("C:/Boards/Tracks.json", BOARD);
      const { store, s } = await open("C:/Boards/Tracks.json");
      expect(s.name).toBe("Tracks");
      store.updateCard("a", { title: "Mabel" });
      await s.autosave();
      expect(host.disk.get("C:/Boards/Tracks.json")).toContain("Mabel");
      expect(store.modified).toBe(false);
      expect(s.status).toMatch(/^Autosaved /);
      const backups = await s.backups();
      expect(backups.map(([, b]) => b.text)).toEqual([BOARD]);
      expect((await recentFiles(host.db)).map((e) => e.handle)).toEqual([pathRef("C:/Boards/Tracks.json")]);
    });

    it("follows the file through Save As, and knows it by path when opened again", async () => {
      host.disk.set("C:/Boards/Tracks.json", BOARD);
      const first = await open("C:/Boards/Tracks.json");
      host.saves.push("C:/Boards/Copy.json");
      expect(await first.s.save(true)).toBe(true);
      expect(first.s.name).toBe("Copy");
      expect(host.disk.get("C:/Boards/Copy.json")).toContain('"title": "Rowan"');
      expect(host.disk.get("C:/Boards/Tracks.json")).toBe(BOARD);
      expect(notices).toContain("Saved “Copy”.");
      // A different reference object to the same path is the same file (as when a desktop
      // window opens a board another window already has).
      const again = await open("C:/Boards/Copy.json");
      expect(again.s.fileKey).toBe(first.s.fileKey);
      expect(again.s.openElsewhere).toBe(true);
    });

    it("keeps a draft (plain data, so it survives storage) when the file can't be written", async () => {
      host.disk.set("C:/Boards/Tracks.json", BOARD);
      host.readOnly.add("C:/Boards/Tracks.json");
      const { store, s } = await open("C:/Boards/Tracks.json");
      store.updateCard("a", { title: "Greta" });
      await s.autosave();
      expect(host.disk.get("C:/Boards/Tracks.json")).toBe(BOARD);
      await s.dispose(false); // the window closed without saving
      const [draft] = await orphanDrafts(host.db, host.locks);
      expect(draft!.text).toContain("Greta");
      expect(structuredClone(draft)).toEqual(draft);
      expect(draft!.handle).toEqual(pathRef("C:/Boards/Tracks.json"));
    });

    it("Save checks for changes made elsewhere, and backs them up, even when reading needs asking first", async () => {
      // A browser handle whose permission lapsed reads as nothing unless asked: Save must
      // ask, not take "nothing" for "unchanged" and overwrite with no backup.
      host.disk.set("C:/Boards/Tracks.json", BOARD);
      const { store, s } = await open("C:/Boards/Tracks.json");
      const elsewhere = '{"cards":[{"id":"a","title":"Greta"}]}';
      host.disk.set("C:/Boards/Tracks.json", elsewhere);
      host.unreadable.add("C:/Boards/Tracks.json");
      store.updateCard("a", { title: "Mabel" });
      const asked: string[] = [];
      page.askConflict = async (name) => {
        asked.push(name);
        return "overwrite";
      };
      try {
        expect(await s.save()).toBe(true);
      } finally {
        page.askConflict = async () => "cancel";
      }
      expect(asked).toEqual(["Tracks"]);
      expect(host.disk.get("C:/Boards/Tracks.json")).toContain("Mabel");
      expect((await s.backups()).map(([, b]) => b.text)).toContain(elsewhere);
    });

    it("Open Recent says when a file has gone", async () => {
      await expect(app.files.reopen(pathRef("C:/Boards/Gone.json"))).rejects.toBeInstanceOf(FileGoneError);
    });

    it("the page tells the host about leaving with unsaved changes", async () => {
      host.disk.set("C:/Boards/Tracks.json", BOARD);
      const { store, s } = await open("C:/Boards/Tracks.json");
      // What App registers: the host decides when to ask and when to keep a draft.
      const stop = app.onLeave({ unsaved: () => store.modified, keepDraft: () => void s.keepDraft(), askToClose: async () => true });
      expect(host.leaving!.unsaved()).toBe(false);
      store.updateCard("a", { title: "Warden" });
      expect(host.leaving!.unsaved()).toBe(true);
      stop();
      expect(host.leaving).toBeNull();
    });
  });
});

describe("browser file handles", () => {
  /** A File System Access handle whose permission has lapsed ("prompt"). */
  function lapsed(granted: boolean) {
    const asked: string[] = [];
    const h = {
      name: "Tracks.json",
      getFile: async () => ({ text: async () => BOARD }),
      queryPermission: async () => "prompt",
      requestPermission: async ({ mode }: { mode: string }) => {
        asked.push(mode);
        return granted ? "granted" : "denied";
      },
    };
    return { h: h as unknown as FileRef, asked };
  }

  it("reads quietly as nothing, or asks once for read and write when told to (Save)", async () => {
    const quiet = lapsed(true);
    expect(await browserFiles.read(quiet.h)).toBeNull();
    expect(quiet.asked).toEqual([]);
    const save = lapsed(true);
    expect(await browserFiles.read(save.h, true)).toBe(BOARD);
    expect(save.asked).toEqual(["readwrite"]);
    const refused = lapsed(false);
    expect(await browserFiles.read(refused.h, true)).toBeNull();
  });
});

describe("key profiles", () => {
  const press = (code: string, key: string, mods: { ctrl?: boolean; shift?: boolean; alt?: boolean } = {}) =>
    ({ code, key, ctrlKey: !!mods.ctrl, metaKey: false, shiftKey: !!mods.shift, altKey: !!mods.alt });

  it("a browser adds cards with N and shows threads with T; the desktop keeps Ctrl+Shift+N and Ctrl+T", () => {
    expect(matchesKey(BROWSER_KEYS.addCard, press("KeyN", "n"))).toBe(true);
    expect(matchesKey(BROWSER_KEYS.addCard, press("KeyN", "N", { shift: true }))).toBe(false);
    expect(matchesKey(BROWSER_KEYS.thread, press("KeyT", "t"))).toBe(true);
    expect(matchesKey(BROWSER_KEYS.thread, press("KeyT", "t", { ctrl: true }))).toBe(false);
    expect(matchesKey(DESKTOP_KEYS.addCard, press("KeyN", "N", { ctrl: true, shift: true }))).toBe(true);
    expect(matchesKey(DESKTOP_KEYS.addCard, press("KeyN", "n"))).toBe(false);
    expect(matchesKey(DESKTOP_KEYS.thread, press("KeyT", "t", { ctrl: true }))).toBe(true);
    expect([BROWSER_KEYS.addCard.label, DESKTOP_KEYS.addCard.label]).toEqual(["N", "Ctrl+Shift+N"]);
  });

  it("Fit is Ctrl+1 by character in both (any layout that types 1 there)", () => {
    for (const keys of [BROWSER_KEYS, DESKTOP_KEYS]) {
      expect(matchesKey(keys.fit, press("Digit1", "1", { ctrl: true }))).toBe(true);
      expect(matchesKey(keys.fit, press("Digit1", "1"))).toBe(false);
    }
  });
});

/** A Windows path (written with / here: backslashes get lost on the way into files). */
const win = (p: string) => p.replace(/\//g, String.fromCharCode(92));

describe("the desktop host", () => {
  let mem: MemoryHost;
  let bridge: FakeBridge;
  let host: Host;
  beforeEach(() => {
    mem = new MemoryHost();
    bridge = fakeBridge(mem);
    host = desktopHost(bridge, mem, (p) => mem.onLeave(p));
    setHost(host);
  });

  it("reports what's running, logs errors to error.log too, and has no service worker", () => {
    expect(host.errors.about()).toEqual(["Heddle 1.2.3 (desktop) error report", "Electron 45.3.3 (Chromium 156.0)", "System: Windows_NT 10.0"]);
    logError("Error: one", T0);
    expect(bridge.logged).toEqual(["Error: one"]);
    expect(errorEntries()).toEqual([{ at: T0, text: "Error: one" }]); // (for Settings' report)
    expect(() => host.installOffline()).not.toThrow();
  });

  it("is the desktop, with the desktop's keys", () => {
    expect(host.kind).toBe("desktop");
    expect(host.keys).toBe(DESKTOP_KEYS);
  });

  it("opens a board here only if this window is blank; one open elsewhere comes forward", async () => {
    mem.disk.set("C:/Boards/Tracks.json", BOARD);
    mem.disk.set("C:/Boards/Garden.json", BOARD);
    bridge.elsewhere.add("C:/Boards/Garden.json");
    const w = host.windows!;
    expect(await w.route(pathRef("C:/Boards/Tracks.json"), true)).toBe("here");
    expect(await w.route(pathRef("C:/Boards/Tracks.json"), false)).toBe("elsewhere");
    expect(await w.route(pathRef("C:/Boards/Garden.json"), true)).toBe("elsewhere");
    expect(await w.route(null, false)).toBe("elsewhere"); // (File → New: a new window)
    await expect(w.route(pathRef("C:/Boards/Gone.json"), true)).rejects.toBeInstanceOf(FileGoneError);
    w.report(pathRef("C:/Boards/Tracks.json"), false);
    expect(bridge.reported).toEqual([["C:/Boards/Tracks.json", false]]);
  });

  it("shows the board it was opened for, and boards handed over later", async () => {
    mem.disk.set("C:/Boards/Tracks.json", BOARD);
    mem.disk.set("C:/Boards/Garden.json", BOARD);
    const shown: string[] = [];
    const opened = desktopHost({ ...bridge, open: { path: "C:/Boards/Tracks.json", name: "Tracks.json", text: BOARD } }, mem, (p) => mem.onLeave(p));
    const stop = opened.windows!.onOpen((f) => shown.push(f ? `${f.fileName} ${(f.ref as { path?: string }).path}` : "new"));
    expect(shown).toEqual(["Tracks.json C:/Boards/Tracks.json"]); // straight away
    bridge.handOver("C:/Boards/Garden.json");
    await expect.poll(() => shown.length).toBe(2);
    expect(shown[1]).toBe("Garden.json C:/Boards/Garden.json");
    stop();
    const blank: string[] = [];
    desktopHost({ ...bridge, newBoard: true }, mem, (p) => mem.onLeave(p)).windows!.onOpen((f) => blank.push(f ? "file" : "new"));
    expect(blank).toEqual(["new"]); // (File → New from another window)
  });

  it("asks the page before its window closes", async () => {
    expect(await bridge.requestClose()).toBe(true); // (nothing to ask yet)
    let answer = false;
    const asked: number[] = [];
    const stop = host.onLeave({ unsaved: () => true, keepDraft: () => {}, askToClose: async () => {
      asked.push(1);
      return answer;
    } });
    expect(await bridge.requestClose()).toBe(false);
    answer = true;
    expect(await bridge.requestClose()).toBe(true);
    expect(asked).toHaveLength(2);
    stop();
  });

  it("knows a file by its path whatever the case or slashes, and saves dropped boards back", async () => {
    expect(await host.files.same(pathRef("C:/Boards/Tracks.json"), pathRef(win("c:/boards/TRACKS.json")))).toBe(true);
    expect(await host.files.same(pathRef("C:/Boards/Tracks.json"), pathRef("C:/Boards/Other.json"))).toBe(false);
    const dropped = Object.assign(new File(["{}"], "Tracks.json"), { path: "C:/Boards/Tracks.json" });
    expect(host.files.refFor(dropped)).toEqual(pathRef("C:/Boards/Tracks.json"));
    expect(host.files.refFor(Object.assign(new File([""], "notes.txt"), { path: "C:/notes.txt" }))).toBeNull();
    expect(host.files.canSaveInPlace()).toBe(true);
    expect(await host.files.pickSave("Tracks")).toBeNull(); // (cancelled)
  });

  it("saves a PDF through the shell's Save dialog, or says it was cancelled", async () => {
    mem.saves.push("C:/Boards/Tracks.pdf");
    expect(await host.pdf("<svg/>", "Tracks")).toBe("saved");
    expect(mem.pdfs).toEqual(["<svg/>"]);
    expect(await host.pdf("<svg/>", "Tracks")).toBe("cancelled");
  });

  it("says why a save failed", async () => {
    mem.readOnly.add("C:/Boards/Tracks.json");
    await expect(host.files.write(pathRef("C:/Boards/Tracks.json"), "{}", true)).rejects.toThrow(/Couldn't save “Tracks.json”: EPERM/);
  });

  it("shows strand pictures from the board's folder", async () => {
    expect(await host.picture("pictures/rowan.png", pathRef("C:/Boards/Tracks.json"))).toMatch(/^data:image\/png/);
    expect(await host.picture("pictures/rowan.png", null)).toBeNull();
  });

  it("copies the Python app's settings and recent boards in once, without overriding", async () => {
    mem.settingsData.set("theme", "system");
    const seeded = desktopHost(fakeBridge(mem, {
      values: { snap_to_grid: "true", wheel_zooms: "false", dark_mode: "true", autosave: "false", show_menu_bar: "true" },
      recent: [win("C:/Boards/Tracks.json"), win("C:/Boards/Garden.json")],
    }), mem);
    expect(Object.fromEntries(mem.settingsData)).toEqual({ theme: "system", snap: "on", wheelZooms: "off", autosave: "off" });
    const recent = await recentFiles(await seeded.storage());
    expect(recent.map((e) => [e.name, (e.handle as { path?: string }).path])).toEqual(
      [["Tracks", win("C:/Boards/Tracks.json")], ["Garden", win("C:/Boards/Garden.json")]]);
  });

  it("the preload asks on the channels the main process answers", () => {
    const preload = readFileSync(new URL("../desktop/preload.cjs", import.meta.url), "utf-8");
    for (const channel of Object.values(CHANNELS)) expect(preload).toContain(`"${channel}"`);
    const main = ["ipc.ts", "windows.ts"].map((f) => readFileSync(new URL(`../desktop/${f}`, import.meta.url), "utf-8")).join("");
    for (const key of Object.keys(CHANNELS)) expect(main).toContain(`CHANNELS.${key}`);
  });
});
