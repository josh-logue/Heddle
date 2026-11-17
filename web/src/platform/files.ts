// Board files, wherever they come from: reading a board from its text, the errors that
// opening and saving can raise, and file names. The host (host.ts) does the picking,
// reading and writing.

import { NotABoardError, boardFromJson, type BoardData } from "../core/model.ts";
import type { FileRef } from "./host.ts";

export type { FileRef };

export interface OpenedBoard {
  board: BoardData;
  /** The file name without ".json", for the title bar. */
  name: string;
  /** Where to save it back (the host's reference to the file), when the host allows that. */
  handle: FileRef | null;
  /** The file's text as read (what's "on disk"), or null for a board with no file. */
  text?: string | null;
}

export class BoardFileError extends Error {}

/** Writing in place wasn't allowed (autosave doesn't ask: asking needs a click). */
export class NoPermissionError extends BoardFileError {}

/** A file used before can't be found any more (moved, renamed or deleted). */
export class FileGoneError extends BoardFileError {
  constructor(name: string) {
    super(`“${name}” can't be found any more: it was moved, renamed or deleted.`);
  }
}

export const baseName = (fileName: string) => fileName.replace(/\.json$/i, "");
export const jsonName = (name: string) => (name.toLowerCase().endsWith(".json") ? name : `${name}.json`);

/** A board from file text, with a friendly message for anything that isn't one. */
export function parseBoard(text: string, fileName: string, handle: FileRef | null = null): OpenedBoard {
  try {
    return { board: boardFromJson(text), name: baseName(fileName), handle, text };
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

/** A board from a dropped file (every host's page gets the same File objects). */
export async function readBoardFile(file: File, handle: FileRef | null = null): Promise<OpenedBoard> {
  return parseBoard(await file.text(), file.name, handle);
}
