"""Graphics item for a story card or a group card.

A *group* has the same header/tags/details as a card but no description; its
member cards (cards whose `parent` is the group's id) sit on top of it and the
group's frame automatically fits around them. Membership is data-driven rather
than Qt parent/child so that z-order stays: groups < arrows < cards.
"""
from __future__ import annotations

import math
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF, QTextLayout, QTextOption,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from . import theme
from .model import DISPLAY_DEFAULTS, KIND_GROUP, KIND_STRAND, CardData

if TYPE_CHECKING:
    from .edge_item import EdgeItem

CARD_WIDTH = 230.0
HEADER_HEIGHT = 32.0
PAD = 10.0
CORNER = 8.0
PORT_RADIUS = 7.0
LOD_TEXT = 0.5    # below this zoom, body text (descriptions, details, tags) isn't drawn
LOD_TITLE = 0.3   # below this, titles and handles aren't either: just coloured shapes
TOGGLE_SIZE = 18.0
BADGE_SIZE = 18.0  # the numbered disc a character thread puts on its cards
FOLD_SIZE = 16.0   # a group's collapse / expand button, left of its title
MAX_DESC_LINES = 6
DIMMED_OPACITY = 0.2

GROUP_PAD = 22.0        # space between member cards and the group's frame
GROUP_MIN_WIDTH = 300.0
GROUP_EMPTY_HEIGHT = 120.0
GROUP_MIN_BODY = 60.0   # smallest manual body height below the header
RESIZE_GRIP = 16.0      # bottom-right drag handle size
FRAME_EDGE_HIT = 14.0   # how close to a group's frame edge counts as "on the edge"
GROUP_Z = -5.0          # below arrows (-1) and cards (0); +0.1 per nesting level

WRAP = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
LEFT_VCENTER = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
RIGHT_VCENTER = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
CENTER = int(Qt.AlignmentFlag.AlignCenter)
CENTER_WRAP = CENTER | int(Qt.TextFlag.TextWordWrap)

# Strand cards: a small mark before the name saying what kind of strand it is.
STRAND_MARKS = {"characters": "☺", "locations": "⌂", "tags": "#", "status": "◑"}
STRAND_KIND_NAMES = {"characters": "Character", "locations": "Location", "tags": "Tag", "status": "Status"}

DETAIL_FIELDS = (
    ("characters", "Characters"),
    ("pov", "POV"),
    ("locations", "Locations"),
    ("status", "Status"),
    ("notes", "Notes"),
)


def _font(point_size: float, bold: bool = False, italic: bool = False) -> QFont:
    f = QFont()
    f.setPointSizeF(point_size)
    f.setBold(bold)
    f.setItalic(italic)
    return f


def readable_text_color(bg: QColor) -> QColor:
    lum = 0.299 * bg.redF() + 0.587 * bg.greenF() + 0.114 * bg.blueF()
    return QColor("#1e1e1e") if lum > 0.62 else QColor("#ffffff")


ELLIPSIS = "…"


def elide_lines(text: str, font: QFont, width: float, max_lines: int) -> tuple[str, bool]:
    """Wrap `text` to `width` (at word boundaries, or mid-word for words too long to
    fit) and keep at most `max_lines` lines, ending the last with an ellipsis if
    anything was cut. The result has explicit line breaks, so drawing it with
    TextWordWrap reproduces exactly these lines. Returns (text, was_cut)."""
    t = text.replace("\r\n", "\n").replace("\n", " ")  # Qt's line separator
    layout = QTextLayout(t, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    spans: list[tuple[int, int]] = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        spans.append((line.textStart(), line.textLength()))
    layout.endLayout()
    lines = [t[s:s + n].rstrip("  ") for s, n in spans]
    if len(lines) <= max_lines:
        return "\n".join(lines), False
    fm = QFontMetricsF(font)
    start, length = spans[max_lines - 1]
    rest = " ".join(t[start:].replace(" ", " ").split())
    last = fm.elidedText(rest, Qt.TextElideMode.ElideRight, width)
    if not last.endswith(ELLIPSIS):
        # The rest only spilled onto more lines because of line breaks, so it
        # fits as one line: cut it at the last visible line and mark the cut.
        last = fm.elidedText(lines[max_lines - 1] + ELLIPSIS, Qt.TextElideMode.ElideRight, width)
    return "\n".join(lines[:max_lines - 1] + [last]), True


def _tooltip_html(text: str) -> str:
    """Rich-text tooltip so long text wraps instead of making one huge line."""
    return "<p style='white-space:pre-wrap'>" + escape(text) + "</p>"


class CardItem(QGraphicsItem):
    """A draggable card or group. Drag the round handle on its right edge to connect it."""

    def __init__(self, card: CardData):
        super().__init__()
        self.card = card
        self.edges: list[EdgeItem] = []
        self.details_visible = False  # always starts hidden
        self.dimmed = False  # filtered out by the filter panel
        # Path/thread highlight: None = none showing, True = lit, False = faded.
        self.highlight: bool | None = None
        self._focus = False  # the card a highlight is centred on
        # Worked out from the arrows by the scene (not saved): characters this card
        # introduces, and the card's number in a character thread being shown.
        self.introduces: list[str] = []
        self.badge = ""
        self.search_hits = 0  # collapsed group: search matches hidden inside it

        self._title_font = _font(10.5, bold=True)
        self._body_font = _font(9.5)
        self._placeholder_font = _font(9.5, italic=True)
        self._small_font = _font(8.5)
        self._small_italic = _font(8.5, italic=True)
        self._label_font = _font(7.5, bold=True)

        self._width = CARD_WIDTH
        self._height = HEADER_HEIGHT + 40
        self._header_area_h = HEADER_HEIGHT  # groups: height of header+tags+details
        self._closed_h = self._height  # cards: height with details hidden (see anchor_scene_rect)
        self._collapsed_header_h = HEADER_HEIGHT  # groups: the same with details hidden
        self._member_count = 0
        # (rect, text, font, role) where role is "text" or "muted"; resolved at paint time
        self._blocks: list[tuple[QRectF, str, QFont, str]] = []
        self._tag_pills: list[tuple[QRectF, str]] = []
        self._char_pills: list[tuple[QRectF, str]] = []  # characters on the card face
        self._details_top: float | None = None

        self._hover_part: str | None = None
        self._drop_highlight = False
        self._connecting = False
        self._resizing = False
        self._resize_offset = QPointF()
        self._press_pos: QPointF | None = None
        self._fitting = True  # suppresses dragging members along during refits
        self._last_pos = QPointF(card.x, card.y)

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self._update_cache_mode()
        self.setPos(card.x, card.y)
        self._fitting = False
        self._relayout()

    # ----- identity ---------------------------------------------------------
    @property
    def is_group(self) -> bool:
        return self.card.kind == KIND_GROUP

    @property
    def is_strand(self) -> bool:
        """A strand card: stands for a strand, showing its name (and description in its details)."""
        return self.card.kind == KIND_STRAND

    def strand_description(self) -> str:
        """A strand card's description: its strand's, from the Strands panel."""
        scene = self.scene()
        info = scene.strand(self.card.strand_kind, self.card.strand) \
            if scene is not None and hasattr(scene, "strand") else None
        return info.description.strip() if info else ""

    def members(self) -> list[CardItem]:
        scene = self.scene()
        return scene.members_of(self) if scene is not None and self.is_group else []

    # ----- geometry ---------------------------------------------------------
    def card_rect(self) -> QRectF:
        return QRectF(0, 0, self._width, self._height)

    def card_scene_rect(self) -> QRectF:
        return self.mapRectToScene(self.card_rect())

    def anchor_scene_rect(self) -> QRectF:
        """Where arrows meet the card: the card as it looks with details hidden. Details
        only grow a card downwards, so anchoring to this keeps its arrows (and other
        cards' arrows routed round it) still while its details are open."""
        if self.is_group:
            return self.card_scene_rect()
        return self.mapRectToScene(QRectF(0, 0, self._width, min(self._closed_h, self._height)))

    def header_area_height(self) -> float:
        return self._header_area_h

    @property
    def has_port(self) -> bool:
        """Only plain cards get a drag handle (unless the board hides handles); groups,
        and any card then, connect via right-click → Connect to…"""
        return not self.is_group and bool(self.board_option("show_handles"))

    def port_center(self) -> QPointF:
        # Groups have no handle, but a connection line drawn from one starts beside the title bar.
        y = HEADER_HEIGHT / 2 if self.is_group else min(self._closed_h, self._height) / 2
        return QPointF(self._width, y)

    def port_scene_pos(self) -> QPointF:
        return self.mapToScene(self.port_center())

    def fold_rect(self) -> QRectF:
        """A group's collapse / expand button, at the left of its title bar."""
        return QRectF(PAD - 4, (HEADER_HEIGHT - FOLD_SIZE) / 2, FOLD_SIZE, FOLD_SIZE)

    @property
    def collapsed(self) -> bool:
        return self.is_group and self.card.collapsed

    def toggle_rect(self) -> QRectF:
        return QRectF(self._width - PAD - TOGGLE_SIZE + 4, (HEADER_HEIGHT - TOGGLE_SIZE) / 2,
                      TOGGLE_SIZE, TOGGLE_SIZE)

    def resize_rect(self) -> QRectF:
        return QRectF(self._width - RESIZE_GRIP, self._height - RESIZE_GRIP, RESIZE_GRIP, RESIZE_GRIP)

    @property
    def manually_sized(self) -> bool:
        return self.is_group and self.card.width > 0 and self.card.height > 0

    def boundingRect(self) -> QRectF:
        return QRectF(-3, -3, self._width + PORT_RADIUS + 8, self._height + 8)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self.card_rect(), CORNER, CORNER)
        if self.has_port:
            path.addEllipse(self.port_center(), PORT_RADIUS + 3, PORT_RADIUS + 3)
        return path

    def _part_at(self, pos: QPointF) -> str:
        p = self.port_center()
        if self.has_port and math.hypot(pos.x() - p.x(), pos.y() - p.y()) <= PORT_RADIUS + 3:
            return "port"
        if self.is_group and self.fold_rect().adjusted(-2, -2, 2, 2).contains(pos):
            return "fold"
        if self.toggle_rect().adjusted(-3, -3, 3, 3).contains(pos):
            return "toggle"
        if self.is_group and not self.collapsed and self.resize_rect().contains(pos):
            return "resize"
        if self.is_group and pos.y() > self._header_area_h:
            return "group_body"
        return "body"

    # ----- state ------------------------------------------------------------
    def apply_data(self, card: CardData) -> None:
        if not self.is_group:
            # A plain card's position lives in pos(); carry it over so that turning
            # the card into a group keeps it in place.
            card.x, card.y = self.pos().x(), self.pos().y()
        old_parent = self.card.parent
        self.card = card
        scene = self.scene()
        if scene is not None and hasattr(scene, "card_data_replaced"):
            scene.card_data_replaced(self, old_parent)
        self._update_cache_mode()
        self._relayout()

    def _update_cache_mode(self) -> None:
        # Plain cards keep a pixmap of themselves, so panning and nearby repaints just
        # blit it instead of laying out text again. Groups aren't cached: at high zoom
        # a large frame would make a huge pixmap. (update() refreshes the cache.)
        mode = QGraphicsItem.CacheMode.NoCache if self.is_group else QGraphicsItem.CacheMode.DeviceCoordinateCache
        if self.cacheMode() != mode:
            self.setCacheMode(mode)

    def set_details_visible(self, visible: bool) -> None:
        if visible != self.details_visible:
            self.details_visible = visible
            self._relayout()

    def toggle_details(self) -> None:
        """▸ clicked: open or close the details, letting the board make room."""
        scene = self.scene()
        if scene is not None and hasattr(scene, "show_details"):
            scene.show_details(self, not self.details_visible)
        else:
            self.set_details_visible(not self.details_visible)

    def set_dimmed(self, dimmed: bool) -> None:
        if dimmed != self.dimmed:
            self.dimmed = dimmed
            self._apply_opacity()

    def set_highlight(self, state: bool | None, focus: bool = False) -> None:
        """Lit (True, outlined), faded (False) or no highlight showing (None).
        Combines with the filter: a card faded by either one is faded."""
        focus = focus and state is True
        if state != self.highlight or focus != self._focus:
            self.highlight, self._focus = state, focus
            self._apply_opacity()
            self.update()  # the outline changes, and plain cards cache their pixmap

    @property
    def faded(self) -> bool:
        """Faded out by the filter or by a highlight (drawn see-through)."""
        return self.dimmed or self.highlight is False

    def _apply_opacity(self) -> None:
        self.setOpacity(DIMMED_OPACITY if self.faded else 1.0)

    def set_introduces(self, names: list[str]) -> None:
        """Characters this card introduces: a ★ in the header, and a line in its details."""
        if names != self.introduces:
            self.introduces = list(names)
            if self.details_visible:
                self._relayout()
            else:
                self.update()

    def set_badge(self, text: str) -> None:
        """A small numbered disc at the start of the header ("" for none)."""
        if text != self.badge:
            self.badge = text
            self.update()

    def set_drop_highlight(self, on: bool) -> None:
        if on != self._drop_highlight:
            self._drop_highlight = on
            self.update()

    def refit(self) -> None:
        """Recompute layout (for groups: re-fit the frame around members)."""
        self._relayout()

    def contains_card(self, other: CardItem) -> bool:
        """Is `other` inside this group, at any depth?"""
        scene = self.scene()
        if not self.is_group or other is self or scene is None:
            return False
        return any(a is self for a in scene.ancestors(other))

    def body_scene_rect(self) -> QRectF:
        """A group's frame below its header panel: where its cards sit."""
        r = self.card_scene_rect()
        r.setTop(r.top() + self._header_area_h)
        return r

    def on_frame_edge(self, scene_pos: QPointF) -> bool:
        """Is scene_pos on this group's header or close to its frame's edge?"""
        p = self.mapFromScene(scene_pos)
        return (p.y() <= self._header_area_h or p.x() <= FRAME_EDGE_HIT
                or p.x() >= self._width - FRAME_EDGE_HIT or p.y() >= self._height - FRAME_EDGE_HIT)

    def _exporting(self) -> bool:
        """Is the board being drawn into an exported image (no editing controls)?"""
        return getattr(self.scene(), "export_background", None) is not None

    def board_option(self, key: str):
        """One of the board's display options (the default before it's on a board)."""
        display = getattr(self.scene(), "display", None) or DISPLAY_DEFAULTS
        return display.get(key, DISPLAY_DEFAULTS.get(key))

    def face_options(self) -> tuple[bool, bool, bool]:
        """(show POV line, show character pills, show tag pills): board display options."""
        return (bool(self.board_option("show_pov")), bool(self.board_option("show_characters")),
                bool(self.board_option("show_tags")))

    def layout_options(self) -> tuple:
        """The board options this card's layout reads. A card is laid out before it
        joins a board (with the defaults), so the scene compares this with
        `laid_out_with` and re-lays it out when they differ."""
        return (*self.face_options(), bool(self.board_option("show_no_description")))

    def shows_introductions(self) -> bool:
        return bool(self.introduces) and bool(self.board_option("show_introductions"))

    def _layout_pills(self, values: list[str], y: float, inner: float) -> tuple[list, float]:
        """Rounded pills for values, wrapping onto new rows; returns them and the y below."""
        if not values:
            return [], y
        fm = QFontMetricsF(self._small_font)
        pill_h = fm.height() + 4
        pills = []
        x = PAD
        for value in values:
            text = fm.elidedText(value, Qt.TextElideMode.ElideRight, inner - 12)
            w = fm.horizontalAdvance(text) + 12
            if x > PAD and x + w > PAD + inner:  # wrap to next row
                x = PAD
                y += pill_h + 4
            pills.append((QRectF(x, y, w, pill_h), text))
            x += w + 4
        return pills, y + pill_h + 6

    def _relayout(self) -> None:
        """Recompute text blocks and size from the current data; groups also fit
        their frame around their members. Changes propagate to the parent group."""
        self.prepareGeometryChange()
        self.laid_out_with = self.layout_options()
        c = self.card
        group = self.is_group
        members = self.members() if group else []
        self._member_count = len(members)
        bbox: QRectF | None = None
        for m in members:
            r = m.card_scene_rect()
            bbox = r if bbox is None else bbox.united(r)

        # Groups: card.x/y (and width/height when sized by hand) describe the frame as it
        # looks with details hidden. They change only through real edits (moving,
        # resizing, arranging). The frame drawn here is derived from them plus the
        # current header height and is never written back, so showing details, or a
        # member growing, can't alter saved data.
        manual = group and c.width > 0 and c.height > 0
        left = c.x
        if manual:
            # Frame = the manually sized rect, grown if needed to still hold every card.
            right = left + c.width
            if bbox is not None:
                left = min(left, bbox.left() - GROUP_PAD)
                right = max(right, bbox.right() + GROUP_PAD)
            self._width = max(right - left, GROUP_MIN_WIDTH)
        elif group:
            self._width = max(GROUP_MIN_WIDTH, bbox.width() + 2 * GROUP_PAD) if bbox else GROUP_MIN_WIDTH
            if bbox is not None:
                left = bbox.left() - GROUP_PAD
        else:
            self._width = CARD_WIDTH
        inner = self._width - 2 * PAD
        blocks: list[tuple[QRectF, str, QFont, str]] = []
        y = HEADER_HEIGHT + PAD
        if self.is_strand:
            self._layout_strand(blocks, inner)
            self._finish_relayout()
            return

        # Board display options: tag pills, a POV line, and the characters as outlined pills.
        show_pov, show_characters, show_tags = self.face_options()
        self._tag_pills, y = self._layout_pills(c.tags if show_tags else [], y, inner)

        pov = c.pov if show_pov else ""
        if pov:
            lfm, vfm = QFontMetricsF(self._label_font), QFontMetricsF(self._small_font)
            label_w = lfm.horizontalAdvance("POV") + 1
            line_h = vfm.height()
            # Line the small capital label up with the name's baseline.
            dy = vfm.ascent() - lfm.ascent()
            blocks.append((QRectF(PAD, y + dy, label_w, lfm.height()), "POV", self._label_font, "muted"))
            name_x = PAD + label_w + 6
            name = vfm.elidedText(pov, Qt.TextElideMode.ElideRight, PAD + inner - name_x)
            blocks.append((QRectF(name_x, y, PAD + inner - name_x, line_h), name, self._small_font, "text"))
            y += line_h + 6
        face_characters = [ch for ch in c.characters
                           if not (pov and ch.casefold() == pov.casefold())] if show_characters else []
        self._char_pills, y = self._layout_pills(face_characters, y, inner)
        # Anything shown under a header (groups need this to size their header panel).
        has_face = bool(self._tag_pills or pov or self._char_pills)

        if group:
            self.setToolTip("")
        elif not c.description.strip() and not self.board_option("show_no_description"):
            # "No description" hidden: a card with nothing else on its face keeps the
            # line's space (so it doesn't shrink to a sliver); otherwise what's there
            # (tags, POV, characters) is the body, and the line closes up.
            self.setToolTip("")
            if has_face:
                y += PAD - 6  # (the face rows already end with 6 px of spacing)
            else:
                y += QFontMetricsF(self._placeholder_font).height() + PAD
        else:
            desc = c.description.strip()
            font = self._body_font if desc else self._placeholder_font
            text = desc or "No description"
            fm = QFontMetricsF(font)
            text, truncated = elide_lines(text, font, inner, MAX_DESC_LINES)
            # Hovering a cut-off description shows all of it.
            self.setToolTip(_tooltip_html(desc) if truncated else "")
            h = fm.boundingRect(QRectF(0, 0, inner, 1e6), WRAP, text).height()
            blocks.append((QRectF(PAD, y, inner, h), text, font, "text" if desc else "muted"))
            y += h + PAD

        y_without_details = self._closed_h = y
        self._details_top = None
        if self.details_visible:
            self._details_top = y - PAD / 2 if (not group or has_face) else None
            y += PAD / 2 if self._details_top is not None else 0
            lfm = QFontMetricsF(self._label_font)
            vfm = QFontMetricsF(self._small_font)
            shown = False
            for key, label in DETAIL_FIELDS:
                raw = getattr(c, key)
                value = ", ".join(raw) if isinstance(raw, list) else raw.strip()
                if not value:
                    continue
                shown = True
                blocks.append((QRectF(PAD, y, inner, lfm.height()), label.upper(), self._label_font, "muted"))
                y += lfm.height() + 1
                vh = vfm.boundingRect(QRectF(0, 0, inner, 1e6), WRAP, value).height()
                blocks.append((QRectF(PAD, y, inner, vh), value, self._small_font, "text"))
                y += vh + 6
            if self.shows_introductions():  # worked out from the arrows, not typed in
                shown = True
                blocks.append((QRectF(PAD, y, inner, lfm.height()), "INTRODUCES ★",
                               self._label_font, "muted"))
                y += lfm.height() + 1
                value = ", ".join(self.introduces)
                vh = vfm.boundingRect(QRectF(0, 0, inner, 1e6), WRAP, value).height()
                blocks.append((QRectF(PAD, y, inner, vh), value, self._small_font, "text"))
                y += vh + 6
            if not shown:
                ifm = QFontMetricsF(self._small_italic)
                blocks.append((QRectF(PAD, y, inner, ifm.height()),
                               "No details yet. Double-click the title to add.", self._small_italic, "muted"))
                y += ifm.height() + 6
            y += PAD - 6

        self._blocks = blocks
        if group:
            hdr = self._header_area_h = y if (has_face or self.details_visible) else HEADER_HEIGHT
            # Header height with details hidden: depends only on data (the tags).
            hdr0 = self._collapsed_header_h = y_without_details if has_face else HEADER_HEIGHT
            if manual:
                body_top = c.y + hdr0
                bottom = c.y + c.height
                if bbox is not None:
                    body_top = min(body_top, bbox.top() - GROUP_PAD)
                    bottom = max(bottom, bbox.bottom() + GROUP_PAD)
                bottom = max(bottom, body_top + GROUP_MIN_BODY)
            elif bbox is not None:
                body_top = bbox.top() - GROUP_PAD
                bottom = bbox.bottom() + GROUP_PAD
                # The anchor follows the cards' top-left corners, which are data (not
                # their heights, which change with details); this keeps an emptied
                # group where it was.
                c.x, c.y = left, body_top - hdr0
            else:
                body_top = c.y + hdr0
                bottom = body_top + GROUP_EMPTY_HEIGHT
            top = body_top - hdr  # extra header (shown details) grows upward
            # Collapsed: just the header (its cards keep their places, hidden).
            self._height = hdr if c.collapsed else bottom - top
            if QPointF(left, top) != self.pos():
                self._fitting = True
                self.setPos(left, top)
                self._fitting = False
        else:
            self._header_area_h = HEADER_HEIGHT
            self._height = y
        self._finish_relayout()

    def _finish_relayout(self) -> None:
        self.update()
        for edge in self.edges:
            edge.adjust()
        scene = self.scene()
        if self.collapsed and scene is not None and hasattr(scene, "folded_edges"):
            for edge in scene.folded_edges(self):  # they meet this folded frame
                if edge.isVisible():
                    edge.adjust()
        if scene is not None and self.card.parent:
            parent = scene.cards.get(self.card.parent)
            if parent is not None and parent is not self:
                parent.refit()

    def _layout_strand(self, blocks: list, inner: float) -> None:
        """A strand card is just its title bar (the strand's name); its details show
        the strand's description. Its picture is never drawn on the canvas."""
        self._tag_pills, self._char_pills = [], []
        self.setToolTip(f"{STRAND_KIND_NAMES.get(self.card.strand_kind, 'Strand')}: {self.card.strand}")
        y = self._closed_h = HEADER_HEIGHT
        self._details_top = None
        if self.details_visible:
            y += PAD
            desc = self.strand_description()
            font = self._small_font if desc else self._small_italic
            text = desc or "No description yet. Add one in Strands."
            h = QFontMetricsF(font).boundingRect(QRectF(0, 0, inner, 1e6), WRAP, text).height()
            blocks.append((QRectF(PAD, y, inner, h), text, font, "text" if desc else "muted"))
            y += h + PAD
        self._blocks = blocks
        self._header_area_h = HEADER_HEIGHT
        self._height = y

    # ----- painting ---------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Zoomed far out, text is unreadable and laying it out dominates the cost of
        # drawing many cards: skip body text below LOD_TEXT, titles below LOD_TITLE.
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        show_text, show_title = lod >= LOD_TEXT, lod >= LOD_TITLE
        t = theme.current()
        if not show_title:
            self._paint_overview(painter, t)
            return
        color = QColor(self.card.color)
        path = QPainterPath()
        path.addRoundedRect(self.card_rect(), CORNER, CORNER)

        if self.is_group:
            self._paint_group_body(painter, t, color, path, show_text)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            if self.board_option("show_shadows"):
                painter.setBrush(t.card_shadow)
                painter.drawPath(path.translated(2, 3))
            painter.setBrush(t.card_bg)
            painter.drawPath(path)

        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(0, 0, self._width, HEADER_HEIGHT), color)
        painter.restore()

        if show_title:
            self._paint_header_text(painter, color, show_text)

        if self._tag_pills:
            tint = QColor(color)
            tint.setAlpha(80 if t.dark else 50)
            painter.setFont(self._small_font)
            for rect_, text in self._tag_pills:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tint)
                r = rect_.height() / 2
                painter.drawRoundedRect(rect_, r, r)
                if show_text:
                    painter.setPen(t.card_text)
                    painter.drawText(rect_, CENTER, text)

        if self._char_pills:  # characters: outlined, so they read apart from tags
            ring = QColor(color)
            ring.setAlpha(200 if t.dark else 170)
            painter.setFont(self._small_font)
            for rect_, text in self._char_pills:
                painter.setPen(QPen(ring, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                r = rect_.height() / 2
                painter.drawRoundedRect(rect_.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
                if show_text:
                    painter.setPen(t.card_text)
                    painter.drawText(rect_, CENTER, text)

        if self._details_top is not None:
            painter.setPen(QPen(t.card_border, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(PAD, self._details_top), QPointF(self._width - PAD, self._details_top))

        if show_text:
            for r, text, font, role in self._blocks:
                painter.save()
                painter.setClipRect(r.adjusted(0, 0, 0, 1))
                painter.setFont(font)
                painter.setPen(t.card_text if role == "text" else t.card_muted)
                painter.drawText(r, WRAP, text)
                painter.restore()

        if self.isSelected():
            pen = QPen(t.selected, 2.5)
        elif self._drop_highlight:
            pen = QPen(color.lighter(130) if t.dark else color.darker(115), 2.5, Qt.PenStyle.DashLine)
        elif self.highlight:
            pen = QPen(t.highlight, 3.5 if self._focus else 2.5)
        elif self.is_group:
            edge = QColor(color)
            edge.setAlpha(170)
            pen = QPen(edge, 1.5)
        else:
            pen = QPen(t.card_border, 1)
        if (self.card.outside_story and self.board_option("story_tools")
                and pen.style() == Qt.PenStyle.SolidLine):
            pen.setStyle(Qt.PenStyle.DashLine)  # left out of the story tools
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        if self.is_group and not self.collapsed and show_title and not self._exporting():
            self._paint_resize_grip(painter, t, color)

        if self.has_port and show_title and not self._exporting():
            radius = PORT_RADIUS + (2 if self._hover_part == "port" else 0)
            painter.setPen(QPen(t.port_ring, 2))
            painter.setBrush(color.darker(110))
            painter.drawEllipse(self.port_center(), radius, radius)

    def _paint_overview(self, painter: QPainter, t) -> None:
        """Far zoomed out: plain blocks (body plus coloured header), no corners,
        shadow, clipping or text. Cheap to draw for thousands of cards."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        color = QColor(self.card.color)
        body = self.card_rect()
        if self.is_group:
            wash = QColor(color)
            wash.setAlpha(45 if t.dark else 30)
            painter.fillRect(body, t.canvas_bg)
            painter.fillRect(body, wash)
        else:
            painter.fillRect(body, t.card_bg)
        painter.fillRect(QRectF(0, 0, self._width, HEADER_HEIGHT), color)
        if self.isSelected() or self._drop_highlight:
            painter.setPen(QPen(t.selected if self.isSelected() else color, 0))  # cosmetic: always 1px
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(body)
        elif self.is_group:
            painter.setPen(QPen(color, 0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(body)

    def _paint_header_text(self, painter: QPainter, color: QColor, show_count: bool) -> None:
        header_text = readable_text_color(color)
        title_right = self._width - 2.5 * PAD - TOGGLE_SIZE
        painter.setFont(self._title_font)
        if self.is_group and show_count and (self.board_option("show_group_count") or self.collapsed):
            count = f"{self._member_count} card{'s' if self._member_count != 1 else ''}"
            if self.collapsed and self.search_hits:  # matches hidden inside it
                count += f" · {self.search_hits} found"
            count_w = QFontMetricsF(self._small_font).horizontalAdvance(count) + 8
            faded = QColor(header_text)
            faded.setAlpha(190)
            painter.setFont(self._small_font)
            painter.setPen(faded)
            painter.drawText(QRectF(title_right - count_w, 0, count_w, HEADER_HEIGHT), RIGHT_VCENTER, count)
            painter.setFont(self._title_font)
            title_right -= count_w + 6
        if self.shows_introductions():  # ★: this card introduces a character
            star_w = QFontMetricsF(self._title_font).horizontalAdvance("★") + 4
            painter.setPen(header_text)
            painter.drawText(QRectF(title_right - star_w, 0, star_w, HEADER_HEIGHT), RIGHT_VCENTER, "★")
            title_right -= star_w + 2
        title_left = PAD
        if self.is_group:
            if not self._exporting():
                self._paint_fold(painter, header_text)
            title_left += FOLD_SIZE + 2
        if self.is_strand:  # what kind of strand it stands for
            mark = STRAND_MARKS.get(self.card.strand_kind, "•")
            mark_w = QFontMetricsF(self._title_font).horizontalAdvance(mark) + 6
            painter.setPen(header_text)
            painter.drawText(QRectF(title_left, 0, mark_w, HEADER_HEIGHT), LEFT_VCENTER, mark)
            title_left += mark_w
        if self.badge:  # its number in the character thread being shown
            d = BADGE_SIZE
            disc = QRectF(title_left - 3, (HEADER_HEIGHT - d) / 2, d, d)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(header_text)
            painter.drawEllipse(disc)
            painter.setPen(color)
            painter.setFont(self._label_font)
            painter.drawText(disc, CENTER, self.badge)
            painter.setFont(self._title_font)
            title_left = disc.right() + 6
        title_rect = QRectF(title_left, 0, title_right - title_left, HEADER_HEIGHT)
        title = QFontMetricsF(self._title_font).elidedText(
            self.card.title or "Untitled", Qt.TextElideMode.ElideRight, title_rect.width())
        painter.setPen(header_text)
        painter.drawText(title_rect, LEFT_VCENTER, title)
        if not self._exporting():  # editing controls aren't drawn in exported images
            self._paint_toggle(painter, header_text)

    def _paint_fold(self, painter: QPainter, fg: QColor) -> None:
        """A small boxed − (collapse) or + (expand) at the left of a group's title."""
        r = self.fold_rect().adjusted(2, 2, -2, -2)
        ring = QColor(fg)
        ring.setAlpha(255 if self._hover_part == "fold" else 170)
        painter.setPen(QPen(ring, 1.3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(r, 2.5, 2.5)
        c, arm = r.center(), r.width() * 0.28
        painter.drawLine(QPointF(c.x() - arm, c.y()), QPointF(c.x() + arm, c.y()))
        if self.collapsed:
            painter.drawLine(QPointF(c.x(), c.y() - arm), QPointF(c.x(), c.y() + arm))

    def _paint_resize_grip(self, painter: QPainter, t, color: QColor) -> None:
        hot = self._hover_part == "resize" or self._resizing
        grip = QColor(color.lighter(140) if t.dark else color.darker(120))
        grip.setAlpha(255 if hot else 150)
        painter.setPen(QPen(grip, 1.6 if hot else 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        r, b = self._width - 4, self._height - 4
        for d in (4.0, 8.0, 12.0):  # three diagonal ridges
            painter.drawLine(QPointF(r - d, b), QPointF(r, b - d))

    def _paint_group_body(self, painter: QPainter, t, color: QColor, path: QPainterPath,
                          show_text: bool = True) -> None:
        # Opaque canvas-colored base (hides the grid), then a wash of the group color.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.canvas_bg)
        painter.drawPath(path)
        wash = QColor(color)
        wash.setAlpha(45 if t.dark else 30)
        painter.setBrush(wash)
        painter.drawPath(path)
        if self._header_area_h > HEADER_HEIGHT:  # solid panel behind tags/details
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(0, 0, self._width, self._header_area_h), t.card_bg)
            line = QColor(color)
            line.setAlpha(120)
            painter.setPen(QPen(line, 1))
            painter.drawLine(QPointF(0, self._header_area_h), QPointF(self._width, self._header_area_h))
            painter.restore()
        if self._member_count == 0 and show_text:
            area =QRectF(PAD, self._header_area_h, self._width - 2 * PAD, self._height - self._header_area_h)
            painter.setFont(self._small_italic)
            painter.setPen(t.card_muted)
            painter.drawText(area, CENTER_WRAP,
                             "Drag cards here, or double-click to add one")

    def _paint_toggle(self, painter: QPainter, fg: QColor) -> None:
        r = self.toggle_rect()
        if self._hover_part == "toggle":
            bg = QColor(fg)
            bg.setAlpha(45)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawEllipse(r)
        x, y, s = r.x(), r.y(), r.width()
        if self.details_visible:  # pointing down
            pts = [QPointF(x + s * 0.25, y + s * 0.36), QPointF(x + s * 0.75, y + s * 0.36),
                   QPointF(x + s * 0.5, y + s * 0.70)]
        else:  # pointing right
            pts = [QPointF(x + s * 0.36, y + s * 0.25), QPointF(x + s * 0.36, y + s * 0.75),
                   QPointF(x + s * 0.70, y + s * 0.5)]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fg)
        painter.drawPolygon(QPolygonF(pts))

    # ----- interaction ------------------------------------------------------
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            new_pos = self.pos()
            if self.is_group and not self._fitting:
                dx, dy = new_pos.x() - self._last_pos.x(), new_pos.y() - self._last_pos.y()
                if dx or dy:
                    # A real move (drag, arrange…): shift the saved anchor with it.
                    self.card.x += dx
                    self.card.y += dy
                    scene = self.scene()
                    skip_selected = scene is not None and hasattr(scene, "selection_moving") \
                        and scene.selection_moving()
                    for m in self.members():
                        # During a drag or nudge, selected members move themselves.
                        if not (skip_selected and m.isSelected()):
                            m.moveBy(dx, dy)
            self._last_pos = QPointF(new_pos)
            scene = self.scene()
            if scene is not None and hasattr(scene, "ensure_room"):
                scene.ensure_room(self.card_scene_rect())  # dragged far out: keep it reachable
                scene.card_moved(self)
            for edge in self.edges:
                edge.adjust()
        return super().itemChange(change, value)

    def hoverMoveEvent(self, event) -> None:
        part = self._part_at(event.pos())
        if part != self._hover_part:
            self._hover_part = part
            cursor = {"port": Qt.CursorShape.CrossCursor,
                      "toggle": Qt.CursorShape.PointingHandCursor,
                      "fold": Qt.CursorShape.PointingHandCursor,
                      "resize": Qt.CursorShape.SizeFDiagCursor}.get(part, Qt.CursorShape.OpenHandCursor)
            self.setCursor(cursor)
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover_part = None
        self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)

    @property
    def hover_state(self) -> str | None:
        """Which part of the card the pointer is over ("port", "toggle", "resize",
        "" for elsewhere), or None. Settable, e.g. to hide hover effects for an export."""
        return self._hover_part

    @hover_state.setter
    def hover_state(self, part: str | None) -> None:
        if part != self._hover_part:
            self._hover_part = part
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            part = self._part_at(event.pos())
            if part == "toggle":
                self.toggle_details()
                event.accept()
                return
            if part == "fold" and self.scene() is not None:
                self.scene().set_collapsed([self], not self.collapsed)
                event.accept()
                return
            if part == "port":
                self._connecting = True
                self.scene().begin_connection(self, event.scenePos())
                event.accept()
                return
            if part == "resize":
                self._resizing = True
                # Keep the grip under the cursor at the same offset while dragging.
                self._resize_offset = QPointF(self._width - event.pos().x(), self._height - event.pos().y())
                event.accept()
                return
        self._press_pos = QPointF(self.pos())
        if event.button() == Qt.MouseButton.LeftButton and self.scene() is not None:
            self.scene().begin_move()  # a drag may follow: route arrows simply until it ends
        super().mousePressEvent(event)

    def resize_to(self, width: float, height: float) -> None:
        """Manually size a group's frame from its current top-left corner (it still
        grows to hold all its cards). Stored as the details-hidden frame."""
        hdr, hdr0 = self._header_area_h, self._collapsed_header_h
        body_top = self.pos().y() + hdr
        self.card.x = self.pos().x()
        self.card.y = body_top - hdr0
        self.card.width = max(width, GROUP_MIN_WIDTH)
        self.card.height = hdr0 + max(height - hdr, GROUP_MIN_BODY)
        self._relayout()

    def reset_size(self) -> None:
        self.card.width = self.card.height = 0.0
        self._relayout()

    def mouseMoveEvent(self, event) -> None:
        if self._connecting:
            self.scene().update_connection(event.scenePos())
            event.accept()
            return
        if self._resizing:
            scene_pos = event.scenePos()
            self.resize_to(scene_pos.x() - self.pos().x() + self._resize_offset.x(),
                           scene_pos.y() - self.pos().y() + self._resize_offset.y())
            event.accept()
            return
        scene = self.scene()
        if scene is not None and hasattr(scene, "moving_selection"):
            with scene.moving_selection():  # Qt moves every selected card by the same step
                super().mouseMoveEvent(event)
        else:
            super().mouseMoveEvent(event)
        if self._press_pos is not None:
            scene = self.scene()
            if self.pos() != self._press_pos:
                scene.lift_for_drag(self)  # drawn on top while it moves (once per drag)
            scene.update_drop_hint(self, event.scenePos())

    def mouseReleaseEvent(self, event) -> None:
        if self._connecting:
            self._connecting = False
            self.scene().finish_connection(event.scenePos(), event.modifiers())
            event.accept()
            return
        if self._resizing:
            self._resizing = False
            self.update()
            self.scene().mark_modified()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        moved = self._press_pos is not None and self.pos() != self._press_pos
        self.scene().end_move(moved)
        if moved:
            self.scene().handle_drop(self, event.scenePos())  # join/leave groups, refit, mark modified
        else:
            self.scene().clear_drop_hint()
            self.scene().end_lift()
        self._press_pos = None

    def sceneEvent(self, event) -> bool:
        # Losing the mouse grab (also sent after an ordinary release) ends any move:
        # if it was taken away mid-drag, e.g. by a dialog, the board mustn't go on
        # thinking cards are moving. (Plain graphics items have no ungrab handler of
        # their own; the scene tells them through this general event.)
        if event.type() == QEvent.Type.UngrabMouse:
            scene = self.scene()
            if scene is not None and hasattr(scene, "end_move"):
                scene.end_move()
                scene.end_lift()  # and nothing stays drawn on top
        return super().sceneEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        part = self._part_at(event.pos())
        scene = self.scene()
        if part == "toggle":
            self.toggle_details()
        elif part == "fold":
            scene.set_collapsed([self], not self.collapsed)  # a quick second click
        elif part == "resize":
            self.reset_size()  # back to fitting snugly around the cards
            scene.mark_modified()
        elif part == "group_body":
            pos = event.scenePos()
            QTimer.singleShot(0, lambda: scene.create_card_at(pos, group=self))
        elif part == "body" and self.is_strand:
            # Its description is edited in the Strands panel: show it there.
            QTimer.singleShot(0, lambda: scene.strand_card_opened.emit(self.card.strand_kind,
                                                                       self.card.strand))
        elif part == "body":
            # Defer so the dialog doesn't open while the mouse is still grabbed.
            QTimer.singleShot(0, lambda: scene.edit_card(self))
        event.accept()
