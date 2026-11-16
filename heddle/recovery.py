"""Recovery copies of untitled boards.

An untitled board is autosaved here (the app's local data folder, not Documents)
rather than under a made-up name. Each copy has a lock held by the window that
owns it, so a copy whose window is still open is never offered for recovery.
If the app closes without the board being saved, the copy is left behind (and its
lock goes stale with the process), and the next launch offers to recover it.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLockFile

from .model import BoardData, save_board
from .settings import data_dir

ENV_DIR = "HEDDLE_RECOVERY_DIR"  # overrides the folder (used by the tests)


def recovery_dir() -> Path:
    override = os.environ.get(ENV_DIR, "").strip()
    if override:
        return Path(override)
    return data_dir("recovery")


def _lock_for(path: Path) -> QLockFile:
    lock = QLockFile(str(path) + ".lock")
    # Never treat a lock as stale just because it's old (its window may have been
    # open for days); a lock is stale only when the process that took it has gone.
    lock.setStaleLockTime(0)
    return lock


class RecoveryFile:
    """One untitled board's recovery copy, locked while its window is open."""

    def __init__(self, path: Path, lock: QLockFile):
        self.path = path
        self._lock = lock

    @classmethod
    def create(cls) -> RecoveryFile:
        folder = recovery_dir()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = folder / f"Untitled-{stamp}-{uuid.uuid4().hex[:6]}.json"
        lock = _lock_for(path)
        lock.tryLock(0)
        return cls(path, lock)

    def write(self, board: BoardData) -> None:
        save_board(board, self.path)

    def discard(self) -> None:
        """The board was saved properly, or thrown away: remove the copy."""
        try:
            self.path.unlink(missing_ok=True)
        finally:
            self._lock.unlock()


def orphans() -> list[tuple[Path, QLockFile]]:
    """Recovery copies whose window has gone (newest first), each with its lock
    now held by the caller: discard the copy, adopt it, or unlock() to leave it."""
    folder = recovery_dir()
    if not folder.is_dir():
        return []
    found = []
    for path in folder.glob("*.json"):
        lock = _lock_for(path)
        if lock.tryLock(0):  # nobody holds it: its window closed without saving
            found.append((path, lock))
    found.sort(key=lambda pl: pl[0].stat().st_mtime, reverse=True)
    return found
