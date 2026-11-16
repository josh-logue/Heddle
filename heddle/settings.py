"""App-wide preferences stored with QSettings (registry on Windows)."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

# key -> (default, section in the Settings dialog, label, tooltip)
OPTIONS: dict[str, tuple[bool, str, str, str]] = {
    "commit_pending_entries": (
        True,
        "Card editor",
        "Save tag/location/character on dialog accept",
        "When you press OK in the card editor, any tag, character or location still typed in "
        "its box (not yet added with Enter) is added to the card instead of being discarded.",
    ),
    "wheel_zooms": (
        False,
        "Canvas",
        "Mouse wheel zooms (Ctrl+wheel scrolls)",
        "Off (default, trackpad-friendly): scrolling pans the board, Shift+scroll pans "
        "sideways, and Ctrl+scroll or pinching zooms.\nOn: the wheel zooms and Ctrl+wheel pans.",
    ),
    "show_menu_bar": (
        False,
        "Window",
        "Show the menu bar (File, Edit, View, Help)",
        "Off (default): the menus are in the toolbar's ☰ button, and tapping Alt shows the menu "
        "bar for a moment (Alt+F opens File, and so on). On: the menu bar is always shown.",
    ),
    "show_banners": (
        True,
        "Canvas",
        "Show bars over the canvas for filters and highlights",
        "A bar at the top of the canvas says when a filter or highlight is on, with buttons to "
        "clear it. Off: the status bar still shows the filter, and Esc still clears a highlight.",
    ),
    "snap_to_grid": (
        False,
        "Canvas",
        "Snap cards to the grid",
        "Cards land on the 25 px grid when you drop or nudge them, and new cards start on it "
        "(arrow keys then step to the next grid line; Shift+arrow still moves 1 px). Cards you "
        "don't move stay where they are.",
    ),
}


def store() -> QSettings:
    """All app preferences: the registry on Windows, or an INI file if
    HEDDLE_SETTINGS_FILE is set (used by the tests to stay isolated)."""
    path = os.environ.get("HEDDLE_SETTINGS_FILE", "").strip()
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    current = QSettings(APP_NAME, APP_NAME)
    _adopt_legacy(current)
    return current


APP_NAME = "Heddle"
# The app's former names, newest first (WarpingWeft until November 2026, StoryBoard before
# that). Their preferences and local data are carried over once, so someone who skipped a
# version still gets theirs; the newest name that has anything wins.
LEGACY_APP_NAMES = ("WarpingWeft", "StoryBoard")
_legacy_checked = False


def _legacy_store(name: str) -> QSettings:
    """The preferences saved under a former name (a seam the tests replace)."""
    return QSettings(name, name)


def _adopt_legacy(current: QSettings) -> None:
    """First run after a rename: copy preferences saved under a former name, so the
    theme, autosave choice, window layout, Open Recent etc. aren't reset. The old entry
    is left in place (harmless, and lets an older copy of the app keep working)."""
    global _legacy_checked
    if _legacy_checked:
        return
    _legacy_checked = True
    if current.allKeys():
        return
    for name in LEGACY_APP_NAMES:
        legacy = _legacy_store(name)
        keys = legacy.allKeys()
        if not keys:
            continue
        for key in keys:
            current.setValue(key, legacy.value(key))
        current.sync()
        return


def _data_base() -> Path:
    """%LOCALAPPDATA% on Windows: local app data, not the synced Documents folder."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation))


def data_dir(sub: str) -> Path:
    """The app's local folder `sub` (backups, logs, recovery) under %LOCALAPPDATA%\\Heddle.
    The first time it's missing, the same folder from a former name is moved over, so
    Restore from Backup, crash recovery and the error log keep their history. If the
    move fails (e.g. a file is in use), the old folder is used as it is."""
    base = _data_base()
    root = base / APP_NAME / sub
    if root.exists():
        return root
    for name in LEGACY_APP_NAMES:
        legacy = base / name / sub
        if legacy.is_dir():
            try:
                root.parent.mkdir(parents=True, exist_ok=True)
                legacy.rename(root)
            except OSError:
                return legacy
            return root
    return root


def get(key: str) -> bool:
    default = OPTIONS[key][0]
    return store().value(key, default, type=bool)


def set(key: str, value: bool) -> None:  # noqa: A001 - mirrors get()
    store().setValue(key, bool(value))
