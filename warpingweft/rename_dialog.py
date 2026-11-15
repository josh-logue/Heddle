"""Dialog for renaming a strand (a tag, character, location or status) on every card."""
from __future__ import annotations

from html import escape

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QVBoxLayout, QWidget,
)

from .model import RENAMABLE_FIELDS, CardData, count_values

FIELD_LABELS = {"tags": "Tag", "characters": "Character", "locations": "Location",
                "status": "Status"}


def value_counts(cards: list[CardData], field_name: str, saved=()) -> list[tuple[str, int]]:
    """(display spelling, number of cards) for each distinct value, alphabetical.
    Saved values no card uses are included with a count of 0."""
    return sorted(count_values(cards, field_name, saved).values(), key=lambda t: t[0].casefold())


def confirm_text(old: str, new: str, count: int, merge_with: str | None) -> str:
    noun = "card" if count == 1 else "cards"
    effect = f"This changes {count} {noun}." if count else "No card uses this strand yet."
    text = (f"Are you sure you want to rename <b><i>{escape(old)}</i></b> to "
            f"<b><i>{escape(new)}</i></b>?<br><br>{effect}")
    if merge_with is not None:
        text += (f"<br><i>{escape(merge_with)}</i> already exists, so the two will be merged "
                 f"into one entry.")
    return text


class RenameDialog(QDialog):
    def __init__(self, cards: list[CardData], field_name: str = "tags", value: str = "",
                 parent: QWidget | None = None, saved_values: dict[str, list[str]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Rename strand")
        self.setMinimumWidth(380)
        self._cards = cards
        self._saved = saved_values or {}
        self._counts: dict[str, int] = {}

        self.field_combo = QComboBox()
        for name in RENAMABLE_FIELDS:
            self.field_combo.addItem(FIELD_LABELS[name], name)
        self.value_combo = QComboBox()
        self.value_combo.setMinimumContentsLength(18)
        self.new_edit = QLineEdit()
        self.new_edit.setPlaceholderText("New name")
        self.empty_label = QLabel()
        self.empty_label.setEnabled(False)

        form = QFormLayout()
        form.addRow("Rename a:", self.field_combo)
        form.addRow("Current name:", self.value_combo)
        form.addRow("New name:", self.new_edit)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Rename…")
        self.buttons.accepted.connect(self._submit)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.buttons)

        self.field_combo.currentIndexChanged.connect(self._fill_values)
        self.value_combo.currentIndexChanged.connect(self._on_value_changed)
        self.new_edit.textChanged.connect(self._update_ok)

        idx = self.field_combo.findData(field_name)
        self.field_combo.setCurrentIndex(max(idx, 0))
        self._fill_values()
        if value:
            idx = next((i for i in range(self.value_combo.count())
                        if self.value_combo.itemData(i).casefold() == value.casefold()), -1)
            if idx >= 0:
                self.value_combo.setCurrentIndex(idx)
                self.new_edit.setFocus()
        self._update_ok()

    # ----- results ----------------------------------------------------------
    def field_name(self) -> str:
        return self.field_combo.currentData()

    def old_value(self) -> str:
        return self.value_combo.currentData() or ""

    def new_value(self) -> str:
        return self.new_edit.text().strip()

    # ----- internals --------------------------------------------------------
    def _fill_values(self) -> None:
        values = value_counts(self._cards, self.field_name(),
                              self._saved.get(self.field_name(), ()))
        self._counts = {v.casefold(): n for v, n in values}
        self.value_combo.blockSignals(True)
        self.value_combo.clear()
        for v, n in values:
            self.value_combo.addItem(f"{v}   ({n})" if n else f"{v}   (unused)", v)
        self.value_combo.blockSignals(False)
        label = FIELD_LABELS[self.field_name()].lower()
        self.empty_label.setText("" if values else f"No card has a {label} yet.")
        self.empty_label.setVisible(not values)
        self.value_combo.setEnabled(bool(values))
        self._on_value_changed()

    def _on_value_changed(self, *_args) -> None:
        self.new_edit.setText(self.old_value())
        self.new_edit.selectAll()
        self._update_ok()

    def _update_ok(self, *_args) -> None:
        new, old = self.new_value(), self.old_value()
        # A case-only change (e.g. "rowan" -> "Rowan") is a valid rename.
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(old) and bool(new) and new != old)

    def _merge_target(self) -> str | None:
        new_key = self.new_value().casefold()
        if new_key == self.old_value().casefold():
            return None
        for i in range(self.value_combo.count()):
            v = self.value_combo.itemData(i)
            if v.casefold() == new_key:
                return v
        return None

    def _submit(self) -> None:
        old, new = self.old_value(), self.new_value()
        if not old or not new or old == new:
            return
        count = self._counts.get(old.casefold(), 0)
        answer = QMessageBox.question(
            self, "Confirm rename", confirm_text(old, new, count, self._merge_target()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.accept()
        # "No" leaves the dialog open so the name can be corrected.
