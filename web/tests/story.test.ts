// Ported from the pure parts of tests/test_checks.py, tests/test_routes.py,
// tests/test_export.py and tests/test_demo_boards.py.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { isEnding, runChecks, summary, type Report } from "../src/core/checks.ts";
import { OUTLINE, exportRoute, exportText } from "../src/core/exportText.ts";
import { StoryGraph } from "../src/core/graph.ts";
import {
  FORMAT_VERSION, allValues, boardFromDict, boardFromJson, makeBoard, makeCard, makeConnection, makeRoute,
  routeKeyId, type CardData,
} from "../src/core/model.ts";
import { inheritedValues, listRoutes, matches, mergedFields, routeTitle, stepsText } from "../src/core/routes.ts";

function graph(cards: CardData[], pairs: [string, string][]): StoryGraph {
  return new StoryGraph(cards, pairs.map(([s, t]) => makeConnection({ source: s, target: t, id: `${s}>${t}` })));
}

describe("story checks", () => {
  const card = (id: string, x = 0, y = 0, extra: Record<string, unknown> = {}) => makeCard({ id, title: id, x, y, ...extra });
  const kinds = (r: Report) => {
    const out: Record<string, string[][]> = {};
    for (const k of ["dead_end", "loose_starts", "cycle", "isolated", "start", "ending"]) {
      const found = r.ofKind(k);
      if (found.length) out[k] = found.map((f) => [...f.cards]);
    }
    return out;
  };

  it("flags a chain with an unmarked end", () => {
    const r = runChecks(graph([card("A"), card("B", 300), card("C", 600)], [["A", "B"], ["B", "C"]]));
    expect(kinds(r)).toEqual({ dead_end: [["C"]], start: [["A"]] });
    expect(r.paths.count).toBe(1);
    expect(r.warnings).toBe(1);
    expect(summary(r)).toBe("1 start · 1 end · 1 route · 1 to look at");
  });

  it("doesn't count marked endings as dead ends", () => {
    const cards = [card("A"), card("B", 300, 0, { tags: ["ending"] }), card("C", 300, 300, { status: "Ending" }),
      card("D", 300, 600, { tags: ["Finale"] })];
    const pairs: [string, string][] = [["A", "B"], ["A", "C"], ["A", "D"]];
    const r = runChecks(graph(cards, pairs));
    expect(kinds(r).ending).toEqual([["B"], ["C"]]);
    expect(kinds(r).dead_end).toEqual([["D"]]);
    expect(runChecks(graph(cards, pairs), null, "finale").ofKind("dead_end")[0]!.cards).toEqual(["B"]);
    expect(isEnding(card("x", 0, 0, { tags: ["Ending"] }))).toBe(true);
    expect(isEnding(card("x"), "")).toBe(false);
  });

  it("flags two openings into one chain", () => {
    let r = runChecks(graph([card("A"), card("B", 0, 300), card("M", 300, 0, { tags: ["Ending"] })], [["A", "M"], ["B", "M"]]));
    expect(kinds(r).loose_starts).toEqual([["A", "B"]]);
    expect(r.paths.count).toBe(2);
    r = runChecks(graph([card("A"), card("B", 300), card("C", 0, 300), card("D", 300, 300)], [["A", "B"], ["C", "D"]]));
    expect(kinds(r).loose_starts).toBeUndefined();
    expect(kinds(r).start).toEqual([["A"], ["C"]]);
  });

  it("reports loops", () => {
    const r = runChecks(graph([card("S"), card("A", 300), card("B", 600), card("E", 900, 0, { tags: ["Ending"] })],
      [["S", "A"], ["A", "B"], ["B", "A"], ["B", "E"]]));
    expect(kinds(r).cycle).toEqual([["A", "B"]]);
    expect(r.ofKind("cycle")[0]!.message).toBe("A → B → A");
    expect(summary(r)).toContain("plus loops");
  });

  it("lists cards without arrows on a board with arrows", () => {
    const r = runChecks(graph([card("A"), card("B", 300, 0, { tags: ["Ending"] }), card("Note", 0, 400)], [["A", "B"]]));
    expect(kinds(r).isolated).toEqual([["Note"]]);
    expect(kinds(r).dead_end).toBeUndefined();
  });

  it("has nothing to check without arrows", () => {
    const r = runChecks(graph([card("A"), card("B", 300)], []));
    expect(r.has_arrows).toBe(false);
    expect(r.findings).toEqual([]);
    expect(summary(r)).toBe("No arrows here, so there's nothing to check.");
  });

  it("checks one group", () => {
    const cards = [card("Out", -500), card("G", 0, 0, { kind: "group" }), card("P", 0, 60, { parent: "G" }),
      card("Q", 300, 60, { parent: "G" }), card("Loose", 0, 300, { parent: "G" }), card("After", 900), card("Elsewhere", 0, 900)];
    const r = runChecks(graph(cards, [["Out", "P"], ["P", "Q"], ["Q", "After"], ["Elsewhere", "After"]]), "G");
    expect(kinds(r)).toEqual({ isolated: [["Loose"]] });
    expect(r.stops).toBe(3);
  });
});

describe("route helpers", () => {
  const C = (id: string, extra: Record<string, unknown> = {}) => makeCard({ id, title: id.toUpperCase(), ...extra });

  it("give titles, steps and inherited values", () => {
    const cards = new Map([
      ["a", C("a", { title: "Start", tags: ["Dark", "x"], pov: "Mara", status: "Draft" })],
      ["b", C("b", { title: "", tags: ["dark", "Y"], characters: ["Rowan"], locations: ["Keep"] })],
      ["c", C("c", { title: "End", status: "Draft" })],
    ]);
    const key = ["a", "b+c"];
    expect(routeTitle(key, cards, null)).toBe("Start → Untitled");
    expect(routeTitle(key, cards, makeRoute({ key, name: " Main " }))).toBe("Main");
    expect(stepsText(key, cards)).toEqual(["Start", "↻ Untitled, End"]);
    const got = inheritedValues(["a", "b", "c"], cards);
    expect(got.get("tags")).toEqual(["Dark", "x", "Y"]);
    expect(got.get("characters")).toEqual(["Mara", "Rowan"]);
    expect(got.get("pov")).toEqual(["Mara"]);
    expect(got.get("locations")).toEqual(["Keep"]);
    expect(got.get("status")).toEqual(["Draft"]);
  });

  it("merge fields only when inheriting", () => {
    const cards = new Map([["a", C("a", { tags: ["Dark", "Main"] })]]);
    const own = makeRoute({ key: ["a"], tags: ["main"] });
    expect(mergedFields(own, ["a"], cards).get("tags")!.inherited).toEqual([]);
    own.inherit = true;
    expect(mergedFields(own, ["a"], cards).get("tags")).toEqual({ own: ["main"], inherited: ["Dark"] });
  });

  it("filter by names, cards and values", () => {
    const cards = new Map([["a", C("a", { title: "Harbour", tags: ["Storm"] })], ["b", C("b", { title: "Tower" })]]);
    const key = ["a", "b"];
    const data = makeRoute({ key, name: "Sea road", notes: "wet", inherit: true });
    for (const text of ["", "sea", "TOWER", "storm", "wet"]) expect(matches(text, key, cards, data)).toBe(true);
    expect(matches("castle", key, cards, data)).toBe(false);
    data.inherit = false;
    expect(matches("storm", key, cards, data)).toBe(false);
  });

  it("keep saved routes and find missing ones", () => {
    const g = graph([C("a", { x: 0 }), C("b", { x: 100 }), C("c", { x: 100, y: 200 }), C("d", { x: 200 })],
      [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]]);
    const saved = new Map([
      makeRoute({ key: ["a", "c", "d"], name: "Low road" }), makeRoute({ key: ["a", "x", "d"], name: "Gone" }),
    ].map((r) => [routeKeyId(r.key), r]));
    const listing = listRoutes(g, saved, 1);
    expect(listing.routes.map((r) => r.key)).toEqual([["a", "b", "d"], ["a", "c", "d"]]);
    expect(listing.total).toBe(2);
    expect(listing.missing.map((m) => m.name)).toEqual(["Gone"]);
  });

  it("clean route data", () => {
    const r = makeRoute({ key: ["a", "", 3, " b "], name: null, tags: "x, y,x", pov: "Mara", characters: ["mara"], inherit: "yes" });
    expect(r.key).toEqual(["a", "b"]);
    expect(r.name).toBe("");
    expect(r.tags).toEqual(["x", "y"]);
    expect([r.pov, r.characters, r.inherit]).toEqual(["mara", ["mara"], false]);
  });

  it("load older boards and skip bad entries", () => {
    expect(boardFromDict({ version: 3, cards: [] }).routes).toEqual([]);
    const raw = { version: 4, cards: [], routes: ["junk", { key: [] }, { key: ["a"], name: "One" }, { key: ["a"], name: "Dup" }, { key: ["b"] }] };
    expect(boardFromDict(raw).routes.map((r) => r.name)).toEqual(["One"]);
  });
});

describe("Markdown export", () => {
  function storyBoard() {
    const cards = [
      makeCard({ id: "open", title: "Opening", description: "It begins.", x: -600, characters: ["Mabel"], status: "Draft", notes: "Keep it short.\nReally." }),
      makeCard({ id: "act", title: "Act One", kind: "group", x: -300, y: -60 }),
      makeCard({ id: "meet", title: "Meeting", description: "They meet.", x: -280, parent: "act", pov: "Mabel", characters: ["Gus"] }),
      makeCard({ id: "choice", title: "Choice", x: 50, parent: "act" }),
      makeCard({ id: "exile", title: "Exile", x: 500, y: -150 }),
      makeCard({ id: "crown", title: "Crown", x: 500, y: 150 }),
      makeCard({ id: "note", title: "Loose note", x: -600, y: 600 }),
    ];
    const conns = ([["open", "act", ""], ["meet", "choice", ""], ["choice", "exile", "if she refuses"], ["choice", "crown", ""]] as const)
      .map(([s, t, label]) => makeConnection({ source: s, target: t, label, id: `${s}>${t}` }));
    const board = makeBoard({ cards, connections: conns });
    return { board, g: new StoryGraph(board.cards, board.connections) };
  }
  const headings = (md: string) => md.split("\n").filter((l) => l.startsWith("#"));

  it("writes a document in story order with branches", () => {
    const { board, g } = storyBoard();
    const md = exportText(board, g, "My Story");
    expect(headings(md)).toEqual(["# My Story", "## Opening", "## Act One", "### Meeting", "### Choice", "## Exile", "## Crown", "## Loose note"]);
    expect(md).toContain("*Next: Exile (if she refuses) · Crown*");
    expect(md).not.toContain("Next: Meeting");
    expect(md).toContain("**POV:** Mabel · **Characters:** Gus");
    expect(md).toContain("**Characters:** Mabel · **Status:** Draft");
    expect(md).toContain("It begins.");
    expect(md).not.toContain("> Keep it short.");
  });

  it("follows the include options", () => {
    const { board, g } = storyBoard();
    const md = exportText(board, g, "S", { descriptions: false, details: false, notes: true, next_steps: false });
    for (const s of ["It begins.", "**POV:**", "Next:"]) expect(md).not.toContain(s);
    expect(md).toContain("> Keep it short.\n> Really.");
  });

  it("nests groups in an outline", () => {
    const { board, g } = storyBoard();
    const lines = exportText(board, g, "S", { layout: OUTLINE, details: false }).split("\n");
    expect(lines).toContain("- **Act One**");
    expect(lines).toContain("  - **Meeting**: They meet.");
    expect(lines).toContain("    - Next: Exile (if she refuses) · Crown");
  });

  it("keeps the groups around a selection", () => {
    const { board, g } = storyBoard();
    expect(headings(exportText(board, g, "S", {}, ["choice", "crown"]))).toEqual(["# S", "## Act One", "### Choice", "## Crown"]);
  });

  it("uses reading order without arrows", () => {
    const board = makeBoard({ cards: [makeCard({ id: "b", title: "B", x: 300 }), makeCard({ id: "a", title: "A" }), makeCard({ id: "c", title: "C", y: 300 })] });
    const md = exportText(board, new StoryGraph(board.cards, []), "S");
    expect(md.split("\n").filter((l) => l.startsWith("## "))).toEqual(["## A", "## B", "## C"]);
  });

  it("exports a route", () => {
    const { board } = storyBoard();
    const md = exportRoute(board, ["open", "meet", "choice", "exile"], ["", "", "", "if she refuses"], "Route");
    expect(md).toContain("## 4. Exile");
    expect(md).toContain("*via “if she refuses”*");
    expect(exportRoute(board, ["open", "exile"], ["", "if she refuses"], "R", { layout: OUTLINE }))
      .toContain("2. **Exile** *(via “if she refuses”)*");
  });
});

describe("demo boards", () => {
  const load = (name: string) =>
    boardFromJson(readFileSync(fileURLToPath(new URL(`../../examples/${name}`, import.meta.url)), "utf-8"));

  it("Lantern Tide still shows its findings", () => {
    const board = load("lantern-tide.json");
    expect(board.source_version).toBe(FORMAT_VERSION);
    const g = new StoryGraph(board.cards, board.connections);
    const report = runChecks(g);
    const sets = (k: string) => report.ofKind(k).map((f) => new Set(f.cards));
    expect(sets("dead_end")).toEqual([new Set(["quarters"])]);
    expect(sets("loose_starts")).toEqual([new Set(["lantern", "coldopen"])]);
    expect(sets("cycle")).toEqual([new Set(["market", "lost", "bells"])]);
    expect(sets("isolated")).toEqual([new Set(["festival"])]);
    expect(new Set(sets("ending").flatMap((s) => [...s]))).toEqual(new Set(["relight", "flood", "keep"]));
    const intro = g.introductions();
    for (const id of ["lantern", "coldopen", "hall", "bargain"]) expect(intro.has(id)).toBe(true);
    const keys = new Set(g.routes().map((r) => routeKeyId(r.key)));
    expect(board.routes.every((r) => keys.has(routeKeyId(r.key)))).toBe(true);
    expect(board.routes.length).toBe(3);
  });

  it("Hollybank Garden is a sorting board", () => {
    const board = load("hollybank-garden.json");
    expect(board.connections).toEqual([]);
    expect(board.display.story_tools).toBe(false);
    expect(allValues(board, "tags")).toContain("Frost Tender");
    expect(board.cards.some((c) => c.tags.includes("Frost Tender"))).toBe(false);
  });

  it("the demos show strand fields and a folded group", () => {
    const lantern = load("lantern-tide.json");
    const people = lantern.strands.filter((s) => s.kind === "characters");
    expect(people.length).toBeGreaterThan(0);
    for (const s of people) expect(s.fields.map(([name]) => name)).toEqual(["Age", "Role"]);
    expect(lantern.cards.filter((c) => c.collapsed).map((c) => c.id)).toEqual(["notes"]);
    const garden = load("hollybank-garden.json");
    const bare = garden.strands.filter((s) => s.kind === "locations" && s.fields.length === 0);
    expect(bare.map((s) => s.name)).toEqual(["Orchard Corner"]); // left for Apply to…
  });
});
