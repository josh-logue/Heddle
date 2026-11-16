// Ported from tests/test_graph.py, and the graph half of tests/test_routes.py.
import { describe, expect, it } from "vitest";
import { StoryGraph, longestPathLayers } from "../src/core/graph.ts";
import { makeCard, makeConnection, type CardData } from "../src/core/model.ts";

function card(id: string, x = 0, y = 0, parent = "", group = false): CardData {
  return makeCard({ id, title: id, x, y, parent, kind: group ? "group" : "card" });
}

function graph(cards: CardData[], pairs: [string, string][]): StoryGraph {
  return new StoryGraph(cards, pairs.map(([s, t]) => makeConnection({ source: s, target: t, id: `${s}>${t}` })));
}

const set = (...ids: string[]) => new Set(ids);

describe("StoryGraph", () => {
  it("follows a chain", () => {
    const g = graph([card("A"), card("B", 300), card("C", 600)], [["A", "B"], ["B", "C"]]);
    expect(g.downstream("A")).toEqual(set("B", "C"));
    expect(g.upstream("C")).toEqual(set("A", "B"));
    expect(g.downstream("C")).toEqual(set());
    expect(g.arrowOrder()).toEqual(["A", "B", "C"]);
    expect(g.countPaths()).toEqual({ count: 1, has_cycles: false });
    expect(g.cycles()).toEqual([]);
  });

  it("branches and merges", () => {
    const g = graph([card("A"), card("B", 300, 200), card("C", 300, 0), card("D", 600)],
      [["A", "B"], ["A", "C"], ["B", "D"], ["C", "D"]]);
    expect(g.countPaths().count).toBe(2);
    expect(g.arrowOrder()).toEqual(["A", "C", "B", "D"]); // same step: top to bottom
    expect(g.upstream("D")).toEqual(set("A", "B", "C"));
  });

  it("finds a cycle and counts it once", () => {
    const g = graph([card("A"), card("B", 300), card("C", 600), card("D", 900)],
      [["A", "B"], ["B", "C"], ["C", "A"], ["C", "D"]]);
    expect(g.cycles()).toEqual([["A", "B", "C"]]);
    expect(g.countPaths()).toEqual({ count: 1, has_cycles: true });
    expect(g.downstream("A").has("A")).toBe(true);
    expect(g.arrowOrder().at(-1)).toBe("D");
  });

  it("enters a group at its first cards and leaves from its last", () => {
    const cards = [card("X", 0), card("G", 200, 0, "", true), card("P", 220, 50, "G"),
      card("Q", 520, 50, "G"), card("Y", 900)];
    const g = graph(cards, [["X", "G"], ["P", "Q"], ["G", "Y"]]);
    expect(g.nodes()).not.toContain("G");
    expect(g.succ.get("X")).toEqual(["P"]);
    expect(g.pred.get("Y")).toEqual(["Q"]);
    expect(g.downstream("X")).toEqual(set("P", "Q", "Y"));
    expect(g.arrowOrder()).toEqual(["X", "P", "Q", "Y"]);
    expect(g.downstream("G")).toEqual(set("Y"));
    expect(g.upstream("G")).toEqual(set("X"));
    expect(g.arrowsWithin(["X", "P"])).toEqual(set("X>G"));
    expect(g.arrowsWithin(["P", "Q", "Y"])).toEqual(set("P>Q", "G>Y"));
  });

  it("leads into every card of a group without inner arrows", () => {
    const g = graph([card("X"), card("G", 200, 0, "", true), card("P", 220, 0, "G"), card("Q", 220, 200, "G")], [["X", "G"]]);
    expect([...g.succ.get("X")!].sort()).toEqual(["P", "Q"]);
    expect(g.countPaths().count).toBe(2);
  });

  it("expands nested groups down to cards", () => {
    const cards = [card("X"), card("G", 200, 0, "", true), card("H", 220, 0, "G", true),
      card("P", 240, 20, "H"), card("Q", 600, 0, "G"), card("Y", 1000)];
    const g = graph(cards, [["X", "G"], ["P", "Q"], ["G", "Y"]]);
    expect(g.succ.get("X")).toEqual(["P"]);
    expect(g.pred.get("Y")).toEqual(["Q"]);
    expect(g.containersOf(["P"])).toEqual(set("H", "G"));
    expect(g.contents("G")).toEqual(set("H", "P", "Q"));
  });

  it("enters a group that is one big loop at its top-left card", () => {
    const g = graph([card("X"), card("G", 200, 0, "", true), card("P", 220, 0, "G"), card("Q", 220, 300, "G")],
      [["X", "G"], ["P", "Q"], ["Q", "P"]]);
    expect(g.succ.get("X")).toEqual(["P"]);
    expect(g.cycles()).toEqual([["P", "Q"]]);
  });

  it("treats an empty group as an ordinary stop", () => {
    const g = graph([card("A"), card("E", 300, 0, "", true), card("B", 600)], [["A", "E"], ["E", "B"]]);
    expect(g.nodes()).toContain("E");
    expect(g.arrowOrder()).toEqual(["A", "E", "B"]);
  });

  it("uses reading order without arrows", () => {
    const g = graph([card("B", 300, 0), card("A", 0, 0), card("C", 0, 200)], []);
    expect(g.arrowOrder()).toEqual(["A", "B", "C"]);
    expect(g.countPaths().count).toBe(0);
    expect(g.routes()).toEqual([]);
  });

  it("ignores bad arrows", () => {
    const g = new StoryGraph([card("A"), card("B", 300)], [
      makeConnection({ source: "A", target: "B", id: "1" }), makeConnection({ source: "A", target: "B", id: "2" }),
      makeConnection({ source: "A", target: "A", id: "3" }), makeConnection({ source: "A", target: "zzz", id: "4" }),
    ]);
    expect([...g.arrows.keys()]).toEqual(["1"]);
    expect(g.succ.get("A")).toEqual(["B"]);
  });

  it("lists separate chains in reading order", () => {
    const g = graph([card("C", 0, 400), card("D", 300, 400), card("A", 0, 0), card("B", 300, 0)], [["A", "B"], ["C", "D"]]);
    expect(g.arrowOrder()).toEqual(["A", "B", "C", "D"]);
  });

  it("drops back-edges when layering", () => {
    const succ = new Map([["a", ["b"]], ["b", ["c"]], ["c", ["a"]]]);
    expect([...longestPathLayers(["a", "b", "c"], succ, (i) => i).values()].sort()).toEqual([0, 1, 2]);
  });

  it("handles many characters at once (more than 64 introductions)", () => {
    const names = Array.from({ length: 80 }, (_, k) => `C${k}`);
    const a = makeCard({ id: "a", characters: names.slice(0, 70) });
    const b = makeCard({ id: "b", x: 300, characters: names });
    const g = new StoryGraph([a, b], [makeConnection({ source: "a", target: "b" })]);
    expect(g.introductions().get("b")).toEqual(names.slice(70));
  });
});

describe("routes", () => {
  const C = (id: string, extra: Record<string, unknown> = {}) => makeCard({ id, title: id.toUpperCase(), ...extra });
  const diamond = () => graph([C("a", { x: 0 }), C("b", { x: 100 }), C("c", { x: 100, y: 200 }), C("d", { x: 200 })],
    [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]]);

  it("match the count, in reading order", () => {
    const g = diamond();
    const keys = g.routes().map((r) => r.key);
    expect(keys).toEqual([["a", "b", "d"], ["a", "c", "d"]]);
    expect(keys.length).toBe(g.countPaths().count);
  });

  it("treat a loop as one stop", () => {
    const g = graph(["a", "b", "c", "d"].map((i, n) => C(i, { x: n * 100 })), [["a", "b"], ["b", "c"], ["c", "b"], ["c", "d"]]);
    const [route, ...rest] = g.routes();
    expect(rest).toEqual([]);
    expect(route!.key).toEqual(["a", "b+c", "d"]);
    expect(route!.stops[1]).toEqual(["b", "c"]);
    expect(route!.hasLoop).toBe(true);
  });

  it("go through groups' cards", () => {
    const cards = [C("a", { x: 0 }), makeCard({ id: "g", kind: "group" }), C("m", { x: 100, parent: "g" }),
      C("n", { x: 200, parent: "g" }), C("z", { x: 300 })];
    expect(graph(cards, [["a", "g"], ["m", "n"], ["g", "z"]]).routes().map((r) => r.key)).toEqual([["a", "m", "n", "z"]]);
  });

  it("respect a limit and handle long chains without recursion", () => {
    const cards = [C("s")];
    const arrows: [string, string][] = [];
    let prev = "s";
    for (let k = 0; k < 6; k++) {
      cards.push(C(`u${k}`, { x: k * 3 + 1 }), C(`d${k}`, { x: k * 3 + 1, y: 9 }), C(`j${k}`, { x: k * 3 + 2 }));
      arrows.push([prev, `u${k}`], [prev, `d${k}`], [`u${k}`, `j${k}`], [`d${k}`, `j${k}`]);
      prev = `j${k}`;
    }
    const g = graph(cards, arrows);
    expect(g.routes().length).toBe(64);
    expect(g.countPaths().count).toBe(64);
    expect(g.routes(10).length).toBe(10);
    const chain = Array.from({ length: 3000 }, (_, i) => C(`c${i}`, { x: i }));
    const long = graph(chain, Array.from({ length: 2999 }, (_, i) => [`c${i}`, `c${i + 1}`] as [string, string]));
    expect(long.routes()[0]!.cards.length).toBe(3000);
  });

  it("check a key is still a complete route", () => {
    const g = diamond();
    expect(g.routeForKey(["a", "b", "d"])!.key).toEqual(["a", "b", "d"]);
    for (const key of [["a", "b"], ["b", "d"], ["a", "d"], ["a", "x", "d"], []]) expect(g.routeForKey(key)).toBeNull();
  });

  it("walk only their own steps", () => {
    const g = new StoryGraph([C("a"), C("b", { x: 100 }), C("c", { x: 200 })], [
      makeConnection({ source: "a", target: "b", id: "ab" }), makeConnection({ source: "b", target: "c", id: "bc" }),
      makeConnection({ source: "a", target: "c", id: "ac" })]);
    expect(g.routeArrows(g.routeForKey(["a", "b", "c"])!)).toEqual(set("ab", "bc"));
    expect(g.routeArrows(g.routeForKey(["a", "c"])!)).toEqual(set("ac"));
  });
});
