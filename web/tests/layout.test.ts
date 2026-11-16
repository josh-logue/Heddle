// Ported from tests/test_layout.py and tests/test_layout_stable.py.
import { describe, expect, it } from "vitest";
import { H_GAP, ROW_GAP, V_GAP, arrange, makeNode, type Node, type Positions } from "../src/core/layout.ts";

const N = (id: string, x = 0, y = 0, color = "", w = 100, h = 50): Node => makeNode(id, w, h, { x, y, color });
const at = (p: Positions, id: string) => p.get(id)!;
const obj = (p: Positions) => Object.fromEntries(p);

describe("arrange", () => {
  it("runs a chain left to right with gaps", () => {
    const p = arrange([N("a"), N("b"), N("c")], [["a", "b"], ["b", "c"]]);
    expect(obj(p)).toEqual({ a: [0, 0], b: [100 + H_GAP, 0], c: [2 * (100 + H_GAP), 0] });
  });

  it("stacks branches and centres the merge", () => {
    const p = arrange([N("a"), N("b", 0, 0), N("c", 0, 100), N("d")], [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]]);
    expect(at(p, "b")[0]).toBe(at(p, "c")[0]);
    expect(at(p, "c")[1]).toBe(at(p, "b")[1] + 50 + V_GAP);
    expect(at(p, "d")[0]).toBeGreaterThan(at(p, "b")[0]);
    expect(Math.abs(at(p, "d")[1] + 25 - (at(p, "b")[1] + at(p, "c")[1] + 50) / 2)).toBeLessThan(1e-6);
  });

  it("tolerates cycles", () => {
    const p = arrange([N("a"), N("b"), N("c")], [["a", "b"], ["b", "c"], ["c", "a"]]);
    expect(new Set(p.keys())).toEqual(new Set(["a", "b", "c"]));
    expect(new Set([...p.values()].map(([x]) => x)).size).toBe(3);
  });

  it("ignores self-loops and unknown ids", () => {
    const p = arrange([N("a"), N("b")], [["a", "a"], ["a", "zzz"], ["a", "b"]]);
    expect(at(p, "b")[0]).toBe(100 + H_GAP);
  });

  it("stacks separate chains in their current order", () => {
    const p = arrange([N("x", 0, 500), N("y", 0, 500), N("a"), N("b")], [["a", "b"], ["x", "y"]]);
    expect(at(p, "a")[1]).toBe(0);
    expect(at(p, "x")[1]).toBe(50 + ROW_GAP);
  });

  it("transposes when vertical", () => {
    const p = arrange([N("a"), N("b"), N("c")], [["a", "b"], ["b", "c"]], { vertical: true });
    expect(obj(p)).toEqual({ a: [0, 0], b: [0, 50 + H_GAP], c: [0, 2 * (50 + H_GAP)] });
  });

  it("puts each colour on its own row", () => {
    const nodes = [N("intro", 0, 0, "p"), N("elect", 0, 0, "o"), N("adjust", 0, 0, "p"), N("pack", 0, 0, "r")];
    const p = arrange(nodes, [["intro", "elect"], ["elect", "adjust"], ["adjust", "pack"]], { byColor: true });
    expect(at(p, "intro")[1]).toBe(0);
    expect(at(p, "adjust")[1]).toBe(0);
    expect(at(p, "elect")[1]).toBe(50 + V_GAP);
    expect(at(p, "pack")[1]).toBe(2 * (50 + V_GAP));
    const xs = ["intro", "elect", "adjust", "pack"].map((i) => at(p, i)[0]);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    expect(new Set(xs).size).toBe(4);
  });
});

function crossed(p: Positions, edges: [string, string][]): number {
  let n = 0;
  edges.forEach(([a1, b1], k) => {
    for (const [a2, b2] of edges.slice(k + 1)) {
      if (at(p, a1)[0] === at(p, a2)[0] && at(p, b1)[0] === at(p, b2)[0]
          && (at(p, a1)[1] - at(p, a2)[1]) * (at(p, b1)[1] - at(p, b2)[1]) < 0) n++;
    }
  });
  return n;
}

describe("fewer crossed arrows", () => {
  it("untangles a simple crossing", () => {
    const edges: [string, string][] = [["a", "c"], ["b", "d"]];
    const p = arrange([N("a", 0, 0), N("b", 0, 100), N("d", 0, 0), N("c", 0, 100)], edges);
    expect(crossed(p, edges)).toBe(0);
    expect(at(p, "c")[1]).toBeLessThan(at(p, "d")[1]);
  });

  it("untangles branches across several steps", () => {
    const nodes = [N("s", 0, 0), N("a1", 0, 0), N("b1", 0, 100), N("b2", 0, 0), N("a2", 0, 100),
      N("a3", 0, 0), N("b3", 0, 100), N("end", 0, 0)];
    const edges: [string, string][] = [["s", "a1"], ["s", "b1"], ["a1", "a2"], ["b1", "b2"], ["a2", "a3"],
      ["b2", "b3"], ["a3", "end"], ["b3", "end"]];
    expect(crossed(arrange(nodes, edges), edges)).toBe(0);
    expect(crossed(arrange(nodes.map((n) => ({ ...n, color: "x" })), edges, { byColor: true }), edges)).toBe(0);
  });

  it("keeps a clean manual order", () => {
    const p = arrange([N("s"), N("lower", 0, 100), N("upper", 0, 0)], [["s", "upper"], ["s", "lower"]]);
    expect(at(p, "upper")[1]).toBeLessThan(at(p, "lower")[1]);
  });

  it("gives the same layout for cards at the very same spot", () => {
    // Python needed this test because its string hashing changes per run; here the
    // answer must simply not depend on anything but the input order.
    const ids = ["start", "left", "right", "mid", "tail", "spur", "end"];
    const edges: [string, string][] = [["start", "left"], ["start", "right"], ["left", "mid"], ["right", "mid"],
      ["mid", "tail"], ["mid", "spur"], ["tail", "end"], ["spur", "end"]];
    const run = () => JSON.stringify([...arrange(ids.map((i) => makeNode(i, 230, 100)), edges)]);
    expect(run()).toBe(run());
  });
});

describe("cards without arrows", () => {
  const loose = () => [0, 1, 2, 3, 4].map((k) => N(String(k), k * 10));

  it("follow the arrow direction", () => {
    const h = arrange(loose(), []);
    expect(new Set([...h.values()].map(([, y]) => y))).toEqual(new Set([0]));
    expect([0, 1, 2, 3, 4].map((k) => at(h, String(k))[0])).toEqual([0, 130, 260, 390, 520]);
    const v = arrange(loose(), [], { vertical: true });
    expect(new Set([...v.values()].map(([x]) => x))).toEqual(new Set([0]));
    expect([0, 1, 2, 3, 4].map((k) => at(v, String(k))[1])).toEqual([0, 80, 160, 240, 320]);
  });

  it("wrap into a grid", () => {
    const g = arrange(loose(), [], { grid: true });
    expect(at(g, "2")).toEqual([260, 0]);
    expect(at(g, "3")).toEqual([0, 80]);
    const gv = arrange(loose(), [], { grid: true, vertical: true });
    expect(at(gv, "2")).toEqual([0, 160]);
    expect(at(gv, "3")).toEqual([130, 0]);
  });

  it("go after the chains", () => {
    const p = arrange([N("a"), N("b", 200), N("x", 0, 500), N("y", 50, 500)], [["a", "b"]]);
    expect(at(p, "x")).toEqual([0, 50 + ROW_GAP]);
    expect(at(p, "y")).toEqual([100 + V_GAP, 50 + ROW_GAP]);
  });

  it("split by colour", () => {
    const p = arrange([N("r1", 0, 0, "red"), N("b1", 1, 0, "blue"), N("r2", 2, 0, "red")], [], { byColor: true });
    expect(at(p, "r1")[1]).toBe(0);
    expect(at(p, "r2")[1]).toBe(0);
    expect(at(p, "b1")[1]).toBe(50 + V_GAP);
  });
});
