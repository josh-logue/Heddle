"""Strands: every strand on the board (the entries in its tags, characters,
locations and statuses), how much each is used, and each strand's own description
(also shown in its strand cards' details), custom fields (Age, Biome…) and picture
(only shown here). The fields and the picture each fold away under a header, so the
pane stays usable in a narrow dock.

Pictures are linked, not copied: the board keeps the image's path (see
model.StrandInfo). A picture whose file has gone shows its path and a Relink button.

A strand can be dragged from the list onto the board (see BoardScene.drop_strand)."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices, QDrag, QFont, QFontMetrics, QImageReader, QPainter, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .apply_fields_dialog import KIND_ONE, KIND_PLURAL, ApplyFieldsDialog
from .model import BUILTIN_STATUSES, RENAMABLE_FIELDS, StrandInfo
from .view import strand_mime

REFRESH_DELAY_MS = 300   # re-list this long after the board settles
COMMIT_DELAY_MS = 700    # a description is saved this long after you stop typing
PREVIEW_MAX = 260        # px: the picture preview fits in this square
FIELDS_VISIBLE_ROWS = 6  # the fields table grows to this many rows, then scrolls
NEW_FIELD_NAME = "Field"  # an added field's name until you type one ("Field 2"… if taken)
KIND_LABELS = {"tags": "Tags", "characters": "Characters", "locations": "Locations", "status": "Statuses"}
KIND_SINGULAR = {"tags": "tag", "characters": "character", "locations": "location", "status": "status"}
DETAILS_MARK = " ✎"      # after a strand's name in the list when it has details
ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_NAME = Qt.ItemDataRole.UserRole + 1
BUILTIN_KEYS = {s.casefold() for s in BUILTIN_STATUSES}


def is_builtin(kind: str, name: str) -> bool:
    """A status every board has (Draft, Final…): listed even when unused."""
    return kind == "status" and name.casefold() in BUILTIN_KEYS


def image_filter() -> str:
    """File-dialog filter for every image format Qt can read here."""
    exts = sorted({bytes(f).decode() for f in QImageReader.supportedImageFormats()})
    return "Images (" + " ".join(f"*.{e}" for e in exts) + ");;All files (*)"


def usage_text(cards: int, routes: int, strand_cards: int = 0, builtin: bool = False) -> str:
    bits = []
    if cards:
        bits.append(f"{cards} card" + ("" if cards == 1 else "s"))
    if routes:
        bits.append(f"{routes} route" + ("" if routes == 1 else "s"))
    if strand_cards:
        bits.append(f"{strand_cards} strand card" + ("" if strand_cards == 1 else "s"))
    return " · ".join(bits) or ("built-in" if builtin else "unused")


class StrandTree(QTreeWidget):
    """The strand list. A strand can be dragged onto the board. The drag is always a
    copy: Qt deletes the row after a "move", and the list must keep it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def drag_payload(self):
        """Drag data for the current strand, or None (a heading, or nothing picked)."""
        item = self.currentItem()
        name = item.data(0, ROLE_NAME) if item is not None else None
        return strand_mime(item.data(0, ROLE_KIND), name) if name is not None else None

    def startDrag(self, _actions) -> None:
        mime = self.drag_payload()
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(mime.text()))
        drag.setHotSpot(QPoint(-8, -8))  # the pill sits just below and right of the pointer
        drag.exec(Qt.DropAction.CopyAction)

    def _drag_pixmap(self, name: str) -> QPixmap:
        """A small pill with the strand's name, carried under the pointer."""
        metrics = QFontMetrics(self.font())
        text = metrics.elidedText(name, Qt.TextElideMode.ElideRight, 220)
        w, h = metrics.horizontalAdvance(text) + 16, metrics.height() + 8
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(round(w * ratio), round(h * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        p.setPen(pal.highlight().color())
        p.setBrush(pal.base())
        p.drawRoundedRect(QRect(0, 0, w - 1, h - 1), h / 2, h / 2)
        p.setPen(pal.text().color())
        p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        return pixmap


class StrandsPanel(QWidget):
    show_cards = Signal(list)  # CardItems to select and bring into view
    remove_unused_requested = Signal()  # the window runs Edit → Remove Unused Strands…

    def __init__(self, scene, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene = scene
        self._selected: tuple[str, str] | None = None   # (kind, casefolded name)
        self._collapsed: set[str] = set()
        self._folded: set[str] = set()   # detail sections folded away: "fields", "picture"
        self._shown: tuple | None = None
        self._previews: dict[str, tuple[float, QPixmap]] = {}  # path -> (mtime, scaled pixmap)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a strand")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        self.tree = StrandTree()
        self.tree.setToolTip("Drag a strand onto a card to add it to the card, or onto a "
                             "group or a blank spot for a strand card")
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setRootIsDecorated(True)
        self.tree.currentItemChanged.connect(self._on_current)
        self.tree.itemCollapsed.connect(lambda it: self._collapsed.add(it.data(0, ROLE_KIND)))
        self.tree.itemExpanded.connect(lambda it: self._collapsed.discard(it.data(0, ROLE_KIND)))
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(self.search)
        tv.addWidget(self.tree, 1)
        self.remove_unused_btn = QPushButton("Remove unused…")
        self.remove_unused_btn.setAutoDefault(False)
        self.remove_unused_btn.setToolTip("Pick strands that nothing on the board uses and take "
                                          "them off it (as Edit → Remove Unused Strands…)")
        self.remove_unused_btn.clicked.connect(self._remove_unused)
        unused_row = QHBoxLayout()
        unused_row.addStretch()
        unused_row.addWidget(self.remove_unused_btn)
        tv.addLayout(unused_row)

        self.details = self._build_details()
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(top)
        self.splitter.addWidget(self.details)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.splitter)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DELAY_MS)
        self._timer.timeout.connect(self.refresh)
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(COMMIT_DELAY_MS)
        self._commit_timer.timeout.connect(self.commit_description)
        scene.modified.connect(self.schedule)
        scene.history_changed.connect(self.schedule)
        scene.value_renamed.connect(self._on_renamed)
        self.refresh()

    # ----- the detail pane -------------------------------------------------------------
    def _build_details(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        self.title = QLabel()
        bold = QFont()
        bold.setBold(True)
        bold.setPointSizeF(bold.pointSizeF() + 1)
        self.title.setFont(bold)
        self.title.setWordWrap(True)
        self.usage = QLabel()
        self.usage.setEnabled(False)

        self.rename_btn = QPushButton("Rename…")
        self.rename_btn.setToolTip("Rename (or merge) it on every card and route")
        self.rename_btn.clicked.connect(self._rename)
        self.select_btn = QPushButton("Select cards")
        self.select_btn.setToolTip("Select the cards that have it and bring them into view")
        self.select_btn.clicked.connect(self._select_cards)
        self.thread_btn = QPushButton("Show thread")
        self.thread_btn.setToolTip("Light up every card featuring this character, in story order")
        self.thread_btn.clicked.connect(self._show_thread)
        self.add_card_btn = QPushButton("Add to board")
        self.add_card_btn.setToolTip("Put a strand card for it in the middle of the view: its "
                                     "name, with its description in the card's details")
        self.add_card_btn.clicked.connect(self._add_to_board)
        actions = QHBoxLayout()
        for b in (self.rename_btn, self.select_btn, self.thread_btn, self.add_card_btn):
            b.setAutoDefault(False)
            actions.addWidget(b)
        actions.addStretch()

        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Description…")
        self.description.textChanged.connect(self._on_typed)
        self.description.installEventFilter(self)

        self.fields_toggle = self._section_toggle("fields")
        self.fields_box = self._build_fields()

        self.picture_toggle = self._section_toggle("picture")
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumHeight(60)
        self.picture.setWordWrap(True)
        self.picture.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.choose_btn = QPushButton("Choose picture…")
        self.choose_btn.clicked.connect(self._choose_picture)
        self.remove_pic_btn = QPushButton("Remove")
        self.remove_pic_btn.setToolTip("Unlink the picture (the image file isn't touched)")
        self.remove_pic_btn.clicked.connect(lambda: self._set_picture(""))
        self.open_pic_btn = QPushButton("Open")
        self.open_pic_btn.setToolTip("Open the picture in your image viewer")
        self.open_pic_btn.clicked.connect(self._open_picture)
        pic_row = QHBoxLayout()
        for b in (self.choose_btn, self.remove_pic_btn, self.open_pic_btn):
            b.setAutoDefault(False)
            pic_row.addWidget(b)
        pic_row.addStretch()
        self.picture_box = QWidget()
        pv = QVBoxLayout(self.picture_box)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(self.picture)
        pv.addLayout(pic_row)
        self.clear_btn = QPushButton("Clear details")
        self.clear_btn.setToolTip("Remove its description, fields and picture (undo with Ctrl+Z)")
        self.clear_btn.setAutoDefault(False)
        self.clear_btn.clicked.connect(self._clear_details)
        clear_row = QHBoxLayout()
        clear_row.addStretch()
        clear_row.addWidget(self.clear_btn)

        self.empty = QLabel("Pick a strand above to see where it's used and give it a "
                            "description, fields and a picture.")
        self.empty.setWordWrap(True)
        self.empty.setEnabled(False)

        self._detail_widgets = [self.title, self.usage, self.description, self.fields_toggle,
                                self.picture_toggle]
        v.addWidget(self.empty)
        v.addWidget(self.title)
        v.addWidget(self.usage)
        v.addLayout(actions)
        v.addWidget(self.description, 1)
        v.addWidget(self.fields_toggle)
        v.addWidget(self.fields_box)
        v.addWidget(self.picture_toggle)
        v.addWidget(self.picture_box)
        v.addLayout(clear_row)
        self._buttons = [self.rename_btn, self.select_btn, self.thread_btn, self.add_card_btn, self.choose_btn,
                         self.remove_pic_btn, self.open_pic_btn, self.clear_btn]
        return box

    def _section_toggle(self, key: str) -> QToolButton:
        """A section's header: its name with ▾ (open) or ▸ (folded); a click folds it."""
        button = QToolButton()
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        font = button.font()
        font.setBold(True)
        button.setFont(font)
        button.clicked.connect(lambda: self._toggle_section(key))
        return button

    def _build_fields(self) -> QWidget:
        """The custom fields: a Field | Value table edited in place (each edit is one
        undo step), with buttons to add, remove and reorder fields."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        t = self.fields_table = QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(["Field", "Value"])
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(t.fontMetrics().height() + 8)  # compact rows
        header = t.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(0, 110)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        t.setToolTip("Double-click a name or value to change it")
        t.itemChanged.connect(self._on_field_edited)
        t.currentCellChanged.connect(lambda *_: self._update_field_buttons())
        self.fields_empty = QLabel("No fields yet. Add your own, such as age or biome.")
        self.fields_empty.setWordWrap(True)
        self.fields_empty.setEnabled(False)

        self.add_field_btn = QPushButton("Add field")
        self.add_field_btn.setToolTip("Add a field to this strand and type its name")
        self.add_field_btn.clicked.connect(self._add_field)
        self.remove_field_btn = QPushButton("Remove")
        self.remove_field_btn.setToolTip("Remove the picked field (undo with Ctrl+Z)")
        self.remove_field_btn.clicked.connect(self._remove_field)
        self.field_up_btn = QPushButton("▲")
        self.field_up_btn.setToolTip("Move the picked field up")
        self.field_up_btn.clicked.connect(lambda: self._move_field(-1))
        self.field_down_btn = QPushButton("▼")
        self.field_down_btn.setToolTip("Move the picked field down")
        self.field_down_btn.clicked.connect(lambda: self._move_field(1))
        self.apply_fields_btn = QPushButton("Apply to…")
        self.apply_fields_btn.setToolTip("Copy these fields' names to other strands of the same kind")
        self.apply_fields_btn.clicked.connect(self._apply_fields)
        row = QHBoxLayout()
        for b in (self.add_field_btn, self.remove_field_btn, self.field_up_btn, self.field_down_btn):
            b.setAutoDefault(False)
            row.addWidget(b)
        for b in (self.field_up_btn, self.field_down_btn):
            b.setMaximumWidth(b.fontMetrics().horizontalAdvance("▲") + 24)
        row.addStretch()
        self.apply_fields_btn.setAutoDefault(False)
        row.addWidget(self.apply_fields_btn)
        self.fields_note = QLabel()   # why a name was refused
        self.fields_note.setWordWrap(True)
        self.fields_note.setEnabled(False)
        self.fields_note.hide()
        v.addWidget(t)
        v.addWidget(self.fields_empty)
        v.addLayout(row)
        v.addWidget(self.fields_note)
        self._fit_table()
        return box

    # ----- public --------------------------------------------------------------------------
    def schedule(self) -> None:
        """Re-list soon, if the panel is showing (it catches up when shown)."""
        if self.isVisible():
            self._timer.start()

    def selected(self) -> tuple[str, str] | None:
        """(kind, name) of the strand shown in the detail pane."""
        if self._selected is None:
            return None
        kind, key = self._selected
        name = next((n for n in self.scene.all_values(kind) if n.casefold() == key), None)
        return (kind, name) if name is not None else None

    def select(self, kind: str, name: str) -> bool:
        """Show this strand (if the board has it)."""
        key = (kind, name.strip().casefold())
        for item in self._strand_items():
            name = item.data(0, ROLE_NAME)
            if name is not None and (item.data(0, ROLE_KIND), name.casefold()) == key:
                self.tree.setCurrentItem(item)
                return True
        return False

    def refresh(self) -> None:
        self._timer.stop()
        rows = []
        for kind in RENAMABLE_FIELDS:
            usage = self.scene.strand_usage(kind)
            on_cards = self.scene.strand_card_counts(kind)
            rows.append((kind, tuple((name, (*usage.get(name.casefold(), (0, 0)),
                                             on_cards.get(name.casefold(), 0)),
                                      self.scene.strand(kind, name) is not None)
                                     for name in self.scene.all_values(kind))))
        shown = tuple(rows)
        if shown != self._shown:
            self._shown = shown
            self._fill(rows)
            plain, detailed = self.scene.unused_strands()
            self.remove_unused_btn.setEnabled(bool(plain or detailed))
        self._show_selected()

    # ----- the list ----------------------------------------------------------------------------
    def _strand_items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def _fill(self, rows) -> None:
        scroll = self.tree.verticalScrollBar().value()
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        italic = QFont()
        italic.setItalic(True)
        current = None
        for kind, strands in rows:
            top = QTreeWidgetItem(self.tree, [f"{KIND_LABELS[kind]}   ({len(strands)})", ""])
            top.setFont(0, bold)
            top.setData(0, ROLE_KIND, kind)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for name, (cards, routes, strand_cards), has_details in strands:
                item = QTreeWidgetItem(top, [name + (DETAILS_MARK if has_details else ""),
                                             usage_text(cards, routes, strand_cards,
                                                        is_builtin(kind, name))])
                item.setData(0, ROLE_KIND, kind)
                item.setData(0, ROLE_NAME, name)
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not (cards or routes or strand_cards):
                    item.setFont(0, italic)
                    item.setFont(1, italic)
                if has_details:
                    item.setToolTip(0, "Has a description, fields or a picture")
                if self._selected == (kind, name.casefold()):
                    current = item
            if not strands:
                none = QTreeWidgetItem(top, [f"No {KIND_LABELS[kind].lower()} yet", ""])
                none.setFlags(Qt.ItemFlag.NoItemFlags)
                none.setFont(0, italic)
            top.setExpanded(kind not in self._collapsed)
        self.tree.resizeColumnToContents(1)
        if current is not None:
            self.tree.setCurrentItem(current)
        self.tree.blockSignals(False)
        self._apply_search(self.search.text())
        self.tree.verticalScrollBar().setValue(scroll)

    def _apply_search(self, text: str) -> None:
        needle = text.strip().casefold()
        for item in self._strand_items():
            name = item.data(0, ROLE_NAME)
            item.setHidden(bool(needle) and (name is None or needle not in name.casefold()))

    def _on_current(self, item, _previous=None) -> None:
        self.commit_description()  # anything typed for the strand being left
        self._finish_field_edit()
        if item is None or item.data(0, ROLE_NAME) is None:
            return
        self._selected = (item.data(0, ROLE_KIND), item.data(0, ROLE_NAME).casefold())
        self._show_selected(force=True)

    def _on_renamed(self, field: str, old: str, new: str) -> None:
        if self._selected == (field, old.strip().casefold()):
            self._selected = (field, new.strip().casefold())

    # ----- showing the selected strand -------------------------------------------------------------
    def _show_selected(self, force: bool = False) -> None:
        sel = self.selected()
        has = sel is not None
        self.empty.setVisible(not has)
        for w in self._detail_widgets:
            w.setVisible(has)
        for b in self._buttons:
            b.setVisible(has)
        if not has:
            self._show_sections()
            return
        kind, name = sel
        info = self.scene.strand(kind, name)
        cards, routes = self.scene.strand_usage(kind).get(name.casefold(), (0, 0))
        strand_cards = self.scene.strand_card_counts(kind).get(name.casefold(), 0)
        self.title.setText(f"{name}")
        builtin = is_builtin(kind, name)
        self.usage.setText(f"{KIND_SINGULAR[kind].capitalize()} · "
                           f"{usage_text(cards, routes, strand_cards, builtin)}"
                           + ("" if cards or routes or strand_cards or builtin else " (kept on the board)"))
        self.select_btn.setEnabled(cards > 0)
        # An unused built-in status has nothing to rename (its name is always there).
        self.rename_btn.setEnabled(not builtin or bool(cards or routes or strand_cards))
        self.thread_btn.setVisible(kind == "characters"
                                   and bool(self.scene.display.get("story_tools", True)))
        self.thread_btn.setEnabled(cards > 0)
        # The description is only replaced while nothing typed is waiting to be saved,
        # so a refresh never wipes what you're typing (an undo still shows through).
        stored = info.description if info else ""
        if force or (not self._commit_timer.isActive() and self.description.toPlainText() != stored):
            self.description.blockSignals(True)
            self.description.setPlainText(stored)
            self.description.blockSignals(False)
        self._show_fields(info.fields if info else (), force)
        self._show_picture(info.picture if info else "")
        self.clear_btn.setEnabled(info is not None)

    def _toggle_section(self, key: str) -> None:
        self._folded ^= {key}
        self._show_sections()

    def _show_sections(self) -> None:
        """Header texts, and which sections are open. Folding is per section (not per
        strand) and lasts while the panel exists."""
        has = self.selected() is not None
        for key, toggle, box, label in (
                ("fields", self.fields_toggle, self.fields_box,
                 f"Fields ({self.fields_table.rowCount()})"),
                ("picture", self.picture_toggle, self.picture_box, "Picture")):
            folded = key in self._folded
            toggle.setText(("▸ " if folded else "▾ ") + label)
            toggle.setToolTip(f"{'Show' if folded else 'Hide'} the {key}")
            box.setVisible(has and not folded)

    def _table_fields(self) -> tuple[tuple[str, str], ...]:
        t = self.fields_table
        return tuple((t.item(r, 0).text(), t.item(r, 1).text()) for r in range(t.rowCount()))

    def _show_fields(self, fields, force: bool = False) -> None:
        """Fill the table, unless a cell is being edited (a refresh mustn't take the
        typing away; the edit is saved when it ends and the table catches up). Existing
        items are updated in place rather than replaced, as this can run while one of
        them is reporting its own change."""
        t = self.fields_table
        editing = t.state() == QAbstractItemView.State.EditingState
        if force or (not editing and self._table_fields() != tuple(fields)):
            row, col = t.currentRow(), max(t.currentColumn(), 0)
            t.blockSignals(True)
            t.setRowCount(len(fields))
            for r, pair in enumerate(fields):
                for c, text in enumerate(pair):
                    item = t.item(r, c)
                    if item is None:
                        t.setItem(r, c, QTableWidgetItem(text))
                    elif item.text() != text:
                        item.setText(text)
            t.blockSignals(False)
            if force:
                self._note("")
            if 0 <= row < len(fields):
                t.setCurrentCell(row, col)
            self._fit_table()
        t.setVisible(bool(fields))
        self.fields_empty.setVisible(not fields)
        self._update_field_buttons()
        self._show_sections()

    def _fit_table(self) -> None:
        """As tall as its rows, up to FIELDS_VISIBLE_ROWS; past that it scrolls, so a
        long list never pushes the picture out of the pane."""
        t = self.fields_table
        rows = min(t.rowCount(), FIELDS_VISIBLE_ROWS)
        t.setFixedHeight(t.horizontalHeader().sizeHint().height()
                         + rows * t.verticalHeader().defaultSectionSize() + 2 * t.frameWidth())

    def _update_field_buttons(self) -> None:
        r, n = self.fields_table.currentRow(), self.fields_table.rowCount()
        self.remove_field_btn.setEnabled(0 <= r < n)
        self.field_up_btn.setEnabled(0 < r < n)
        self.field_down_btn.setEnabled(0 <= r < n - 1)
        self.apply_fields_btn.setEnabled(n > 0)

    def _note(self, text: str) -> None:
        self.fields_note.setText(text)
        self.fields_note.setVisible(bool(text))

    def _show_picture(self, path: str) -> None:
        self.remove_pic_btn.setEnabled(bool(path))
        if not path:
            self.picture.setPixmap(QPixmap())
            self.picture.setText("No picture")
            self.picture.setEnabled(False)
            self.choose_btn.setText("Choose picture…")
            self.open_pic_btn.setEnabled(False)
            return
        pixmap = self._preview(path)
        self.open_pic_btn.setEnabled(pixmap is not None)
        if pixmap is None:
            self.picture.setPixmap(QPixmap())
            self.picture.setText(f"Picture not found (or not an image):\n{path}")
            self.picture.setEnabled(True)
            self.choose_btn.setText("Relink…")
            return
        self.picture.setText("")
        self.picture.setPixmap(pixmap)
        self.picture.setEnabled(True)
        self.picture.setToolTip(path)
        self.choose_btn.setText("Change picture…")

    def _preview(self, path: str) -> QPixmap | None:
        """The picture scaled to fit, or None if it can't be read. Cached, and re-read
        if the file changes."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._previews.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        reader = QImageReader(path)
        reader.setAutoTransform(True)  # photos taken sideways stand up
        image = reader.read()
        if image.isNull():
            return None
        pixmap = QPixmap.fromImage(image)
        if pixmap.width() > PREVIEW_MAX or pixmap.height() > PREVIEW_MAX:
            pixmap = pixmap.scaled(PREVIEW_MAX, PREVIEW_MAX, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        self._previews[path] = (mtime, pixmap)
        return pixmap

    # ----- editing ------------------------------------------------------------------------------------
    def _info_for(self, kind: str, name: str) -> StrandInfo:
        info = self.scene.strand(kind, name)
        return replace(info, name=name) if info else StrandInfo(kind=kind, name=name)

    def _on_typed(self) -> None:
        self._commit_timer.start()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.description and event.type() == QEvent.Type.FocusOut:
            self.commit_description()
        return False

    def commit_description(self) -> bool:
        """Save what's typed in the description (one undo step)."""
        self._commit_timer.stop()
        sel = self.selected()
        if sel is None:
            return False
        info = self._info_for(*sel)
        text = self.description.toPlainText()
        if text == info.description:
            return False
        return self.scene.set_strand_info(replace(info, description=text))

    # ----- editing fields ---------------------------------------------------------------------------
    def _finish_field_edit(self) -> None:
        """Save a cell that's still being edited (moving the current cell commits it)."""
        if self.fields_table.state() == QAbstractItemView.State.EditingState:
            self.fields_table.setCurrentIndex(QModelIndex())

    def _commit_fields(self, fields) -> bool:
        """Store the selected strand's fields (one undo step)."""
        sel = self.selected()
        if sel is None:
            return False
        self.commit_description()
        info = self._info_for(*sel)
        if tuple(fields) == info.fields:
            return False
        return self.scene.set_strand_info(replace(info, fields=tuple(fields)))

    def _on_field_edited(self, item: QTableWidgetItem) -> None:
        """A cell's edit ended. The change is applied to the stored fields (not the
        whole table, which may be behind an undo made meanwhile). A name that's empty
        or already used (ignoring case) is refused and put back."""
        sel = self.selected()
        if sel is None:
            return
        fields = list(self._info_for(*sel).fields)
        r, c = item.row(), item.column()
        if r >= len(fields):
            self._show_fields(fields, force=True)
            return
        name, value = fields[r]
        text = " ".join(item.text().split())
        if c == 0:
            refusal = ("A field needs a name." if not text else
                       f"“{text}” is already a field." if text.casefold() != name.casefold()
                       and any(n.casefold() == text.casefold() for n, _ in fields) else "")
            if refusal:
                self.fields_table.blockSignals(True)
                item.setText(name)
                self.fields_table.blockSignals(False)
                self._note(refusal)
                return
            fields[r] = (text, value)
        else:
            fields[r] = (name, text)
        self._note("")
        self._commit_fields(fields)

    def _add_field(self) -> None:
        sel = self.selected()
        if sel is None:
            return
        self._finish_field_edit()
        fields = self._info_for(*sel).fields
        taken = {n.casefold() for n, _ in fields}
        name, n = NEW_FIELD_NAME, 2
        while name.casefold() in taken:
            name, n = f"{NEW_FIELD_NAME} {n}", n + 1
        fields = (*fields, (name, ""))
        self._commit_fields(fields)
        self._show_fields(fields, force=True)
        t = self.fields_table
        t.setCurrentCell(len(fields) - 1, 0)
        t.scrollToItem(t.item(len(fields) - 1, 0))
        t.setFocus()
        t.editItem(t.item(len(fields) - 1, 0))

    def _remove_field(self) -> None:
        sel = self.selected()
        r = self.fields_table.currentRow()
        if sel is None or r < 0:
            return
        self._finish_field_edit()
        fields = list(self._info_for(*sel).fields)
        if r < len(fields):
            del fields[r]
            self._commit_fields(fields)
            self._show_fields(fields, force=True)
            if fields:
                self.fields_table.setCurrentCell(min(r, len(fields) - 1), 0)

    def _move_field(self, step: int) -> None:
        sel = self.selected()
        t = self.fields_table
        r, c = t.currentRow(), max(t.currentColumn(), 0)
        if sel is None:
            return
        self._finish_field_edit()
        fields = list(self._info_for(*sel).fields)
        to = r + step
        if not (0 <= r < len(fields) and 0 <= to < len(fields)):
            return
        fields[r], fields[to] = fields[to], fields[r]
        self._commit_fields(fields)
        self._show_fields(fields, force=True)
        t.setCurrentCell(to, c)

    def _apply_fields(self) -> None:
        """Copy this strand's field names (and, if asked, values) to other strands of
        the same kind, picked in a dialog; says in the status bar what was added."""
        sel = self.selected()
        if sel is None:
            return
        self._finish_field_edit()
        self.commit_description()
        kind, name = sel
        info = self.scene.strand(kind, name)
        if info is None or not info.fields:
            return
        others = [v for v in self.scene.all_values(kind) if v.casefold() != name.casefold()]
        dialog = ApplyFieldsDialog(kind, name, info.fields, others, self)
        if not dialog.exec():
            return
        targets = dialog.selected_targets()
        changed, added = self.scene.apply_strand_fields(kind, name, targets, dialog.selected_names(),
                                                        dialog.with_values())
        if changed:
            self.scene.notice.emit(f"Added {added} field{'' if added == 1 else 's'} to {changed} "
                                   + (KIND_ONE[kind] if changed == 1 else KIND_PLURAL[kind]))
        elif targets:
            self.scene.notice.emit(f"That {KIND_ONE[kind]} already has these fields" if len(targets) == 1
                                   else f"Those {KIND_PLURAL[kind]} already have these fields")
        self._show_selected()

    def _set_picture(self, path: str) -> None:
        sel = self.selected()
        if sel is None:
            return
        self.commit_description()
        self.scene.set_strand_info(replace(self._info_for(*sel), picture=path))
        self._show_selected()

    def _choose_picture(self) -> None:
        sel = self.selected()
        if sel is None:
            return
        info = self.scene.strand(*sel)
        start = str(Path(info.picture).parent) if info and info.picture else ""
        path, _ = QFileDialog.getOpenFileName(self, f"Picture for “{sel[1]}”", start, image_filter())
        if path:
            self._set_picture(os.path.normpath(path))

    def _open_picture(self) -> None:
        sel = self.selected()
        info = self.scene.strand(*sel) if sel else None
        if info and info.picture:
            QDesktopServices.openUrl(QUrl.fromLocalFile(info.picture))

    def _clear_details(self) -> None:
        sel = self.selected()
        if sel is None:
            return
        self._commit_timer.stop()
        self.scene.set_strand_info(StrandInfo(kind=sel[0], name=sel[1]))  # blank: forgotten
        self._show_selected(force=True)

    # ----- actions on the board -----------------------------------------------------------------------
    def _rename(self) -> None:
        sel = self.selected()
        if sel is not None:
            self.commit_description()
            self.scene.open_rename_dialog(*sel)

    def _cards_with(self, kind: str, name: str) -> list:
        key = name.casefold()
        out = []
        for item in self.scene.cards.values():
            raw = getattr(item.card, kind)
            values = raw if isinstance(raw, list) else [raw]
            if any(v.strip().casefold() == key for v in values):
                out.append(item)
        return out

    def _remove_unused(self) -> None:
        self.commit_description()
        self.remove_unused_requested.emit()
        self.refresh()

    def _add_to_board(self) -> None:
        sel = self.selected()
        if sel is not None:
            self.commit_description()
            self.scene.create_strand_card(*sel)

    def _select_cards(self) -> None:
        sel = self.selected()
        if sel is not None:
            self.show_cards.emit(self._cards_with(*sel))

    def _show_thread(self) -> None:
        sel = self.selected()
        if sel is not None:
            self.scene.show_thread(sel[1])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event) -> None:
        self.commit_description()
        self._finish_field_edit()
        super().hideEvent(event)
