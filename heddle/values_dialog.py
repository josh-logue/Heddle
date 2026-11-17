"""Checklist of strands (and custom colours) grouped by category, used for importing
strands from another board and for removing unused saved strands."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import theme
from .model import RENAMABLE_FIELDS
from .widgets import swatch_icon

COLORS_KEY = "custom_colors"
CATEGORY_LABELS = {"tags": "Tags", "characters": "Characters", "locations": "Locations",
                   "status": "Statuses", COLORS_KEY: "Custom colors"}
CATEGORY_ORDER = (*RENAMABLE_FIELDS, COLORS_KEY)
ROLE_VALUE = Qt.ItemDataRole.UserRole


class ValueChecklistDialog(QDialog):
    """`values` maps category -> list of values; all start checked. With `extra` (more
    values, same shape) and `extra_label`, a checkbox below the list adds those to it,
    marked ✎ (Remove Unused Strands: strands that have a description, picture or fields,
    or are in a strand group)."""

    def __init__(self, title: str, intro: str, values: dict[str, list[str]], ok_text: str,
                 parent: QWidget | None = None, extra: dict[str, list[str]] | None = None,
                 extra_label: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(400, 480)
        self._values = values
        self._extra = {k: v for k, v in (extra or {}).items() if v}

        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(theme.checkbox_stylesheet())
        self.tree.itemChanged.connect(self._update_ok)
        self.extra_check = QCheckBox(extra_label)
        self.extra_check.setVisible(bool(self._extra))
        self.extra_check.toggled.connect(self._fill)

        check_all = QPushButton("Check all")
        uncheck_all = QPushButton("Uncheck all")
        check_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        uncheck_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        self.count_label = QLabel()
        row = QHBoxLayout()
        row.addWidget(check_all)
        row.addWidget(uncheck_all)
        row.addStretch()
        row.addWidget(self.count_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(ok_text)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro_label)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.extra_check)
        layout.addLayout(row)
        layout.addWidget(self.buttons)
        self._fill()

    def _fill(self, *_args) -> None:
        """(Re)build the list; ticks already made are kept."""
        was = self.selected() if self.tree.topLevelItemCount() else None
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        extra = self._extra if self.extra_check.isChecked() else {}
        for cat in CATEGORY_ORDER:
            plain = list(self._values.get(cat) or [])
            more = [v for v in extra.get(cat, []) if v not in plain]
            if not plain and not more:
                continue
            top = QTreeWidgetItem(self.tree, [f"{CATEGORY_LABELS[cat]}   ({len(plain) + len(more)})"])
            top.setFont(0, bold)
            top.setData(0, ROLE_VALUE, cat)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                         | Qt.ItemFlag.ItemIsAutoTristate)
            for v in plain + more:
                child = QTreeWidgetItem(top, [v + ("  ✎" if v in more else "")])
                child.setData(0, ROLE_VALUE, v)
                child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                ticked = was is None or v in was.get(cat, []) or v in more
                child.setCheckState(0, Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)
                if v in more:
                    child.setToolTip(0, "Has a description, picture or fields, or is in a strand group: "
                                       "those go too")
                if cat == COLORS_KEY:
                    child.setIcon(0, swatch_icon(v))
            top.setExpanded(True)
        self.tree.blockSignals(False)
        self._update_ok()

    def _tops(self):
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _set_all(self, state: Qt.CheckState) -> None:
        for top in self._tops():
            top.setCheckState(0, state)  # auto-tristate pushes it to the children

    def selected(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for top in self._tops():
            chosen = [top.child(j).data(0, ROLE_VALUE) for j in range(top.childCount())
                      if top.child(j).checkState(0) == Qt.CheckState.Checked]
            if chosen:
                out[top.data(0, ROLE_VALUE)] = chosen
        return out

    def _update_ok(self, *_args) -> None:
        n = sum(len(v) for v in self.selected().values())
        total = sum(top.childCount() for top in self._tops())
        self.count_label.setText(f"{n} of {total} selected")
        self.ok_button.setEnabled(n > 0)
