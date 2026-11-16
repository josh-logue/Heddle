// The shared fixtures (web/fixtures, built by build_fixtures.py from the Python core):
// every case's input goes through the TypeScript core, which must give exactly the
// results the desktop app gives. Parameters (queries, selections, renames, layout inputs)
// are read from the expected results, so both sides always run the same calls.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import * as checks from "../src/core/checks.ts";
import * as exportText from "../src/core/exportText.ts";
import * as filters from "../src/core/filters.ts";
import { StoryGraph } from "../src/core/graph.ts";
import * as layout from "../src/core/layout.ts";
import * as model from "../src/core/model.ts";
import { casefold, sortedBy, sortedStrings } from "../src/core/pystr.ts";
import * as routes from "../src/core/routes.ts";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Json = any;

const dir = fileURLToPath(new URL("../fixtures/", import.meta.url));
const read = (name: string): Json => JSON.parse(readFileSync(dir + name, "utf-8"));
const manifest = read("manifest.json");

const pairs = <K, V>(m: Map<K, V>) => [...m].map(([k, v]) => [k, v]);
const sorted = (s: Iterable<string>) => sortedStrings(s);

function fixedIds(): void {
  let n = 0;
  model.setIdMaker(() => `new${++n}`);
}

afterEach(() => model.setIdMaker(null));

function graphResults(g: StoryGraph, board: model.BoardData, exp: Json) {
  const cards = [...g.cards.keys()];
  const rs = g.routes(300);
  const keys: string[][] = exp.route_for_key.map((e: Json) => e[0]);
  return {
    nodes: g.nodes(),
    outside: sorted(g.outside),
    arrows: [...g.arrows].map(([k, v]) => [k, [...v]]),
    boundary_arrows: sorted(g.boundaryArrows),
    succ: pairs(g.succ),
    pred: pairs(g.pred),
    arrow_ends: [...g.arrowEnds].map(([k, [a, b]]) => [k, [[...a], [...b]]]),
    entry_cards: cards.map((i) => [i, g.entryCards(i)]),
    exit_cards: cards.map((i) => [i, g.exitCards(i)]),
    contents: cards.filter((i) => g.members.get(i)?.length).map((i) => [i, sorted(g.contents(i))]),
    downstream: cards.map((i) => [i, sorted(g.downstream(i))]),
    upstream: cards.map((i) => [i, sorted(g.upstream(i))]),
    arrow_order: g.arrowOrder(),
    components: g.components(),
    cycles: g.cycles(),
    strongly_connected: g.stronglyConnected(),
    count_paths: [g.countPaths().count, g.countPaths().has_cycles],
    introductions: pairs(g.introductions()),
    featuring: sortedBy(new Set(board.cards.flatMap((c) => c.characters)), casefold)
      .map((n) => [n, g.featuring(n)]),
    outline_story: pairs(g.outline(true)),
    outline_reading: pairs(g.outline(false)),
    routes: rs.map((r) => ({ stops: r.stops.map((s) => [...s]), key: r.key, arrows: sorted(g.routeArrows(r)) })),
    route_for_key: keys.map((k) => [k, g.routeForKey(k) !== null]),
  };
}

function checkResults(g: StoryGraph) {
  const scopes: (string | null)[] = [null, ...[...g.cards.keys()].filter((i) => g.members.get(i)?.length)];
  return scopes.map((scope) => {
    const r = checks.runChecks(g, scope);
    return {
      scope, findings: r.findings.map((f) => [f.kind, [...f.cards], f.message]),
      paths: [r.paths.count, r.paths.has_cycles], has_arrows: r.has_arrows, stops: r.stops,
      warnings: r.warnings, summary: checks.summary(r),
    };
  });
}

function routeResults(g: StoryGraph, board: model.BoardData, exp: Json) {
  const cards = new Map(board.cards.map((c) => [c.id, c]));
  const saved = new Map(board.routes.map((r) => [model.routeKeyId(r.key), r]));
  const listing = routes.listRoutes(g, saved, 50);
  const labels = model.titleLabels(board.cards);
  const dataFor = (key: string[]) => saved.get(model.routeKeyId(key)) ?? null;
  return {
    total: listing.total,
    rows: listing.routes.map((r) => ({
      key: r.key,
      title: routes.routeTitle(r.key, cards, dataFor(r.key), r.stops, labels),
      default: routes.defaultTitle(r.key, cards),
      steps: routes.stepsText(r.key, cards, r.stops, labels),
      loops: routes.loopDetails(r.key, cards, r.stops, labels),
      search: routes.searchText(r.key, cards, dataFor(r.key), labels),
      inherited: pairs(routes.inheritedValues(r.cards, cards)),
    })),
    missing: listing.missing.map((r) => r.name),
    matches: exp.matches.map(([q]: [string]) => [q, listing.routes.map((r) => routes.matches(q, r.key, cards, dataFor(r.key)))]),
  };
}

function filterResults(g: StoryGraph, board: model.BoardData, exp: Json) {
  const extras: filters.Extras = new Map([["introduces", g.introductions()]]);
  const options = filters.collectOptions(board.cards, extras);
  const info = new Map(board.strands.map((s) => [model.strandInfoKey(s), s]));
  return {
    options: [...options].map(([cat, opts]) => [cat, opts.map((o) => [...o])]),
    search: exp.search.map(([q]: [string]) => [q, filters.searchCards(board.cards, q, info)]),
    matches: exp.matches.map((m: Json) => {
      const sel = new Map<string, Set<string>>(m.selection.map(([c, v]: [string, string[]]) => [c, new Set(v)]));
      return {
        selection: m.selection, match_all: m.match_all,
        cards: board.cards.filter((c) => filters.matches(c, sel, m.match_all, extras)).map((c) => c.id),
      };
    }),
    counts: [
      filters.describeCounts({ cards_shown: 2, cards_total: 17, groups_shown: 1, groups_total: 5 }),
      filters.describeCounts({ cards_shown: 1, cards_total: 1, groups_shown: 0, groups_total: 0 }, false),
    ],
  };
}

function exportResults(g: StoryGraph, board: model.BoardData) {
  const variants: Record<string, Partial<exportText.TextOptions>> = {
    document: {}, outline: { layout: "outline" }, everything: { notes: true },
    "outline-everything": { layout: "outline", notes: true },
    bare: { descriptions: false, details: false, next_steps: false },
  };
  const out: Record<string, string> = {};
  for (const [name, opt] of Object.entries(variants)) out[name] = exportText.exportText(board, g, "Board *title*", opt);
  const group = board.cards.find((c) => g.members.get(c.id)?.length);
  if (group) out["only-group"] = exportText.exportText(board, g, "Part", {}, [group.id]);
  const labels = new Map(board.connections.map((e) => [e.id, e.label]));
  g.routes(3).forEach((r, n) => {
    const cards = r.cards;
    const via = [""];
    for (let k = 0; k + 1 < cards.length; k++) {
      via.push(g.stepArrows(cards[k]!, cards[k + 1]!).map((a) => labels.get(a)!).find((l) => l) ?? "");
    }
    out[`route-${n}`] = exportText.exportRoute(board, cards, via, "Route");
    out[`route-${n}-outline`] = exportText.exportRoute(board, cards, via, "Route", { layout: "outline", notes: true });
  });
  return out;
}

function modelResults(board: model.BoardData, exp: Json) {
  const copyCards = () => structuredClone(board.cards);
  return {
    all_values: model.RENAMABLE_FIELDS.map((f) => [f, model.allValues(board, f)]),
    count_values: model.RENAMABLE_FIELDS.map((f) => [f, pairs(model.countValues(board.cards, f))]),
    title_labels: pairs(model.titleLabels(board.cards)),
    from_newer_version: model.fromNewerVersion(board),
    renames: exp.renames.map(({ field, old, new: name }: Json) => {
      const cards = copyCards();
      const changed = model.renameValue(cards, field, old, name);
      return {
        field, old, new: name, changed: changed.map((c) => c.id),
        values: cards.map((c) => [c.id, c[field as model.StrandKind], c.pov]),
      };
    }),
    replaces: exp.replaces.map(({ find, replacement, match_case }: Json) => {
      const cards = copyCards();
      const fields = model.REPLACE_FIELDS.map(([f]) => f);
      const count = model.countReplacements(cards, find, fields, match_case);
      const changed = model.replaceText(cards, find, replacement, fields, match_case);
      return {
        find, replacement, match_case, count, changed: changed.map((c) => c.id),
        text: changed.map((c) => [c.id, c.title, c.description, c.notes]),
      };
    }),
    bulk_edit: (() => {
      const cards = copyCards();
      const chars: string[] = exp.bulk_edit.remove_characters;
      const changed = model.applyBulkEdit(cards, {
        color: "#123abc", addTags: ["New", "plot"], removeTags: ["PLOT"], status: " Final ",
        add: { locations: ["Dock"] }, remove: { characters: chars },
      });
      return {
        remove_characters: chars, changed: changed.map((c) => c.id),
        cards: cards.map((c) => [c.id, c.color, c.tags, c.characters, c.pov, c.locations, c.status]),
      };
    })(),
  };
}

function layoutResults(exp: Json[]) {
  return exp.map((c: Json) => {
    const nodes = c.nodes.map(([id, w, h, x, y, color, group]: Json) => ({ id, w, h, x, y, color, group }));
    const labels = new Map(c.labels.map(([s, t, w, h]: Json) => [layout.edgeKey(s, t), [w, h] as const]));
    const o = c.options;
    const placed = layout.arrange(nodes, c.edges, {
      byColor: o.by_color, vertical: o.vertical, grid: o.grid, wrap: o.wrap, labels: labels as layout.LabelSizes,
    });
    const positions = sortedBy([...placed].map(([i, [x, y]]) => [i, x, y] as const), (p) => p[0]);
    return { ...c, positions };
  });
}

const sortPositions = (cases: Json[]) =>
  cases.map((c) => ({ ...c, positions: sortedBy(c.positions, (p: Json) => p[0]) }));

describe("shared fixtures", () => {
  it("are for this board format", () => {
    expect(manifest.format_version).toBe(model.FORMAT_VERSION);
  });

  for (const file of manifest.cases as string[]) {
    describe(file, () => {
      const { input, expected: exp } = read(`cases/${file}`);
      const load = () => {
        fixedIds();
        return model.boardFromDict(structuredClone(input));
      };

      if (exp.error) {
        it("is refused", () => expect(load).toThrow(exp.error));
        return;
      }

      it("loads and saves the same", () => {
        const board = load();
        expect(model.boardToDict(board)).toEqual(exp.board);
        expect(board.source_version).toBe(exp.source_version);
        expect(board.load_notes).toEqual(exp.load_notes);
      });

      it("model", () => {
        const board = load();
        expect(modelResults(board, exp.model)).toEqual(exp.model);
      });

      it("graph", () => {
        const board = load();
        expect(graphResults(new StoryGraph(board.cards, board.connections), board, exp.graph)).toEqual(exp.graph);
      });

      it("checks", () => {
        const board = load();
        expect(checkResults(new StoryGraph(board.cards, board.connections))).toEqual(exp.checks);
      });

      it("routes", () => {
        const board = load();
        expect(routeResults(new StoryGraph(board.cards, board.connections), board, exp.routes)).toEqual(exp.routes);
      });

      it("filters and search", () => {
        const board = load();
        expect(filterResults(new StoryGraph(board.cards, board.connections), board, exp.filters)).toEqual(exp.filters);
      });

      it("export", () => {
        const board = load();
        expect(exportResults(new StoryGraph(board.cards, board.connections), board)).toEqual(exp.export);
      });

      it("auto-arrange", () => {
        expect(layoutResults(exp.layout)).toEqual(sortPositions(exp.layout));
      });
    });
  }
});
