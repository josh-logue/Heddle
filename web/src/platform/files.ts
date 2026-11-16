// Opening and saving board files in a browser.
//
// Chrome and Edge have the File System Access API: a board opened or saved through it can
// be saved again in place. Other browsers can only read a picked file and download a
// fresh copy on every save. W9's desktop shell will supply its own version of this file.

import { NotABoardError, boardFromJson, type BoardData } from "../core/model.ts";

export interface OpenedBoard {
  board: BoardData;
  /** The file name without ".json", for the title bar. */
  name: string;
  /** Where to save it back, when the browser allows that. */
  handle: FileHandle | null;
}

/** The parts of the File System Access API used here (not in every TypeScript lib). */
export interface FileHandle {
  name: string;
  getFile(): Promise<File>;
  createWritable(): Promise<{ write(data: string): Promise<void>; close(): Promise<void> }>;
  queryPermission?(opts: { mode: "readwrite" }): Promise<PermissionState>;
  requestPermission?(opts: { mode: "readwrite" }): Promise<PermissionState>;
}

type PickerOptions = { types: { description: string; accept: Record<string, string[]> }[]; suggestedName?: string };
type FsWindow = Window & {
  showOpenFilePicker?: (o: PickerOptions) => Promise<FileHandle[]>;
  showSaveFilePicker?: (o: PickerOptions) => Promise<FileHandle>;
};
const fsWindow = () => window as FsWindow;
const TYPES = [{ description: "Heddle board", accept: { "application/json": [".json"] } }];

/** Can this browser save a board back to the file it came from? */
export const canSaveInPlace = () => typeof fsWindow().showSaveFilePicker === "function";

export class BoardFileError extends Error {}

const baseName = (fileName: string) => fileName.replace(/\.json$/i, "");

/** A board from file text, with a friendly message for anything that isn't one. */
export function parseBoard(text: string, fileName: string, handle: FileHandle | null = null): OpenedBoard {
  try {
    return { board: boardFromJson(text), name: baseName(fileName), handle };
  } catch (e) {
    if (e instanceof SyntaxError) {
      throw new BoardFileError(`“${fileName}” isn't a Heddle board: it isn't a readable JSON file.`);
    }
    if (e instanceof NotABoardError) {
      throw new BoardFileError(`“${fileName}” isn't a Heddle board: it has no cards list.`);
    }
    throw e;
  }
}

export async function readBoardFile(file: File, handle: FileHandle | null = null): Promise<OpenedBoard> {
  return parseBoard(await file.text(), file.name, handle);
}

const aborted = (e: unknown) => e instanceof DOMException && e.name === "AbortError";

/** Ask for a board file. Resolves null if the picker is closed without one. */
export async function pickBoard(): Promise<OpenedBoard | null> {
  const w = fsWindow();
  if (w.showOpenFilePicker) {
    try {
      const [handle] = await w.showOpenFilePicker({ types: TYPES });
      return handle ? readBoardFile(await handle.getFile(), handle) : null;
    } catch (e) {
      if (aborted(e)) return null;
      throw e;
    }
  }
  const file = await new Promise<File | null>((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.addEventListener("change", () => resolve(input.files?.[0] ?? null), { once: true });
    input.addEventListener("cancel", () => resolve(null), { once: true });
    input.click();
  });
  return file ? readBoardFile(file) : null;
}

/** The result of saving: where it went, or null if the save was cancelled. */
export interface Saved {
  name: string;
  handle: FileHandle | null;
  /** True when the file was downloaded rather than written in place. */
  downloaded: boolean;
}

/** Save to `handle` (asking for permission to write if needed). */
export async function saveToHandle(handle: FileHandle, text: string): Promise<Saved> {
  if (handle.queryPermission && (await handle.queryPermission({ mode: "readwrite" })) !== "granted") {
    if (handle.requestPermission && (await handle.requestPermission({ mode: "readwrite" })) !== "granted") {
      throw new BoardFileError(`Heddle wasn't allowed to save to “${handle.name}”. Use Save As to choose a file.`);
    }
  }
  const out = await handle.createWritable();
  await out.write(text);
  await out.close();
  return { name: baseName(handle.name), handle, downloaded: false };
}

/** Save As: choose a file where the browser allows it, otherwise download a copy. */
export async function saveAs(text: string, suggestedName: string): Promise<Saved | null> {
  const w = fsWindow();
  const fileName = suggestedName.toLowerCase().endsWith(".json") ? suggestedName : `${suggestedName}.json`;
  if (w.showSaveFilePicker) {
    try {
      const handle = await w.showSaveFilePicker({ types: TYPES, suggestedName: fileName });
      return await saveToHandle(handle, text);
    } catch (e) {
      if (aborted(e)) return null;
      throw e;
    }
  }
  download(text, fileName);
  return { name: baseName(fileName), handle: null, downloaded: true };
}

export function download(text: string, fileName: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
