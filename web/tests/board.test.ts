// Card layout, text wrapping and arrow geometry (board/), with a fake text measurer.
import { describe, expect, it } from "vitest";
import { DISPLAY_DEFAULTS, boardFromDict, makeCard, makeConnection, type CardData } from "../src/core/model.ts";
import {
  CARD_WIDTH, GROUP_MIN_WIDTH, GROUP_PAD, HEADER_HEIGHT, PAD, Structure, anchorRect, layoutBoard, paintOrder,
} from "../src/board/metrics.ts";
import { ARROW_LEN, REVERSE_OFFSET, routeArrows } from "../src/board/routing.ts";
import { elide, elideLines, fakeMeasurer, wrapLines } from "../src/board/text.ts";
import { BoardViewer } from "../src/board/viewer.ts";

const m = fakeMeasurer();
// With the fake measurer every "small" character is 34/3 × 0.55 px wide.

describe("text", () => {
  it("wraps at spaces, keeps line breaks and breaks words too long for a line", () => {
    const w = m.width("aaaaa", "body");
    expect(wrapLines(m, "aa bb cc", "body", w)).toEqual(["aa bb", "cc"]);
    expect(wrapLines(m, "aa\n\nbb", "body", w)).toEqual(["aa", "", "bb"]);
    expect(wrapLines(m, "abcdefghijkl", "body", w)).toEqual(["abcde", "fghij", "kl"]);
    expect(wrapLines(m, "", "body", w)).toEqual([""]);
  });

  it("elides on the right", () => {
    const w = m.width("abcd…", "body");
    expect(elide(m, "abc", "body", w)).toBe("abc");
    expect(elide(m, "abcdefgh", "body", w)).toBe("abcd…");
  });

  it("keeps at most a number of lines, marking the cut", () => {
    const w = m.width("aaaaa", "body");
    const [lines, cut] = elideLines(m, "aa bb cc dd ee ff gg", "body", w, 2);
    expect(cut).toBe(true);
    expect(lines.length).toBe(2);
    expect(lines[1]!.endsWith("…")).toBe(true);
    expect(elideLines(m, "aa bb", "body", w, 2)).toEqual([["aa bb"], false]);
    // Cut only by line breaks: the last kept line gets the mark.
    expect(elideLines(m, "a\nb\nc", "body", w, 2)).toEqual([["a", "b…"], true]);
  });
});

function layout(cards: CardData[], extra: Partial<Parameters<typeof layoutBoard>[0]> = {}) {
  return layoutBoard({ cards, display: DISPLAY_DEFAULTS, ...extra }, m);
}

describe("card layout", () => {
  it("sizes a plain card from its text", () => {
    const short = layout([makeCard({ id: "a", description: "Hi" })]).get("a")!;
    const long = layout([makeCard({ id: "a", description: "word ".repeat(80) })]).get("a")!;
    expect(short.w).toBe(CARD_WIDTH);
    expect(short.h).toBeGreaterThan(HEADER_HEIGHT);
    expect(long.h).toBeGreaterThan(short.h);
    expect(long.tooltip).not.toBe(""); // cut off: hovering shows it all
    expect(long.blocks[0]!.lines.length).toBe(6);
  });

  it("grows with details but keeps arrows on the closed card", () => {
    const card = makeCard({ id: "a", characters: ["Rowan"], notes: "n" });
    const closed = layout([card]).get("a")!;
    const open = layout([card], { details: new Set(["a"]) }).get("a")!;
    expect(open.h).toBeGreaterThan(closed.h);
    expect(anchorRect(open)).toEqual(anchorRect(closed));
    expect(open.blocks.some((b) => b.lines[0] === "CHARACTERS")).toBe(true);
  });

  it("follows the board's face options", () => {
    const card = makeCard({ id: "a", tags: ["Plot"], pov: "Mabel", characters: ["Mabel", "Greta"] });
    const plain = layout([card]).get("a")!;
    expect(plain.tagPills.map((p) => p.text)).toEqual(["Plot"]);
    expect(plain.charPills).toEqual([]);
    const more = layout([card], { display: { ...DISPLAY_DEFAULTS, show_characters: true, show_tags: false } }).get("a")!;
    expect(more.tagPills).toEqual([]);
    expect(more.charPills.map((p) => p.text)).toEqual(["Greta"]); // the POV has its own line
    const compact = layout([makeCard({ id: "a", description: "x" })],
      { display: { ...DISPLAY_DEFAULTS, show_description: false, compact_cards: true } }).get("a")!;
    expect(compact.h).toBe(HEADER_HEIGHT);
    expect(compact.tooltip).toBe("x");
  });

  it("fits a group around its cards, nested groups first", () => {
    const cards = [
      makeCard({ id: "g", kind: "group", x: 0, y: 0 }),
      makeCard({ id: "h", kind: "group", parent: "g" }),
      makeCard({ id: "a", x: 100, y: 200, parent: "h" }),
      makeCard({ id: "b", x: 600, y: 200, parent: "g" }),
    ];
    const boxes = layout(cards);
    const [g, h, a, b] = ["g", "h", "a", "b"].map((i) => boxes.get(i)!);
    expect(h!.x).toBe(a!.x - GROUP_PAD);
    expect(h!.y + h!.h).toBe(a!.y + a!.h + GROUP_PAD);
    expect(g!.x).toBe(h!.x - GROUP_PAD);
    expect(g!.x + g!.w).toBe(b!.x + CARD_WIDTH + GROUP_PAD);
    expect(g!.memberCount).toBe(2);
    expect(paintOrder(boxes).groups.map((x) => x.card.id)).toEqual(["g", "h"]);
  });

  it("gives an empty group its minimum size and a collapsed one just its title bar", () => {
    const boxes = layout([makeCard({ id: "g", kind: "group", x: 5, y: 6 })]);
    expect(boxes.get("g")).toMatchObject({ x: 5, y: 6, w: GROUP_MIN_WIDTH });
    const folded = layout([makeCard({ id: "g", kind: "group", collapsed: true }), makeCard({ id: "a", parent: "g" })]);
    expect(folded.get("g")!.h).toBe(HEADER_HEIGHT);
    expect(folded.get("a")!.visible).toBe(false);
  });

  it("drops broken and looping memberships", () => {
    const s = new Structure([
      makeCard({ id: "a", parent: "nope" }), makeCard({ id: "b", parent: "a" }),
      makeCard({ id: "g", kind: "group", parent: "h" }), makeCard({ id: "h", kind: "group", parent: "g" }),
    ]);
    expect(s.parentOf.has("a")).toBe(false);
    expect(s.parentOf.has("b")).toBe(false); // a isn't a group
    expect(s.parentOf.has("g") && s.parentOf.has("h")).toBe(false);
  });

  it("shows a strand card's description in its details", () => {
    const board = boardFromDict({
      cards: [{ id: "s", kind: "strand", strand_kind: "characters", strand: "Rowan" }],
      strands: [{ kind: "characters", name: "rowan", description: "Keeper", fields: [{ name: "Age", value: "9" }] }],
    });
    const box = layoutBoard({ cards: board.cards, strands: board.strands, details: new Set(["s"]) }, m).get("s")!;
    expect(box.blocks.map((b) => b.lines.join(" "))).toEqual(["Keeper", "Age: 9"]);
    expect(box.tooltip).toBe("Character: Rowan");
  });
});

describe("arrows", () => {
  const two = (bx: number, by = 0) => [makeCard({ id: "a", x: 0, y: 0 }), makeCard({ id: "b", x: bx, y: by })];

  function shapes(cards: CardData[], conns: [string, string, string?][], routing = "straight") {
    const display = { ...DISPLAY_DEFAULTS, arrow_routing: routing as "straight" };
    const s = new Structure(cards);
    const boxes = layoutBoard({ cards, display }, m, s);
    const connections = conns.map(([source, target, label]) => makeConnection({ source, target, label: label ?? "", id: `${source}>${target}` }));
    return { boxes, arrows: routeArrows(connections, boxes, s, display, m) };
  }

  it("runs straight between the cards' edges", () => {
    const { boxes, arrows } = shapes(two(500), [["a", "b"]]);
    const [arrow] = arrows;
    const a = boxes.get("a")!;
    expect(arrow!.path.start[0]).toBeCloseTo(CARD_WIDTH);
    expect(arrow!.head[0][0]).toBeCloseTo(500);
    expect(arrow!.path.start[1]).toBeCloseTo(a.h / 2);
  });

  it("offsets arrows both ways between two cards", () => {
    const { arrows } = shapes(two(500), [["a", "b"], ["b", "a"]]);
    expect(Math.abs(arrows[0]!.path.start[1] - arrows[1]!.path.start[1])).toBeCloseTo(2 * REVERSE_OFFSET);
  });

  it("draws nothing for overlapping cards, self-loops, missing ends or repeats", () => {
    expect(shapes(two(20), [["a", "b"]]).arrows).toEqual([]);
    expect(shapes(two(500), [["a", "a"], ["a", "zz"]]).arrows).toEqual([]);
    expect(shapes(two(500), [["a", "b"], ["a", "b"]]).arrows.length).toBe(1);
  });

  it("curves between facing sides and routes round cards in the way", () => {
    const cards = [...two(800), makeCard({ id: "c", x: 400, y: 0 })];
    const curved = shapes(cards, [["a", "b"]], "curved").arrows[0]!;
    expect(curved.path.segments[0]!.kind).toBe("C");
    const avoid = shapes(cards, [["a", "b"]], "avoid").arrows[0]!;
    const c = shapes(cards, [], "avoid").boxes.get("c")!;
    const throughC = avoid.path.points().some(([x, y]) => x > c.x && x < c.x + c.w && y > c.y && y < c.y + c.h);
    expect(throughC).toBe(false);
    expect(avoid.path.segments.length).toBe(3); // out, level, back in
  });

  it("puts the label halfway along, shortened if long", () => {
    const { arrows } = shapes(two(800), [["a", "b", "x ".repeat(100)]]);
    expect(arrows[0]!.labelText.endsWith("…")).toBe(true);
    expect(arrows[0]!.tooltip).toBe("x ".repeat(99) + "x");
  });

  it("draws first and last-card markers inside a group", () => {
    const cards = [makeCard({ id: "g", kind: "group" }), makeCard({ id: "p", x: 200, y: 200, parent: "g" })];
    const { boxes, arrows } = shapes(cards, [["g", "p"], ["p", "g"]]);
    const g = boxes.get("g")!;
    const [first, last] = arrows;
    expect(first!.path.start[0]).toBeCloseTo(g.x); // from the frame's left side...
    expect(first!.head[0][0]).toBeCloseTo(200); // ...to the card
    expect(last!.head[0][0]).toBeCloseTo(g.x + g.w); // and out to the right side
  });

  it("meets a collapsed group's frame, merging arrows into it", () => {
    const cards = [makeCard({ id: "x", x: -600 }), makeCard({ id: "g", kind: "group", collapsed: true }),
      makeCard({ id: "p", x: 200, y: 200, parent: "g" }), makeCard({ id: "q", x: 200, y: 500, parent: "g" })];
    const { arrows } = shapes(cards, [["x", "p"], ["x", "q"], ["p", "q"]]);
    expect(arrows.length).toBe(1); // p -> q folds away; the other two merge
    expect(arrows[0]).toMatchObject({ from: "x", to: "g", merged: 2, labelText: "×2" });
  });

  it("keeps the arrowhead its full length", () => {
    const { arrows } = shapes(two(500), [["a", "b"]]);
    const [tip, l] = arrows[0]!.head;
    expect(Math.hypot(tip[0] - (l[0] + arrows[0]!.head[2][0]) / 2, tip[1] - (l[1] + arrows[0]!.head[2][1]) / 2)).toBeCloseTo(ARROW_LEN);
  });
});

describe("making room", () => {
  const notes = "a long note ".repeat(30);

  it("pushes the card below down while details are open, and back after", () => {
    const board = boardFromDict({ cards: [{ id: "a", y: 0, notes }, { id: "b", y: 150 }, { id: "far", x: 900, y: 150 }] });
    const v = new BoardViewer(board, m);
    const b0 = v.boxes.get("b")!.y;
    v.toggleDetails("a");
    const a = v.boxes.get("a")!;
    expect(v.boxes.get("b")!.y).toBe(a.y + a.h + 30); // the usual gap below
    expect(v.boxes.get("far")!.y).toBe(150); // not in the way: stays put
    expect(board.cards[1]!.y).toBe(150); // nothing saved changes
    v.toggleDetails("a");
    expect(v.boxes.get("b")!.y).toBe(b0);
  });

  it("carries on down the line: a pushed card pushes the next", () => {
    const board = boardFromDict({ cards: [{ id: "a", notes }, { id: "b", y: 150 }, { id: "c", y: 300 }] });
    const v = new BoardViewer(board, m);
    v.toggleDetails("a");
    const b = v.boxes.get("b")!;
    expect(v.boxes.get("c")!.y).toBe(b.y + b.h + 30);
  });

  it("moves a group's cards with it", () => {
    const board = boardFromDict({ cards: [
      { id: "a", notes }, { id: "g", kind: "group" }, { id: "p", parent: "g", x: 30, y: 200 }] });
    const v = new BoardViewer(board, m);
    const p0 = v.boxes.get("p")!.y;
    v.toggleDetails("a");
    expect(v.boxes.get("p")!.y).toBeGreaterThan(p0);
    expect(v.boxes.get("g")!.y).toBeLessThan(v.boxes.get("p")!.y);
    v.setAllDetails(false);
    expect(v.boxes.get("p")!.y).toBe(p0);
  });

  it("makes room when a group unfolds", () => {
    const board = boardFromDict({ cards: [
      { id: "g", kind: "group", collapsed: true }, { id: "p", parent: "g", x: 30, y: 80 }, { id: "below", y: 100 }] });
    const v = new BoardViewer(board, m);
    v.setCollapsed("g", false);
    const g = v.boxes.get("g")!;
    expect(v.boxes.get("below")!.y).toBe(g.y + g.h + 30);
  });
});

describe("viewer", () => {
  it("folds groups and shows details", () => {
    const board = boardFromDict({
      cards: [{ id: "g", kind: "group" }, { id: "a", parent: "g", x: 30, y: 60, characters: ["Rowan"] }, { id: "b", x: 600 }],
      connections: [{ source: "a", target: "b" }],
    });
    const v = new BoardViewer(board, m);
    const before = v.version;
    v.setCollapsed("g", true);
    expect(v.boxes.get("a")!.visible).toBe(false);
    expect(v.arrows[0]!.from).toBe("g");
    expect(v.version).toBeGreaterThan(before);
    v.setCollapsed("g", false);
    const h = v.boxes.get("a")!.h;
    v.toggleDetails("a");
    expect(v.boxes.get("a")!.h).toBeGreaterThan(h);
    v.setAllDetails(false);
    expect(v.boxes.get("a")!.h).toBe(h);
    expect(v.boxes.get("a")!.introduces).toEqual(["Rowan"]); // first on the only route
    expect(PAD).toBe(10);
  });
});
