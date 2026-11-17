// The desktop shell's files (desktop/files.ts), on a real temporary folder: backups in the
// Python app's layout (heddle/backups.py), error.log in its format, safe writes, the
// registry read, and strand pictures.
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  BACKUP_INTERVAL_MS, KEEP_BACKUPS, MAX_LOG_BYTES, appendLog, backupDirFor, listBackups, makeBackup, parseRegQuery,
  picturePath, pictureUrl, stamp, writeAtomic,
} from "../desktop/files.ts";

const BS = String.fromCharCode(92); // (backslashes get lost on the way into this file)
const win = (p: string) => p.replace(/\//g, BS);
const T0 = new Date(2026, 10, 16, 9, 0, 0).getTime(); // local time, as backup names are

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(os.tmpdir(), "heddle-files-"));
});
afterEach(() => rmSync(dir, { recursive: true, force: true }));

describe.runIf(process.platform === "win32")("backup folders", () => {
  it("are named as the Python app names them (stem, then 8 of sha1 of the casefolded full path)", () => {
    // Expected values from heddle.backups.backup_dir_for on this machine.
    const name = (board: string) => path.basename(backupDirFor(win(board), "C:/root"));
    expect(name("C:/Boards/Rowan.json")).toBe("Rowan-a9efdd0b");
    expect(name("C:/Boards/Straße & Co.json")).toBe("Straße _ Co-ad5a1b1d");
    expect(name("D:/Ünïcode/Ma bel.json")).toBe("Ma bel-29060a2f");
  });
});

describe("backups", () => {
  const board = () => path.join(dir, "Tracks.json");

  it("keeps the first, then at most one every 5 minutes unless forced, and skips repeats", async () => {
    const root = path.join(dir, "backups");
    expect(await makeBackup(board(), root, '{"cards":[1]}', T0)).not.toBeNull();
    expect(await makeBackup(board(), root, '{"cards":[2]}', T0 + 60_000)).toBeNull();
    expect(await makeBackup(board(), root, '{"cards":[1]}', T0 + 60_000, true)).toBeNull(); // the same as the newest
    expect(await makeBackup(board(), root, '{"cards":[3]}', T0 + 60_000, true)).not.toBeNull();
    expect(await makeBackup(board(), root, '{"cards":[4]}', T0 + 60_000, true)).not.toBeNull(); // same second: numbered
    expect(await makeBackup(board(), root, '{"cards":[5]}', T0 + BACKUP_INTERVAL_MS + 60_000)).not.toBeNull();
    expect(await makeBackup(board(), root, "  ", T0 + 2 * BACKUP_INTERVAL_MS, true)).toBeNull();
    const list = await listBackups(board(), root);
    expect(list.map((b) => path.basename(b.path))).toEqual([
      `Tracks ${stamp(T0 + BACKUP_INTERVAL_MS + 60_000)}.json`,
      "Tracks 2026-11-16 09-01-00 (1).json",
      "Tracks 2026-11-16 09-01-00.json",
      "Tracks 2026-11-16 09-00-00.json",
    ]);
    expect(readFileSync(list[1]!.path, "utf-8")).toBe('{"cards":[4]}');
    expect(list.map((b) => b.seq)).toEqual([0, 1, 0, 0]);
  });

  it("keeps the newest 20, and reads the Python app's backups (ignoring other files)", async () => {
    const root = path.join(dir, "backups");
    const folder = backupDirFor(board(), root);
    mkdirSync(folder, { recursive: true });
    writeFileSync(path.join(folder, "Tracks 2026-11-15 08-00-00.json"), "python");
    writeFileSync(path.join(folder, "Tracks 2026-11-15 08-00-00 (2).json"), "python 2");
    writeFileSync(path.join(folder, "Other 2026-11-15 08-00-00.json"), "not this board");
    writeFileSync(path.join(folder, "Tracks notes.json"), "no time");
    const list = await listBackups(board(), root);
    expect(list.map((b) => [path.basename(b.path), b.seq])).toEqual([
      ["Tracks 2026-11-15 08-00-00 (2).json", 2], ["Tracks 2026-11-15 08-00-00.json", 0]]);
    expect(list[0]!.at).toBe(new Date(2026, 10, 15, 8, 0, 0).getTime());
    for (let i = 0; i < KEEP_BACKUPS + 3; i++) await makeBackup(board(), root, `{"n":${i}}`, T0 + i * 1000, true);
    const kept = await listBackups(board(), root);
    expect(kept).toHaveLength(KEEP_BACKUPS);
    expect(readFileSync(kept[0]!.path, "utf-8")).toBe(`{"n":${KEEP_BACKUPS + 2}}`);
    expect(readdirSync(folder)).toContain("Other 2026-11-15 08-00-00.json"); // (only this board's go)
  });
});

describe("files and the log", () => {
  it("writes a file whole, leaving no temporary file", async () => {
    const file = path.join(dir, "Board.json");
    writeFileSync(file, "old");
    await writeAtomic(file, "new");
    expect(readFileSync(file, "utf-8")).toBe("new");
    expect(readdirSync(dir)).toEqual(["Board.json"]);
  });

  it("appends to error.log in the Python app's format, starting afresh past 1 MB", async () => {
    await appendLog(dir, "Error: one\n", T0);
    await appendLog(dir, "Error: two", T0 + 1000);
    expect(readFileSync(path.join(dir, "error.log"), "utf-8")).toBe(
      "===== 2026-11-16 09:00:00 =====\nError: one\n\n===== 2026-11-16 09:00:01 =====\nError: two\n\n");
    writeFileSync(path.join(dir, "error.log"), "x".repeat(MAX_LOG_BYTES + 1));
    await appendLog(dir, "Error: three", T0);
    expect(readFileSync(path.join(dir, "error.log"), "utf-8")).toContain("Error: three");
    expect(readFileSync(path.join(dir, "error.log.old"), "utf-8")).toHaveLength(MAX_LOG_BYTES + 1);
  });

  it("reads the Python app's settings as reg query prints them", () => {
    const multi = [win("C:/Boards/Tracks.json"), win("C:/Boards/A b.json")].join(`${BS}0`);
    const out = [
      "", "HKEY_CURRENT_USER" + BS + "Software" + BS + "Heddle" + BS + "Heddle",
      "    autosave    REG_SZ    true",
      `    recent_files    REG_MULTI_SZ    ${multi}`,
      "    snap_to_grid    REG_SZ    false",
      "", "HKEY_CURRENT_USER" + BS + "Software" + BS + "Heddle" + BS + "Heddle" + BS + "window", "",
    ].join("\r\n");
    expect(parseRegQuery(out)).toEqual({
      values: { autosave: "true", snap_to_grid: "false" },
      recent: [win("C:/Boards/Tracks.json"), win("C:/Boards/A b.json")],
    });
  });
});

describe("strand pictures", () => {
  it("are found from the board's folder when relative (as model.picture_from_file)", () => {
    const board = path.join(dir, "Tracks.json");
    expect(picturePath("pictures/rowan.png", board)).toBe(path.join(dir, "pictures", "rowan.png"));
    expect(picturePath(path.join(dir, "x.png"), null)).toBe(path.join(dir, "x.png"));
    expect(picturePath("pictures/rowan.png", null)).toBeNull();
    expect(picturePath("", board)).toBeNull();
  });

  it("are read as data URLs: images only", async () => {
    writeFileSync(path.join(dir, "rowan.png"), Buffer.from([137, 80, 78, 71]));
    writeFileSync(path.join(dir, "notes.txt"), "text");
    expect(await pictureUrl(path.join(dir, "rowan.png"))).toBe("data:image/png;base64,iVBORw==");
    expect(await pictureUrl(path.join(dir, "notes.txt"))).toBeNull();
    expect(await pictureUrl(path.join(dir, "gone.png"))).toBeNull();
  });
});
