"""The Help window (F1): the controls from controls.md, scrollable and resizable."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from .help_text import help_markdown


class HelpDialog(QDialog):
    """Not modal, so you can try things on the board while it's open."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("WarpingWeft controls")
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setMarkdown(help_markdown())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.browser, 1)
        layout.addWidget(buttons)
        # A comfortable reading size that always fits the screen (it scrolls inside).
        screen = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        width, height = 720, 760
        if avail is not None:
            width = min(width, int(avail.width() * 0.9))
            height = min(height, int(avail.height() * 0.85))
        self.resize(width, height)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
