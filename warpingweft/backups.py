"""Rolling backups of board files, and detecting changes made on disk by others.

No Qt here. Backups live outside the board's folder (normally the local, unsynced
app-data folder), one sub-folder per board file:

    <root>/<stem>-<hash of full path>/<stem> 2026-11-13 14-05-22.json
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

KEEP = 20                    # newest backups kept per board
MIN_INTERVAL_S = 5 * 60      # at most one backup per board every 5 minutes (unless forced)
_STAMP = "%Y-%m-%d %H-%M-%S"


def backup_dir_for(board: Path, root: Path) -> Path:
    full = str(Path(board).resolve()).casefold()
    digest = hashlib.sha1(full.encode("utf-8")).hexdigest()[:8]
    stem = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in Path(board).stem) or "board"
    return Path(root) / f"{stem}-{digest}"


def list_backups(board: Path, root: Path) -> list[tuple[Path, datetime]]:
    """Backups of this board, newest first."""
    folder = backup_dir_for(board, root)
    if not folder.is_dir():
        return []
    found = []
    prefix = Path(board).stem + " "
    for f in folder.glob("*.json"):
        name = f.stem
        if not name.startswith(prefix):
            continue
        try:
            when = datetime.strptime(name[len(prefix):len(prefix) + 19], _STAMP)
        except ValueError:
            continue
        # Several backups in one second are numbered " (1)", " (2)"… in order made.
        rest = name[len(prefix) + 19:].strip()
        seq = int(rest[1:-1]) if rest.startswith("(") and rest.endswith(")") and rest[1:-1].isdigit() else 0
        found.append((f, when, seq))
    found.sort(key=lambda t: (t[1], t[2]), reverse=True)
    return [(f, when) for f, when, _ in found]


def make_backup(board: Path, root: Path, now: datetime | None = None, force: bool = False,
                keep: int = KEEP, min_interval_s: float = MIN_INTERVAL_S) -> Path | None:
    """Copy the board file as it is now into its backup folder, before it gets
    overwritten. Skipped if the file doesn't exist yet, or (unless forced) if the
    newest backup is recent. Old backups beyond `keep` are deleted. Returns the new
    backup's path, or None if none was made."""
    board = Path(board)
    if not board.is_file():
        return None
    now = now or datetime.now()
    existing = list_backups(board, root)
    if existing and not force and (now - existing[0][1]).total_seconds() < min_interval_s:
        return None
    folder = backup_dir_for(board, root)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{board.stem} {now.strftime(_STAMP)}.json"
    n = 1
    while target.exists():  # two forced backups in the same second
        target = folder / f"{board.stem} {now.strftime(_STAMP)} ({n}).json"
        n += 1
    shutil.copy2(board, target)
    for old, _ in list_backups(board, root)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def file_digest(path: Path) -> str | None:
    """Fingerprint of a file's contents (None if it doesn't exist or can't be read).
    Contents rather than modified time: a sync client may touch the time without
    changing anything, and clocks on two machines needn't agree."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None
