// Python's string rules, checked against what Python itself answered (fixtures/strings.json).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  casefold, codePoints, compareKeys, rstrip, sortedBy, sortedStrings, splitLines, splitWords, strip,
} from "../src/core/pystr.ts";

const fixture = JSON.parse(readFileSync(fileURLToPath(new URL("../fixtures/strings.json", import.meta.url)), "utf-8"));

describe("Python string rules", () => {
  it("casefolds every character as Python does", () => {
    const wrong = (fixture.casefold as [number, string][])
      .filter(([cp, folded]) => casefold(String.fromCodePoint(cp)) !== folded)
      .map(([cp]) => cp.toString(16));
    // A few letters newer than Python's Unicode version may differ; none may today.
    expect(wrong).toEqual([]);
  });

  for (const s of fixture.samples as Record<string, unknown>[]) {
    it(`handles ${JSON.stringify(s.text)}`, () => {
      const text = s.text as string;
      expect(casefold(text)).toBe(s.casefold);
      expect(strip(text)).toBe(s.strip);
      expect(rstrip(text)).toBe(s.rstrip);
      expect(splitWords(text)).toEqual(s.split);
      expect(splitLines(text)).toEqual(s.splitlines);
      expect(codePoints(text).length).toBe(s.length);
    });
  }

  it("sorts by code point", () => {
    const words = fixture.words as string[];
    expect(sortedStrings(words)).toEqual(fixture.sorted);
    expect(sortedBy(words, casefold)).toEqual(fixture.sorted_casefold); // stable on ties
  });

  it("compares tuples element by element", () => {
    expect(compareKeys([1, "b"], [1, "a"])).toBeGreaterThan(0);
    expect(compareKeys([1], [1, 0])).toBeLessThan(0);
    expect(compareKeys([0.5, 2], [0.5, 2])).toBe(0);
  });
});

describe("Go to Card ranking and natural sorting", async () => {
  const { rank, compareNatural } = await import("../src/core/rank.ts");
  it("ranks starts, word starts and anywhere", () => {
    expect(rank("Warden Hall", "war")).toBe(0);
    expect(rank("The Warden", "war")).toBe(1);
    expect(rank("Night-watch", "watch")).toBe(1);
    expect(rank("Stewardship", "war")).toBe(2);
    expect(rank("Harbour", "war")).toBeNull();
  });
  it("sorts Card 2 before Card 10, ignoring case", () => {
    expect(["card 10", "Card 2", "apple"].sort(compareNatural)).toEqual(["apple", "Card 2", "card 10"]);
  });
});
