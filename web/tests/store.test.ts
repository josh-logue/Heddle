// The editable board store: undo, moving, adding, editing, removing, arrows, folding,
// details and making room.
import { describe, expect, it } from "vitest";
import { boardFromDict, boardFromJson } from "../src/core/model.ts";
import { GRID, BoardStore, nextLine, snapped } from "../src/board/store.ts";
import { fakeMeasurer } from "../src/board/text.ts";

const m = fakeMeasurer();
const store = (raw: Record<string, unknown>) => new BoardStore(boardFromDict(raw), m);
const xOf = (s: BoardStore, id: string) => s.card(id)!.x;

describe("undo and saving", () => {
  it("records one step per edit and tracks the saved state", () => {
    const s = store({ cards: [{ id: "a" }] });
    expect(s.modified).toBe(false);
    s.updateCard("a", { title: "Rowan" });
    expect(s.modified).toBe(true);
    expect(s.card("a")!.title).toBe("Rowan");
    s.undo();
    expect(s.card("a")!.title).toBe("New card");
    expect(s.modified).toBe(false);
    s.redo();
    s.markSaved();
    expect(s.modified).toBe(false);
    expect(boardFromJson(s.toJson()).cards[0]!.title).toBe("Rowan");
  });

  it("shares unchanged cards between undo steps", () => {
    const s = store({ cards: [{ id: "a" }, { id: "b" }] });
    const b = s.card("b");
    s.updateCard("a", { title: "x" });
    expect(s.card("b")).toBe(b);
  });

  it("doesn't record an edit that changes nothing", () => {
    const s = store({ cards: [{ id: "a", title: "x" }] });
    s.updateCard("a", { title: "x" });
    expect(s.history.canUndo()).toBe(false);
  });

  it("keeps a group's saved corner with its cards", () => {
    const s = store({ cards: [{ id: "g", kind: "group", x: 999, y: 999 }, { id: "p", parent: "g", x: 100, y: 100 }] });
    expect([xOf(s, "g"), s.card("g")!.y]).toEqual([100 - 22, 100 - 22 - 32]);
    expect(s.modified).toBe(false); // fitted on opening, as the desktop does
  });
});

describe("moving", () => {
  it("moves a group with its cards, and the selection by its roots", () => {
    const s = store({ cards: [{ id: "g", kind: "group" }, { id: "p", parent: "g", x: 100, y: 100 }, { id: "q", x: 600 }] });
    s.select(["g", "p", "q"]);
    expect(s.moveRoots().sort()).toEqual(["g", "q"]);
    s.commit(s.movedBy(s.moveRoots(), 50, 0));
    expect(xOf(s, "p")).toBe(150);
    expect(xOf(s, "q")).toBe(650);
    expect(s.history.canUndo()).toBe(true);
  });

  it("nudges, and with snap steps to the next grid line", () => {
    const s = store({ cards: [{ id: "a", x: 13, y: 0 }] });
    s.select(["a"]);
    s.nudge(10, 0);
    expect(xOf(s, "a")).toBe(23);
    s.nudge(1, 0, true);
    expect(xOf(s, "a")).toBe(25);
    expect(snapped(37)).toBe(GRID);
    expect(nextLine(50, -1)).toBe(25);
    s.preview(s.movedBy(["a"], 7, 13));
    s.commit(s.snappedState(["a"]));
    expect([xOf(s, "a"), s.card("a")!.y]).toEqual([25, 25]);
  });
});

describe("adding, editing and removing", () => {
  it("adds a card only once it's kept", () => {
    const s = store({ cards: [] });
    const c = s.addCard(300, 200);
    expect(s.selected.has(c.id)).toBe(true);
    expect(s.state.cards.length).toBe(1);
    s.discardNew(c.id);
    expect(s.state.cards.length).toBe(0);
    const d = s.addCard(300, 200);
    s.updateCard(d.id, { title: "Kept" });
    s.undo();
    expect(s.state.cards.length).toBe(0); // adding and editing it is one step
  });

  it("remembers a custom colour", () => {
    const s = store({ cards: [{ id: "a" }] });
    s.updateCard("a", { color: "#123abc" });
    expect(s.state.custom_colors).toEqual(["#123abc"]);
  });

  it("removes cards with their arrows, releasing a group's cards", () => {
    const s = store({
      cards: [{ id: "g", kind: "group" }, { id: "p", parent: "g", x: 40, y: 80 }, { id: "q", x: 600 }],
      connections: [{ id: "e", source: "p", target: "q" }],
    });
    s.select(["g", "q"]);
    expect(s.describeSelection()).toBe("2 items (1 card, 1 group)");
    s.removeSelection();
    expect(s.state.cards.map((c) => [c.id, c.parent])).toEqual([["p", ""]]);
    expect(s.state.connections).toEqual([]);
    s.undo();
    expect(s.state.cards.length).toBe(3);
  });
});

describe("arrows", () => {
  it("connects once each way and never to itself", () => {
    const s = store({ cards: [{ id: "a" }, { id: "b", x: 500 }] });
    expect(s.connect("a", "a")).toBeNull();
    const e = s.connect("a", "b")!;
    expect(s.connect("a", "b")).toBeNull();
    expect(s.arrows.length).toBe(1);
    s.updateArrows([e.id], { label: "go", style: "dashed" });
    expect(s.state.connections[0]).toMatchObject({ label: "go", style: "dashed", source: "a" });
    s.reverseArrows([e.id]);
    expect(s.state.connections[0]).toMatchObject({ source: "b", target: "a", id: e.id, label: "go" });
  });

  it("won't reverse an arrow onto one going the other way", () => {
    const s = store({ cards: [{ id: "a" }, { id: "b", x: 500 }],
      connections: [{ id: "1", source: "a", target: "b" }, { id: "2", source: "b", target: "a" }] });
    s.reverseArrows(["1"]);
    expect(s.state.connections[0]).toMatchObject({ source: "a", target: "b" });
  });
});

describe("folding, details and making room", () => {
  const notes = "a long note ".repeat(30);

  it("folds a group (an undoable edit) and arrows meet its frame", () => {
    const s = store({ cards: [{ id: "g", kind: "group" }, { id: "a", parent: "g", x: 30, y: 60 }, { id: "b", x: 900 }],
      connections: [{ source: "a", target: "b" }] });
    s.setCollapsed(["g"], true);
    expect(s.boxes.get("a")!.visible).toBe(false);
    expect(s.arrows[0]!.from).toBe("g");
    s.undo();
    expect(s.boxes.get("a")!.visible).toBe(true);
  });

  it("pushes the card below down while details are open, and back after, saving nothing", () => {
    const s = store({ cards: [{ id: "a", y: 0, notes }, { id: "b", y: 150 }, { id: "far", x: 900, y: 150 }] });
    s.toggleDetails("a");
    const a = s.boxes.get("a")!;
    expect(s.boxes.get("b")!.y).toBe(a.y + a.h + 30);
    expect(s.boxes.get("far")!.y).toBe(150);
    expect(s.card("b")!.y).toBe(150);
    expect(s.modified).toBe(false);
    s.toggleDetails("a");
    expect(s.boxes.get("b")!.y).toBe(150);
  });

  it("carries on down the line, and moves a group's cards with it", () => {
    const s = store({ cards: [{ id: "a", notes }, { id: "b", y: 150 }, { id: "g", kind: "group" },
      { id: "p", parent: "g", x: 300, y: 400 }] });
    const p0 = s.boxes.get("p")!.y;
    s.setDetails(["a"], true);
    const b = s.boxes.get("b")!;
    expect(b.y).toBeGreaterThan(150);
    s.setDetails(["a"], false);
    expect(s.boxes.get("p")!.y).toBe(p0);
  });

  it("keeps a pushed card where it is once it's moved by hand", () => {
    const s = store({ cards: [{ id: "a", notes }, { id: "b", y: 150 }] });
    s.toggleDetails("a");
    const pushed = s.boxes.get("b")!.y;
    s.select(["b"]);
    s.nudge(10, 0);
    expect(s.card("b")!.y).toBe(pushed); // the push became its own position
    s.toggleDetails("a");
    expect(s.boxes.get("b")!.y).toBe(pushed); // and isn't given back
  });

  it("makes room when a group unfolds", () => {
    const s = store({ cards: [{ id: "g", kind: "group", collapsed: true }, { id: "p", parent: "g", x: 30, y: 80 },
      { id: "below", y: 100 }] });
    s.setCollapsed(["g"], false);
    const g = s.boxes.get("g")!;
    expect(s.boxes.get("below")!.y).toBe(g.y + g.h + 30);
    expect(s.card("below")!.y).toBe(g.y + g.h + 30); // a real move, as on the desktop
  });
});
