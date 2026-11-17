"""Constants shared by the board scene and its mixins (scene.py re-exports them)."""
from __future__ import annotations

from typing import NamedTuple
from dataclasses import fields

from PySide6.QtCore import QRectF, Qt

from .layout import V_GAP
from .model import (
    CardData,
    ConnectionData,
    RouteData, StrandGroup, StrandInfo,
)


GRID = 25
# The board area the view can scroll over: at least this much (centred on 0, 0),
# grown to hold every card and arrow plus SCENE_MARGIN, so nothing is out of reach
# and there's room to drag further out before it grows again.
BASE_SCENE_RECT = QRectF(-20000, -20000, 40000, 40000)
SCENE_MARGIN = 5000.0
PUSH_GAP = V_GAP     # auto-arrange: gap left when pushing neighbours out of a grown group's way
PASTE_OFFSET = 30.0   # pasting/duplicating without a mouse position: offset from the originals
NUDGE_STEP = 10.0     # arrow keys move the selection this far...
NUDGE_FINE = 1.0      # ...or this far with Shift
NUDGE_SETTLE_MS = 500  # a burst of nudges with gaps shorter than this is one undo step
NUDGE_KEYS = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
              Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
_CARD_FIELDS = tuple(f.name for f in fields(CardData))  # order of values in undo snapshots
_CONN_FIELDS = tuple(f.name for f in fields(ConnectionData))
_ROUTE_FIELDS = tuple(f.name for f in fields(RouteData))
_STRAND_FIELDS = tuple(f.name for f in fields(StrandInfo))
_GROUP_FIELDS = tuple(f.name for f in fields(StrandGroup))
# Between two descriptions joined when strands merge (renaming one to the other's name).
MERGED_DESCRIPTIONS = "\n\n———\n\n"
# Display options that change a card's size, or just what's drawn on it (cards cache
# their picture, so those are redrawn).
_LAYOUT_OPTIONS = ("show_pov", "show_characters", "show_tags", "show_introductions", "show_handles",
                   "show_no_description", "show_description", "compact_cards")
_LOOK_OPTIONS = ("show_group_count", "show_shadows", "story_tools")
MAJOR_EVERY = 5
ARRANGE_GAP = 30.0
ARRANGE_COLUMNS = 3
# Dragging a card's handle at least this far and dropping on empty canvas creates a
# new card there, already connected (shorter drags are treated as a slip).
NEW_CARD_MIN_DRAG = 40.0
# With "avoid cards" routing, arrows are re-routed this long after the board settles
# (moving one card can change which other arrows it's in the way of).
REROUTE_DELAY_MS = 120
# While cards or groups are dragged they're drawn this far above everything else
# (with their contents and the arrows between them), so a group dragged over
# another one doesn't vanish behind its frame.
DRAG_LIFT = 500.0


class Highlight(NamedTuple):
    """The highlight showing on the board (see BoardScene.set_highlight)."""
    cards: set[str]        # lit card ids
    arrows: set[str]       # lit arrow (connection) ids
    focus: str | None      # the card it's centred on, if any
    label: str             # what the banner says
    owner: str             # who made it ("paths", "reader", "thread", …): they clear only their own
