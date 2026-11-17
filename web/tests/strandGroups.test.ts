// Strand groups in the core and store: loaded, saved, kept in step with renames and
// removals, and undoable (heddle/scene_strands.py; the panels come later).
import { describe, expect, it } from "vitest";
import { boardFromDict, boardFromJson, cleanStrandGroups, groupHas, makeStrandGroup } from "../src/core/model.ts";
import { BoardStore } from "../src/board/store.ts";
import { fakeMeasurer } from "../src/board/text.ts";

const store = (raw: Record<string, unknown>) => new BoardStore(boardFromDict(raw), fakeMeasurer());
const groups = (s: BoardStore) => s.state.strand_groups.map((g) => [g.kind, g.name, [...g.members]]);

describe("strand groups", () => {
  it("are cleaned like the desktop's", () => {
    const g = makeStrandGroup({ kind: "characters", name: " The\nFamily ", members: [" Rowan ", "Mabel", "rowan", 3] });
    expect([g.name, g.members, g.description]).toEqual(["The Family", ["Rowan", "Mabel"], ""]);
    expect(makeStrandGroup({ name: "x", members: "a, b" }).members).toEqual([]); // only a real list
    expect(groupHas(g, " ROWAN ")).toBe(true);
    expect(cleanStrandGroups([{ kind: "tags", name: "A" }, { kind: "tags", name: "a" }, "junk"]).length).toBe(1);
  });

  it("keep their members on the board and survive saving", () => {
    const s = store({ cards: [], strand_groups: [{ kind: "locations", name: "Wards", members: ["East Ward"] }] });
    expect(s.allValues("locations")).toEqual(["East Ward"]);
    expect(boardFromJson(s.toJson()).strand_groups).toEqual(s.state.strand_groups);
  });

  it("follow a strand's rename, merging duplicates, as one undo step", () => {
    const s = store({
      cards: [{ id: "a", characters: ["Rowan", "Ro"] }],
      strand_groups: [{ kind: "characters", name: "Family", members: ["Rowan", "Ro"] },
                      { kind: "characters", name: "Council", members: ["Ro", "Greta"] }],
    });
    s.renameStrand("characters", "ro", "Rowan");
    expect(groups(s)).toEqual([["characters", "Family", ["Rowan"]], ["characters", "Council", ["Rowan", "Greta"]]]);
    expect(s.allValues("characters")).not.toContain("Ro");
    s.undo();
    expect(groups(s)[1]).toEqual(["characters", "Council", ["Ro", "Greta"]]);
  });

  it("hold back unused members from Remove Unused unless asked, and lose removed ones", () => {
    const s = store({
      cards: [{ id: "a", tags: ["used"] }], saved_values: { tags: ["spare"] },
      strand_groups: [{ kind: "tags", name: "Moods", members: ["grim"] }],
    });
    expect(s.unusedStrands()).toEqual([{ tags: ["spare"] }, { tags: ["grim"] }]);
    expect(s.unusedSaved()).toEqual({ tags: ["spare"] });
    expect(s.removeSaved({ tags: ["grim"] })).toBe(1);
    expect(groups(s)).toEqual([["tags", "Moods", []]]); // the group stays, empty
    expect(s.allValues("tags")).not.toContain("grim");
    s.undo();
    expect(groups(s)).toEqual([["tags", "Moods", ["grim"]]]);
  });
});

describe("strand group operations", () => {
  const board = () => store({
    cards: [{ id: "a", characters: ["Rowan"] }, { id: "b", x: 400 },
            { id: "s", x: 800, kind: "strand", strand_kind: "characters", strand: "Greta" }],
  });

  it("make, rename, fill and delete groups, each one undo step", () => {
    const s = board();
    expect(s.createStrandGroup("characters", "Family", ["ROWAN", "Mabel", "rowan"])!.members).toEqual(["Rowan", "Mabel"]);
    expect(s.createStrandGroup("characters", "family")).toBeNull(); // taken
    expect(s.createStrandGroup("characters", "  ")).toBeNull();
    expect(s.allValues("characters")).toContain("Mabel");           // kept by the group
    expect(s.updateStrandGroup("characters", "Family", { name: "Kin", description: "Blood" })).toBe(true);
    expect(s.updateStrandGroup("characters", "Kin", { name: "Kin" })).toBe(false); // no change
    expect(s.addToStrandGroup("characters", "kin", ["Greta", "rowan"])).toBe(1);
    expect(s.removeFromStrandGroup("characters", "Kin", ["MABEL", "Nobody"])).toBe(1);
    expect(s.allValues("characters")).toContain("Mabel");           // left the group: kept as saved
    expect(groups(s)).toEqual([["characters", "Kin", ["Rowan", "Greta"]]]);
    s.undo();
    expect(groups(s)).toEqual([["characters", "Kin", ["Rowan", "Mabel", "Greta"]]]);
    expect(s.deleteStrandGroup("characters", "KIN")).toBe(true);
    expect(s.state.strand_groups).toEqual([]);
    expect(s.groupsWith("characters", "Rowan")).toEqual([]);
  });

  it("lists groups alphabetically and offers only tag, character and location ones", () => {
    const s = board();
    s.createStrandGroup("characters", "Zeal", ["Rowan"]);
    s.createStrandGroup("characters", "2024", ["Rowan"]);
    s.createStrandGroup("status", "Done", ["Final"]);
    expect(s.groupsOf("characters").map((g) => g.name)).toEqual(["2024", "Zeal"]);
    expect(s.groupsWith("characters", "rowan").length).toBe(2);
    const choices = s.strandGroupChoices();
    expect(Object.keys(choices)).toEqual(["characters"]);
    expect([...choices.characters!.keys()]).toEqual(["2024", "Zeal"]);
  });

  it("add a group's strands to cards, skipping strand cards, and say what happened", () => {
    const s = board();
    s.createStrandGroup("characters", "Family", ["Rowan", "Mabel"]);
    s.createStrandGroup("locations", "Empty");
    s.createStrandGroup("status", "Done", ["Final"]);
    expect(s.addStrandGroupToCards(["a", "b", "s"], "characters", "family"))
      .toEqual([2, "Added the strand group “Family” to 2 cards"]);
    expect(s.card("a")!.characters).toEqual(["Rowan", "Mabel"]);
    expect(s.card("s")!.characters).toEqual([]);
    expect(s.addStrandGroupToCards(["a"], "characters", "Family")).toEqual([0, "That card already had the strand group “Family”"]);
    expect(s.addStrandGroupToCards(["a"], "locations", "Empty")).toEqual([0, "The strand group “Empty” has no strands yet"]);
    expect(s.addStrandGroupToCards(["a"], "status", "Done")).toEqual([0, ""]); // filter-only
    s.undo();
    expect(s.card("b")!.characters).toEqual([]);
  });

  it("take a dropped group only on a standard card", () => {
    const s = board();
    const a = s.boxes.get("a")!;
    const [x, y] = [a.x + a.w / 2, a.y + 10];
    expect(s.strandGroupDropTarget("characters", x, y)).toBe("a");
    expect(s.strandGroupDropTarget("status", x, y)).toBeNull();
    expect(s.strandGroupDropTarget("characters", 99999, 99999)).toBeNull();     // the blank board
    const g = s.boxes.get("s")!;
    expect(s.strandGroupDropTarget("characters", g.x + 5, g.y + 5)).toBeNull(); // a strand card
    expect(s.dropStrandGroup("locations", "Docks", ["Pier", "Harbour"], x, y))
      .toEqual([true, "Added the strand group “Docks” to 1 card"]);           // from another board
    expect(s.card("a")!.locations).toEqual(["Pier", "Harbour"]);
  });
});
