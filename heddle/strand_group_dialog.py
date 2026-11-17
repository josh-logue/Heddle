"""Naming a strand group: a new one (which kind, and which strands to start with) or a
renamed one. The OK button stays off while the name is blank or the kind already has a
group by that name, with a note saying why."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from .model import RENAMABLE_FIELDS

KIND_GROUP_LABELS = {"tags": "Tags", "characters": "Characters", "locations": "Locations",
                     "status": "Statuses"}
_PLURAL = {"tags": "tags", "characters": "characters", "locations": "locations", "status": "statuses"}
_ONE = {"tags": "tag", "characters": "character", "locations": "location", "status": "status"}


def strands_text(n: int, kind: str) -> str:
    """'1 character', '3 statuses'."""
    return f"{n} {_ONE[kind] if n == 1 else _PLURAL[kind]}"


class StrandGroupDialog(QDialog):
    """`taken(kind, name)` says whether a name is already used. For a new group pass
    `picked` ({kind: [selected strands]}): the strands it starts with follow the kind
    chosen. For a rename pass `name` and leave `picked` as None: the kind is fixed."""

    def __init__(self, kind: str, taken: Callable[[str, str], bool], name: str = "",
                 picked: dict[str, list[str]] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._taken = taken
        self._picked = picked
        self._old = name.strip().casefold()
        renaming = picked is None
        self.setWindowTitle("Rename Strand Group" if renaming else "New Strand Group")
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("e.g. Family, Act 1 tags, The Wards")
        self.name_edit.selectAll()
        self.kind_combo = QComboBox()
        for k in RENAMABLE_FIELDS:
            self.kind_combo.addItem(KIND_GROUP_LABELS[k], k)
        self.kind_combo.setCurrentIndex(max(RENAMABLE_FIELDS.index(kind) if kind in RENAMABLE_FIELDS else 0, 0))
        self.kind_combo.setEnabled(not renaming)
        self.kind_combo.setToolTip("A strand group holds strands of one kind" if not renaming
                                   else "A strand group's kind can't change")
        self.members_note = QLabel()
        self.members_note.setWordWrap(True)
        self.members_note.setEnabled(False)   # muted
        self.members_note.setVisible(not renaming)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Kind", self.kind_combo)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Rename" if renaming else "Create")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(self.members_note)
        v.addWidget(self.problem)
        v.addWidget(self.buttons)
        self.name_edit.textChanged.connect(self._update)
        self.kind_combo.currentIndexChanged.connect(self._update)
        self.setMinimumWidth(340)
        self._update()

    def kind(self) -> str:
        return self.kind_combo.currentData()

    def name(self) -> str:
        return " ".join(self.name_edit.text().split())

    def members(self) -> list[str]:
        """The strands a new group starts with: the picked ones of its kind."""
        return list((self._picked or {}).get(self.kind(), []))

    def _update(self, *_args) -> None:
        name, kind = self.name(), self.kind()
        problem = ""
        if name and name.casefold() != self._old and self._taken(kind, name):
            problem = f"There's already a {_ONE[kind]} strand group called “{name}”."
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(name) and not problem)
        if self._picked is not None:
            n = len(self.members())
            self.members_note.setText(
                f"It starts with the {strands_text(n, kind)} you picked." if n else
                f"It starts empty. Tick {_PLURAL[kind]} in its member list, or right-click "
                f"one and choose Add to Strand Group.")
