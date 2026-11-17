// Board files in a browser (part of browserHost).
//
// Chrome and Edge have the File System Access API: a board opened or saved through it can
// be saved again in place. Other browsers can only read a picked file and download a
// fresh copy on every save.

import { FileGoneError, NoPermissionError, jsonName, type FileRef } from "../files.ts";
import type { HostFiles, PickedFile } from "../host.ts";

/** The parts of the File System Access API used here (not in every TypeScript lib). */
export interface FileHandle extends FileRef {
  name: string;
  getFile(): Promise<File>;
  createWritable(): Promise<{ write(data: string | Blob): Promise<void>; close(): Promise<void> }>;
  queryPermission?(opts: { mode: "read" | "readwrite" }): Promise<PermissionState>;
  requestPermission?(opts: { mode: "read" | "readwrite" }): Promise<PermissionState>;
  isSameEntry?(other: FileHandle): Promise<boolean>;
}

type PickerOptions = { types: { description: string; accept: Record<string, string[]> }[]; suggestedName?: string };
type FsWindow = Window & {
  showOpenFilePicker?: (o: PickerOptions) => Promise<FileHandle[]>;
  showSaveFilePicker?: (o: PickerOptions) => Promise<FileHandle>;
};
const fsWindow = () => window as FsWindow;
const TYPES = [{ description: "Heddle board", accept: { "application/json": [".json"] } }];

const aborted = (e: unknown) => e instanceof DOMException && e.name === "AbortError";
const handle = (ref: FileRef) => ref as FileHandle;

/** Can this browser save a board back to the file it came from? */
const canSaveInPlace = () => typeof fsWindow().showSaveFilePicker === "function";

/** Ask for a board file. Resolves null if the picker is closed without one. */
async function pickBoard(): Promise<PickedFile | null> {
  const w = fsWindow();
  if (w.showOpenFilePicker) {
    try {
      const [h] = await w.showOpenFilePicker({ types: TYPES });
      if (!h) return null;
      const file = await h.getFile();
      return { ref: h, fileName: file.name, text: await file.text() };
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
  return file ? { ref: null, fileName: file.name, text: await file.text() } : null;
}

/** May this page use the file (asking, if `ask`, which needs a user's click)? */
async function permitted(h: FileHandle, mode: "read" | "readwrite", ask: boolean): Promise<boolean> {
  if (!h.queryPermission) return true;
  if ((await h.queryPermission({ mode })) === "granted") return true;
  return ask && !!h.requestPermission && (await h.requestPermission({ mode })) === "granted";
}

async function reopen(ref: FileRef): Promise<string | null> {
  try {
    if (!(await permitted(handle(ref), "read", true))) return null;
    return await (await handle(ref).getFile()).text();
  } catch (e) {
    if (e instanceof DOMException && e.name === "NotFoundError") throw new FileGoneError(ref.name);
    throw e;
  }
}

/** A file's text as it is now, or null if it can't be read (gone, not allowed). */
async function read(ref: FileRef): Promise<string | null> {
  try {
    if (!(await permitted(handle(ref), "read", false))) return null;
    return await (await handle(ref).getFile()).text();
  } catch {
    return null;
  }
}

/** Write a board file in place. Without permission, `ask` asks for it; else this throws
 *  NoPermissionError. */
async function write(ref: FileRef, text: string, ask: boolean): Promise<void> {
  const h = handle(ref);
  if (!(await permitted(h, "readwrite", ask))) {
    throw new NoPermissionError(`Heddle wasn't allowed to save to “${h.name}”. Use Save As to choose a file.`);
  }
  const out = await h.createWritable();
  await out.write(text);
  await out.close();
}

/** Save As's file choice: a handle, null if cancelled, or "download" where the browser
 *  can't save in place. */
async function pickSave(suggestedName: string): Promise<FileRef | null | "download"> {
  const w = fsWindow();
  if (!w.showSaveFilePicker) return "download";
  try {
    return await w.showSaveFilePicker({ types: TYPES, suggestedName: jsonName(suggestedName) });
  } catch (e) {
    if (aborted(e)) return null;
    throw e;
  }
}

function download(data: string | Blob, fileName: string, type = "application/json"): void {
  const url = URL.createObjectURL(typeof data === "string" ? new Blob([data], { type }) : data);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Two handles to the same file (Chrome and Edge's isSameEntry)? */
async function same(a: FileRef, b: FileRef): Promise<boolean> {
  if (a === b) return true;
  try {
    return (await handle(a).isSameEntry?.(handle(b))) ?? false;
  } catch {
    return false;
  }
}

/** An exported file (Markdown, PNG, SVG): where the browser has a save dialog, the user
 *  picks the place (true if saved, false if cancelled); elsewhere it's downloaded. */
async function saveExport(data: string | Blob, fileName: string, type: string, description: string): Promise<boolean | "downloaded"> {
  const w = fsWindow();
  const ext = fileName.slice(fileName.lastIndexOf("."));
  if (!w.showSaveFilePicker) {
    download(data, fileName, type);
    return "downloaded";
  }
  let h: FileHandle;
  try {
    h = await w.showSaveFilePicker({ types: [{ description, accept: { [type]: [ext] } }], suggestedName: fileName });
  } catch (e) {
    if (aborted(e)) return false;
    throw e;
  }
  const out = await h.createWritable();
  await out.write(data);
  await out.close();
  return true;
}

export const browserFiles: HostFiles = {
  canSaveInPlace, pickBoard, reopen, read, write, pickSave, same, saveExport,
  download: (text, fileName) => download(text, fileName),
  refFor: () => null, // (a dropped file can be read, not saved back to)
};
