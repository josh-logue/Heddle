"""Minimap: a small overview of the whole board floating in the canvas's bottom-right
corner, with a box showing the part that's on screen. Click or drag on it to move
there, scroll on it to zoom, double-click to fit the board.

It draws its own simplified picture (plain coloured blocks, no text or arrows)
rather than being a second view of the scene, so it stays cheap on big boards and
never shows hover effects, drag ghosts or the grid. The picture is cached and only
redrawn, at most every REBUILD_DELAY_MS, after the board changes.

It can be minimised to a small button (its own button, shown while the pointer is
over the map, or Ctrl+Shift+M) but not closed outright."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsView, QToolButton, QWidget

from . import theme

MAP_SIZE = QSize(220, 150)      # expanded
BUTTON_SIZE = 20                # the minimise / expand button
MARGIN = 10                     # from the canvas's bottom-right corner
INSET = 6                       # map drawing area inside the frame
CORNER = 6
REBUILD_DELAY_MS = 40           # coalesce bursts of board changes into one redraw
PAD_FRACTION = 0.05             # empty border around the cards, as a share of their extent
MIN_PAD = 60.0                  # scene px
MIN_BLOCK = 1.5                 # px: tiny cards still show up
FADED_ALPHA = 70
ZOOM_STEP = 1.15


class Minimap(QWidget):
    expanded_changed = Signal(bool)

    def __init__(self, view, expanded: bool = True):
        """`view` is the BoardView it floats over and steers."""
        super().__init__(view)
        self.view = view
        self.scene = view.scene()
        self.setObjectName("minimap")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setProperty("blocksSpacePan", True)  # dragging here pans; Space-to-pan doesn't apply
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._expanded = expanded
        self._pixmap: QPixmap | None = None
        self._pixmap_key = None          # (extent, size, dpr) the cached picture was drawn for
        self._dirty = True
        self._world = QRectF()           # cards' extent (padded) from the last rebuild
        self._dragging = False
        self._grab_offset = QPointF()    # scene offset from the pointer to the box's centre
        self._frozen_extent: QRectF | None = None  # held still while dragging on the map
        self.rebuild_count = 0           # for tests: how often the picture was redrawn

        self.button = QToolButton(self)
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setAutoRaise(True)
        self.button.clicked.connect(self.toggle_expanded)

        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(REBUILD_DELAY_MS)
        self._rebuild_timer.timeout.connect(self._mark_dirty)

        # The board's look changed: cards moved, recoloured, selected, faded, lit…
        self.scene.changed.connect(self.schedule_rebuild)
        self.scene.selectionChanged.connect(self.schedule_rebuild)
        self.scene.modified.connect(self.schedule_rebuild)
        self.scene.highlight_changed.connect(self.schedule_rebuild)
        # Only the on-screen box moved: repaint, reusing the cached picture.
        view.viewport_changed.connect(self.update)
        view.installEventFilter(self)

        self.apply_theme()
        self._apply_expanded()
        self.show()

    # ----- minimise / expand ------------------------------------------------------
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self._expanded:
            self._expanded = expanded
            self._apply_expanded()
            self.expanded_changed.emit(expanded)

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def _apply_expanded(self) -> None:
        if self._expanded:
            self.setFixedSize(MAP_SIZE)
            self.button.setText("−")
            self.button.setToolTip("Minimise the minimap (Ctrl+Shift+M)")
            self.button.setGeometry(self.width() - BUTTON_SIZE - 3, 3, BUTTON_SIZE, BUTTON_SIZE)
            # Shown only while the pointer is over the map, so it doesn't cover cards.
            self.button.setVisible(self.underMouse())
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._dirty = True
        else:
            self.setFixedSize(BUTTON_SIZE + 4, BUTTON_SIZE + 4)
            self.button.setText("▣")
            self.button.setToolTip("Show the minimap (Ctrl+Shift+M)")
            self.button.setGeometry(2, 2, BUTTON_SIZE, BUTTON_SIZE)
            self.button.show()
            self.unsetCursor()
            self._dragging = False
            self._frozen_extent = None
        self._reposition()
        self.raise_()
        self.update()

    def _reposition(self) -> None:
        host = self.view
        self.move(max(0, host.width() - self.width() - MARGIN),
                  max(0, host.height() - self.height() - MARGIN))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.view and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def enterEvent(self, event) -> None:
        self.button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._expanded:
            self.button.hide()
        super().leaveEvent(event)

    # ----- theme ------------------------------------------------------------------
    def apply_theme(self) -> None:
        t = theme.current()
        bg, hover = QColor(t.canvas_bg), QColor(t.card_text)
        bg.setAlpha(225)  # legible over the map drawn beneath it
        hover.setAlpha(40)
        rgba = lambda c: f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"  # noqa: E731
        self.button.setStyleSheet(
            f"QToolButton {{ border: none; border-radius: 4px; padding: 0; background: {rgba(bg)};"
            f" color: {t.card_muted.name()}; font-size: 15px; font-weight: bold; }}"
            f" QToolButton:hover {{ background: {rgba(hover)}; color: {t.card_text.name()}; }}")
        self._dirty = True
        self.update()

    # ----- keeping the picture current -------------------------------------------------
    def schedule_rebuild(self, *_args) -> None:
        if not self._rebuild_timer.isActive():
            self._rebuild_timer.start()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.update()

    def map_rect(self) -> QRectF:
        """The drawing area inside the frame, in widget pixels."""
        return QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET)

    def _cards_extent(self) -> QRectF:
        bounds = QRectF()
        for item in self.scene.cards.values():
            if not item.isVisible():  # folded inside a collapsed group
                continue
            r = item.card_scene_rect()
            bounds = r if bounds.isNull() else bounds.united(r)
        if bounds.isNull():
            return bounds
        pad = max(MIN_PAD, PAD_FRACTION * max(bounds.width(), bounds.height()))
        return bounds.adjusted(-pad, -pad, pad, pad)

    def extent(self) -> QRectF:
        """The part of the board the map shows: the cards, plus the on-screen area
        so its box never falls off the map."""
        if self._frozen_extent is not None:
            return self._frozen_extent  # mid-drag: moving the box mustn't rescale the map
        world = self._world if not self._world.isNull() else self._cards_extent()
        visible = self.view.visible_scene_rect()
        return visible if world.isNull() else world.united(visible)

    def _transform(self, extent: QRectF) -> tuple[float, float, float]:
        """(scale, dx, dy) taking scene coordinates to widget pixels, keeping the
        aspect ratio and centring the extent in the map area."""
        area = self.map_rect()
        if extent.width() <= 0 or extent.height() <= 0:
            return 1.0, area.center().x(), area.center().y()
        s = min(area.width() / extent.width(), area.height() / extent.height())
        dx = area.left() + (area.width() - extent.width() * s) / 2 - extent.left() * s
        dy = area.top() + (area.height() - extent.height() * s) / 2 - extent.top() * s
        return s, dx, dy

    def scene_to_map(self, p: QPointF) -> QPointF:
        s, dx, dy = self._transform(self.extent())
        return QPointF(p.x() * s + dx, p.y() * s + dy)

    def map_to_scene(self, p: QPointF) -> QPointF:
        s, dx, dy = self._transform(self.extent())
        return QPointF((p.x() - dx) / s, (p.y() - dy) / s)

    def _scene_rect_to_map(self, r: QRectF, xf) -> QRectF:
        s, dx, dy = xf
        out = QRectF(r.left() * s + dx, r.top() * s + dy, r.width() * s, r.height() * s)
        if out.width() < MIN_BLOCK or out.height() < MIN_BLOCK:
            c = out.center()
            w, h = max(out.width(), MIN_BLOCK), max(out.height(), MIN_BLOCK)
            out = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        return out

    def _refresh_world(self) -> None:
        """Work out the cards' extent again. While a mouse button is held (a card
        being dragged) it only grows, so the map doesn't jitter under the drag; it
        settles to fit on the next change after release."""
        fresh = self._cards_extent()
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton and not self._world.isNull() \
                and not fresh.isNull():
            fresh = fresh.united(self._world)
        self._world = fresh

    def _render(self) -> None:
        """Draw the board layer: groups (outermost first), then cards, then the
        selected and lit outlines on top so nothing covers them."""
        self.rebuild_count += 1
        extent = self.extent()
        xf = self._transform(extent)
        dpr = self.devicePixelRatioF()
        pm = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        t = theme.current()
        p = QPainter(pm)
        p.setClipRect(self.map_rect())

        groups, cards = [], []
        for item in self.scene.cards.values():
            if item.isVisible():  # (not folded inside a collapsed group)
                (groups if item.is_group else cards).append(item)
        groups.sort(key=self._depth)
        outlines = []
        for item in groups + cards:
            r = self._scene_rect_to_map(item.card_scene_rect(), xf)
            color = QColor(item.card.color)
            faded = item.faded
            if item.is_group:
                wash = QColor(color)
                wash.setAlpha(25 if faded else 55)
                edge = QColor(color)
                edge.setAlpha(FADED_ALPHA if faded else 190)
                p.setPen(QPen(edge, 1))
                p.setBrush(wash)
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
            else:
                if faded:
                    color.setAlpha(FADED_ALPHA)
                p.fillRect(r, color)
            if item.isSelected():
                outlines.append((r, t.selected))
            elif item.highlight is True:
                outlines.append((r, t.highlight))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r, c in outlines:
            p.setPen(QPen(c, 1.5))
            p.drawRect(r.adjusted(-1, -1, 1, 1))
        p.end()
        self._pixmap = pm
        self._pixmap_key = (extent, self.size(), dpr)

    def _depth(self, item) -> int:
        depth, parent, seen = 0, item.card.parent, set()
        while parent and parent in self.scene.cards and parent not in seen:
            seen.add(parent)
            depth += 1
            parent = self.scene.cards[parent].card.parent
        return depth

    # ----- painting ---------------------------------------------------------------
    def paintEvent(self, event) -> None:
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), CORNER, CORNER)
        bg = QColor(t.canvas_bg)
        bg.setAlpha(238)
        p.setPen(QPen(t.card_border, 1))
        p.setBrush(bg)
        p.drawPath(frame)
        if not self._expanded:
            return

        if self._dirty:
            self._refresh_world()
        extent = self.extent()
        key = (extent, self.size(), self.devicePixelRatioF())
        if self._dirty or self._pixmap is None or key != self._pixmap_key:
            self._render()
            self._dirty = False
        p.drawPixmap(0, 0, self._pixmap)

        # The on-screen box.
        box = self._scene_rect_to_map(self.view.visible_scene_rect(), self._transform(extent))
        p.setClipRect(self.map_rect().adjusted(-1, -1, 1, 1))
        fill = QColor(t.card_text)
        fill.setAlpha(28)
        edge = QColor(t.card_text)
        edge.setAlpha(170)
        p.setPen(QPen(edge, 1.2))
        p.setBrush(fill)
        p.drawRect(box)

    # ----- steering the main view -------------------------------------------------------
    def _on_map(self, pos: QPointF) -> bool:
        return self._expanded and self.map_rect().contains(pos) \
            and not (self.button.isVisible() and self.button.geometry().contains(pos.toPoint()))

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton and self._on_map(pos):
            target = self.map_to_scene(pos)
            visible = self.view.visible_scene_rect()
            # Grabbing the box drags it from where you grabbed it; elsewhere it jumps there.
            self._grab_offset = visible.center() - target if visible.contains(target) else QPointF()
            self._dragging = True
            self._frozen_extent = self.extent()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.view.centerOn(target + self._grab_offset)
            event.accept()
            return
        event.accept()  # never let a click fall through to the board underneath

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.view.centerOn(self.map_to_scene(event.position()) + self._grab_offset)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._frozen_extent = None
            self.update()
            if self._expanded:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_map(event.position()):
            self._dragging = False
            self._frozen_extent = None
            self.view.fit_all()
        event.accept()

    def wheelEvent(self, event) -> None:
        """Scroll on the map zooms the board about the centre of the screen."""
        if self._expanded:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                anchor = self.view.transformationAnchor()
                self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
                self.view.zoom_by(ZOOM_STEP ** (delta / 120))
                self.view.setTransformationAnchor(anchor)
        event.accept()
