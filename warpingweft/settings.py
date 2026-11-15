"""App-wide preferences stored with QSettings (registry on Windows)."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

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
    WARPINGWEFT_SETTINGS_FILE is set (used by the tests to stay isolated)."""
    path = os.environ.get("WARPINGWEFT_SETTINGS_FILE", "").strip()
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    current = QSettings(APP_NAME, APP_NAME)
    _adopt_legacy(current)
    return current


APP_NAME = "WarpingWeft"
LEGACY_APP_NAME = "StoryBoard"  # the app's former name; its preferences are carried over once
_legacy_checked = False


def _adopt_legacy(current: QSettings) -> None:
    """First run after the rename: copy preferences saved under the old name, so
    the theme, autosave choice, window layout etc. aren't reset. The old entry is
    left in place (harmless, and lets an older copy of the app keep working)."""
    global _legacy_checked
    if _legacy_checked:
        return
    _legacy_checked = True
    if current.allKeys():
        return
    legacy = QSettings(LEGACY_APP_NAME, LEGACY_APP_NAME)
    keys = legacy.allKeys()
    for key in keys:
        current.setValue(key, legacy.value(key))
    if keys:
        current.sync()


def get(key: str) -> bool:
    default = OPTIONS[key][0]
    return store().value(key, default, type=bool)


def set(key: str, value: bool) -> None:  # noqa: A001 - mirrors get()
    store().setValue(key, bool(value))
