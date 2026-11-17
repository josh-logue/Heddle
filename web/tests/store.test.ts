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

  it("doesn't record a drag that ends where it started (as the desktop compares by value)", () => {
    const s = store({ cards: [{ id: "a", x: 0, y: 0 }, { id: "b", x: 400, y: 0 }] });
    s.select(["a"]);
    const roots = s.moveRoots();
    s.beginMove(roots);
    const base = s.movedBy(roots, 0, 0); // what the canvas does once a drag starts
    s.preview(s.movedBy(roots, 50, 20, base));
    s.preview(s.movedBy(roots, 0, 0, base));
    s.endMove();
    expect(s.commit()).toBe(false);
    expect(s.history.canUndo()).toBe(false);
    expect(s.modified).toBe(false);
  });

  it("doesn't record nudges that cancel out, and a board moved back to its saved state isn't modified", () => {
    const s = store({ cards: [{ id: "a", x: 0, y: 0 }] });
    s.select(["a"]);
    s.nudgePreview(10, 0);
    s.nudgePreview(-10, 0);
    expect(s.commit()).toBe(false);
    expect(s.modified).toBe(false);
    s.nudge(10, 0);
    expect(s.modified).toBe(true);
    s.nudge(-10, 0); // two steps, but back where it was saved
    expect(s.history.canUndo()).toBe(true);
    expect(s.modified).toBe(false);
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

describe("copy, cut, paste and duplicate", () => {
  const board = () => store({
    cards: [{ id: "g", kind: "group" }, { id: "p", parent: "g", x: 40, y: 80, color: "#123abc" },
      { id: "q", parent: "g", x: 400, y: 80 }, { id: "far", x: 2000, y: 2000 }],
    connections: [{ id: "e", source: "p", target: "q", label: "on" }, { id: "f", source: "q", target: "far" }],
    custom_colors: ["#123abc", "#999999"],
  });

  it("copies a group with everything in it, its own arrows and the colours it uses", () => {
    const s = board();
    s.select(["g"]);
    const f = s.selectionFragment()!;
    expect(f.cards.map((c) => c.id).sort()).toEqual(["g", "p", "q"]);
    expect(f.connections.map((c) => c.id)).toEqual(["e"]);
    expect(f.custom_colors).toEqual(["#123abc"]);
    s.clearSelection();
    expect(s.selectionFragment()).toBeNull();
  });

  it("duplicates beside the originals, in the same group, as one step", () => {
    const s = board();
    s.select(["p"]);
    const [id] = s.duplicate();
    const copy = s.card(id!)!;
    expect([copy.x, copy.y, copy.parent]).toEqual([70, 110, "g"]);
    expect([...s.selected]).toEqual([id]);
    s.undo();
    expect(s.card(id!)).toBeUndefined();
  });

  it("pastes at a point, joining the group there, with fresh ids and arrows", () => {
    const s = board();
    s.select(["p", "q"]);
    const f = s.selectionFragment()!;
    const g = s.boxes.get("g")!;
    const ids = s.paste(f, [g.x + 30, g.y + g.headerH + 10]);
    const cards = ids.map((i) => s.card(i)!);
    expect(cards.every((c) => c.parent === "g" && !["p", "q"].includes(c.id))).toBe(true);
    expect(Math.min(...cards.map((c) => c.x))).toBe(g.x + 30);
    const arrows = s.state.connections.filter((e) => ids.includes(e.source));
    expect(arrows.map((e) => e.label)).toEqual(["on"]);
  });

  it("pastes into another board, bringing custom colours", () => {
    const s = board();
    s.select(["p"]);
    const f = s.selectionFragment()!;
    const other = store({ cards: [] });
    const [id] = other.paste(f, [0, 0]);
    expect(other.card(id!)!.parent).toBe("");
    expect(other.state.custom_colors).toEqual(["#123abc"]);
  });

  it("cuts a group with its cards", () => {
    const s = board();
    s.select(["g"]);
    const f = s.cut()!;
    expect(f.cards.length).toBe(3);
    expect(s.state.cards.map((c) => c.id)).toEqual(["far"]);
    expect(s.state.connections).toEqual([]);
  });

  it("an arrow edit that changes nothing isn't an undo step", () => {
    const s = board();
    s.updateArrows(["e"], { label: "on" });
    expect(s.history.canUndo()).toBe(false);
  });
});

describe("groups", () => {
  const board = () => store({
    cards: [{ id: "g", kind: "group" }, { id: "p", parent: "g", x: 40, y: 80 }, { id: "q", parent: "g", x: 400, y: 80 },
      { id: "loose", x: 900, y: 80 }, { id: "h", kind: "group", x: 900, y: 600 }],
    connections: [{ id: "e", source: "p", target: "q" }],
  });
  const inside = (s: BoardStore, g: string): [number, number] => {
    const b = s.boxes.get(g)!;
    return [b.x + 40, b.y + b.headerH + 40];
  };

  it("drops cards into the group under the pointer, and out of one onto the canvas", () => {
    const s = board();
    expect(s.dropHint(["loose"], ...inside(s, "g"))).toBe("g");
    s.dropInto(["loose"], ...inside(s, "g"));
    s.commit();
    expect(s.card("loose")!.parent).toBe("g");
    expect(s.dropHint(["p"], ...inside(s, "g"))).toBeNull(); // already there: nothing to announce
    s.dropInto(["p"], 5000, 5000);
    s.commit();
    expect(s.card("p")!.parent).toBe("");
    s.undo();
    expect(s.card("p")!.parent).toBe("g");
  });

  it("never drops a group into itself or what's inside it", () => {
    const s = board();
    s.dropInto(["h"], ...inside(s, "g"));
    s.commit();
    expect(s.card("h")!.parent).toBe("g");
    expect(s.groupForDrop(["g"], ...inside(s, "h"))).toBeNull();
  });

  it("parks a card dropped on a collapsed group under its other cards", () => {
    const s = board();
    s.setCollapsed(["g"], true);
    const g = s.boxes.get("g")!;
    s.dropInto(["loose"], g.x + 100, g.y + 10);
    s.commit();
    expect(s.card("loose")!.parent).toBe("g");
    expect(s.boxes.get("loose")!.visible).toBe(false);
    expect(s.card("loose")!.x).toBe(40);
  });

  it("removes a card from its group, stepping it outside the frame", () => {
    const s = board();
    const g = s.boxes.get("g")!;
    s.removeFromGroup("q");
    expect(s.card("q")!.parent).toBe("");
    expect(s.card("q")!.x).toBe(g.x + g.w + 30);
  });

  it("ungroups, leaving the cards where they are", () => {
    const s = board();
    s.ungroup("g");
    expect(s.state.cards.filter((c) => c.parent === "g")).toEqual([]);
    expect([s.card("p")!.x, s.card("q")!.x]).toEqual([40, 400]);
  });

  it("lets a group's cards go when it becomes a card", () => {
    const s = board();
    s.updateCard("g", { kind: "card" });
    expect(s.card("p")!.parent).toBe("");
  });

  it("sets a group's members from the editor: new ones in a grid, removed ones beside it", () => {
    const s = board();
    const frame = s.boxes.get("g")!;
    s.updateCard("g", { title: "Act One" }, { members: ["p", "loose"] });
    expect(s.card("loose")!.parent).toBe("g");
    expect(s.card("q")!.parent).toBe("");
    expect(s.card("q")!.x).toBe(frame.x + frame.w + 60);
    s.undo(); // title and members: one step
    expect(s.card("g")!.title).toBe("New card");
    expect(s.card("q")!.parent).toBe("g");
    expect(s.memberCandidates("g").map(([id, , m]) => [id, m])).toContainEqual(["p", true]);
    expect(s.memberCandidates("h").map(([id]) => id)).not.toContain("h");
  });

  it("auto-arranges a group by its arrows and fits it snugly", () => {
    const s = store({
      cards: [{ id: "g", kind: "group", width: 2000, height: 2000 }, { id: "a", parent: "g", x: 600, y: 300 },
        { id: "b", parent: "g", x: 40, y: 80 }, { id: "c", parent: "g", x: 40, y: 400 }],
      connections: [{ source: "a", target: "b" }, { source: "b", target: "c" }],
    });
    s.autoArrange(["g"]);
    const [a, b, c] = ["a", "b", "c"].map((i) => s.boxes.get(i)!);
    expect(a!.y).toBe(b!.y);
    expect(b!.x).toBeGreaterThan(a!.x);
    expect(c!.x).toBeGreaterThan(b!.x);
    const g = s.card("g")!;
    expect([g.width, g.height]).toEqual([0, 0]);
    expect(s.history.canUndo()).toBe(true);
  });

  it("resizes a group by hand, never smaller than its cards, and fits it again", () => {
    const s = board();
    const before = s.boxes.get("g")!;
    s.commit(s.resizedGroup("g", before.w + 300, before.h + 200));
    expect(s.boxes.get("g")!.w).toBe(before.w + 300);
    expect(s.boxes.get("g")!.h).toBeCloseTo(before.h + 200);
    s.commit(s.resizedGroup("g", 10, 10));
    expect(s.boxes.get("g")!.w).toBe(before.w); // still holds every card
    s.fitFrame("g");
    expect(s.card("g")!.width).toBe(0);
  });

  it("sets arrange options", () => {
    const s = board();
    s.setArrangeOptions(["g", "p"], { arrange_wrap: 3 });
    expect(s.card("g")!.arrange_wrap).toBe(3);
    expect(s.card("p")!.arrange_wrap).toBe(0); // not a group
  });
});

describe("dragging", () => {
  it("holds the frames of the groups round a dragged card still until the drop", () => {
    const s = store({ cards: [{ id: "g", kind: "group" }, { id: "p", parent: "g", x: 40, y: 80 }] });
    const frame = { ...s.boxes.get("g")! };
    s.beginMove(["p"]);
    s.preview(s.movedBy(["p"], 0, 900));
    expect(s.boxes.get("g")!.h).toBe(frame.h); // not stretched after the card
    s.dropInto(["p"], 60, s.boxes.get("p")!.y + 10);
    s.endMove();
    s.commit();
    expect(s.card("p")!.parent).toBe("");
  });
});

describe("finding and board-wide edits", () => {
  const board = () => store({
    cards: [{ id: "a", title: "Rowan arrives", tags: ["Plot"], characters: ["Rowan"] },
      { id: "b", title: "Mabel's tide", x: 400, tags: ["plot", "Act 1"] },
      { id: "g", kind: "group", collapsed: true, x: 0, y: 600 }, { id: "c", title: "Hidden tide", parent: "g", x: 30, y: 700 }],
  });

  it("fades what the filter doesn't match and counts what it shows", () => {
    const s = board();
    s.setFilter(new Map([["tags", new Set(["plot"])]]), new Set());
    expect([...s.dimmed].sort()).toEqual(["c", "g"]);
    expect(s.filterCounts).toEqual({ cards_shown: 2, cards_total: 3, groups_shown: 0, groups_total: 1 });
    s.setFilter(new Map([["tags", new Set(["plot", "act 1"])]]), new Set(["tags"]));
    expect(s.dimmed.has("a")).toBe(true);
    s.setFilter(new Map(), new Set());
    expect(s.dimmed.size).toBe(0);
    expect(s.filterActive).toBe(false);
  });

  it("counts search matches folded into a collapsed group, and reveals them", () => {
    const s = board();
    s.setSearchHits(["b", "c"]);
    expect([...s.searchHits]).toEqual([["g", 1]]);
    expect(s.reveal(["c"])).toBe(true);
    expect(s.boxes.get("c")!.visible).toBe(true);
    expect(s.reveal(["c"])).toBe(false);
    expect(s.titleContext("c")).toBe("New card");
  });

  it("edits several cards as one step", () => {
    const s = board();
    expect(s.bulkEdit(["a", "b"], { color: "#123abc", addTags: ["New"], removeTags: ["PLOT"], status: " Final " })).toBe(2);
    expect(s.card("a")).toMatchObject({ color: "#123abc", tags: ["New"], status: "Final" });
    expect(s.card("b")!.tags).toEqual(["Act 1", "New"]);
    expect(s.state.custom_colors).toEqual(["#123abc"]);
    s.undo();
    expect(s.card("a")!.tags).toEqual(["Plot"]);
  });

  it("replaces text, in every card or just the chosen ones", () => {
    const s = board();
    expect(s.replaceInCards("tide", "sea", ["title"], false)).toBe(2);
    expect(s.card("c")!.title).toBe("Hidden sea");
    s.undo();
    expect(s.replaceInCards("tide", "sea", ["title"], false, ["b"])).toBe(1);
    expect(s.card("c")!.title).toBe("Hidden tide");
    expect(s.replaceInCards("zzz", "x", ["title"], false)).toBe(0);
  });

  it("changes display options as one step", () => {
    const s = board();
    s.setDisplay({ show_grid: false, arrow_routing: "curved" });
    expect(s.state.display).toMatchObject({ show_grid: false, arrow_routing: "curved" });
    s.undo();
    expect(s.state.display.show_grid).toBe(true);
  });
});

describe("strands", () => {
  const board = () => store({
    cards: [{ id: "a", tags: ["Plot"], characters: ["Rowan"] }, { id: "b", x: 400, characters: ["rowan", "Mabel"] },
      { id: "s", kind: "strand", strand_kind: "characters", strand: "Rowan", x: 900 }],
    saved_values: { locations: ["Harbour"], tags: ["Spare"] },
    strands: [{ kind: "characters", name: "Rowan", description: "Keeper", fields: [{ name: "Age", value: "41" }] },
      { kind: "characters", name: "Mabel", description: "Scribe", fields: [{ name: "Home", value: "Dock" }] },
      { kind: "tags", name: "Spare", description: "Kept for later" }],
  });

  it("lists every strand, with the built-in statuses and strand cards' strands", () => {
    const s = board();
    expect(s.allValues("characters")).toEqual(["Mabel", "Rowan"]);
    expect(s.allValues("status")).toContain("Draft");
    expect([...s.strandUsage("characters")]).toEqual([["rowan", [2, 0]], ["mabel", [1, 0]]]);
    expect([...s.strandCardCounts("characters")]).toEqual([["rowan", 1]]);
    expect(s.cardsWith("characters", "ROWAN").sort()).toEqual(["a", "b", "s"]);
  });

  it("keeps a strand an edit leaves unused as a saved strand", () => {
    const s = board();
    s.updateCard("a", { tags: [] });
    expect(s.state.saved_values.tags).toEqual(["Spare", "Plot"]);
  });

  it("renames everywhere, merging details onto an existing strand", () => {
    const s = board();
    s.renameStrand("characters", "Rowan", "Mabel");
    expect(s.card("a")!.characters).toEqual(["Mabel"]);
    expect(s.card("b")!.characters).toEqual(["Mabel"]);
    expect(s.card("s")!.strand).toBe("Mabel");
    const info = s.strand("characters", "mabel")!;
    expect(info.description).toBe("Scribe\n\n———\n\nKeeper");
    expect(info.fields).toEqual([["Home", "Dock"], ["Age", "41"]]);
    expect(s.allValues("characters")).toEqual(["Mabel"]); // the old name isn't kept
    s.undo();
    expect(s.allValues("characters")).toEqual(["Mabel", "Rowan"]);
  });

  it("stores and forgets a strand's details", () => {
    const s = board();
    expect(s.setStrandInfo({ kind: "tags", name: "plot", description: "The main line", picture: "", fields: [] })).toBe(true);
    expect(s.strand("tags", "PLOT")!.description).toBe("The main line");
    expect(s.setStrandInfo({ kind: "tags", name: "Plot", description: "", picture: "", fields: [] })).toBe(true);
    expect(s.strand("tags", "plot")).toBeUndefined();
  });

  it("applies one strand's fields to others", () => {
    const s = board();
    expect(s.applyStrandFields("characters", "Rowan", ["Mabel", "nobody"], null, true)).toEqual([1, 1]);
    expect(s.strand("characters", "Mabel")!.fields).toEqual([["Home", "Dock"], ["Age", "41"]]);
  });

  it("finds and removes unused strands and colours", () => {
    const s = store({ cards: [{ id: "a", color: "#111111" }], custom_colors: ["#111111", "#222222"],
      saved_values: { locations: ["Harbour"], tags: ["Spare"] }, strands: [{ kind: "tags", name: "Spare", description: "x" }] });
    expect(s.unusedStrands()).toEqual([{ locations: ["Harbour"] }, { tags: ["Spare"] }]);
    expect(s.unusedSaved()).toEqual({ locations: ["Harbour"], custom_colors: ["#222222"] });
    expect(s.removeSaved(s.unusedSaved(true))).toBe(3);
    expect(s.allValues("tags")).toEqual([]);
    expect(s.state.custom_colors).toEqual(["#111111"]);
  });

  it("imports strands it doesn't have, with their details", () => {
    const s = board();
    const added = s.importStrands({ tags: ["plot", "Twist"], locations: ["Lighthouse"] }, ["#abcdef", "#4a7fc1"],
      [{ kind: "tags", name: "Twist", description: "A turn", picture: "", fields: [] }]);
    expect(added).toBe(3); // "plot" is already here, the preset colour isn't custom
    expect(s.strand("tags", "twist")!.description).toBe("A turn");
    expect(s.state.custom_colors).toEqual(["#abcdef"]);
  });

  it("drops a strand onto a card, a group or the blank board", () => {
    const s = store({ cards: [{ id: "a", x: 0, y: 0 }, { id: "g", kind: "group", x: 0, y: 400, width: 600, height: 300 },
      { id: "st", kind: "strand", strand_kind: "tags", strand: "X", x: 900 }] });
    expect(s.dropStrand("characters", "Rowan", 50, 20)).toEqual([true, ""]);
    expect(s.card("a")!.characters).toEqual(["Rowan"]);
    expect(s.dropStrand("characters", "rowan", 50, 20)[0]).toBe(false);
    s.dropStrand("status", "Draft", 50, 20);
    expect(s.dropStrand("status", "Final", 50, 20)[1]).toContain("status Draft → Final");
    const g = s.boxes.get("g")!;
    s.dropStrand("locations", "Harbour", g.x + 100, g.y + g.headerH + 100);
    const made = s.state.cards.at(-1)!;
    expect([made.kind, made.strand_kind, made.strand, made.parent]).toEqual(["strand", "locations", "Harbour", "g"]);
    expect(s.strandDropTarget(950, 10)).toBeNull(); // a strand card's strand is fixed
    expect(s.strandDropTarget(5000, 5000)).toEqual(["new", null]);
  });

  it("counts colour use, leaving out the card being edited", () => {
    const s = store({ cards: [{ id: "a", color: "#111111" }, { id: "b", color: "#111111" }],
      connections: [{ source: "a", target: "b", color: "#222222" }] });
    expect(s.colorUsage("a").get("#111111")).toBe(1);
    expect(s.colorUsage().get("#222222")).toBe(1);
  });
});
