// Ported from tests/test_history.py.
import { describe, expect, it } from "vitest";
import { History, deepEqual } from "../src/core/history.ts";

type S = { n: number };

describe("History", () => {
  it("ignores a commit that changes nothing", () => {
    const h = new History<S>();
    h.reset({ n: 0 });
    expect(h.commit({ n: 0 })).toBe(false);
    expect(h.canUndo()).toBe(false);
  });

  it("undoes and redoes, and a new edit clears redo", () => {
    const h = new History<S>();
    h.reset({ n: 0 });
    h.commit({ n: 1 });
    h.commit({ n: 2 });
    expect(h.undo()).toEqual({ n: 1 });
    expect(h.undo()).toEqual({ n: 0 });
    expect(h.undo()).toBeNull();
    expect(h.redo()).toEqual({ n: 1 });
    h.commit({ n: 9 });
    expect(h.canRedo()).toBe(false);
    expect(h.undo()).toEqual({ n: 1 });
  });

  it("drops the oldest steps past the limit", () => {
    const h = new History<S>(3);
    h.reset({ n: 0 });
    for (let i = 1; i < 6; i++) h.commit({ n: i });
    expect([h.undo()!.n, h.undo()!.n, h.undo()!.n]).toEqual([4, 3, 2]);
    expect(h.undo()).toBeNull();
  });

  it("tracks the saved state", () => {
    const h = new History<S>();
    h.reset({ n: 0 });
    expect(h.atSaved()).toBe(true);
    h.commit({ n: 1 });
    expect(h.atSaved()).toBe(false);
    h.markSaved();
    h.commit({ n: 2 });
    h.undo();
    expect(h.atSaved()).toBe(true);
  });
});

describe("deepEqual", () => {
  it("compares plain data structurally", () => {
    expect(deepEqual({ a: [1, { b: "x" }] }, { a: [1, { b: "x" }] })).toBe(true);
    expect(deepEqual({ a: [1] }, { a: [1, 2] })).toBe(false);
    expect(deepEqual(new Map([["k", [1]]]), new Map([["k", [1]]]))).toBe(true);
    expect(deepEqual(new Set([1]), new Set([2]))).toBe(false);
    expect(deepEqual([1], { 0: 1 })).toBe(false);
    expect(deepEqual(NaN, NaN)).toBe(true);
  });
});
