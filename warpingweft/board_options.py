"""View → Board Options…: every display option of the open board in one place.
They're saved with the board, and OK applies the changes as one undo step."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget,
)

from .model import DISPLAY_DEFAULTS

# (section, [(option, label, tooltip)]) in the order shown.
SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Card face", [
        ("show_tags", "Tags", "Tag pills on each card (tags still work in filters when hidden)"),
        ("show_pov", "POV", "Each card's point-of-view character"),
        ("show_characters", "Characters", "Each card's characters as pills"),
        ("show_introductions", "★ introductions",
         "A ★ on cards that introduce a character, and an Introduces line in their details"),
        ("show_group_count", "Group card count", "\"N cards\" in each group's title bar"),
        ("show_shadows", "Card shadows", "A drop shadow under each card"),
        ("show_no_description", "“No description”",
         "The words on cards that have no description. Hidden, a card with nothing else on "
         "its face keeps the space blank; one showing tags, POV or characters closes it up"),
    ]),
    ("Canvas and arrows", [
        ("show_handles", "Connection handles",
         "The ● handle for dragging out arrows. Hidden, arrows are still made with "
         "right-click → Connect to…"),
        ("show_arrow_labels", "Arrow labels", "Label text on arrows (hidden: shown when you point at one)"),
        ("show_grid", "Grid", "The background grid (snapping to it works either way)"),
    ]),
    ("Story", [
        ("story_tools", "Story tools",
         "★ introductions, the Introduces filter, Story Checks, Routes, the Path Reader and "
         "character threads. Turn off for a board that just sorts things into groups."),
        ("follow_paths", "Highlight paths of selection", "Selecting a card lights up its paths"),
    ]),
]
ROUTINGS = [("straight", "Straight"), ("curved", "Curved"), ("avoid", "Curved, avoiding cards")]


class BoardOptionsDialog(QDialog):
    def __init__(self, display: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Board Options")
        intro = QLabel("These are saved with this board.")
        intro.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        self.checks: dict[str, QCheckBox] = {}
        for title, options in SECTIONS:
            box = QGroupBox(title)
            v = QVBoxLayout(box)
            for key, label, tip in options:
                check = QCheckBox(label)
                check.setToolTip(tip)
                check.setChecked(bool(display.get(key, DISPLAY_DEFAULTS[key])))
                self.checks[key] = check
                v.addWidget(check)
            if title == "Canvas and arrows":
                self.routing = QComboBox()
                for key, label in ROUTINGS:
                    self.routing.addItem(label, key)
                current = display.get("arrow_routing", DISPLAY_DEFAULTS["arrow_routing"])
                self.routing.setCurrentIndex(max(0, self.routing.findData(current)))
                form = QFormLayout()
                form.addRow("Arrows", self.routing)
                v.addLayout(form)
            layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        out = {key: check.isChecked() for key, check in self.checks.items()}
        out["arrow_routing"] = self.routing.currentData()
        return out
