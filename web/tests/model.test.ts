// Ported from tests/test_model.py (file saving moves to platform/ later), plus the
// identifiers both apps must share.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  APP_ID, APP_NAME, CARD_COLORS, FORMAT_VERSION, NotABoardError, allValues, applyFields, boardFromDict,
  boardFromJson, boardToJson, boardValues, cleanFields, cleanList, cloneFragment, countValues, makeBoard,
  makeCard, makeConnection, makeRoute, mergeFields, renameInList, renameValue, routeIsBlank, type CardData,
} from "../src/core/model.ts";

const modelPy = readFileSync(fileURLToPath(new URL("../../heddle/model.py", import.meta.url)), "utf-8");

describe("board format identifiers", () => {
  it("matches the desktop app's FORMAT_VERSION", () => {
    const match = /^FORMAT_VERSION = (\d+)$/m.exec(modelPy);
    expect(match).not.toBeNull();
    expect(FORMAT_VERSION).toBe(Number(match![1]));
  });

  it("writes the same app name", () => {
    expect(APP_ID).toBe("Heddle");
    expect(APP_NAME).toBe(APP_ID);
    expect(JSON.parse(boardToJson(makeBoard())).app).toBe("Heddle");
  });
});

describe("cleanList", () => {
  it("splits, strips and dedupes case-insensitively", () => {
    expect(cleanList("Mara, rowan ,, MARA, Rowan")).toEqual(["Mara", "rowan"]);
    expect(cleanList(["a", " b ", 3, null, "A"])).toEqual(["a", "b"]);
    expect(cleanList(null)).toEqual([]);
    expect(cleanList(42)).toEqual([]);
  });
});

describe("loading older or hand-written files", () => {
  it("splits comma strings and recovers custom colors", () => {
    const board = boardFromDict({ cards: [{ id: "c1", title: "Old", characters: "Mara, Rowan", color: "#123456" }] });
    expect(board.cards[0]!.characters).toEqual(["Mara", "Rowan"]);
    expect(board.custom_colors).toEqual(["#123456"]);
  });

  it("doesn't check the app name", () => {
    const board = boardFromDict({ app: "Something else", version: 12, cards: [{ id: "a", title: "Rowan" }] });
    expect(board.cards.map((c) => c.title)).toEqual(["Rowan"]);
  });

  it("ignores unknown keys", () => {
    const board = boardFromDict({ cards: [{ title: "x", from_the_future: 1 }], extra: true });
    expect(board.cards[0]!.title).toBe("x");
  });

  it("refuses something that isn't a board", () => {
    expect(() => boardFromDict({ nope: [] })).toThrow(NotABoardError);
    expect(() => boardFromDict([])).toThrow("This file is not a Heddle board.");
    expect(() => boardFromJson("{not json")).toThrow(SyntaxError);
  });
});

describe("damaged values are coerced", () => {
  it("coerces card fields", () => {
    const c = makeCard({
      id: null, title: 7, description: null, color: "red", status: ["x"], notes: { a: 1 }, parent: 3,
      x: "12", y: NaN, width: Infinity, height: true, tags: null, kind: null,
      arrange_by_color: "false", arrange_vertical: 1, arrange_grid: "yes",
    });
    expect(c.id).toMatch(/^[0-9a-f]{12}$/);
    expect([c.title, c.description, c.color, c.status, c.notes, c.parent]).toEqual(["7", "", CARD_COLORS[0], "", "", "3"]);
    expect([c.x, c.y, c.width, c.height]).toEqual([0, 0, 0, 0]);
    expect(c.tags).toEqual([]);
    expect(c.kind).toBe("card");
    expect([c.arrange_by_color, c.arrange_vertical, c.arrange_grid]).toEqual([false, false, false]);
    expect(makeCard({ color: "#ABCDEF" }).color).toBe("#abcdef");
  });

  it("coerces arrow fields", () => {
    const e = makeConnection({ source: null, target: 5, label: null, id: "" });
    expect([e.source, e.target, e.label]).toEqual(["", "5", ""]);
    expect(e.id).toMatch(/^[0-9a-f]{12}$/);
    expect(() => makeConnection({ source: "a" })).toThrow(TypeError);
  });

  it("repairs duplicate ids and bad lists", () => {
    const b = boardFromDict({
      cards: [{ id: "d" }, { id: "d" }], connections: "junk", custom_colors: ["#123456", "red", 5],
    });
    expect(new Set(b.cards.map((c) => c.id)).size).toBe(2);
    expect(b.connections).toEqual([]);
    expect(b.custom_colors).toEqual(["#123456"]);
    expect(b.load_notes).toEqual(["1 card given a new id (the id was used twice)"]);
  });
});

describe("rename and merge", () => {
  const cards = (): CardData[] => [
    makeCard({ characters: ["Rowan", "Bob"], status: "Draft", tags: ["intro"] }),
    makeCard({ characters: ["rowan"], status: "draft" }),
    makeCard({ characters: ["Mara", "Rowan2"], status: "Final" }),
  ];

  it("is case-insensitive and only touches matches", () => {
    const cs = cards();
    const changed = renameValue(cs, "characters", "ROWAN", "Rówan");
    expect(cs.map((c) => c.characters)).toEqual([["Rówan", "Bob"], ["Rówan"], ["Mara", "Rowan2"]]);
    expect(changed.length).toBe(2);
  });

  it("merges into an existing value with the typed spelling", () => {
    const cs = cards();
    renameValue(cs, "characters", "Bob", "ROWAN");
    expect(cs[0]!.characters).toEqual(["ROWAN"]);
    expect(cs[1]!.characters).toEqual(["ROWAN"]);
  });

  it("can change only the case", () => {
    const cs = cards();
    renameValue(cs, "characters", "rowan", "ROWAN");
    expect(cs[0]!.characters[0]).toBe("ROWAN");
    expect(cs[1]!.characters).toEqual(["ROWAN"]);
  });

  it("renames a status", () => {
    const cs = cards();
    expect(renameValue(cs, "status", "DRAFT", "Revised").length).toBe(2);
    expect(cs.map((c) => c.status)).toEqual(["Revised", "Revised", "Final"]);
  });

  it("does nothing for no-ops and refuses other fields", () => {
    const cs = cards();
    expect(renameValue(cs, "tags", "missing", "x")).toEqual([]);
    expect(renameValue(cs, "tags", "intro", "   ")).toEqual([]);
    expect(() => renameValue(cs, "color", "a", "b")).toThrow();
  });

  it("merges in a plain list", () => {
    expect(renameInList(["Forest", "Lake", "forest2"], "lake", "FOREST")).toEqual(["FOREST", "forest2"]);
  });
});

describe("counting values", () => {
  it("follows the rules", () => {
    const cs = [makeCard({ tags: ["Plot", "plot", "Act"] }), makeCard({ tags: ["PLOT"] }), makeCard({ status: "Draft" })];
    expect([...countValues(cs, "tags", ["act", "Saved"])]).toEqual([
      ["plot", ["Plot", 2]], ["act", ["Act", 1]], ["saved", ["Saved", 0]],
    ]);
    expect([...countValues(cs, "status")]).toEqual([["draft", ["Draft", 1]]]);
  });

  it("keeps integer-like values in the order they were found", () => {
    const cs = [makeCard({ tags: ["10", "Plot", "7"] })];
    expect([...countValues(cs, "tags").keys()]).toEqual(["10", "plot", "7"]);
  });

  it("combines cards and extras, first spelling wins", () => {
    const cs = [makeCard({ tags: ["b", "A"] }), makeCard({ tags: ["a", "c"] })];
    expect(boardValues(cs, "tags", ["C", "d"])).toEqual(["A", "b", "c", "d"]);
    expect(boardValues(cs, "status")).toEqual([]);
  });
});

describe("saving", () => {
  it("round-trips saved values", () => {
    const b = makeBoard({ cards: [makeCard({ tags: ["x"] })], saved_values: { locations: ["Forest", "forest"] } });
    const loaded = boardFromJson(boardToJson(b));
    expect(loaded.saved_values).toEqual({ locations: ["Forest"] });
    expect(allValues(loaded, "locations")).toEqual(["Forest"]);
    expect(allValues(loaded, "tags")).toEqual(["x"]);
  });

  it("round-trips a whole board unchanged", () => {
    const b = boardFromDict({
      cards: [{ id: "a", title: "A", tags: ["t"], x: 12.5 }, { id: "g", kind: "group", collapsed: true }],
      connections: [{ id: "e", source: "a", target: "g", style: "dashed", label: "on" }],
      routes: [{ key: ["a"], name: "R" }],
      strands: [{ kind: "tags", name: "t", fields: [{ name: "Age", value: "3" }], picture: "p.png" }],
    });
    const again = boardFromJson(boardToJson(b));
    expect(boardToJson(again)).toBe(boardToJson(b));
  });

  it("doesn't save blank routes", () => {
    expect(routeIsBlank(makeRoute({ key: ["a"] }))).toBe(true);
    expect(routeIsBlank(makeRoute({ key: ["a"], inherit: true }))).toBe(false);
    const b = makeBoard({ routes: [makeRoute({ key: ["a", "b"], name: "Only way" }), makeRoute({ key: ["b", "a"] })] });
    expect((JSON.parse(boardToJson(b)).routes as { key: string[] }[]).map((r) => r.key)).toEqual([["a", "b"]]);
  });
});

describe("strand fields", () => {
  it("cleans fields", () => {
    expect(cleanFields([{ name: " Age ", value: "4\n1" }, ["age", "x"], { name: "" }, ["Home", "Dock"], 5]))
      .toEqual([["Age", "4 1"], ["Home", "Dock"]]);
  });

  it("merges and applies fields", () => {
    expect(mergeFields([["Age", ""], ["Home", "Dock"]], [["age", "41"], ["Eyes", "grey"]]))
      .toEqual([["Age", "41"], ["Home", "Dock"], ["Eyes", "grey"]]);
    expect(applyFields([["Age", "41"], ["Eyes", "grey"]], [["age", ""]])).toEqual([["age", ""], ["Eyes", ""]]);
    expect(applyFields([["Age", "41"], ["Eyes", "grey"]], [["age", ""]], ["eyes"], true))
      .toEqual([["age", ""], ["Eyes", "grey"]]);
  });
});

describe("cloneFragment", () => {
  it("gives fresh ids and keeps the fragment's own links", () => {
    const frag = makeBoard({
      cards: [makeCard({ id: "g", kind: "group" }), makeCard({ id: "a", parent: "g" }), makeCard({ id: "b", parent: "outside" })],
      connections: [makeConnection({ id: "e", source: "a", target: "b", style: "dotted" }),
                    makeConnection({ id: "f", source: "a", target: "zz" })],
    });
    const out = cloneFragment(frag, new Set(["outside"]));
    const [g, a, b] = out.cards;
    expect(new Set([g!.id, a!.id, b!.id, "g", "a", "b"]).size).toBe(6);
    expect(a!.parent).toBe(g!.id);
    expect(b!.parent).toBe("outside");
    expect(cloneFragment(frag).cards[2]!.parent).toBe("");
    expect(out.connections.length).toBe(1);
    expect(out.connections[0]).toMatchObject({ source: a!.id, target: b!.id, style: "dotted" });
  });
});
