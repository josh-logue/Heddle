"""Export the board (or the selected cards) as a PNG image, SVG or PDF."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator

from . import theme
from .card_item import CardItem
from .edge_item import EdgeItem

MARGIN = 30.0            # around the exported cards, in board units
MAX_PNG_SIDE = 16000     # pixels; bigger images get unwieldy (SVG has no limit)
# PDF pages bigger than 200 inches (14,400 pt) on a side won't open in many readers
# (Acrobat among them), so a bigger board is scaled down to fit. It's vector, so
# zooming in on the page still shows everything sharply.
MAX_PDF_POINTS = 14400.0
PT_PER_UNIT = 0.75       # board units are 1/96 inch; PDF points are 1/72 inch
FORMATS = (".png", ".svg", ".pdf")


class ExportTooLarge(ValueError):
    """The PNG would be bigger than MAX_PNG_SIDE on a side."""


@dataclass
class ImageOptions:
    selection_only: bool = False  # just the selected cards (and arrows between them)
    scale: float = 2.0            # PNG only: pixels per board unit
    transparent: bool = False     # no background at all (else the canvas colour, no grid)
    light: bool = False           # force the light theme (e.g. for printing)
    as_shown: bool = False        # keep the filter's and highlight's fading


def export_items(scene, selection_only: bool) -> tuple[list[CardItem], list[EdgeItem]]:
    """The cards and arrows to export: everything, or the selected cards plus the
    contents of selected groups and the arrows between exported cards."""
    # Cards folded inside a collapsed group (and their merged arrows) aren't drawn.
    if not selection_only:
        return ([i for i in scene.cards.values() if i.isVisible()],
                [e for e in scene.edges if e.isVisible()])
    cards = {i for i in scene.selectedItems() if isinstance(i, CardItem)}
    for item in list(cards):
        if item.is_group:
            cards |= scene.descendants(item)
    cards = {i for i in cards if i.isVisible()}
    edges = [e for e in scene.edges if e.isVisible() and set(e.ends()) <= cards]
    return list(cards), edges


def export_rect(cards: list[CardItem], edges: list[EdgeItem]) -> QRectF:
    rect = QRectF()
    for item in [*cards, *edges]:
        r = item.card_scene_rect() if isinstance(item, CardItem) else item.sceneBoundingRect()
        rect = r if rect.isNull() else rect.united(r)
    return rect.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)


@contextmanager
def _prepared(scene, options: ImageOptions, cards, edges):
    """Make the board look right for export, and put everything back afterwards:
    no selection, hover or grid; unexported items hidden; fading removed unless
    `as_shown`; the light theme if asked."""
    selected = scene.selectedItems()
    scene.clearSelection()
    keep = set(cards) | set(edges)
    hidden = [i for i in [*scene.cards.values(), *scene.edges] if i not in keep and i.isVisible()]
    for i in hidden:
        i.setVisible(False)
    dimmed = [c for c in scene.cards.values() if c.dimmed] if not options.as_shown else []
    try:
        with scene.export_view(keep_highlight=options.as_shown), \
                theme.temporarily(theme.LIGHT if options.light else theme.current()):
            for c in dimmed:
                c.set_dimmed(False)
            if dimmed:
                for e in scene.edges:
                    e.refresh_opacity()
            scene.export_background = "transparent" if options.transparent else "plain"
            try:
                yield
            finally:
                scene.export_background = None
                for c in dimmed:
                    c.set_dimmed(True)
                if dimmed:
                    for e in scene.edges:
                        e.refresh_opacity()
    finally:
        for i in hidden:
            i.setVisible(True)
        for i in selected:
            if i.scene() is scene:
                i.setSelected(True)


def export_image(scene, path: Path, options: ImageOptions | None = None) -> QSize:
    """Write the board to `path` (.png, .svg or .pdf). Returns the output size in
    pixels (PNG) or board units (SVG / PDF). Raises ExportTooLarge for an
    oversized PNG and ValueError for an unknown file type or nothing to export."""
    options = options or ImageOptions()
    path = Path(path)
    kind = path.suffix.lower()
    if kind not in FORMATS:
        raise ValueError(f"Can't export to {path.suffix or 'a file without an extension'}: "
                         "use .png, .svg or .pdf")
    cards, edges = export_items(scene, options.selection_only)
    if not cards:
        raise ValueError("There's nothing to export" +
                         (": no cards are selected" if options.selection_only else ""))
    source = export_rect(cards, edges)
    w, h = source.width(), source.height()
    if kind == ".png":
        scale = max(options.scale, 1.0)  # below 1, card text would be dropped as unreadable
        size = QSize(round(w * scale), round(h * scale))
        if max(size.width(), size.height()) > MAX_PNG_SIDE:
            raise ExportTooLarge(
                f"The image would be {size.width()} × {size.height()} pixels. Use a smaller "
                f"scale, export the selection only, or export as SVG or PDF instead.")
    else:
        size = QSize(round(w), round(h))

    with _prepared(scene, options, cards, edges):
        if kind == ".png":
            image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            _render(painter, scene, QRectF(0, 0, size.width(), size.height()), source)
            painter.end()
            if not image.save(str(path)):
                raise OSError(f"Couldn't write {path}")
        elif kind == ".svg":
            gen = QSvgGenerator()
            gen.setFileName(str(path))
            gen.setSize(size)
            gen.setViewBox(QRect(0, 0, size.width(), size.height()))
            gen.setTitle(path.stem)
            painter = QPainter(gen)
            _render(painter, scene, QRectF(0, 0, size.width(), size.height()), source)
            painter.end()
        else:  # PDF: one page exactly the board's shape, shrunk if it's too big to open
            writer = QPdfWriter(str(path))
            writer.setTitle(path.stem)
            writer.setPageSize(QPageSize(pdf_page_size(w, h), QPageSize.Unit.Point,
                                         path.stem, QPageSize.SizeMatchPolicy.ExactMatch))
            writer.setPageMargins(QMarginsF(0, 0, 0, 0))
            painter = QPainter(writer)
            _render(painter, scene, QRectF(0, 0, writer.width(), writer.height()), source)
            painter.end()
    return size


def pdf_page_size(w: float, h: float) -> QSizeF:
    """The PDF page (in points) for a board area of w × h board units: actual size
    (1 unit = 1/96 inch), scaled down to keep both sides within MAX_PDF_POINTS."""
    pw, ph = w * PT_PER_UNIT, h * PT_PER_UNIT
    fit = min(1.0, MAX_PDF_POINTS / max(pw, ph, 1e-9))
    return QSizeF(pw * fit, ph * fit)


def _render(painter: QPainter, scene, target: QRectF, source: QRectF) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, target, source, Qt.AspectRatioMode.KeepAspectRatio)
