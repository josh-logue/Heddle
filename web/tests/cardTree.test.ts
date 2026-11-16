// The Card List's rows (core/cardTree.ts).
import { describe, expect, it } from "vitest";
import { cardListRows, cardListSummary, narrowed, type CardListOptions } from "../src/core/cardTree.ts";
import { StoryGraph } from "../src/core/graph.ts";
import { boardFromDict } from "../src/core/model.ts";

const board = boardFromDict({
  cards: [
    { id: "g", title: "Act One", kind: "group" }, { id: "b", title: "Card 10", parent: "g", x: 0, y: 0 },
    { id: "a", title: "Card 2", parent: "g", x: 300, y: 0, description: "The lamp goes out" },
    { id: "z", title: "Alone", x: 0, y: 900 },
  ],
  connections: [{ source: "b", target: "a" }],
});
const graph = new StoryGraph(board.cards, board.connections);
const opts = (o: Partial<CardListOptions> = {}): CardListOptions => ({
  sort: "story", storyTools: true, needle: "", fullText: false, strandInfo: new Map(), dimmed: new Set(), hideDimmed: false, ...o,
});
const ids = (o: Partial<CardListOptions> = {}) => cardListRows(graph, opts(o)).map((r) => `${"·".repeat(r.depth)}${r.id}`);

describe("Card List rows", () => {
  it("follow the groups, in story order, top to bottom or A–Z", () => {
    expect(ids()).toEqual(["g", "·b", "·a", "z"]);
    expect(ids({ sort: "position" })).toEqual(["g", "·b", "·a", "z"]);
    expect(ids({ sort: "title" })).toEqual(["g", "·a", "·b", "z"]); // Card 2 before Card 10
  });

  it("narrow to matches, keeping the groups round them, greyed", () => {
    const rows = cardListRows(graph, opts({ needle: "card 2" }));
    expect(rows.map((r) => [r.id, r.muted])).toEqual([["g", true], ["a", false]]);
    expect(ids({ needle: "lamp" })).toEqual([]);
    const full = cardListRows(graph, opts({ needle: "lamp", fullText: true }));
    expect(full.map((r) => r.id)).toEqual(["g", "a"]);
    expect(full[1]!.found).toEqual(["Description", "The lamp goes out"]);
  });

  it("grey or hide what the filter dims", () => {
    expect(cardListRows(graph, opts({ dimmed: new Set(["z"]) })).find((r) => r.id === "z")!.muted).toBe(true);
    expect(ids({ dimmed: new Set(["z", "g", "a"]), hideDimmed: true })).toEqual(["g", "·b"]);
  });

  it("sum up what's listed", () => {
    expect(cardListSummary(cardListRows(graph, opts()), board.cards)).toBe("3 cards · 1 group");
    expect(cardListSummary(cardListRows(graph, opts({ needle: "alone" })), board.cards)).toBe("1 of 3 cards");
    expect([...narrowed(new Map([["", ["g"]], ["g", ["a"]]]), ["a"])].sort()).toEqual(["a", "g"]);
  });
});
