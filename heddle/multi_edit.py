"""Edit several selected cards at once: colour, tags, characters and locations (add /
remove) and status. Every field starts as "no change", so cards keep whatever differs
between them."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QLabel, QVBoxLayout, QWidget,
)

from . import settings
from .details_form import STATUS_PRESETS
from .dialogs import SWATCH_COLUMNS, ColorSwatch
from .model import BULK_LIST_FIELDS, CARD_COLORS
from .token_input import STRAND_GROUPS_KEY, TokenInput

KEEP_STATUS = "(keep each card's status)"
SINGULAR = {"tags": "tag", "characters": "character", "locations": "location"}


class MultiEditDialog(QDialog):
    def __init__(self, count: int, custom_colors=(), suggestions: dict | None = None,
                 in_selection: dict | None = None, parent: QWidget | None = None):
        """suggestions: the board's strands per field (to add); in_selection: the values
        the selected cards have per field (to remove)."""
        super().__init__(parent)
        self.setWindowTitle(f"Edit {count} cards")
        self.setMinimumWidth(460)

        intro = QLabel(f"Changes apply to all <b>{count}</b> selected cards. Anything left as "
                       "it is stays different on each card.")
        intro.setWordWrap(True)

        # Colour: off = keep each card's colour; on = the chosen swatch for all.
        self.color_check = QCheckBox("Change color to:")
        self._swatches = QButtonGroup(self)
        self._swatches.setExclusive(True)
        grid = QGridLayout()
        grid.setSpacing(2)
        colours = list(CARD_COLORS) + [c for c in custom_colors if c not in CARD_COLORS]
        for i, c in enumerate(colours):
            sw = ColorSwatch(c, c not in CARD_COLORS, self)
            sw.setToolTip(c)
            sw.clicked.connect(lambda _=False: self.color_check.setChecked(True))
            self._swatches.addButton(sw)
            grid.addWidget(sw, i // SWATCH_COLUMNS, i % SWATCH_COLUMNS)
        grid.setColumnStretch(SWATCH_COLUMNS, 1)
        # No swatch starts selected, so nothing suggests a colour change until one is
        # picked; unticking "Change color" clears the pick again.
        self.color_check.toggled.connect(self._on_color_toggled)
        swatch_box = QWidget()
        swatch_box.setLayout(grid)

        suggestions, in_selection = suggestions or {}, in_selection or {}
        # Strand groups: picking one adds (or removes) all its strands.
        groups = suggestions.get(STRAND_GROUPS_KEY, {})
        self.adders: dict[str, TokenInput] = {}
        self.removers: dict[str, TokenInput] = {}
        for f in BULK_LIST_FIELDS:
            self.adders[f] = TokenInput([], list(suggestions.get(f, [])), SINGULAR[f], groups=groups.get(f))
            self.adders[f].edit.setPlaceholderText(f"{f.capitalize()} to add to every card")
            self.removers[f] = TokenInput([], list(in_selection.get(f, [])), SINGULAR[f], groups=groups.get(f))
            self.removers[f].edit.setPlaceholderText(f"{f.capitalize()} to remove from every card")
        self.add_tags, self.remove_tags = self.adders["tags"], self.removers["tags"]
        status_suggestions = suggestions.get("status", [])

        self.status_combo = QComboBox()
        self.status_combo.setEditable(True)
        presets = {s.casefold() for s in STATUS_PRESETS}
        self.status_combo.addItems([KEEP_STATUS] + STATUS_PRESETS
                                   + [s for s in status_suggestions if s.casefold() not in presets])
        self.status_combo.setToolTip("Leave as the first item to keep each card's status; "
                                     "choose the blank item to clear it")

        form = QFormLayout()
        form.addRow(self.color_check)
        form.addRow(swatch_box)
        for f in BULK_LIST_FIELDS:
            form.addRow(f"Add {f}:", self.adders[f])
            form.addRow(f"Remove {f}:", self.removers[f])
        form.addRow("Status:", self.status_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(f"Apply to {count} cards")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_color_toggled(self, on: bool) -> None:
        if not on and self._swatches.checkedButton() is not None:
            self._swatches.setExclusive(False)  # an exclusive group can't uncheck its last button
            self._swatches.checkedButton().setChecked(False)
            self._swatches.setExclusive(True)

    def accept(self) -> None:
        if settings.get("commit_pending_entries"):
            for box in (*self.adders.values(), *self.removers.values()):
                box.commit_pending()
        super().accept()

    # ----- results (None / empty = no change) ----------------------------------
    def color(self) -> str | None:
        if not self.color_check.isChecked():
            return None
        btn = self._swatches.checkedButton()
        return btn.color_name if btn is not None else None

    def status(self) -> str | None:
        text = self.status_combo.currentText()
        return None if text == KEEP_STATUS else text.strip()

    def to_add(self) -> dict[str, list[str]]:
        """{field: values to add to every card}, for the fields with any."""
        return {f: box.values() for f, box in self.adders.items() if box.values()}

    def to_remove(self) -> dict[str, list[str]]:
        return {f: box.values() for f, box in self.removers.items() if box.values()}
