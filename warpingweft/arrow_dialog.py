"""Editor for one or several arrows: label, line style and color."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from . import theme
from .dialogs import ColorSwatch
from .edge_item import DASH_PATTERNS
from .model import ARROW_STYLES, CARD_COLORS, ConnectionData

STYLE_LABELS = {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted"}
SWATCH_COLUMNS = 10


def style_icon(style: str, color: QColor | None = None, size: QSize = QSize(46, 14)) -> QIcon:
    """A short horizontal line in the given style, for buttons and menus."""
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color or theme.current().edge_line, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    if style in DASH_PATTERNS:
        pen.setDashPattern(DASH_PATTERNS[style])
    p.setPen(pen)
    y = size.height() / 2
    p.drawLine(QPointF(3, y), QPointF(size.width() - 3, y))
    p.end()
    return QIcon(pm)


class ArrowDialog(QDialog):
    """Edits the arrows passed in. For several arrows, anything left untouched (no
    style or color chosen while they differ) stays as it is on each arrow, and the
    label isn't offered. After exec(): label(), style(), color() give the choices
    (None = leave as is), and added_custom_colors any colors added to the palette."""

    def __init__(self, conns: list[ConnectionData], custom_colors=(), parent: QWidget | None = None):
        super().__init__(parent)
        self._conns = conns
        single = len(conns) == 1
        self.setWindowTitle("Edit arrow" if single else f"Edit {len(conns)} arrows")
        self.added_custom_colors: list[str] = []

        self.label_edit = QLineEdit(conns[0].label if single else "")
        self.label_edit.setPlaceholderText('Optional, e.g. "if she refuses"')

        # Line style: one toggle button per style, showing what it looks like.
        self._style_group = QButtonGroup(self)
        style_row = QHBoxLayout()
        style_row.setContentsMargins(0, 0, 0, 0)
        common_style = conns[0].style if all(c.style == conns[0].style for c in conns) else None
        self.style_buttons: dict[str, QToolButton] = {}
        for key in ARROW_STYLES:
            b = QToolButton()
            b.setCheckable(True)
            b.setText(STYLE_LABELS[key])
            b.setIcon(style_icon(key))
            b.setIconSize(QSize(46, 14))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setChecked(key == common_style)
            self._style_group.addButton(b)
            self.style_buttons[key] = b
            style_row.addWidget(b)
        style_row.addStretch()
        style_box = QWidget()
        style_box.setLayout(style_row)

        # Color: the theme's arrow color, the card palette, the board's custom colors.
        common_color = conns[0].color if all(c.color == conns[0].color for c in conns) else None
        self._color: str | None = common_color
        self._swatch_group = QButtonGroup(self)
        self._swatches: list[tuple[ColorSwatch, str]] = []
        self._grid = QGridLayout()
        self._grid.setSpacing(2)
        self._grid.setContentsMargins(0, 0, 0, 0)
        default = ColorSwatch(theme.current().edge_line.name(), False, self)
        default.setToolTip("Default (follows the light/dark theme)")
        self._add_swatch(default, "")
        for c in CARD_COLORS:
            self._add_swatch(ColorSwatch(c, False, self), c)
        for c in custom_colors:
            self._add_swatch(ColorSwatch(QColor(c).name(), True, self), QColor(c).name())
        if common_color and not any(v == common_color for _, v in self._swatches):
            self._add_swatch(ColorSwatch(common_color, True, self), common_color)
            self.added_custom_colors.append(common_color)
        custom_btn = QPushButton("Custom color…")
        custom_btn.setAutoDefault(False)
        custom_btn.clicked.connect(self._pick_custom_color)
        self.color_label = QLabel()
        bottom = QHBoxLayout()
        bottom.addWidget(self.color_label)
        bottom.addStretch()
        bottom.addWidget(custom_btn)
        color_box = QWidget()
        cv = QVBoxLayout(color_box)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addLayout(self._grid)
        cv.addLayout(bottom)
        self._select_color(common_color)

        form = QFormLayout()
        if single:
            form.addRow("Label", self.label_edit)
        form.addRow("Line", style_box)
        form.addRow("Color", color_box)
        if not single:
            note = QLabel("Anything you leave unset stays as it is on each arrow.")
            note.setEnabled(False)
            form.addRow("", note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        if single:
            self.label_edit.setFocus()
            self.label_edit.selectAll()

    # ----- colors ---------------------------------------------------------------
    def _add_swatch(self, sw: ColorSwatch, value: str) -> None:
        sw.clicked.connect(lambda _=False, v=value: self._select_color(v))
        self._swatch_group.addButton(sw)
        self._swatches.append((sw, value))
        n = len(self._swatches) - 1
        self._grid.addWidget(sw, n // SWATCH_COLUMNS, n % SWATCH_COLUMNS)
        self._grid.setColumnStretch(SWATCH_COLUMNS, 1)

    def _select_color(self, value: str | None) -> None:
        self._color = value
        for sw, v in self._swatches:
            if v == value:
                sw.setChecked(True)
        if value is None:
            self.color_label.setText("<i>Mixed: unchanged</i>")
        else:
            self.color_label.setText("Selected: <b>default</b>" if value == "" else f"Selected: <b>{value}</b>")

    def _pick_custom_color(self) -> None:
        start = QColor(self._color) if self._color else theme.current().edge_line
        picked = QColorDialog.getColor(start, self, "Custom arrow color")
        if not picked.isValid():
            return
        name = picked.name()
        if not any(v == name for _, v in self._swatches):
            self._add_swatch(ColorSwatch(name, True, self), name)
            self.added_custom_colors.append(name)
        self._select_color(name)

    # ----- results ----------------------------------------------------------------
    def label(self) -> str | None:
        return self.label_edit.text().strip() if len(self._conns) == 1 else None

    def style(self) -> str | None:
        return next((k for k, b in self.style_buttons.items() if b.isChecked()), None)

    def color(self) -> str | None:
        return self._color
