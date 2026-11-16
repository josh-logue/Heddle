// Copied cards on the clipboard (heddle/main_window.py: copy, cut, paste).
//
// A page can put its own data on the system clipboard only during a real copy event
// (Ctrl+C / Ctrl+X), and read it back only during a paste event (Ctrl+V). Those carry
// the cards as board JSON under CLIPBOARD_MIME, plus their titles as plain text for
// pasting elsewhere, so they work between tabs and windows. Menu commands can't do
// that, so the last cards copied in this tab are also kept here for "Paste here".

import { CLIPBOARD_MIME, boardFromDict, boardToDict, type BoardData } from "../core/model.ts";

let local: string | null = null;

function encode(fragment: BoardData): [json: string, text: string] {
  return [JSON.stringify(boardToDict(fragment)), fragment.cards.map((c) => c.title).join("\n")];
}

function decode(json: string | null | undefined): BoardData | null {
  if (!json) return null;
  try {
    const raw = JSON.parse(json);
    // Only the cards of a Heddle board: not just any JSON someone copied.
    if (!raw || typeof raw !== "object" || !Array.isArray(raw.cards) || raw.app === undefined) return null;
    return boardFromDict(raw);
  } catch {
    return null;
  }
}

/** Put cards on the clipboard: through the copy event when there is one. */
export function writeFragment(fragment: BoardData, event?: ClipboardEvent): void {
  const [json, text] = encode(fragment);
  local = json;
  if (event?.clipboardData) {
    event.clipboardData.setData(CLIPBOARD_MIME, json);
    event.clipboardData.setData("text/plain", text);
    event.preventDefault();
  } else {
    void navigator.clipboard?.writeText(text).catch(() => undefined);
  }
}

/** Cards from the clipboard: the paste event's, else the last ones copied in this tab. */
export function readFragment(event?: ClipboardEvent): BoardData | null {
  const data = event?.clipboardData;
  if (data) {
    const found = decode(data.getData(CLIPBOARD_MIME)) ?? decode(data.getData("text/plain"));
    if (found) return found;
    if (data.types.length) return null; // something else was copied since: not our cards
  }
  return decode(local);
}

/** Is there something "Paste here" can paste? */
export function canPasteHere(): boolean {
  return local !== null;
}
