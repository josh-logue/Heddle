"""Bar floating over the top of the canvas while a filter is active, so dimmed
cards are explained even when the filter panel is hidden."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from . import theme
from .filters import FilterCounts, describe_counts

MARGIN_TOP = 10


class FilterBanner(QFrame):
    show_panel_requested = Signal()
    clear_requested = Signal()

    def __init__(self, host: QWidget):
        """`host` is the widget it floats over (the board view); it stays centred
        along the host's top edge as the host resizes."""
        super().__init__(host)
        self.setObjectName("filterBanner")
        self.label = QLabel()
        self.show_btn = QPushButton("Show filter")
        self.clear_btn = QPushButton("Clear")
        for b in (self.show_btn, self.clear_btn):
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_btn.clicked.connect(self.show_panel_requested)
        self.clear_btn.clicked.connect(self.clear_requested)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 5, 6, 5)
        row.setSpacing(8)
        row.addWidget(self.label)
        row.addSpacing(6)
        row.addWidget(self.show_btn)
        row.addWidget(self.clear_btn)
        self.apply_theme()
        self.hide()
        host.installEventFilter(self)

    enabled = True  # Settings: the floating bars can be turned off

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self.hide()

    def apply_theme(self) -> None:
        self.setStyleSheet(theme.banner_stylesheet())

    def update_state(self, counts: FilterCounts, active: bool, panel_visible: bool,
                     note: str = "") -> None:
        """`note` names any "match all" categories at work ("all tags")."""
        if not active or not self.enabled:
            self.hide()
            return
        self.label.setText(f"<b>Filter on</b> · showing {describe_counts(counts)}"
                           + (f" · {note}" if note else ""))
        self.show_btn.setVisible(not panel_visible)  # no point offering it when it's open
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self) -> None:
        host = self.parentWidget()
        self.move(max(0, (host.width() - self.width()) // 2), MARGIN_TOP)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False


class HighlightBanner(QFrame):
    """Bar over the canvas while a path or thread highlight is showing: says what's
    lit and offers to clear it. Sits just below the filter banner when both show."""
    clear_requested = Signal()

    def __init__(self, host: QWidget, above: QWidget | None = None):
        super().__init__(host)
        self.setObjectName("filterBanner")  # same look as the filter banner
        self._above = above
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setAutoDefault(False)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_requested)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 5, 6, 5)
        row.setSpacing(8)
        row.addWidget(self.label)
        row.addSpacing(6)
        row.addWidget(self.clear_btn)
        self.apply_theme()
        self.hide()
        host.installEventFilter(self)
        if above is not None:  # follow the filter banner as it appears / disappears
            above.installEventFilter(self)

    def apply_theme(self) -> None:
        self.setStyleSheet(theme.banner_stylesheet())

    enabled = True  # Settings: the floating bars can be turned off

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self.hide()

    def update_state(self, description: str) -> None:
        if not description or not self.enabled:
            self.hide()
            return
        self.label.setText(f"<b>{escape(description)}</b> · Esc to clear")
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self) -> None:
        host = self.parentWidget()
        top = MARGIN_TOP
        if self._above is not None and self._above.isVisible():
            top = self._above.geometry().bottom() + 6
        self.move(max(0, (host.width() - self.width()) // 2), top)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Move):
            if obj is self.parentWidget() or obj is self._above:
                self._reposition()
        return False
