"""Apply fields: copy one strand's custom field names to other strands of the same
kind (Strands panel → Apply to…). It only picks what to copy and where; the scene does
the copying (BoardScene.apply_strand_fields), as one undo step."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QScrollArea, QVBoxLayout, QWidget,
)

from . import theme

KIND_PLURAL = {"tags": "tags", "characters": "characters", "locations": "locations",
               "status": "statuses"}
KIND_ONE = {"tags": "tag", "characters": "character", "locations": "location", "status": "status"}
FIELD_LIST_MAX = 150  # px: the field checkboxes scroll past this height


class AllCheckBox(QCheckBox):
    """"All …": shows a part-ticked state when only some strands are ticked, but a
    click only ever ticks all (from none or some) or unticks all."""

    def nextCheckState(self) -> None:
        self.setCheckState(Qt.CheckState.Unchecked if self.checkState() == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)


class ApplyFieldsDialog(QDialog):
    def __init__(self, kind: str, source: str, fields, others: list[str],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Apply fields from “{source}”")
        self.resize(360, 500)
        plural = KIND_PLURAL.get(kind, "strands")

        intro = QLabel(f"Adds the ticked fields to the ticked {plural}, empty unless you tick "
                       f"“Also copy the values”. Fields a {KIND_ONE.get(kind, 'strand')} "
                       "already has keep their values, and nothing is removed.")
        intro.setWordWrap(True)

        fields_label = QLabel("<b>Fields</b>")
        self.field_checks: list[QCheckBox] = []
        field_box = QWidget()
        fv = QVBoxLayout(field_box)
        fv.setContentsMargins(0, 0, 0, 0)
        for name, value in fields:
            check = QCheckBox(name)
            check.setChecked(True)
            if value:
                check.setToolTip(f"{name}: {value}")
            check.toggled.connect(self._update_apply)
            fv.addWidget(check)
            self.field_checks.append(check)
        fv.addStretch()
        field_scroll = QScrollArea()
        field_scroll.setWidget(field_box)
        field_scroll.setWidgetResizable(True)
        field_scroll.setMaximumHeight(min(FIELD_LIST_MAX, field_box.sizeHint().height() + 4))

        to_label = QLabel(f"<b>To these {plural}</b>")
        self.all_check = AllCheckBox(f"All {plural} ({len(others)})")
        self.all_check.setEnabled(bool(others))
        self.all_check.stateChanged.connect(self._on_all)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Find {KIND_ONE.get(kind, 'strand')}")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.targets = QListWidget()
        self.targets.setStyleSheet(theme.checkbox_stylesheet())
        for name in others:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.targets.addItem(item)
        self.targets.itemChanged.connect(self._on_target)

        self.values_check = QCheckBox("Also copy the values (only into empty fields)")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(fields_label)
        layout.addWidget(field_scroll)
        layout.addWidget(to_label)
        layout.addWidget(self.all_check)
        layout.addWidget(self.search)
        layout.addWidget(self.targets, 1)
        layout.addWidget(self.values_check)
        layout.addWidget(buttons)
        self._update_apply()

    # ----- what was picked ---------------------------------------------------------------
    def selected_names(self) -> list[str]:
        return [c.text() for c in self.field_checks if c.isChecked()]

    def selected_targets(self) -> list[str]:
        return [item.text() for item in self._items() if item.checkState() == Qt.CheckState.Checked]

    def with_values(self) -> bool:
        return self.values_check.isChecked()

    def target_item(self, name: str) -> QListWidgetItem | None:
        return next((i for i in self._items() if i.text() == name), None)

    # ----- keeping it consistent -----------------------------------------------------------
    def _items(self):
        return [self.targets.item(r) for r in range(self.targets.count())]

    def _on_all(self, state) -> None:
        state = Qt.CheckState(state)
        if state == Qt.CheckState.PartiallyChecked:
            return
        self.targets.blockSignals(True)
        for item in self._items():  # all of them, found by the search or not
            item.setCheckState(state)
        self.targets.blockSignals(False)
        self._update_apply()

    def _on_target(self, _item=None) -> None:
        picked = len(self.selected_targets())
        state = (Qt.CheckState.Unchecked if not picked else
                 Qt.CheckState.Checked if picked == self.targets.count() else
                 Qt.CheckState.PartiallyChecked)
        self.all_check.blockSignals(True)
        self.all_check.setCheckState(state)
        self.all_check.blockSignals(False)
        self._update_apply()

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for item in self._items():
            item.setHidden(bool(needle) and needle not in item.text().casefold())

    def _update_apply(self) -> None:
        self.apply_button.setEnabled(bool(self.selected_names() and self.selected_targets()))
