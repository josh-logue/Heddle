// The browser's fallback file picker (a hidden file input), with a stand-in document: the
// input is in the page while open, a file wins over a "cancel" that comes just before it
// (Firefox), and a real cancel still resolves null.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CANCEL_GRACE_MS, pickWithInput } from "../src/platform/browser/files.ts";

class FakeInput extends EventTarget {
  type = "";
  accept = "";
  style: Record<string, string> = {};
  files: File[] | null = null;
  clicked = false;
  inPage = false;
  click() { this.clicked = true; }
  remove() { this.inPage = false; }
  choose(file: File) {
    this.files = [file];
    this.dispatchEvent(new Event("change"));
  }
  cancel() { this.dispatchEvent(new Event("cancel")); }
}

let input: FakeInput;
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("document", {
    createElement: () => (input = new FakeInput()),
    body: { append: (el: FakeInput) => { el.inPage = true; } },
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const board = () => new File(["{}"], "board.json", { type: "application/json" });

describe("pickWithInput", () => {
  it("puts the input in the page while open and takes it out after", async () => {
    const picked = pickWithInput();
    expect(input.clicked).toBe(true);
    expect(input.inPage).toBe(true);
    expect(input.type).toBe("file");
    input.choose(board());
    expect((await picked)?.name).toBe("board.json");
    expect(input.inPage).toBe(false);
  });

  it("still takes a file that arrives just after a cancel", async () => {
    const picked = pickWithInput();
    input.cancel();
    vi.advanceTimersByTime(CANCEL_GRACE_MS / 2);
    input.choose(board());
    expect((await picked)?.name).toBe("board.json");
  });

  it("resolves null when the picker is really cancelled", async () => {
    const picked = pickWithInput();
    input.cancel();
    vi.advanceTimersByTime(CANCEL_GRACE_MS);
    expect(await picked).toBeNull();
    expect(input.inPage).toBe(false);
  });
});
