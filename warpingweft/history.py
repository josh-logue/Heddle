"""Undo/redo history of whole-board snapshots (no Qt).

Each committed state is an immutable value that compares equal for equal boards
(see BoardScene._snapshot, which shares unchanged cards between snapshots so
whole-board snapshots stay cheap). That makes every kind of edit undoable without
per-action undo code.
"""
from __future__ import annotations

from typing import Any

UNDO_LIMIT = 200

State = Any


class History:
    def __init__(self, limit: int = UNDO_LIMIT):
        self.limit = limit
        self._undo: list[State] = []
        self._redo: list[State] = []
        self.current: State | None = None
        self.saved: State | None = None

    def reset(self, state: State) -> None:
        """Start fresh (new or opened board); the given state counts as saved."""
        self._undo.clear()
        self._redo.clear()
        self.current = self.saved = state

    def commit(self, state: State) -> bool:
        """Record a new state after an edit. Returns False if nothing actually changed."""
        if state == self.current:
            return False
        if self.current is not None:
            self._undo.append(self.current)
            del self._undo[:-self.limit]
        self._redo.clear()
        self.current = state
        return True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> State | None:
        if not self._undo:
            return None
        self._redo.append(self.current)
        self.current = self._undo.pop()
        return self.current

    def redo(self) -> State | None:
        if not self._redo:
            return None
        self._undo.append(self.current)
        self.current = self._redo.pop()
        return self.current

    def mark_saved(self) -> None:
        self.saved = self.current

    def at_saved(self) -> bool:
        return self.current == self.saved
