// The story tools on the board: path highlights, follow-selection, threads, "not part of
// the story", route fields and the Path Reader. Ported from tests/test_paths.py,
// tests/test_reader_highlight.py and the thread tests of tests/test_characters.py.
import { describe, expect, it } from "vitest";
import { boardFromDict, makeRoute } from "../src/core/model.ts";
import { BoardStore } from "../src/board/store.ts";
import { OWNER, PathReader } from "../src/board/reader.ts";
import { fakeMeasurer } from "../src/board/text.ts";
import { buildMenu, type MenuActions, type MenuItem } from "../src/canvas/menus.ts";

const m = fakeMeasurer();
type Raw = Record<string, unknown>;

/** A → B, then a branch: B → C ("if she refuses"), B → D ("if she agrees"); C → E and
 *  D → E; plus an unrelated card Z. Ids are the titles. */
function story(extra: Raw[] = []): BoardStore {
  const cards = [["A", 0, 0], ["B", 400, 0], ["C", 800, -200], ["D", 800, 200], ["E", 1200, 0], ["Z", 0, 800]]
    .map(([id, x, y]) => ({ id, title: id, x, y }));
  const arrows = [["A", "B", ""], ["B", "C", "if she refuses"], ["B", "D", "if she agrees"], ["C", "E", ""], ["D", "E", ""]]
    .map(([s, t, label]) => ({ id: `${s}>${t}`, source: s, target: t, label }));
  return new BoardStore(boardFromDict({ cards: [...cards, ...extra], connections: arrows }), m);
}

const lit = (s: BoardStore) => [...s.lit].sort();
const litArrows = (s: BoardStore) => [...(s.highlight?.arrows ?? [])].sort();

describe("path highlights", () => {
  it("lights up before, after or both", () => {
    const s = story();
    const label = s.highlightPaths("C");
    expect(lit(s)).toEqual(["A", "B", "C", "E"]);
    expect(label).toContain("2 before, 1 after");
    expect(label).toContain("“C”");
    expect(litArrows(s)).toEqual(["A>B", "B>C", "C>E"]);
    s.highlightPaths("C", "before");
    expect(lit(s)).toEqual(["A", "B", "C"]);
    s.highlightPaths("C", "after");
    expect(lit(s)).toEqual(["C", "E"]);
    expect(s.highlightOwner).toBe("paths");
  });

  it("lights a group's cards with it", () => {
    const s = new BoardStore(boardFromDict({
      cards: [{ id: "X", x: -500 }, { id: "G", kind: "group" }, { id: "P", parent: "G", x: 0, y: 60 }, { id: "Y", x: 800 }, { id: "Z", y: 800 }],
      connections: [{ source: "X", target: "G" }, { source: "G", target: "Y" }],
    }), m);
    expect(s.highlightPaths("G")).toContain("1 before, 1 after");
    expect(lit(s)).toEqual(["G", "P", "X", "Y"]);
  });

  it("lights the groups round a lit card, so their frames don't fade", () => {
    const t = new BoardStore(boardFromDict({
      cards: [{ id: "g", kind: "group" }, { id: "p", parent: "g" }, { id: "q", x: 500 }],
      connections: [{ source: "p", target: "q" }],
    }), m);
    t.highlightPaths("q");
    expect(lit(t)).toEqual(["g", "p", "q"]);
  });

  it("H toggles the selected card's paths; Shift+H steps the direction", () => {
    const s = story();
    expect(s.togglePaths()).toBe("Select one card to highlight its paths");
    expect(s.highlight).toBeNull();
    s.select(["B"]);
    s.togglePaths();
    expect(s.highlight?.focus).toBe("B");
    expect(s.highlight?.label).toContain("“B”");
    s.togglePaths(); // again: off
    expect(s.highlight).toBeNull();
    s.cyclePathsMode(); // no highlight yet: starts at "only what leads here"
    expect(s.highlight?.label).toMatch(/^What leads to “B”/);
    s.cyclePathsMode();
    expect(s.highlight?.label).toMatch(/^What follows “B”/);
    s.cyclePathsMode();
    expect(s.highlight?.label).toMatch(/^Paths through “B”/);
  });

  it("follows the selection while the board option is on", () => {
    const s = story();
    s.setDisplay({ follow_paths: true });
    s.select(["D"]);
    expect(lit(s)).toEqual(["A", "B", "D", "E"]);
    s.clearSelection();
    expect(s.highlight).toBeNull();
    s.setDisplay({ follow_paths: false });
    s.select(["D"]);
    expect(s.highlight).toBeNull();
  });

  it("isn't saved or undoable, and keeps showing through edits for cards that still exist", () => {
    const s = story();
    s.highlightPaths("C");
    s.updateCard("Z", { title: "Zed" });
    expect(s.highlightOwner).toBe("paths");
    expect(s.toJson()).not.toContain("highlight");
    s.remove(["C"]);
    expect(lit(s)).toEqual(["A", "B", "E"]);
    s.remove(["A", "B", "E"]);
    expect(s.highlight).toBeNull();
  });

  it("ends a story tool's highlight when the story tools are turned off, but not a path highlight", () => {
    const s = story([{ id: "M", characters: ["Mabel"], x: 0, y: 1200 }]);
    s.showThread("Mabel");
    s.setDisplay({ story_tools: false });
    expect(s.highlight).toBeNull();
    s.highlightPaths("B");
    s.setDisplay({ story_tools: true });
    s.setDisplay({ story_tools: false });
    expect(s.highlightOwner).toBe("paths");
  });
});

/** Intro → Election → After (Rowan in all, Sable in Election), and a loose card with Rowan. */
function threadBoard(): BoardStore {
  return new BoardStore(boardFromDict({
    cards: [
      { id: "intro", title: "Intro", characters: ["Rowan"] },
      { id: "election", title: "Election", x: 400, characters: ["Rowan", "Sable"] },
      { id: "after", title: "After", x: 800, characters: ["rowan"] },
      { id: "loose", title: "Loose", y: 600, characters: ["Rowan"] },
      { id: "pack", title: "Pack", y: 1200 },
      { id: "rowanCard", kind: "strand", strand_kind: "characters", strand: "Rowan", x: 1500 },
    ],
    connections: [{ id: "a1", source: "intro", target: "election" }, { id: "a2", source: "election", target: "after" }],
  }), m);
}

describe("character threads", () => {
  it("numbers, lights and joins the cards", () => {
    const s = threadBoard();
    const label = s.showThread("rowan");
    expect(s.thread?.ids).toEqual(["intro", "election", "after", "loose"]);
    expect(["intro", "election", "after", "loose"].map((id) => s.threadNumber(id))).toEqual([1, 2, 3, 4]);
    expect(s.threadNumber("pack")).toBe(0);
    expect(lit(s)).toEqual(["after", "election", "intro", "loose", "rowanCard"]); // its strand card too
    expect(label.startsWith("Thread: Rowan · 4 cards")).toBe(true);
    expect(label).toContain("introduced in “Intro”");
    expect(litArrows(s)).toEqual(["a1", "a2"]);
  });

  it("goes when cleared or replaced by another highlight", () => {
    const s = threadBoard();
    s.showThread("Rowan");
    s.clearHighlight();
    expect(s.thread).toBeNull();
    s.showThread("Rowan");
    s.highlightPaths("pack");
    expect(s.thread).toBeNull();
    expect(s.threadNumber("intro")).toBe(0);
  });

  it("renumbers after edits and undo", () => {
    const s = threadBoard();
    s.showThread("Sable");
    expect(s.thread?.ids).toEqual(["election"]);
    s.updateCard("after", { characters: ["rowan", "Sable"] });
    expect(s.thread?.ids).toEqual(["election", "after"]);
    s.undo();
    expect(s.thread?.ids).toEqual(["election"]);
    expect(s.highlightOwner).toBe("thread");
  });

  it("has nothing for a character no card features", () => {
    const s = threadBoard();
    expect(s.showThread("Nobody")).toBe("");
    expect(s.highlight).toBeNull();
  });
});

describe("not part of the story", () => {
  it("O leaves the selected cards out, or puts them back once they're all out (one undo step)", () => {
    const s = story([{ id: "S", kind: "strand", strand_kind: "tags", strand: "x" }]);
    expect(s.toggleOutside([])).toContain("Select a card");
    s.select(["A", "B"]);
    s.toggleOutside();
    expect([s.card("A")!.outside_story, s.card("B")!.outside_story]).toEqual([true, true]);
    s.select(["A", "C", "S"]);
    s.toggleOutside(); // C isn't out yet: all go out (the strand card is skipped)
    expect(s.card("C")!.outside_story).toBe(true);
    s.toggleOutside(); // all out: back in
    expect([s.card("A")!.outside_story, s.card("C")!.outside_story, s.card("B")!.outside_story]).toEqual([false, false, true]);
    s.undo();
    expect(s.card("A")!.outside_story).toBe(true);
    expect(s.toggleOutside(["S"])).toContain("Select a card");
  });
});

describe("route fields", () => {
  it("are saved by key, undoable, and forgotten when blank", () => {
    const s = story();
    const key = ["A", "B", "C", "E"];
    s.setRouteData(makeRoute({ key, name: "Refusal", tags: ["Act 2"] }));
    expect(s.routeData(key)?.name).toBe("Refusal");
    expect(s.routeMap().size).toBe(1);
    s.setRouteData(makeRoute({ key, name: "Refusal", tags: ["Act 2"] }));
    expect(s.history.canUndo()).toBe(true);
    s.setRouteData(makeRoute({ key }));
    expect(s.routeData(key)).toBeNull();
    s.undo();
    expect(s.routeData(key)?.tags).toEqual(["Act 2"]);
    expect(s.deleteRouteData(key)).toBe(true);
    expect(s.deleteRouteData(key)).toBe(false);
  });
});

describe("the right-click menu", () => {
  const act: MenuActions = {
    editCard: () => {}, editArrows: () => {}, editSeveral: () => {}, addCardAt: () => {}, startConnect: () => {},
    copy: () => {}, cut: () => {}, pasteAt: () => {}, canPaste: () => false, deleteSelection: () => {}, notice: () => {},
    read: () => {}, addCardKeys: "N",
  };
  const labels = (items: MenuItem[]) => items.map((i) => i.label);

  it("has the path items, and the story ones only with the story tools on", () => {
    const s = threadBoard();
    const items = buildMenu(s, { card: "election" }, 0, 0, act);
    expect(labels(items)).toEqual(expect.arrayContaining(["Highlight paths", "Not part of the story", "Read from here", "Character thread"]));
    expect(labels(items.find((i) => i.label === "Character thread")!.submenu!)).toEqual(["Rowan", "Sable"]);
    expect(labels(items)).not.toContain("Clear highlight");
    s.showThread("Sable");
    expect(labels(buildMenu(s, { card: "election" }, 0, 0, act))).toContain("Clear highlight");
    s.setDisplay({ story_tools: false });
    const off = labels(buildMenu(s, { card: "election" }, 0, 0, act));
    expect(off).toContain("Highlight paths");
    expect(off).not.toContain("Read from here");
    expect(off).not.toContain("Character thread");
    expect(labels(buildMenu(s, { card: "rowanCard" }, 0, 0, act))).not.toContain("Highlight paths"); // strand cards are outside
  });
});

describe("the Path Reader", () => {
  const titles = (r: PathReader) => r.route;

  it("follows the arrows, stops at branches, goes back the way it came", () => {
    const s = story();
    const shown: string[] = [];
    const r = new PathReader(s, (id) => shown.push(id));
    r.start("A");
    expect(titles(r)).toEqual(["A"]);
    expect(r.next()).toBe(true);
    expect(titles(r)).toEqual(["A", "B"]);
    expect(shown).toEqual(["A", "B"]);
    expect(r.choices()).toEqual([{ id: "C", label: "if she refuses" }, { id: "D", label: "if she agrees" }]); // top to bottom
    expect(r.next()).toBe(false); // a branch: Next alone can't choose
    expect(r.endNote()).toContain("branches");
    expect(r.choose(1)).toBe(true);
    expect(r.via.at(-1)).toBe("if she agrees");
    expect(r.next()).toBe(true);
    expect(r.endNote()).toContain("end of this path");
    expect(r.back()).toBe(true);
    expect(r.route.at(-1)).toBe("D"); // retraces the route taken
    r.restart();
    expect(r.route).toEqual(["A"]);
  });

  it("highlights the route so far and its arrows, centred on the current card", () => {
    const s = story();
    const r = new PathReader(s);
    r.start("A");
    r.next();
    r.choose(0);
    expect(s.highlightOwner).toBe(OWNER);
    expect(lit(s)).toEqual(["A", "B", "C"]);
    expect(litArrows(s)).toEqual(["A>B", "B>C"]);
    expect(s.highlight?.focus).toBe("C");
    expect(s.highlight?.label).toBe("Reading a path · step 3");
  });

  it("offers a group's first cards", () => {
    const s = new BoardStore(boardFromDict({
      cards: [{ id: "G", kind: "group" }, { id: "P", parent: "G", y: 60 }, { id: "Q", parent: "G", y: 300 }],
    }), m);
    const r = new PathReader(s);
    r.start("G");
    expect(r.route).toEqual([]);
    expect(r.choices().map((c) => c.id)).toEqual(["P", "Q"]);
    r.choose(1);
    expect(r.route).toEqual(["Q"]);
    expect(r.back()).toBe(true);
    expect(r.route).toEqual([]); // back to the choice of first card
    s.connect("G", "P"); // P is now the first card
    r.start("G");
    expect(r.route).toEqual(["P"]);
  });

  it("trims the route when a card on it goes, or its arrow does", () => {
    const s = story();
    const r = new PathReader(s);
    r.start("A");
    r.next();
    r.choose(0);
    s.remove(["C"]);
    expect(r.route).toEqual(["A", "B"]);
    s.remove([], ["A>B"]);
    expect(r.route).toEqual(["A"]);
    s.remove(["A"]);
    expect(r.route).toEqual([]);
    expect(r.reading).toBe(false);
  });

  it("stop() ends its own highlight but leaves another", () => {
    const s = story();
    const r = new PathReader(s);
    r.start("A");
    r.stop();
    expect(s.highlight).toBeNull();
    r.start("A");
    s.highlightPaths("E");
    r.stop();
    expect(s.highlightOwner).toBe("paths");
  });

  describe("while reading, an edit (review finding B)", () => {
    const reading = () => {
      const s = new BoardStore(boardFromDict({
        cards: [{ id: "A", characters: ["Mabel"] }, { id: "B", x: 400, characters: ["Mabel"] }, { id: "C", x: 800 }],
        connections: [{ id: "ab", source: "A", target: "B" }, { id: "bc", source: "B", target: "C" }],
      }), m);
      const r = new PathReader(s);
      r.start("A");
      return { s, r };
    };
    const nudge = (s: BoardStore, id: string) => {
      s.select([id]);
      s.nudgePreview(10, 0);
      s.commit();
    };

    it.each(["thread", "paths", "checks"])("keeps another highlight (%s)", (other) => {
      const { s, r } = reading();
      if (other === "thread") s.showThread("Mabel");
      else if (other === "paths") s.highlightPaths("C");
      else s.setHighlight(["C"], [], "C", "Check: dead end", "checks");
      const label = s.highlight!.label;
      nudge(s, "C");
      expect(s.highlightOwner).toBe(other);
      expect(s.highlight!.label).toBe(label);
      expect(r.route).toEqual(["A"]);
    });

    it("doesn't bring back a highlight cleared with Esc", () => {
      const { s } = reading();
      s.clearHighlight();
      nudge(s, "C");
      expect(s.highlight).toBeNull();
    });

    it("a step brings the reader's highlight back", () => {
      const { s, r } = reading();
      s.showThread("Mabel");
      expect(r.next()).toBe(true);
      expect(s.highlightOwner).toBe(OWNER);
      expect(lit(s)).toEqual(["A", "B"]);
    });

    it("the reader's own highlight follows edits and undo", () => {
      const { s, r } = reading();
      r.next();
      nudge(s, "C");
      expect(s.highlightOwner).toBe(OWNER);
      s.undo();
      expect(s.highlightOwner).toBe(OWNER);
      expect(lit(s)).toEqual(["A", "B"]);
    });
  });
});
