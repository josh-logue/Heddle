"""Option dialogs for File → Export: the story as text, the board as an image or PDF.
The choices are remembered between sessions."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QRadioButton, QVBoxLayout, QWidget,
)

from . import settings
from .export import DOCUMENT, OUTLINE, TextOptions
from .export_image import ImageOptions

SCOPE_BOARD, SCOPE_SELECTION, SCOPE_ROUTE = "board", "selection", "route"


def _radios(choices, current, parent) -> tuple[QWidget, QButtonGroup, dict]:
    box = QWidget(parent)
    row = QVBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    group = QButtonGroup(box)
    buttons = {}
    for key, text, enabled in choices:
        b = QRadioButton(text)
        b.setEnabled(enabled)
        group.addButton(b)
        row.addWidget(b)
        buttons[key] = b
    pick = current if current in buttons and buttons[current].isEnabled() else choices[0][0]
    buttons[pick].setChecked(True)
    return box, group, buttons


def _checked(buttons: dict) -> str:
    return next(k for k, b in buttons.items() if b.isChecked())


def _flag(key: str, default: bool) -> bool:
    return settings.store().value(key, default, type=bool)


class ExportTextDialog(QDialog):
    """Scope (board / selection / route being read), layout, and what to include."""

    def __init__(self, has_selection: bool, has_route: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export story as text")
        store = settings.store()
        scope_box, _, self.scope = _radios(
            [(SCOPE_BOARD, "Whole board", True),
             (SCOPE_SELECTION, "Selected cards (and what's in selected groups)", has_selection),
             (SCOPE_ROUTE, "The route being read in the Path Reader", has_route)],
            SCOPE_ROUTE if has_route else SCOPE_BOARD, self)
        layout_box, _, self.layout_choice = _radios(
            [(DOCUMENT, "Document: a heading per group and card, with its text", True),
             (OUTLINE, "Outline: nested bullet points", True)],
            str(store.value("export/text/layout", DOCUMENT)), self)
        self.descriptions = QCheckBox("Descriptions")
        self.details = QCheckBox("Details (POV, characters, locations, status, tags)")
        self.notes = QCheckBox("Notes")
        self.next_steps = QCheckBox("Where each card leads (branches and arrow labels)")
        for box, key, default in ((self.descriptions, "descriptions", True), (self.details, "details", True),
                                  (self.notes, "notes", False), (self.next_steps, "next_steps", True)):
            box.setChecked(_flag(f"export/text/{key}", default))
        include = QWidget()
        iv = QVBoxLayout(include)
        iv.setContentsMargins(0, 0, 0, 0)
        for box in (self.descriptions, self.details, self.notes, self.next_steps):
            iv.addWidget(box)

        form = QFormLayout()
        form.addRow("Export", scope_box)
        form.addRow("Layout", layout_box)
        form.addRow("Include", include)
        note = QLabel("Cards are listed in story order, along the arrows. Saved as Markdown "
                      "(.md), which reads fine as plain text too.")
        note.setWordWrap(True)
        note.setEnabled(False)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export…")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(note)
        v.addWidget(buttons)

    def scope_choice(self) -> str:
        return _checked(self.scope)

    def options(self) -> TextOptions:
        return TextOptions(layout=_checked(self.layout_choice),
                           descriptions=self.descriptions.isChecked(),
                           details=self.details.isChecked(), notes=self.notes.isChecked(),
                           next_steps=self.next_steps.isChecked())

    def accept(self) -> None:
        store = settings.store()
        opt = self.options()
        store.setValue("export/text/layout", opt.layout)
        for key in ("descriptions", "details", "notes", "next_steps"):
            store.setValue(f"export/text/{key}", getattr(opt, key))
        super().accept()


class ExportImageDialog(QDialog):
    """Scope, PNG scale, background, theme, and whether to keep the fading."""

    SCALES = [("1× (screen size)", 1.0), ("2× (sharp)", 2.0), ("3× (print)", 3.0)]

    def __init__(self, has_selection: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export board as image or PDF")
        store = settings.store()
        scope_box, _, self.scope = _radios(
            [(SCOPE_BOARD, "Whole board", True),
             (SCOPE_SELECTION, "Selected cards (and what's in selected groups)", has_selection)],
            SCOPE_BOARD, self)
        self.scale = QComboBox()
        for text, value in self.SCALES:
            self.scale.addItem(text, value)
        saved = float(store.value("export/image/scale", 2.0))
        self.scale.setCurrentIndex(next((n for n, (_, v) in enumerate(self.SCALES) if v == saved), 1))
        self.transparent = QCheckBox("Transparent background (else the canvas colour, without the grid)")
        self.light = QCheckBox("Use the light theme (good for printing)")
        self.as_shown = QCheckBox("Keep the filter's and highlight's fading")
        for box, key, default in ((self.transparent, "transparent", False), (self.light, "light", False),
                                  (self.as_shown, "as_shown", False)):
            box.setChecked(_flag(f"export/image/{key}", default))
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale)
        scale_row.addWidget(QLabel("PNG only; SVG and PDF stay sharp at any size"))
        scale_row.addStretch()
        look = QWidget()
        lv = QVBoxLayout(look)
        lv.setContentsMargins(0, 0, 0, 0)
        for box in (self.transparent, self.light, self.as_shown):
            lv.addWidget(box)

        form = QFormLayout()
        form.addRow("Export", scope_box)
        form.addRow("PNG scale", scale_row)
        form.addRow("Look", look)
        note = QLabel("Choose PNG, SVG or PDF when saving. Handles, toggles and the selection "
                      "aren't drawn.")
        note.setWordWrap(True)
        note.setEnabled(False)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export…")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(note)
        v.addWidget(buttons)

    def options(self) -> ImageOptions:
        return ImageOptions(selection_only=_checked(self.scope) == SCOPE_SELECTION,
                            scale=float(self.scale.currentData()),
                            transparent=self.transparent.isChecked(), light=self.light.isChecked(),
                            as_shown=self.as_shown.isChecked())

    def accept(self) -> None:
        store = settings.store()
        opt = self.options()
        store.setValue("export/image/scale", opt.scale)
        for key in ("transparent", "light", "as_shown"):
            store.setValue(f"export/image/{key}", getattr(opt, key))
        super().accept()
