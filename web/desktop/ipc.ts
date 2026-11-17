// The desktop shell's IPC: what the page's bridge (src/platform/bridge.ts) can ask of the
// main process. Every handler checks the message comes from the app's own page. Board
// files are .json only; pictures only images; anything else is written only where the
// user chose in a dialog.

import { BrowserWindow, dialog, ipcMain, type IpcMainEvent, type IpcMainInvokeEvent } from "electron";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { CHANNELS, type Answer, type DesktopBackup, type DesktopInfo, type DesktopSeed } from "../src/platform/bridge.ts";
import { appendLog, dataDir, listBackups, makeBackup, pictureUrl, picturePath, readText, writeAtomic } from "./files.ts";
import { pdfHtml, pdfPage, type PdfPage } from "./pdf.ts";
import type { Windows } from "./windows.ts";

const BOARD_FILTERS = [{ name: "Heddle board", extensions: ["json"] }];
const isBoard = (file: string) => path.isAbsolute(file) && file.toLowerCase().endsWith(".json");

const backupRoot = () => dataDir("backups", process.env.HEDDLE_BACKUP_DIR);
const logDir = () => dataDir("logs", process.env.HEDDLE_LOG_DIR);

async function answer<T>(fn: () => Promise<T>): Promise<Answer<T>> {
  try {
    return { ok: true, value: await fn() };
  } catch (e) {
    const err = e as NodeJS.ErrnoException;
    return { ok: false, error: err?.message ?? String(e), code: err?.code };
  }
}

/** The drawing printed by Chromium as one page, in a hidden window with no scripts. */
async function printPdf(svg: string, title: string, page: PdfPage): Promise<Buffer> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "heddle-pdf-"));
  const html = path.join(dir, "board.html");
  await fs.writeFile(html, pdfHtml(svg, title, page), "utf-8");
  const win = new BrowserWindow({
    show: false,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, javascript: false },
  });
  try {
    await win.loadFile(html);
    return await win.webContents.printToPDF({
      pageSize: { width: page.width, height: page.height },
      margins: { top: 0, bottom: 0, left: 0, right: 0 },
      printBackground: true,
      pageRanges: "1",
    });
  } finally {
    win.destroy();
    await fs.rm(dir, { recursive: true, force: true });
  }
}

function notBoard(file: string): never {
  throw Object.assign(new Error(`Not a board file: ${file}`), { code: "not_board" });
}

export interface IpcSetup {
  /** Is this message from the app's own page? */
  trusted(e: IpcMainEvent | IpcMainInvokeEvent): boolean;
  info(): DesktopInfo;
  /** The Python app's settings: handed over once, then null. */
  takeSeed(): DesktopSeed | null;
  windows: Windows;
}

export function registerIpc(setup: IpcSetup): void {
  const { trusted, windows } = setup;
  /** An async handler, for trusted senders only. */
  const handle = <A extends unknown[], T>(channel: string, fn: (win: BrowserWindow | null, ...args: A) => Promise<Answer<T> | T>) => {
    ipcMain.handle(channel, async (e, ...args) => {
      if (!trusted(e)) throw new Error("Not allowed");
      return fn(BrowserWindow.fromWebContents(e.sender), ...(args as A));
    });
  };

  ipcMain.on(CHANNELS.start, (e) => {
    e.returnValue = trusted(e) ? { info: setup.info(), seed: setup.takeSeed(), ...windows.started(e.sender) } : null;
  });

  ipcMain.on(CHANNELS.report, (e, file: unknown, blank: unknown) => {
    if (trusted(e)) windows.report(e.sender, { path: typeof file === "string" && isBoard(file) ? file : null, blank: !!blank });
  });
  ipcMain.on(CHANNELS.asksBeforeClosing, (e) => {
    if (trusted(e)) windows.asksBeforeClosing(e.sender);
  });
  ipcMain.on(CHANNELS.closeNow, (e) => {
    if (trusted(e)) windows.closeNow(e.sender);
  });
  ipcMain.handle(CHANNELS.route, async (e, file: string | null, blank: boolean) => {
    if (!trusted(e)) throw new Error("Not allowed");
    return answer(async () => {
      if (file !== null && !isBoard(file)) notBoard(file);
      return windows.route(e.sender, file, !!blank);
    });
  });
  ipcMain.handle(CHANNELS.takeOpen, (e) => (trusted(e) ? windows.takeOpen(e.sender) : null));

  handle(CHANNELS.openDialog, (win) => answer(async () => {
    const options = { title: "Open board", filters: BOARD_FILTERS, properties: ["openFile" as const] };
    const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
    const file = picked.canceled ? undefined : picked.filePaths[0];
    if (!file) return null;
    return { path: file, name: path.basename(file), text: await fs.readFile(file, "utf-8") };
  }));

  ipcMain.handle(CHANNELS.saveDialog, async (e, suggested: string, folder: string | null) => {
    if (!trusted(e)) throw new Error("Not allowed");
    const win = BrowserWindow.fromWebContents(e.sender);
    return answer(async () => {
      const name = suggested.toLowerCase().endsWith(".json") ? suggested : `${suggested}.json`;
      const options = { title: "Save board as", filters: BOARD_FILTERS, defaultPath: folder ? path.join(folder, name) : name };
      const picked = win ? await dialog.showSaveDialog(win, options) : await dialog.showSaveDialog(options);
      if (picked.canceled || !picked.filePath) return null;
      const file = isBoard(picked.filePath) ? picked.filePath : `${picked.filePath}.json`;
      // Two windows owning one file would overwrite each other's work (as the Python app).
      if (windows.holding(file, e.sender)) {
        throw Object.assign(new Error(`“${path.basename(file)}” is open in another window, so this board can't be saved over it. `
          + "Save under a different name, or close that window first."), { code: "open_elsewhere" });
      }
      return file;
    });
  });

  handle(CHANNELS.read, (_win, file: string) => answer(async () => {
    if (!isBoard(file)) notBoard(file);
    const text = await readText(file);
    if (text === null) throw Object.assign(new Error(`“${path.basename(file)}” can't be found`), { code: "gone" });
    return text;
  }));

  handle(CHANNELS.write, (_win, file: string, text: string) => answer(async () => {
    if (!isBoard(file)) notBoard(file);
    await writeAtomic(file, text);
    return null;
  }));

  handle(CHANNELS.saveExport, (win, data: string | Uint8Array, fileName: string, description: string, extension: string) => answer(async () => {
    const ext = extension.replace(/^\./, "");
    const options = { title: "Export", defaultPath: fileName, filters: [{ name: description, extensions: [ext] }] };
    const picked = win ? await dialog.showSaveDialog(win, options) : await dialog.showSaveDialog(options);
    if (picked.canceled || !picked.filePath) return false;
    await writeAtomic(picked.filePath, typeof data === "string" ? data : Buffer.from(data));
    return true;
  }));

  handle(CHANNELS.pdf, (win, svg: string, title: string) => answer(async () => {
    const page = pdfPage(svg);
    if (!page) throw new Error("There's no drawing to export.");
    const options = { title: "Export as PDF", defaultPath: `${title}.pdf`, filters: [{ name: "PDF document", extensions: ["pdf"] }] };
    const picked = win ? await dialog.showSaveDialog(win, options) : await dialog.showSaveDialog(options);
    if (picked.canceled || !picked.filePath) return false;
    const file = picked.filePath.toLowerCase().endsWith(".pdf") ? picked.filePath : `${picked.filePath}.pdf`;
    await writeAtomic(file, await printPdf(svg, title, page));
    return true;
  }));

  handle(CHANNELS.backups, (_win, board: string) => answer(async () => {
    if (!isBoard(board)) notBoard(board);
    const out: DesktopBackup[] = [];
    for (const b of await listBackups(board, backupRoot())) {
      const text = await readText(b.path);
      if (text !== null) out.push({ ...b, text });
    }
    return out;
  }));

  handle(CHANNELS.backup, (_win, board: string, text: string, now: number, force: boolean) => answer(async () => {
    if (!isBoard(board)) notBoard(board);
    await makeBackup(board, backupRoot(), text, now, force);
    return null;
  }));

  ipcMain.on(CHANNELS.log, (e, text: unknown) => {
    if (trusted(e)) void appendLog(logDir(), String(text)).catch(() => undefined);
  });

  handle(CHANNELS.picture, async (_win, picture: string, board: string | null) => {
    const file = picturePath(picture, board && isBoard(board) ? board : null);
    return file ? pictureUrl(file) : null;
  });
}
