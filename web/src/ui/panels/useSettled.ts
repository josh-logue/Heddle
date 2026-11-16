import { useEffect, useState } from "react";
import { StoryGraph } from "../../core/graph.ts";
import type { BoardState, BoardStore } from "../../board/store.ts";

/** `value`, once it has stopped changing for `ms` (the first value straight away), so a
 *  panel that does slow work (story checks, routes) skips the steps of a drag. */
export function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    if (value === settled) return;
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, settled, ms]);
  return settled;
}

/** The story graph of a (settled) board state: the store's cached one while it's current. */
export function graphOf(store: BoardStore, state: BoardState): StoryGraph {
  return state === store.state ? store.storyGraph() : new StoryGraph(state.cards, state.connections);
}
