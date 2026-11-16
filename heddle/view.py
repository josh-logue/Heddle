"""Zoomable, pannable view onto the board."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QCursor, QPainter, QTransform
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QGraphicsView, QLineEdit, QPlainTextEdit, QTextEdit,
)

ZOOM_STEP = 1.15  # per mouse-wheel notch
STRAND_MIME = "application/x-heddle-strand"  # a strand dragged from the Strands panel


def board_files(mime) -> list[Path]:
    """Local .json files in a drag-and-drop payload."""
    if not mime.hasUrls():
        return []
    return [Path(u.toLocalFile()) for u in mime.urls()
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".json")]


def strand_mime(kind: str, name: str) -> QMimeData:
    """Drag payload for a strand: its kind and name (any board window can take it)."""
    mime = QMimeData()
    mime.setData(STRAND_MIME, json.dumps({"kind": kind, "name": name}).encode("utf-8"))
    mime.setText(name)
    return mime


def strand_from_mime(mime) -> tuple[str, str] | None:
    """(kind, name) of a dragged strand, or None if the payload isn't one."""
    if not mime.hasFormat(STRAND_MIME):
        return None
    try:
        raw = json.loads(bytes(mime.data(STRAND_MIME)).decode("utf-8"))
        kind, name = raw["kind"], raw["name"]
    except (ValueError, KeyError, TypeError):
        return None
    return (kind, name) if isinstance(kind, str) and isinstance(name, str) else None


class BoardView(QGraphicsView):
    MIN_SCALE = 0.05  # far enough to see a big board whole (cards are drawn as plain blocks)
    MAX_SCALE = 3.0
    zoom_changed = Signal(float)
    files_dropped = Signal(list)  # board files dropped on the canvas
    viewport_changed = Signal()   # the visible part of the board moved, zoomed or resized

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # Repaint only what changed (a hovered card, a moved arrow), not the whole view.
        # This relies on every item painting within its boundingRect().
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._panning = False
        self._space_held = False
        self._last_pan = QPointF()
        self.wheel_zooms = False  # Settings: plain wheel zooms (Ctrl+wheel pans) instead
        QApplication.instance().installEventFilter(self)

    # ----- zoom -------------------------------------------------------------
    def current_scale(self) -> float:
        return self.transform().m11()

    def visible_scene_rect(self) -> QRectF:
        """The part of the board currently on screen, in scene coordinates."""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.viewport_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewport_changed.emit()

    def zoom_by(self, factor: float) -> None:
        current = self.current_scale()
        new = max(self.MIN_SCALE, min(self.MAX_SCALE, current * factor))
        if abs(new - current) > 1e-9:
            self.scale(new / current, new / current)
            self.zoom_changed.emit(new)
            self.viewport_changed.emit()

    def reset_zoom(self) -> None:
        self.setTransform(QTransform())
        self.zoom_changed.emit(1.0)
        self.viewport_changed.emit()

    def fit_all(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if rect.isNull():
            self.reset_zoom()
            self.centerOn(0, 0)
            return
        self.fitInView(rect.adjusted(-60, -60, 60, 60), Qt.AspectRatioMode.KeepAspectRatio)
        if self.current_scale() > 1.0:
            self.setTransform(QTransform())
            self.centerOn(rect.center())
        elif self.current_scale() < self.MIN_SCALE:
            self.setTransform(QTransform.fromScale(self.MIN_SCALE, self.MIN_SCALE))
            self.centerOn(rect.center())
        self.zoom_changed.emit(self.current_scale())
        self.viewport_changed.emit()

    def wheelEvent(self, event) -> None:
        """Scroll pans (Shift: sideways); Ctrl+scroll zooms. Windows sends a trackpad
        pinch as Ctrl+wheel, so pinching zooms too. With wheel_zooms on, a plain
        wheel zooms and Ctrl+wheel pans instead."""
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl != self.wheel_zooms:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:  # proportional, so smooth trackpad pinches don't race
                self.zoom_by(ZOOM_STEP ** (delta / 120))
        else:
            # Trackpads report exact pixels; mouse wheels report 120 per notch.
            d = event.pixelDelta()
            if d.isNull():
                d = event.angleDelta()
            dx, dy = d.x(), d.y()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and not dx:
                dx, dy = dy, 0  # Shift+wheel scrolls sideways
            self.pan_by(dx, dy)
        event.accept()

    def pan_by(self, dx: float, dy: float) -> None:
        """Move the view so the board shifts by (dx, dy) screen pixels."""
        hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
        hs.setValue(hs.value() - round(dx))
        vs.setValue(vs.value() - round(dy))

    # ----- dropping a board file opens it; dropping a strand adds it ------------
    def _strand_over(self, event) -> bool:
        """A strand dragged over the board: let the scene show where it would land, and
        accept it (as a copy: the panel keeps the strand) unless that spot refuses it.
        Returns False if the drag isn't a strand."""
        strand = strand_from_mime(event.mimeData())
        if strand is None:
            return False
        if self.scene().strand_drag_over(*strand, self.mapToScene(event.position().toPoint())):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()
        return True

    def dragEnterEvent(self, event) -> None:
        if board_files(event.mimeData()):
            event.acceptProposedAction()
        elif strand_from_mime(event.mimeData()) is not None:
            self._strand_over(event)
            event.accept()  # always, so moves keep coming (each move decides the cursor)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if board_files(event.mimeData()):
            event.acceptProposedAction()
        elif not self._strand_over(event):
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self.scene().strand_drag_done()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        files = board_files(event.mimeData())
        strand = strand_from_mime(event.mimeData())
        if files:
            event.acceptProposedAction()
            self.files_dropped.emit(files)
        elif strand is not None:
            if self.scene().drop_strand(*strand, self.mapToScene(event.position().toPoint())):
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                self.setFocus()  # so Ctrl+Z undoes it straight away
            else:
                event.ignore()
        else:
            super().dropEvent(event)

    # ----- pan (middle mouse, or hold Space + left drag) ---------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton and self._space_held):
            self._panning = True
            self._last_pan = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            d = event.position() - self._last_pan
            self._last_pan = event.position()
            self.pan_by(d.x(), d.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
            if self._space_held:
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # Space is watched app-wide (not just when the canvas has keyboard focus): it
    # pans whenever the pointer is over the canvas, unless you're typing somewhere.
    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() == Qt.Key.Key_Space:
            if etype == QEvent.Type.KeyPress:
                if self._space_held:
                    return True  # auto-repeat while held: swallow
                if (not event.isAutoRepeat() and self.window().isActiveWindow()
                        and self._pointer_over_canvas() and not self._focus_keeps_space()):
                    self._set_space_held(True)
                    return True  # don't also toggle a focused checkbox/button
            elif self._space_held:
                if not event.isAutoRepeat():
                    self._set_space_held(False)
                return True
        elif etype == QEvent.Type.WindowDeactivate and obj is self.window():
            self._set_space_held(False)  # alt-tab while holding Space
        return super().eventFilter(obj, event)

    def _set_space_held(self, held: bool) -> None:
        self._space_held = held
        if held:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif not self._panning:
            self.viewport().unsetCursor()

    def _pointer_over_canvas(self) -> bool:
        """Is the pointer over the board itself? Not over a widget floating on it
        that sets the Qt property `blocksSpacePan` (the minimap, which you drag to pan)."""
        vp = self.viewport()
        if not (vp.isVisible() and vp.rect().contains(vp.mapFromGlobal(QCursor.pos()))):
            return False
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None and w is not self:
            if w.property("blocksSpacePan") is True:
                return False
            w = w.parentWidget()
        return True

    @staticmethod
    def _focus_keeps_space() -> bool:
        """Does the focused widget use Space itself? Text boxes do (you're typing),
        and so does any widget that, or whose container, sets the Qt property
        `usesSpaceKey` to True, such as the Path Reader, where Space means "next"."""
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(w, QComboBox) and w.isEditable():
            return True
        while w is not None:
            if w.property("usesSpaceKey") is True:
                return True
            w = w.parentWidget()
        return False
