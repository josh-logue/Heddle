"""Light/dark color themes for the canvas, cards, arrows and app widgets."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    dark: bool
    canvas_bg: QColor
    grid_minor: QColor
    grid_major: QColor
    card_bg: QColor
    card_border: QColor
    card_text: QColor
    card_muted: QColor
    card_shadow: QColor
    port_ring: QColor
    edge_line: QColor
    edge_hover: QColor
    edge_label_bg: QColor
    edge_text: QColor
    selected: QColor
    highlight: QColor  # outline of cards/arrows lit by a path or thread highlight


LIGHT = Theme(
    dark=False,
    canvas_bg=QColor("#f3f1ec"),
    grid_minor=QColor("#e7e4dc"),
    grid_major=QColor("#d9d5cb"),
    card_bg=QColor("#fffdf8"),
    card_border=QColor("#cfcac0"),
    card_text=QColor("#2b2b2b"),
    card_muted=QColor("#8a857c"),
    card_shadow=QColor(0, 0, 0, 35),
    port_ring=QColor("#ffffff"),
    edge_line=QColor("#8a857c"),
    edge_hover=QColor("#4f4b45"),
    edge_label_bg=QColor("#fffdf8"),
    edge_text=QColor("#2b2b2b"),
    selected=QColor("#ff8c1a"),
    highlight=QColor("#1f8a96"),
)

DARK = Theme(
    dark=True,
    canvas_bg=QColor("#1c1d20"),
    grid_minor=QColor("#24262a"),
    grid_major=QColor("#2e3035"),
    card_bg=QColor("#2c2e33"),
    card_border=QColor("#43464d"),
    card_text=QColor("#e4e4e6"),
    card_muted=QColor("#9b9ea6"),
    card_shadow=QColor(0, 0, 0, 120),
    port_ring=QColor("#1c1d20"),
    edge_line=QColor("#8c9099"),
    edge_hover=QColor("#c9ccd3"),
    edge_label_bg=QColor("#2c2e33"),
    edge_text=QColor("#e4e4e6"),
    selected=QColor("#ff9d3d"),
    highlight=QColor("#4cc3cf"),
)

_current: Theme = LIGHT
_CHECK_SVG = (Path(__file__).parent / "assets" / "check.svg").as_posix()
_DASH_SVG = (Path(__file__).parent / "assets" / "dash.svg").as_posix()
ACCENT = "#4a7fc1"


def checkbox_stylesheet() -> str:
    """Explicit item-view checkboxes; Fusion's default outline vanishes in dark mode."""
    border, bg = ("#8c9099", "#2c2e33") if _current.dark else ("#9a958c", "#ffffff")
    return f"""
        QAbstractItemView::indicator {{
            width: 13px; height: 13px; border: 1px solid {border};
            border-radius: 3px; background: {bg};
        }}
        QAbstractItemView::indicator:hover {{ border-color: {ACCENT}; }}
        QAbstractItemView::indicator:checked {{
            background: {ACCENT}; border-color: {ACCENT}; image: url("{_CHECK_SVG}");
        }}
        QAbstractItemView::indicator:indeterminate {{
            background: {ACCENT}; border-color: {ACCENT}; image: url("{_DASH_SVG}");  /* quoted: paths may contain spaces/brackets */
        }}
    """


def banner_stylesheet() -> str:
    """The 'Filter on' bar floating over the canvas."""
    if _current.dark:
        bg, text, btn_bg, btn_border = "#26364d", "#e4e8ef", "#31445f", "#4a6286"
    else:
        bg, text, btn_bg, btn_border = "#e3ecf8", "#1f2d40", "#f5f8fd", "#a9bfdd"
    return f"""
        QFrame#filterBanner {{
            background: {bg}; border: 1px solid {ACCENT}; border-radius: 8px;
        }}
        QFrame#filterBanner QLabel {{ color: {text}; background: transparent; border: none; }}
        QFrame#filterBanner QPushButton {{
            color: {text}; background: {btn_bg}; border: 1px solid {btn_border};
            border-radius: 5px; padding: 3px 10px;
        }}
        QFrame#filterBanner QPushButton:hover {{ border-color: {ACCENT}; }}
    """


def filter_button_stylesheet(active: bool) -> str:
    """Toolbar Filter button: accent-filled while a filter is active."""
    if not active:
        return ""
    return (f"QToolButton {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT};"
            f" border-radius: 4px; padding: 2px 6px; font-weight: bold; }}"
            f"QToolButton:hover {{ background: #5a8fd1; }}")


def chip_stylesheet() -> str:
    border, bg = ("#55585f", "#35373c") if _current.dark else ("#c9c4ba", "#f1eee8")
    return f"""
        QFrame#chip {{ border: 1px solid {border}; border-radius: 10px; background: {bg}; }}
        QFrame#chip QLabel {{ background: transparent; border: none; }}
        QFrame#chip QToolButton {{ border: none; background: transparent; padding: 0; }}
        QFrame#chip QToolButton:hover {{ color: {ACCENT}; }}
    """


@contextmanager
def temporarily(t: Theme):
    """Draw with theme `t` inside the block (e.g. a light-theme export from dark
    mode), then go back to the current one. App widgets aren't restyled."""
    global _current
    previous = _current
    _current = t
    try:
        yield t
    finally:
        _current = previous


def current() -> Theme:
    return _current


def system_prefers_dark() -> bool:
    app = QApplication.instance()
    return bool(app) and app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def _dark_palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: "#2b2d31",
        QPalette.ColorRole.WindowText: "#e4e4e6",
        QPalette.ColorRole.Base: "#232428",
        QPalette.ColorRole.AlternateBase: "#2b2d31",
        QPalette.ColorRole.ToolTipBase: "#2b2d31",
        QPalette.ColorRole.ToolTipText: "#e4e4e6",
        QPalette.ColorRole.PlaceholderText: "#8a8d93",
        QPalette.ColorRole.Text: "#e4e4e6",
        QPalette.ColorRole.Button: "#35373c",
        QPalette.ColorRole.ButtonText: "#e4e4e6",
        QPalette.ColorRole.BrightText: "#ff6b6b",
        QPalette.ColorRole.Link: "#6ea8fe",
        QPalette.ColorRole.Highlight: "#4a7fc1",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Light: "#45484e",
        QPalette.ColorRole.Midlight: "#3a3c41",
        QPalette.ColorRole.Mid: "#2a2c30",
        QPalette.ColorRole.Dark: "#18191b",
        QPalette.ColorRole.Shadow: "#000000",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    disabled = QColor("#6b6e74")
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def apply(dark: bool) -> None:
    """Switch the active theme and restyle the app's widgets to match."""
    global _current
    _current = DARK if dark else LIGHT
    app = QApplication.instance()
    if app is None:
        return
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):  # Qt 6.8+
        hints.setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
    app.setPalette(_dark_palette() if dark else app.style().standardPalette())
