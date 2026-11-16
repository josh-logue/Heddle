"""Multi-value entry widget: removable chips + autocompleting text box + picker list."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCompleter, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QToolButton, QVBoxLayout, QWidget,
)

from . import theme
from .widgets import SearchableChecklist


class FlowLayout(QLayout):
    """Lays widgets out left-to-right, wrapping onto new rows as needed."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        # Height is managed by _ChipBox instead; QFormLayout over-reserves with hfw.
        return False

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x, y, line_h, sp = rect.x(), rect.y(), 0, self.spacing()
        for item in self._items:
            # Newly added widgets are shown on a deferred call, and QWidgetItem
            # reports 0x0 until then, so ask the widget directly.
            w = item.widget()
            hint = w.sizeHint() if w is not None else item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x = rect.x()
                y += line_h + sp
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + sp
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class _ChipBox(QWidget):
    """Holds a FlowLayout and keeps its own height equal to the rows actually used."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.flow = FlowLayout(self)

    def fit_height(self) -> None:
        h = max(self.flow.heightForWidth(max(self.width(), 1)), 1)
        if h != self.height():
            self.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_height()


class Chip(QFrame):
    removed = Signal(str)

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chip")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 1, 2, 1)
        h.setSpacing(2)
        h.addWidget(QLabel(text))
        x = QToolButton()
        x.setText("×")
        x.setAutoRaise(True)
        x.setFixedSize(18, 18)
        x.setToolTip(f"Remove “{text}”")
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.clicked.connect(lambda: self.removed.emit(text))
        h.addWidget(x)


class EntryPickerDialog(QDialog):
    """Checklist of every known entry; checked = on this card."""

    def __init__(self, noun_plural: str, entries: list[str], checked: list[str],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Choose {noun_plural}")
        self.setMinimumSize(320, 380)
        checked_keys = {c.casefold() for c in checked}
        self.checklist = SearchableChecklist(
            [(e, e, e.casefold() in checked_keys) for e in entries], "Filter list…",
            f"No {noun_plural} on this board yet", lambda n, total: f"{n} of {total} selected")
        self.search, self.list = self.checklist.search, self.checklist.list

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addWidget(self.checklist, 1)
        v.addWidget(buttons)

    def checked_values(self) -> list[str]:
        return self.checklist.checked_labels()


class TokenInput(QWidget):
    """Edits a list of strings. Type + Enter (or pick a suggestion) to add;
    × on a chip to remove; ▾ shows existing entries; List… opens a checklist."""

    changed = Signal()

    def __init__(self, values: list[str], suggestions: list[str], noun: str,
                 noun_plural: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._values = list(values)
        self._suggestions = list(suggestions)
        self._noun = noun
        self._noun_plural = noun_plural or noun + "s"
        self.setStyleSheet(theme.chip_stylesheet())

        self._chip_box = _ChipBox()
        self._flow = self._chip_box.flow

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(f"Type a {noun} and press Enter")
        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.edit.setCompleter(self._completer)
        self._completer.activated.connect(self._on_completion)
        self.edit.installEventFilter(self)

        drop = QToolButton()
        drop.setArrowType(Qt.ArrowType.DownArrow)
        drop.setToolTip(f"Show existing {self._noun_plural}")
        drop.clicked.connect(self.show_suggestions)
        add = QToolButton()
        add.setText("Add")
        add.setToolTip(f"Add the typed {noun}")
        add.clicked.connect(self._commit_text)
        pick = QToolButton()
        pick.setText("List…")
        pick.setToolTip(f"Check or uncheck from every {noun} on this board")
        pick.clicked.connect(self.open_picker)

        row = QHBoxLayout()
        row.setSpacing(2)
        row.addWidget(self.edit, 1)
        row.addWidget(drop)
        row.addWidget(add)
        row.addWidget(pick)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(self._chip_box)
        v.addLayout(row)
        self._render()

    # ----- public -----------------------------------------------------------
    def values(self) -> list[str]:
        return list(self._values)

    def add_value(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        key = text.casefold()
        if key in {v.casefold() for v in self._values}:
            return False
        # Reuse the board's existing spelling ("mara" -> "Mara").
        canonical = next((s for s in self._suggestions if s.casefold() == key), text)
        self._values.append(canonical)
        self._render()
        self.changed.emit()
        return True

    def commit_pending(self) -> bool:
        """Add whatever is still typed in the box (as if Enter were pressed)."""
        text = self.edit.text()
        if not text.strip():
            return False
        self.add_value(text)  # an existing entry is simply not duplicated
        self.edit.clear()
        return True

    def remove_value(self, text: str) -> None:
        self._values = [v for v in self._values if v.casefold() != text.casefold()]
        self._render()
        self.changed.emit()

    def set_values(self, values: list[str]) -> None:
        self._values = list(values)
        self._render()
        self.changed.emit()

    def all_entries(self) -> list[str]:
        merged = {s.casefold(): s for s in self._suggestions}
        for v in self._values:
            merged.setdefault(v.casefold(), v)
        return sorted(merged.values(), key=str.casefold)

    def show_suggestions(self) -> None:
        self.edit.setFocus()
        if self._model.rowCount() == 0:
            self.edit.setPlaceholderText(f"No other {self._noun_plural} yet. Type one and press Enter")
            return
        self._completer.setCompletionPrefix(self.edit.text())
        self._completer.complete()

    def open_picker(self) -> None:
        dlg = EntryPickerDialog(self._noun_plural, self.all_entries(), self._values, self)
        if dlg.exec():
            picked = dlg.checked_values()
            picked_keys = {p.casefold() for p in picked}
            current_keys = {v.casefold() for v in self._values}
            kept = [v for v in self._values if v.casefold() in picked_keys]
            self.set_values(kept + [p for p in picked if p.casefold() not in current_keys])

    # ----- internals --------------------------------------------------------
    def _render(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item.widget():
                item.widget().hide()  # deleteLater is deferred; don't leave it painted meanwhile
                item.widget().deleteLater()
        for v in self._values:
            chip = Chip(v)
            chip.removed.connect(self.remove_value)
            self._flow.addWidget(chip)
        if not self._values:
            empty = QLabel(f"No {self._noun_plural} yet")
            empty.setEnabled(False)
            self._flow.addWidget(empty)
        self._chip_box.fit_height()
        current = {v.casefold() for v in self._values}
        self._model.setStringList([s for s in self._suggestions if s.casefold() not in current])

    def _commit_text(self) -> None:
        if self.add_value(self.edit.text()):
            self.edit.clear()
        else:
            self.edit.selectAll()

    def _on_completion(self, text: str) -> None:
        self.add_value(text)
        QTimer.singleShot(0, self.edit.clear)  # after the completer writes its text

    def eventFilter(self, obj, event) -> bool:
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.edit.text().strip():
                self._commit_text()
                return True  # don't let Enter close the dialog
            if key == Qt.Key.Key_Backspace and not self.edit.text() and self._values:
                self.remove_value(self._values[-1])
                return True
            if key == Qt.Key.Key_Down and not self._completer.popup().isVisible():
                self.show_suggestions()
                return True
        return super().eventFilter(obj, event)
