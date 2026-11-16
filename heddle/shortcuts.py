"""Keyboard shortcuts for the card commands, in one place.

The window's actions take their keys from here and the right-click menus show the same
keys (menu_text), so a key changes in one spot. (Standard keys such as Ctrl+C and Del come
from Qt's QKeySequence.StandardKey instead, so they follow the platform.) Plain letters
are safe because these actions only fire while the canvas has keyboard focus (MainWindow._canvas_only_shortcuts):
typing in the Card Panel, the search bar or a dialog never reaches them. Commands that
move many cards at once take Ctrl+Shift, so a stray key press can't rearrange a group.
Letters and Ctrl+Shift+letter only: punctuation moves between keyboard layouts.
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence

KEYS: dict[str, str] = {
    "collapse": "C",              # collapse / expand the selected groups
    "collapse_all": "Shift+C",    # collapse / expand every group
    "details": "D",               # show / hide the selection's details
    "details_all": "Shift+D",     # show / hide every card's details
    "connect": "L",               # start Connect to… from the selected card ("link")
    "paths_cycle": "Shift+H",     # highlight: before and after → before → after
    "outside_story": "O",         # not part of the story (toggle)
    "reverse": "R",               # reverse the selected arrows
    "arrange": "Ctrl+Shift+A",    # auto-arrange the selected groups
    # Keys that were there before the Card menu, kept here so the menus can show them.
    "paths": "H",                 # highlight paths before and after (H again clears)
    "read": "Ctrl+Shift+R",       # read from the selected card
    "edit_selected": "Ctrl+E",    # edit the selected card(s)
    "duplicate": "Ctrl+D",        # duplicate the selection
}

# Keys the scene handles itself (keyPressEvent), not actions: shown as written.
ENTER = "Enter"
ESC = "Esc"


def menu_text(text: str, key) -> str:
    """A menu label with its key in the shortcut column: QMenu right-aligns whatever
    follows a tab. `key` is a KEYS value, a QKeySequence.StandardKey, ENTER or ESC."""
    if key in (ENTER, ESC):
        shown = key
    else:
        shown = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
    return f"{text}\t{shown}"
