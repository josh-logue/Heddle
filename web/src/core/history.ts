// Undo/redo history of whole-board snapshots: a port of heddle/history.py.
//
// Each committed state is an immutable value. Python compares snapshots with ==; here
// the caller passes an equality test (structural by default).

export const UNDO_LIMIT = 200;

export class History<State> {
  private undoStack: State[] = [];
  private redoStack: State[] = [];
  current: State | null = null;
  saved: State | null = null;

  constructor(
    readonly limit: number = UNDO_LIMIT,
    private readonly equals: (a: State, b: State) => boolean = deepEqual,
  ) {}

  private same(a: State | null, b: State | null): boolean {
    if (a === null || b === null) return a === b;
    return this.equals(a, b);
  }

  /** Start fresh (new or opened board); the given state counts as saved. */
  reset(state: State): void {
    this.undoStack = [];
    this.redoStack = [];
    this.current = this.saved = state;
  }

  /** Record a new state after an edit. Returns false if nothing actually changed. */
  commit(state: State): boolean {
    if (this.same(state, this.current)) return false;
    if (this.current !== null) {
      this.undoStack.push(this.current);
      if (this.undoStack.length > this.limit) this.undoStack.splice(0, this.undoStack.length - this.limit);
    }
    this.redoStack = [];
    this.current = state;
    return true;
  }

  canUndo(): boolean {
    return this.undoStack.length > 0;
  }

  canRedo(): boolean {
    return this.redoStack.length > 0;
  }

  undo(): State | null {
    const state = this.undoStack.pop();
    if (state === undefined) return null;
    this.redoStack.push(this.current as State);
    this.current = state;
    return state;
  }

  redo(): State | null {
    const state = this.redoStack.pop();
    if (state === undefined) return null;
    this.undoStack.push(this.current as State);
    this.current = state;
    return state;
  }

  markSaved(): void {
    this.saved = this.current;
  }

  atSaved(): boolean {
    return this.same(this.current, this.saved);
  }
}

/** Structural equality for plain data: objects, arrays, Maps, Sets and primitives. */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a)) {
    return Array.isArray(b) && a.length === b.length && a.every((v, i) => deepEqual(v, b[i]));
  }
  if (a instanceof Map) {
    if (!(b instanceof Map) || a.size !== b.size) return false;
    for (const [k, v] of a) if (!b.has(k) || !deepEqual(v, b.get(k))) return false;
    return true;
  }
  if (a instanceof Set) {
    if (!(b instanceof Set) || a.size !== b.size) return false;
    for (const v of a) if (!b.has(v)) return false;
    return true;
  }
  if (Array.isArray(b) || b instanceof Map || b instanceof Set) return false;
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  const rb = b as Record<string, unknown>;
  const ra = a as Record<string, unknown>;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(rb, k) && deepEqual(ra[k], rb[k]));
}
