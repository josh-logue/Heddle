"""Editor for a route's own fields (Routes panel → Edit fields…)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from .details_form import DetailFields
from .model import RouteData


class RouteDialog(QDialog):
    def __init__(self, data: RouteData, steps: list[str], default_name: str,
                 suggestions: dict[str, list[str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit route")
        self.setMinimumWidth(460)
        self._key = list(data.key)

        path = QLabel(" → ".join(steps))
        path.setWordWrap(True)
        path.setEnabled(False)
        path.setToolTip("The cards this route passes through, in order")

        self.name_edit = QLineEdit(data.name)
        self.name_edit.setPlaceholderText(default_name)
        # Tags, characters, POV, locations, status, notes: the same as the card editor's.
        self.fields = DetailFields(data, suggestions, self)
        self.tags_input = self.fields.tags_input
        self.characters_input = self.fields.characters_input
        self.locations_input = self.fields.locations_input
        self.pov_combo = self.fields.pov_combo
        self.status_combo = self.fields.status_combo
        self.notes_edit = self.fields.notes_edit
        self.inherit_check = QCheckBox("Also show every strand its cards have")
        self.inherit_check.setChecked(data.inherit)
        self.inherit_check.setToolTip("Tags, characters, POV, locations and statuses of the "
                                      "route's cards are listed with its own. They follow the "
                                      "cards as you edit them; nothing is copied.")

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Tags", self.tags_input)
        self.fields.add_detail_rows(form)
        form.addRow("Inherit", self.inherit_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(path)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.name_edit.setFocus()

    def accept(self) -> None:
        self.fields.commit_pending()
        super().accept()

    def route_data(self) -> RouteData:
        return RouteData(key=list(self._key), name=self.name_edit.text().strip(),
                         inherit=self.inherit_check.isChecked(), **self.fields.values())
