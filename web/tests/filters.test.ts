// Ported from tests/test_filters.py.
import { describe, expect, it } from "vitest";
import { NONE_KEY, NONE_LABEL, cardKeys, collectOptions, matches, type Extras } from "../src/core/filters.ts";
import { makeCard } from "../src/core/model.ts";

const A = makeCard({ title: "A", tags: ["Act 1"], characters: ["Mara", "Rowan"], status: "Draft", color: "#4a7fc1" });
const B = makeCard({ title: "B", tags: ["Act 2"], characters: ["Mara"], color: "#d9822b" });
const C = makeCard({ title: "C", tags: [], characters: ["Scribe"], status: "draft", color: "#4a7fc1" });

function sel(kw: Record<string, string[]> = {}): Map<string, Set<string>> {
  const base = new Map<string, Set<string>>(["tags", "color", "characters", "locations", "status"].map((c) => [c, new Set()]));
  for (const [k, v] of Object.entries(kw)) base.set(k, new Set(v));
  return base;
}

describe("filter matching", () => {
  it("matches everything with nothing selected", () => {
    expect([A, B, C].every((c) => matches(c, sel()))).toBe(true);
  });

  it("ORs values within a category", () => {
    const s = sel({ tags: ["act 1", "act 2"] });
    expect([A, B, C].map((c) => matches(c, s))).toEqual([true, true, false]);
  });

  it("ANDs categories", () => {
    const s = sel({ tags: ["act 1", "act 2"], characters: ["rowan"] });
    expect([A, B, C].map((c) => matches(c, s))).toEqual([true, false, false]);
  });

  it("has a match-all mode for characters", () => {
    const s = sel({ characters: ["mara", "rowan"] });
    expect(matches(B, s)).toBe(true);
    expect(matches(B, s, ["characters"])).toBe(false);
    expect(matches(A, s, ["characters"])).toBe(true);
  });

  it("sets match-all per category", () => {
    const d = makeCard({ title: "D", tags: ["Act 1", "Act 2"], characters: ["Mara"], locations: ["Dock", "Mill"] });
    const s = sel({ tags: ["act 1", "act 2"], characters: ["mara", "rowan"] });
    expect([A, B, d].map((c) => matches(c, s, ["tags"]))).toEqual([false, false, true]);
    expect([A, B, d].map((c) => matches(c, s))).toEqual([true, true, true]);
    expect(matches(d, s, ["tags", "characters"])).toBe(false);
    const loc = sel({ locations: ["dock", "mill"] });
    const e = makeCard({ title: "E", locations: ["Dock"] });
    expect(matches(e, loc)).toBe(true);
    expect(matches(e, loc, ["locations"])).toBe(false);
    expect(matches(d, loc, ["locations"])).toBe(true);
  });

  it("matches all introductions", () => {
    const s = new Map([["introduces", new Set(["mara", "rowan"])]]);
    const extras: Extras = new Map([["introduces", new Map([[A.id, ["Mara", "Rowan"]], [B.id, ["Mara"]]])]]);
    expect(matches(B, s, [], extras)).toBe(true);
    expect(matches(B, s, ["introduces"], extras)).toBe(false);
    expect(matches(A, s, ["introduces"], extras)).toBe(true);
  });

  it("ignores match-all for single-value categories", () => {
    const s = sel({ status: ["draft", "done"], color: ["#4a7fc1", "#d9822b"] });
    expect(matches(A, s, ["status", "color", "pov"])).toBe(true);
  });

  it("matches nothing with match-all and (none)", () => {
    const s = sel({ tags: [NONE_KEY, "act 1"] });
    expect([A, B, C].some((c) => matches(c, s, ["tags"]))).toBe(false);
  });

  it("keeps strand cards lit by their own strand", () => {
    const card = makeCard({ title: "Act 1", kind: "strand", strand_kind: "tags", strand: "Act 1" });
    expect(matches(card, sel({ tags: ["act 1", "act 2"] }), ["tags"])).toBe(true);
  });

  it("matches empty fields with the none key", () => {
    expect(cardKeys(C, "tags")).toEqual(new Set([NONE_KEY]));
    expect(cardKeys(B, "status")).toEqual(new Set([NONE_KEY]));
    const s = sel({ status: [NONE_KEY] });
    expect(matches(B, s)).toBe(true);
    expect(matches(A, s)).toBe(false);
  });

  it("is case-insensitive", () => {
    const s = sel({ status: ["draft"] });
    expect(matches(A, s) && matches(C, s)).toBe(true);
  });
});

describe("collectOptions", () => {
  it("counts, sorts and puts (none) last", () => {
    const opts = collectOptions([A, B, C]);
    expect(opts.get("status")).toEqual([["draft", "Draft", 2], [NONE_KEY, NONE_LABEL, 1]]);
    expect(opts.get("characters")!.map(([, d]) => d)).toEqual(["Mara", "Rowan", "Scribe"]);
    expect(opts.get("characters")!.find(([k]) => k === "mara")![2]).toBe(2);
    expect(opts.get("tags")!.at(-1)).toEqual([NONE_KEY, NONE_LABEL, 1]);
    expect(opts.get("color")).toContainEqual(["#4a7fc1", "Blue", 2]);
  });
});
