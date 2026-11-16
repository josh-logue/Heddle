"""Pick one of a board's backups to restore."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QWidget,
)

from .model import load_board

ROLE_PATH = Qt.ItemDataRole.UserRole


def describe(when: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if when.date() == now.date():
        day = "Today"
    elif (now.date() - when.date()).days == 1:
        day = "Yesterday"
    else:
        day = when.strftime("%a %d %b %Y")
    return f"{day}, {when.strftime('%H:%M:%S')}"


class BackupDialog(QDialog):
    def __init__(self, board_name: str, backups: list[tuple[Path, datetime]], folder: Path,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Restore from backup")
        self.resize(440, 420)
        self._folder = folder

        intro = QLabel(f"Earlier versions of <b>{board_name}</b>, newest first. Restoring "
                       "replaces what's on the canvas; you can undo it, and nothing is written "
                       "to the file until you save.")
        intro.setWordWrap(True)

        self.list = QListWidget()
        for path, when in backups:
            try:
                n = len(load_board(path).cards)
                info = f"{n} card{'s' if n != 1 else ''}"
            except Exception:  # damaged backup: still listed, restore will report it
                info = "unreadable"
            item = QListWidgetItem(f"{describe(when)}   ·   {info}")
            item.setData(ROLE_PATH, str(path))
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Restore")
        folder_btn = QPushButton("Show Folder")
        folder_btn.setAutoDefault(False)
        folder_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._folder))))
        buttons.addButton(folder_btn, QDialogButtonBox.ButtonRole.HelpRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)

    def selected_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(item.data(ROLE_PATH)) if item else None

    def selected_label(self) -> str:
        item = self.list.currentItem()
        return item.text().split("   ·   ")[0] if item else ""
