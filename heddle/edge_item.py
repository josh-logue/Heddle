"""Directed arrow connecting two cards, with an optional label."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from . import theme
from .card_item import DIMMED_OPACITY, HEADER_HEIGHT, PORT_RADIUS
from .model import ConnectionData

if TYPE_CHECKING:
    from .card_item import CardItem

ARROW_LEN = 13.0
ARROW_HALF_W = 6.5
REVERSE_OFFSET = 9.0  # separation when A->B and B->A both exist
MAX_LABEL_WIDTH = 160.0  # longer labels are shortened with "…" (full text on hover)
LOD_TEXT = 0.5      # below this zoom, label text isn't drawn (matches card_item.LOD_TEXT)
LOD_OVERVIEW = 0.3  # below this, arrows are plain lines (matches card_item.LOD_TITLE)
CURVE_MIN_PULL = 40.0   # how far a curve heads straight out of a card before bending
AVOID_MARGIN = 14.0     # clearance kept around cards an arrow is routed around
AVOID_SAMPLES = 32      # points checked along an arrow when looking for cards in the way
# Line patterns, in multiples of the pen width (the round caps fill out the dots).
DASH_PATTERNS = {"dashed": [4.0, 3.0], "dotted": [0.01, 2.4]}



def _exit_point(rect: QRectF, p: QPointF, ux: float, uy: float) -> QPointF:
    """Where a ray from p (inside rect) in direction (ux, uy) leaves the rect."""
    ts = []
    if ux > 1e-9:
        ts.append((rect.right() - p.x()) / ux)
    elif ux < -1e-9:
        ts.append((rect.left() - p.x()) / ux)
    if uy > 1e-9:
        ts.append((rect.bottom() - p.y()) / uy)
    elif uy < -1e-9:
        ts.append((rect.top() - p.y()) / uy)
    t = min(ts) if ts else 0.0
    return QPointF(p.x() + ux * t, p.y() + uy * t)


class EdgeItem(QGraphicsItem):
    def __init__(self, source: CardItem, target: CardItem, conn: ConnectionData, draw: bool = True):
        super().__init__()
        self.source = source
        self.target = target
        self.conn = conn
        self._line = QPainterPath()
        self._arrow = QPolygonF()
        self._label_rect = QRectF()
        self._label_text = ""  # the label as drawn (possibly shortened)
        self._hover = False
        self.highlight: bool | None = None  # as CardItem.highlight
        # Arrows that meet at the same collapsed groups are drawn once, marked ×N.
        self.merged = 0
        self.drawn_ends: tuple | None = None  # (start, end) items when last drawn
        self._font = QFont()
        self._font.setPointSizeF(8.5)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(-1)  # draw beneath cards
        self.setAcceptHoverEvents(True)
        source.edges.append(self)
        target.edges.append(self)
        if draw:  # (the scene draws it once it's on the board instead)
            self.adjust()

    def detach(self) -> None:
        for card in (self.source, self.target):
            if self in card.edges:
                card.edges.remove(self)

    def ends(self):
        """(start, end) as drawn: a card inside a collapsed group is drawn as that
        group (the outermost collapsed one), so its arrows meet the folded frame."""
        scene = self.scene()
        if scene is None or not hasattr(scene, "visible_end"):
            return self.source, self.target
        return scene.visible_end(self.source), scene.visible_end(self.target)

    def has_reverse(self) -> bool:
        return any(e.source is self.target and e.target is self.source for e in self.source.edges)

    def set_highlight(self, state: bool | None) -> None:
        if state != self.highlight:
            self.highlight = state
            self.refresh_opacity()
            self.update()

    def refresh_opacity(self) -> None:
        """Faded if either end is filtered out, or a highlight leaves this arrow unlit."""
        faded = self.source.dimmed or self.target.dimmed or self.highlight is False
        self.setOpacity(DIMMED_OPACITY if faded else 1.0)

    def set_label(self, label: str) -> None:
        self.conn.label = label
        self.adjust()

    def is_boundary(self) -> bool:
        """Does this arrow link a group with a card inside it (a first/last card)?"""
        return self.source.contains_card(self.target) or self.target.contains_card(self.source)

    def _boundary_ends(self) -> tuple[QPointF, QPointF] | None:
        """For an arrow between a group and a card inside it: (start, tip) across
        the gap between the card and the nearest side of the frame's inner area.
        Group → card (a first card) runs from the border to the card; card → group
        (a last card) from the card to the border. None for any other arrow."""
        if self.source.contains_card(self.target):
            group, card, inward = self.source, self.target, True
        elif self.target.contains_card(self.source):
            group, card, inward = self.target, self.source, False
        else:
            return None
        body, r = group.body_scene_rect(), card.anchor_scene_rect()
        cx = min(max(r.center().x(), body.left()), body.right())
        # Side arrows run along the card's title bar, clear of ordinary arrows (which
        # meet a card mid-height) and of its connection handle.
        cy = min(max(r.top() + HEADER_HEIGHT / 2, body.top()), body.bottom())
        spans = {  # (point on the border, point on the card) for each side
            "left": (QPointF(body.left(), cy), QPointF(r.left(), cy)),
            "right": (QPointF(body.right(), cy), QPointF(r.right(), cy)),
            "top": (QPointF(cx, body.top()), QPointF(cx, r.top())),
            "bottom": (QPointF(cx, body.bottom()), QPointF(cx, r.bottom())),
        }
        # The story enters on its starting side (left, or top for a group arranged
        # top to bottom) and leaves on the opposite one. If another card sits in the
        # way, use the nearest side that's clear instead.
        vertical = group.card.arrange_vertical
        preferred = ("top" if vertical else "left") if inward else ("bottom" if vertical else "right")
        others = [m.anchor_scene_rect() for m in group.members()
                  if m is not card and not m.contains_card(card)]

        def length(side: str) -> float:
            a, b = spans[side]
            return abs(a.x() - b.x()) + abs(a.y() - b.y())

        def clear(side: str) -> bool:
            a, b = spans[side]
            lane = QRectF(a, b).normalized().adjusted(-1, -1, 1, 1)
            return not any(o.intersects(lane) for o in others)

        opposite = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[preferred]
        # Fall back to a side at right angles first (nearest first): the opposite side
        # would point against the story's direction.
        order = ([preferred] + sorted((k for k in spans if k not in (preferred, opposite)), key=length)
                 + [opposite])
        side = next((k for k in order if clear(k)), preferred)
        border, edge = spans[side]
        return (border, edge) if inward else (edge, border)

    def label_size(self) -> tuple[float, float]:
        """(width, height) of the label as drawn on the canvas; (0, 0) for none (or
        labels hidden on this board, shown on hover instead). Worked out from the text
        alone, so it's known even while the cards are too close to draw the arrow."""
        _, text = self._label_texts()
        if not text:
            return (0.0, 0.0)
        fm = QFontMetricsF(self._font)
        return (fm.horizontalAdvance(text) + 12, fm.height() + 4)

    def _label_texts(self) -> tuple[str, str]:
        """(the label on one line, the label as drawn: shortened, or "" when labels
        are hidden on this board)."""
        label = " ".join(self.conn.label.split())  # one line, even if the file had breaks
        if self.merged > 1:
            return f"{self.merged} arrows into or out of a collapsed group", f"×{self.merged}"
        display = getattr(self.scene(), "display", None)
        if not label or (display is not None and not display.get("show_arrow_labels", True)):
            return label, ""
        fm = QFontMetricsF(self._font)
        return label, fm.elidedText(label, Qt.TextElideMode.ElideRight, MAX_LABEL_WIDTH)

    def routing(self) -> str:
        """The board's arrow routing: "straight", "curved" or "avoid"."""
        display = getattr(self.scene(), "display", None)
        return display.get("arrow_routing", "straight") if display else "straight"

    def adjust(self) -> None:
        """Recompute the arrow's path, head and label position."""
        self.prepareGeometryChange()
        self._line = QPainterPath()
        self._arrow = QPolygonF()
        self._label_rect = QRectF()
        routed = None
        a, b = self.drawn_ends = self.ends()
        ends = self._boundary_ends() if (a, b) == (self.source, self.target) else None
        if ends is not None:  # between a group and a card inside it: always a short straight arrow
            routed = self._straight_between(*ends)
        else:
            routing = self.routing()
            if routing != "straight":
                # While cards are moving, skip the (slow) search for cards in the way;
                # the arrow is routed around them once the move ends.
                scene = self.scene()
                moving = scene is not None and hasattr(scene, "is_moving") and scene.is_moving()
                routed = self._curve(avoid=routing == "avoid" and not moving)
            if routed is None:  # straight, or cards too close/overlapping to curve
                routed = self._straight()
        if routed is None:  # nothing sensible to draw
            self.update()
            return
        self._line, tip, (ux, uy), mid = routed
        if ends is None:
            mid = self._label_centre(mid)
        base = QPointF(tip.x() - ux * ARROW_LEN, tip.y() - uy * ARROW_LEN)
        perp = QPointF(-uy * ARROW_HALF_W, ux * ARROW_HALF_W)
        self._arrow = QPolygonF([tip, base + perp, base - perp])

        label, self._label_text = self._label_texts()
        # Hovering shows a label in full when it's hidden on this board or shortened.
        self.setToolTip(label if label != self._label_text else "")
        if self._label_text:
            w, h = self.label_size()
            self._label_rect = QRectF(mid.x() - w / 2, mid.y() - h / 2, w, h)
        self.update()

    def _label_centre(self, mid: QPointF) -> QPointF:
        """Where the label goes: halfway along the part of the arrow you can see.
        The path already stops where the arrowhead begins; when it leaves from the
        source's handle (a ● on the card's right edge), that covers its start, so the
        label sits halfway between the handle's edge and the arrowhead."""
        length = self._line.length()
        start = self._line.pointAtPercent(0)
        covered = 0.0
        a = self.ends()[0]
        if a.has_port and abs(start.x() - a.anchor_scene_rect().right()) < 1:
            covered = PORT_RADIUS
        if length <= covered:
            return mid
        return self._line.pointAtPercent(self._line.percentAtLength((covered + length) / 2))

    # Each router returns (path ending where the arrowhead starts, tip, unit direction
    # at the tip, label centre), or None if it can't draw this arrow.
    @staticmethod
    def _straight_between(start: QPointF, tip: QPointF):
        dx, dy = tip.x() - start.x(), tip.y() - start.y()
        length = math.hypot(dx, dy)
        if length <= ARROW_LEN:  # e.g. a card pressed against its group's frame
            return None
        ux, uy = dx / length, dy / length
        path = QPainterPath(start)
        path.lineTo(tip.x() - ux * ARROW_LEN, tip.y() - uy * ARROW_LEN)
        return path, tip, (ux, uy), (start + tip) / 2

    def _straight(self):
        """Centre to centre, cut off at both cards' edges."""
        a, b = self.ends()
        s_rect, t_rect = a.anchor_scene_rect(), b.anchor_scene_rect()
        sc, tc = s_rect.center(), t_rect.center()
        dx, dy = tc.x() - sc.x(), tc.y() - sc.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return None
        ux, uy = dx / length, dy / length
        if self.has_reverse():
            off = QPointF(-uy * REVERSE_OFFSET, ux * REVERSE_OFFSET)
            sc, tc = sc + off, tc + off
        start = _exit_point(s_rect, sc, ux, uy)
        tip = _exit_point(t_rect, tc, -ux, -uy)
        span = (tip.x() - start.x()) * ux + (tip.y() - start.y()) * uy
        if span <= ARROW_LEN:  # cards overlap
            return None
        return self._straight_between(start, tip)

    def _curve(self, avoid: bool):
        """A smooth S-curve between the sides of the two cards that face each other
        (right to left when the target is to the right, bottom to top when it's
        below, and so on), leaving and arriving square to the cards. With
        avoid=True, a curve that would cross other cards is bent around them (above
        or below, or to either side) through a point clear of them. None if the
        cards are too close to curve between."""
        a, b = self.ends()
        s, t = a.anchor_scene_rect(), b.anchor_scene_rect()
        gap_x = max(t.left() - s.right(), s.left() - t.right())
        gap_y = max(t.top() - s.bottom(), s.top() - t.bottom())
        if max(gap_x, gap_y) <= ARROW_LEN + 4:
            return None
        horizontal = gap_x >= gap_y

        # Work in (along, across) coordinates so one routine serves both directions.
        def loc(p: QPointF) -> tuple[float, float]:
            return (p.x(), p.y()) if horizontal else (p.y(), p.x())

        def out(a: float, c: float) -> QPointF:
            return QPointF(a, c) if horizontal else QPointF(c, a)

        s_lo, s_hi = (s.left(), s.right()) if horizontal else (s.top(), s.bottom())
        t_lo, t_hi = (t.left(), t.right()) if horizontal else (t.top(), t.bottom())
        sc, tc = loc(s.center()), loc(t.center())
        sign = 1.0 if tc[0] > sc[0] else -1.0
        # Opposite arrows between the same two cards sit side by side.
        off = REVERSE_OFFSET * sign * (1 if horizontal else -1) if self.has_reverse() else 0.0
        a0, c0 = (s_hi if sign > 0 else s_lo), sc[1] + off
        tip_a, c3 = (t_lo if sign > 0 else t_hi), tc[1] + off
        a3 = tip_a - sign * ARROW_LEN  # the curve ends where the arrowhead begins

        def build(lane: tuple[float, float, float] | None = None) -> QPainterPath:
            """The plain S-curve, or (with lane = (across, from, to)) a detour that
            curves out to `across`, runs level from `from` to `to` (along), and
            curves back in to the target."""
            path = QPainterPath(out(a0, c0))
            if lane is None:
                pull = max(abs(a3 - a0) * 0.5, CURVE_MIN_PULL)
                path.cubicTo(out(a0 + sign * pull, c0), out(a3 - sign * pull, c3), out(a3, c3))
                return path
            via, w1, w2 = lane
            p1, p2 = abs(w1 - a0) * 0.5, abs(a3 - w2) * 0.5
            path.cubicTo(out(a0 + sign * p1, c0), out(w1 - sign * p1, via), out(w1, via))
            path.lineTo(out(w2, via))
            path.cubicTo(out(w2 + sign * p2, via), out(a3 - sign * p2, c3), out(a3, c3))
            return path

        def lanes(blocked: list[QRectF]):
            """Detours above and below (or either side of) the blocking cards,
            nearer side first."""
            corners = [loc(r.topLeft()) for r in blocked] + [loc(r.bottomRight()) for r in blocked]
            along = [a for a, _ in corners]
            across = [c for _, c in corners]
            lo_a, hi_a = min(along) - AVOID_MARGIN, max(along) + AVOID_MARGIN
            # Level stretch spans the blockers, leaving room to curve out and back in.
            first, last = (lo_a, hi_a) if sign > 0 else (hi_a, lo_a)
            ease = CURVE_MIN_PULL / 2
            w1 = max(first, a0 + ease) if sign > 0 else min(first, a0 - ease)
            w2 = min(last, a3 - ease) if sign > 0 else max(last, a3 + ease)
            if (w2 - w1) * sign < 0:
                w1 = w2 = (a0 + a3) / 2
            home = (c0 + c3) / 2
            sides = (min(across) - AVOID_MARGIN, max(across) + AVOID_MARGIN)
            return [(via, w1, w2) for via in sorted(sides, key=lambda v: abs(v - home))]

        path = build()
        if avoid:
            blocked = self._cards_in_the_way(path)
            for _ in range(3):  # a detour can meet more cards: widen it and try again
                if not blocked:
                    break
                tried = []
                for lane in lanes(blocked):
                    candidate = build(lane)
                    hits = self._cards_in_the_way(candidate)
                    if not hits:
                        path, blocked = candidate, []
                        break
                    tried.append(hits)
                else:
                    extra = [r for r in tried[0] if r not in blocked]
                    if not extra:
                        break  # no clear way round: keep the plain curve
                    blocked = blocked + extra
        tip = out(tip_a, c3)
        direction = out(sign, 0.0)
        return path, tip, (direction.x(), direction.y()), path.pointAtPercent(0.5)

    def _cards_in_the_way(self, path: QPainterPath) -> list[QRectF]:
        """Cards (not groups, not this arrow's own ends) that the path runs through."""
        scene = self.scene()
        if scene is None:
            return []
        ends = {self.source, self.target, *self.ends()}
        rects = [i.anchor_scene_rect().adjusted(-4, -4, 4, 4)
                 for i in scene.items(path.boundingRect().adjusted(-1, -1, 1, 1))  # a level line has no height
                 if isinstance(i, type(self.source)) and not i.is_group and i not in ends]
        if not rects:
            return []
        points = [path.pointAtPercent(k / AVOID_SAMPLES) for k in range(AVOID_SAMPLES + 1)]
        return [r for r in rects if any(r.contains(pt) for pt in points)]

    def boundingRect(self) -> QRectF:
        r = self._line.boundingRect().united(self._arrow.boundingRect())
        if not self._label_rect.isNull():
            r = r.united(self._label_rect)
        return r.adjusted(-8, -8, 8, 8)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        path = stroker.createStroke(self._line)
        path.addPolygon(self._arrow)
        if not self._label_rect.isNull():
            path.addRect(self._label_rect)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self._line.isEmpty():
            return
        t = theme.current()
        color = self.draw_color()
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        if lod < LOD_OVERVIEW:  # far zoomed out: a plain 1px line, cheap for thousands of arrows
            painter.setPen(QPen(color, 0))
            painter.drawPath(self._line)
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = 3.0 if self.isSelected() or self.highlight else 2.2
        pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        if self.conn.style in DASH_PATTERNS:
            pen.setDashPattern(DASH_PATTERNS[self.conn.style])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._line)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(self._arrow)

        if not self._label_rect.isNull():
            painter.setPen(QPen(color, 1))
            painter.setBrush(t.edge_label_bg)
            painter.drawRoundedRect(self._label_rect, 4, 4)
            # Zoomed far out the label text is unreadable: keep just its box.
            if lod >= LOD_TEXT:
                painter.setFont(self._font)
                painter.setPen(t.edge_text)
                painter.drawText(self._label_rect, int(Qt.AlignmentFlag.AlignCenter), self._label_text)

    def draw_color(self) -> QColor:
        """Selection and highlight colours win; then the arrow's own colour (darker
        or lighter on hover), else the theme's."""
        t = theme.current()
        own = QColor(self.conn.color) if self.conn.color else None
        if self.isSelected():
            return t.selected
        if self.highlight:
            return t.highlight
        if self._hover:
            return (own.lighter(135) if t.dark else own.darker(135)) if own else t.edge_hover
        return own or t.edge_line

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    @property
    def hover_state(self) -> bool:
        """Is the pointer over the arrow? Settable, e.g. to hide hover effects for an export."""
        return self._hover

    @hover_state.setter
    def hover_state(self, on: bool) -> None:
        if on != self._hover:
            self._hover = on
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        QTimer.singleShot(0, lambda: scene.edit_connection_label(self))
        event.accept()
