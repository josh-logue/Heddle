"""Settings panel: one checkbox per option in settings.OPTIONS."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QVBoxLayout, QWidget,
)

from . import settings


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)

        self.checks: dict[str, QCheckBox] = {}
        sections: dict[str, QVBoxLayout] = {}
        layout = QVBoxLayout(self)
        for key, (_default, section, label, tip) in settings.OPTIONS.items():
            if section not in sections:
                box = QGroupBox(section)
                sections[section] = QVBoxLayout(box)
                layout.addWidget(box)
            check = QCheckBox(label)
            check.setToolTip(tip)
            check.setChecked(settings.get(key))
            sections[section].addWidget(check)
            self.checks[key] = check

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addStretch()
        layout.addWidget(buttons)

    def accept(self) -> None:
        for key, check in self.checks.items():
            settings.set(key, check.isChecked())
        super().accept()
