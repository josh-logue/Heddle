// Opening board files in a browser: a file picker, or a file dropped on the page. W7 adds
// saving (the File System Access API where there is one).

import { NotABoardError, boardFromJson, type BoardData } from "../core/model.ts";

export interface OpenedBoard {
  board: BoardData;
  /** The file name without ".json", for the title bar. */
  name: string;
}

export class BoardFileError extends Error {}

/** A board from file text, with a friendly message for anything that isn't one. */
export function parseBoard(text: string, fileName: string): OpenedBoard {
  try {
    return { board: boardFromJson(text), name: fileName.replace(/\.json$/i, "") };
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

export async function readBoardFile(file: File): Promise<OpenedBoard> {
  return parseBoard(await file.text(), file.name);
}

/** Ask for a board file. Resolves null if the picker is closed without one. */
export function pickBoardFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.addEventListener("change", () => resolve(input.files?.[0] ?? null), { once: true });
    input.addEventListener("cancel", () => resolve(null), { once: true });
    input.click();
  });
}
