"""Small widgets and helpers shared by several dialogs and panels."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from . import theme

ROLE_DATA = Qt.ItemDataRole.UserRole


def swatch_icon(color: str) -> QIcon:
    """A small round colour dot, for lists of colours."""
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(0, 0, 0, 90))
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(1, 1, 12, 12))
    p.end()
    return QIcon(pm)


class SearchableChecklist(QWidget):
    """A filterable list of checkable entries with Check all / Uncheck all and a
    running count. Clicking anywhere on a row toggles it, not just the box.

    `entries` are (label, data, checked); `count_text(checked, total)` words the count."""

    def __init__(self, entries: list[tuple[str, Any, bool]], placeholder: str, empty_text: str,
                 count_text: Callable[[int, int], str], parent: QWidget | None = None):
        super().__init__(parent)
        self._count_text = count_text
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)

        self.list = QListWidget()
        self.list.setStyleSheet(theme.checkbox_stylesheet())
        for label, data, checked in entries:
            item = QListWidgetItem(label)
            item.setData(ROLE_DATA, data)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        if not entries:
            item = QListWidgetItem(empty_text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self._pressed: tuple[QListWidgetItem, Qt.CheckState] | None = None
        self.list.itemPressed.connect(lambda it: setattr(self, "_pressed", (it, it.checkState())))
        self.list.itemClicked.connect(self._toggle_on_row_click)
        self.list.itemChanged.connect(lambda _: self._update_count())

        check_all = QPushButton("Check all")
        uncheck_all = QPushButton("Uncheck all")
        for b in (check_all, uncheck_all):
            b.setAutoDefault(False)
        check_all.clicked.connect(lambda: self._set_visible_checked(True))
        uncheck_all.clicked.connect(lambda: self._set_visible_checked(False))
        self.count_label = QLabel()
        row = QHBoxLayout()
        row.addWidget(check_all)
        row.addWidget(uncheck_all)
        row.addStretch()
        row.addWidget(self.count_label)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.search)
        v.addWidget(self.list, 1)
        v.addLayout(row)
        self._update_count()

    # ----- results ----------------------------------------------------------
    def checked_items(self) -> list[QListWidgetItem]:
        return [i for i in self._items() if i.checkState() == Qt.CheckState.Checked]

    def checked_data(self) -> list[Any]:
        return [i.data(ROLE_DATA) for i in self.checked_items()]

    def checked_labels(self) -> list[str]:
        return [i.text() for i in self.checked_items()]

    # ----- internals --------------------------------------------------------
    def _items(self):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                yield item

    def _toggle_on_row_click(self, item: QListWidgetItem) -> None:
        # If the click landed on the box, Qt toggled it between press and click; only
        # toggle when the state is unchanged (a click on the text). Comparing states
        # avoids guessing the box's size, which varies with DPI and style.
        pressed, self._pressed = self._pressed, None
        if not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return
        if pressed is None or pressed[0] is not item or item.checkState() != pressed[1]:
            return
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)

    def _apply_search(self, text: str) -> None:
        needle = text.strip().casefold()
        for item in self._items():
            item.setHidden(bool(needle) and needle not in item.text().casefold())

    def _set_visible_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(state)

    def _update_count(self) -> None:
        items = list(self._items())
        n = sum(i.checkState() == Qt.CheckState.Checked for i in items)
        self.count_label.setText(self._count_text(n, len(items)))
