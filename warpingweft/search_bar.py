"""Toolbar search box: find text in card titles, descriptions and notes and step
through the matches. The window supplies the matching and does the jumping."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget


class SearchBar(QWidget):
    query_changed = Signal(str)   # text edited: show the first match
    step = Signal(int)            # +1 next match, -1 previous
    cleared = Signal()            # Esc: leave the search

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Search cards (Ctrl+F)")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumWidth(220)
        self.edit.textChanged.connect(self.query_changed)
        self.edit.installEventFilter(self)
        self.count = QLabel()
        self.count.setMinimumWidth(56)
        self.count.setEnabled(False)  # muted text
        self.prev_btn = QToolButton(text="▲", toolTip="Previous match (Shift+Enter, Shift+F3)")
        self.next_btn = QToolButton(text="▼", toolTip="Next match (Enter, F3)")
        self.prev_btn.clicked.connect(lambda: self.step.emit(-1))
        self.next_btn.clicked.connect(lambda: self.step.emit(1))
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(2)
        row.addWidget(self.edit)
        row.addWidget(self.count)
        row.addWidget(self.prev_btn)
        row.addWidget(self.next_btn)
        self.show_count(0, 0)

    def text(self) -> str:
        return self.edit.text()

    def focus(self) -> None:
        self.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.edit.selectAll()

    def show_count(self, index: int, total: int) -> None:
        """index is 1-based; 0 means nothing selected yet."""
        if not self.edit.text().strip():
            self.count.setText("")
        elif total == 0:
            self.count.setText("No matches")
        else:
            self.count.setText(f"{index} of {total}" if index else f"{total} found")
        for b in (self.prev_btn, self.next_btn):
            b.setEnabled(total > 0)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                back = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                self.step.emit(-1 if back else 1)
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.edit.clear()
                self.cleared.emit()
                return True
        return False
