// The fixtures (web/fixtures): every case's input goes through the core, which must give
// exactly the recorded results. They began as the Python app's answers, recorded while the
// core was ported, and are now frozen as the TypeScript core's. A deliberate change of
// behaviour or format: run `npm run fixtures`, then read the diff of web/fixtures before
// trusting it (it records whatever the core now answers, bugs included).

import { afterEach, describe, expect, it } from "vitest";
import { StoryGraph } from "../src/core/graph.ts";
import * as model from "../src/core/model.ts";
import {
  checkResults, exportResults, filterResults, graphResults, layoutResults, loadCase, modelResults,
  readFixture, refreshFixtures, routeResults, sortPositions, type Json,
} from "./fixtureResults.ts";

const manifest = readFixture("manifest.json");
const refreshing = Boolean(process.env.HEDDLE_UPDATE_FIXTURES); // (npm run fixtures)

afterEach(() => model.setIdMaker(null));

describe.runIf(refreshing)("refresh the fixtures", () => {
  it("rewrites the cases whose results changed", () => {
    refreshFixtures();
  });
});

describe.skipIf(refreshing)("fixtures", () => {
  it("are for this board format (npm run fixtures after a format change)", () => {
    expect(manifest.format_version).toBe(model.FORMAT_VERSION);
  });

  for (const file of manifest.cases as string[]) {
    describe(file, () => {
      const { input, expected: exp } = readFixture(`cases/${file}`) as Json;
      const load = () => loadCase(input);
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
