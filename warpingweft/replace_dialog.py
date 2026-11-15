"""Edit → Replace…: find and replace text in cards' titles, descriptions and notes.
Strand names aren't touched here: Rename Strand (Ctrl+R) renames them everywhere."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QVBoxLayout, QWidget,
)

from .model import REPLACE_FIELDS, CardData, count_replacements


class ReplaceDialog(QDialog):
    def __init__(self, cards: list[CardData], selected_ids: list[str] = (),
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Replace")
        self.setMinimumWidth(400)
        self._cards = cards
        self._selected = set(selected_ids)

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Text to find")
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace with (empty removes it)")
        self.field_boxes: dict[str, QCheckBox] = {}
        fields_row = QHBoxLayout()
        for name, label in REPLACE_FIELDS:
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self._update)
            self.field_boxes[name] = box
            fields_row.addWidget(box)
        fields_row.addStretch()
        self.case_box = QCheckBox("Match case")
        self.selected_box = QCheckBox(f"Selected cards only ({len(self._selected)})")
        self.selected_box.setEnabled(bool(self._selected))
        self.selected_box.setChecked(len(self._selected) > 1)
        self.preview = QLabel()
        self.preview.setEnabled(False)
        hint = QLabel("To rename a tag, character, location or status everywhere, use "
                      "Edit → Rename Strand… (Ctrl+R).")
        hint.setWordWrap(True)
        hint.setEnabled(False)

        form = QFormLayout()
        form.addRow("Find:", self.find_edit)
        form.addRow("Replace with:", self.replace_edit)
        form.addRow("Look in:", fields_row)
        form.addRow("", self.case_box)
        form.addRow("", self.selected_box)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Replace All")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(hint)
        layout.addWidget(self.buttons)

        for w in (self.find_edit, self.case_box, self.selected_box):
            (w.textChanged if isinstance(w, QLineEdit) else w.toggled).connect(self._update)
        self._update()

    # ----- answers -------------------------------------------------------------------
    def find_text(self) -> str:
        return self.find_edit.text()

    def replacement(self) -> str:
        return self.replace_edit.text()

    def fields(self) -> list[str]:
        return [name for name, box in self.field_boxes.items() if box.isChecked()]

    def match_case(self) -> bool:
        return self.case_box.isChecked()

    def selected_only(self) -> bool:
        return self.selected_box.isEnabled() and self.selected_box.isChecked()

    # ----- preview -------------------------------------------------------------------
    def _update(self, *_args) -> None:
        cards = [c for c in self._cards if c.id in self._selected] if self.selected_only() else self._cards
        total, touched = count_replacements(cards, self.find_text(), self.fields(), self.match_case())
        if not self.find_text():
            self.preview.setText("")
        elif total:
            self.preview.setText(f"{total} match{'es' if total != 1 else ''} in "
                                 f"{touched} card{'s' if touched != 1 else ''} (one undo step)")
        else:
            self.preview.setText("No matches")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(total > 0)
