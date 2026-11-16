"""The Card List: a side panel listing every card on the board as a tree that follows
the groups: in story order (or reading order when story tools are off), top to
bottom, or A–Z. A box narrows it by title (or, with *Search all text*, by anything
Ctrl+F search finds), cards the Filter panel dims are greyed, or left out with *Hide
filtered-out cards*, and a Status column can show where each card stands.

It follows the canvas both ways. Picking a row selects the card and brings it into
view; selecting on the canvas picks its rows. A card folded away inside a collapsed
group can't be selected (Qt ignores hidden items), so picking it selects the folded
group instead, and Enter or a double-click unfolds the group (one undo step) and
hands the keyboard to the canvas. Browsing with the arrow keys therefore never changes
the board.

Rows remember card ids, never CardItems: undo rebuilds every card on the board."""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import settings
from .card_item import STRAND_MARKS
from .filters import search_cards
from .model import KIND_GROUP, KIND_STRAND
from .widgets import swatch_icon

REFRESH_DELAY_MS = 150   # rebuild this long after the board settles
ROLE_ID = Qt.ItemDataRole.UserRole
FOLDED = "⊞"             # a group collapsed on the canvas (as on its title bar)
SORT_KEY = "card_list/sort"            # remembered per machine, like other panels' choices
HIDE_KEY = "card_list/hide_filtered"
STATUS_KEY = "card_list/status_column"
FULL_TEXT_KEY = "card_list/search_all_text"
SORTS = [("story", "Story order"), ("position", "Top to bottom"), ("title", "A–Z")]


def natural_key(text: str) -> tuple:
    """Sorts titles as people expect: ignoring case, and "Card 2" before "Card 10"."""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part)
                 for part in re.split(r"(\d+)", text.strip().casefold()) if part)


def narrowed(children: dict[str, list[str]], matches) -> set[str]:
    """Ids to keep when the list is narrowed to `matches`: the matches and the groups
    around them, so the tree still shows where each one is."""
    parent = {k: p for p, kids in children.items() for k in kids}
    keep: set[str] = set()
    for cid in matches:
        while cid and cid not in keep:
            keep.add(cid)
            cid = parent.get(cid, "")
    return keep


def cached_swatch(color: str, cache: dict[str, QIcon]) -> QIcon:
    """The colour dot the Filter panel uses, painted once per colour."""
    icon = cache.get(color)
    if icon is None:
        icon = cache[color] = swatch_icon(color)
    return icon


def row_text(card, count: int) -> str:
    """What a card's row says: its title, marked as a strand card or a folded group,
    and for a group how many cards it holds (as its title bar counts them)."""
    title = card.title.strip() or "Untitled"
    if card.kind == KIND_STRAND:
        title = f"{STRAND_MARKS.get(card.strand_kind, '•')} {title}"
    if card.kind == KIND_GROUP:
        if card.collapsed:
            title = f"{FOLDED} {title}"
        title += f" · {count}"
    return title


def row_tip(card) -> str:
    lines = []
    first = next((ln.strip() for ln in card.description.splitlines() if ln.strip()), "")
    if first and card.kind != KIND_GROUP:
        lines.append(first if len(first) <= 120 else first[:117] + "…")
    if card.status:
        lines.append(f"Status: {card.status}")
    if card.outside_story:
        lines.append("Not part of the story")
    if card.kind == KIND_GROUP and card.collapsed:
        lines.append("Collapsed on the board")
    return "\n".join(lines)


class CardListPanel(QWidget):
    # Card ids picked in the list, and whether to unfold collapsed groups to reach
    # them (Enter / double-click) rather than select the folded group.
    show_ids = Signal(list, bool)

    def __init__(self, scene, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene = scene
        self._shown: tuple | None = None   # what the tree shows now (skip identical rebuilds)
        self._closed: set[str] = set()     # groups folded in the tree (not on the board)
        self._rows: dict[str, QTreeWidgetItem] = {}
        self._icons: dict[str, QIcon] = {}
        self._syncing = False   # setting rows from the canvas: don't send them back
        self._pushing = False   # sending rows to the canvas: don't follow its echo
        self._filter_on = False  # the Filter panel is dimming cards

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.refresh())
        self.search.installEventFilter(self)
        self.sort = QComboBox()
        for key, label in SORTS:
            self.sort.addItem(label, key)
        self.sort.setToolTip("Story order follows the arrows (top to bottom while story tools are "
                             "off); cards stay in their groups whichever you pick")
        saved = str(settings.store().value(SORT_KEY, "story"))
        self.sort.setCurrentIndex(max(0, self.sort.findData(saved)))
        self.sort.currentIndexChanged.connect(self._sort_changed)
        self.hide_dimmed = QCheckBox("Hide filtered-out cards")
        self.hide_dimmed.setToolTip("Leave out the cards the Filter panel dims (greyed otherwise)")
        self.hide_dimmed.setChecked(settings.store().value(HIDE_KEY, False, type=bool))
        self.hide_dimmed.toggled.connect(self._hide_changed)
        self.hide_dimmed.setVisible(False)  # only while a filter is on
        self._found: set[str] = set()
        # Less used choices, under ⋮: both remembered per machine.
        store = settings.store()
        self.act_status = QAction("Status column", self, checkable=True)
        self.act_status.setChecked(store.value(STATUS_KEY, False, type=bool))
        self.act_status.setStatusTip("Show each card's status (Draft, Final…) beside its title")
        self.act_status.toggled.connect(lambda on: self._option_changed(STATUS_KEY, on))
        self.act_full_text = QAction("Search all text", self, checkable=True)
        self.act_full_text.setChecked(store.value(FULL_TEXT_KEY, False, type=bool))
        self.act_full_text.setStatusTip("Find cards by their description, notes and strands too, "
                                        "as Ctrl+F search does")
        self.act_full_text.toggled.connect(lambda on: self._option_changed(FULL_TEXT_KEY, on))
        self.options = QToolButton()
        self.options.setText("⋮")
        self.options.setToolTip("More: Status column, Search all text")
        self.options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options.setStyleSheet("QToolButton::menu-indicator { image: none; }")  # ⋮ says it all
        options_menu = QMenu(self.options)
        options_menu.addActions([self.act_status, self.act_full_text])
        self.options.setMenu(options_menu)
        self._update_search_hint()

        self.summary = QLabel()
        self.summary.setEnabled(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setColumnHidden(1, not self.act_status.isChecked())
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._on_rows_picked)
        self.tree.itemDoubleClicked.connect(lambda *_: self._activate())
        self.tree.itemCollapsed.connect(self._on_folded)
        self.tree.itemExpanded.connect(self._on_unfolded)
        self.tree.installEventFilter(self)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.sort)
        top.addWidget(self.options)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self.hide_dimmed)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DELAY_MS)
        self._timer.timeout.connect(self.refresh)
        # The canvas's selection comes in bursts (paste, undo, select all): follow it
        # once the burst is over.
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(0)
        self._selection_timer.timeout.connect(self._follow_selection)
        scene.modified.connect(self.schedule)
        scene.history_changed.connect(self.schedule)  # a board opened, undo, redo
        scene.selectionChanged.connect(self._on_scene_selection)

    # ----- public -------------------------------------------------------------------
    def schedule(self) -> None:
        """Rebuild soon, if the panel is showing (it catches up when shown)."""
        if self.isVisible():
            self._timer.start()

    def set_filter_on(self, active: bool) -> None:
        """The Filter panel changed (it re-dims on every edit, too): grey or hide the
        dimmed cards' rows, and offer to hide them while a filter is on."""
        self._filter_on = active
        self.hide_dimmed.setVisible(active)
        self.schedule()

    def sort_mode(self) -> str:
        return self.sort.currentData()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self._timer.stop()
        scene = self.scene
        mode = self.sort_mode()
        by_story = mode == "story" and bool(scene.display.get("story_tools", True))
        children = scene.story_graph().outline(by_story)
        cards = {cid: item.card for cid, item in scene.cards.items()}
        if mode == "title":
            for kids in children.values():
                kids.sort(key=lambda i: natural_key(cards[i].title if i in cards else ""))
        titles = {cid: c.title.strip() or "Untitled" for cid, c in cards.items()}
        needle = " ".join(self.search.text().split()).casefold()
        found = self._matches(cards, titles, needle) if needle else {}
        keep = narrowed(children, found) if needle else None
        self._found = set(found)  # what the box matched (↓ goes to the first)
        dimmed = ({cid for cid, item in scene.cards.items() if item.dimmed}
                  if self._filter_on else set())
        hide_dimmed = self.hide_dimmed.isChecked() and bool(dimmed)
        rows: list = []
        seen: set[str] = set()

        def walk(parent: str, depth: int) -> bool:
            """Add the rows under `parent`; True if any were left in."""
            listed = False
            for cid in children.get(parent, ()):
                card = cards.get(cid)
                if card is None or cid in seen or (keep is not None and cid not in keep):
                    continue
                seen.add(cid)
                at = len(rows)
                rows.append(None)  # filled in once we know whether anything inside stays
                inner = walk(cid, depth + 1)
                is_dimmed = cid in dimmed
                if hide_dimmed and is_dimmed and not inner:
                    del rows[at:]  # a hidden card, or a dimmed group with nothing left in it
                    continue
                # Dimmed cards, and groups listed only to show where a match is, are greyed.
                muted = is_dimmed or (keep is not None and cid not in found)
                tip = row_tip(card)
                where = found.get(cid)
                if where:  # matched by something other than its title
                    tip = "\n".join(filter(None, [f"Found in {where[0].lower()}: {where[1]}", tip]))
                if is_dimmed:
                    tip = "\n".join(filter(None, [tip, "Hidden by the filter"]))
                status = card.status if card.kind != KIND_GROUP else ""
                rows[at] = (cid, depth, row_text(card, len(children.get(cid, ()))), card.color,
                            card.kind == KIND_GROUP, card.outside_story, muted, tip, status)
                listed = True
            return listed

        walk("", 0)
        self._set_summary(rows, cards)
        shown = (bool(needle), *rows)
        if shown != self._shown:  # moving a card rarely changes the list: leave it be then
            self._shown = shown
            self._fill(rows)
        self._follow_selection()

    def row_ids(self) -> list[str]:
        """Every listed card id, top to bottom (expanded or not)."""
        out: list[str] = []

        def walk(item: QTreeWidgetItem) -> None:
            for n in range(item.childCount()):
                child = item.child(n)
                out.append(child.data(0, ROLE_ID))
                walk(child)

        walk(self.tree.invisibleRootItem())
        return out

    def selected_ids(self) -> list[str]:
        return [cid for cid in self.row_ids() if self._rows[cid].isSelected()]

    # ----- internals ------------------------------------------------------------------
    def _matches(self, cards: dict, titles: dict[str, str], needle: str) -> dict[str, tuple | None]:
        """Cards the box finds: {id: None} for a title match, or {id: (field, snippet)}
        for one found elsewhere (Search all text), so its row can say where."""
        found: dict[str, tuple | None] = {cid: None for cid, t in titles.items()
                                          if needle in " ".join(t.split()).casefold()}
        if self.act_full_text.isChecked():
            for cid, label, snippet in search_cards(cards.values(), needle, self.scene.strand_info):
                found.setdefault(cid, (label, snippet))
        return found

    def _option_changed(self, key: str, on: bool) -> None:
        settings.store().setValue(key, on)
        self.tree.setColumnHidden(1, not self.act_status.isChecked())
        self._update_search_hint()
        self.refresh()

    def _update_search_hint(self) -> None:
        full = self.act_full_text.isChecked()
        self.search.setPlaceholderText("Find a card" if full else "Find a card by title")
        what = ("whose title, description, notes or strands contain this" if full
                else "whose title contains this")
        self.search.setToolTip(f"Narrow the list to cards {what} (Esc clears it; ↓ or Enter "
                               "goes to the list)")

    def _set_summary(self, rows: list, cards: dict) -> None:
        n_groups = sum(1 for r in rows if r[4])
        n_cards = len(rows) - n_groups
        total = sum(1 for c in cards.values() if c.kind != KIND_GROUP)
        if not cards:
            text = "No cards yet"
        elif n_cards != total:
            text = f"{n_cards} of {total} cards"
        else:
            text = f"{n_cards} card{'s' if n_cards != 1 else ''}"
            if n_groups:
                text += f" · {n_groups} group{'s' if n_groups != 1 else ''}"
        self.summary.setText(text)

    def _sort_changed(self, _index: int) -> None:
        settings.store().setValue(SORT_KEY, self.sort_mode())
        self.refresh()

    def _hide_changed(self, on: bool) -> None:
        settings.store().setValue(HIDE_KEY, on)
        self.refresh()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:  # dark mode: grey the rows anew
            self._shown = None
            self.schedule()

    def _fill(self, rows: list) -> None:
        scroll = self.tree.verticalScrollBar().value()
        self._syncing = True
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            self._rows = {}
            parents: list[QTreeWidgetItem] = []
            bold, italic = QFont(), QFont()
            bold.setBold(True)
            italic.setItalic(True)
            grey = QBrush(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
            for cid, depth, text, color, is_group, outside, muted, tip, status in rows:
                del parents[depth:]
                item = QTreeWidgetItem(parents[-1] if parents else self.tree, [text, status])
                item.setData(0, ROLE_ID, cid)
                item.setIcon(0, cached_swatch(color, self._icons))
                if is_group or outside:
                    font = QFont(bold if is_group else italic)
                    font.setItalic(outside)
                    item.setFont(0, font)
                if muted:
                    item.setForeground(0, grey)
                    item.setForeground(1, grey)
                if tip:
                    item.setToolTip(0, tip)
                    item.setToolTip(1, tip)
                self._rows[cid] = item
                parents.append(item)
            narrowing = bool(self.search.text().strip())
            for cid, item in self._rows.items():
                if item.childCount():  # while narrowed, everything opens to show the matches
                    item.setExpanded(narrowing or cid not in self._closed)
        finally:
            self.tree.setUpdatesEnabled(True)
            self._syncing = False
        self.tree.verticalScrollBar().setValue(scroll)

    def _on_folded(self, item: QTreeWidgetItem) -> None:
        if not self._syncing and not self.search.text().strip():
            self._closed.add(item.data(0, ROLE_ID))

    def _on_unfolded(self, item: QTreeWidgetItem) -> None:
        if not self._syncing and not self.search.text().strip():
            self._closed.discard(item.data(0, ROLE_ID))

    def _on_scene_selection(self) -> None:
        if not self._pushing and self.isVisible():
            self._selection_timer.start()

    def _follow_selection(self) -> None:
        """Pick the rows of the cards selected on the canvas."""
        self._selection_timer.stop()
        try:
            picked = {i.card.id for i in self.scene.selectedItems() if hasattr(i, "card")}
        except RuntimeError:  # the scene is being torn down
            return
        picked &= self._rows.keys()  # a card the list leaves out can't be picked
        if picked == set(self.selected_ids()):
            return
        self._syncing = True
        try:
            first = None
            for cid, item in self._rows.items():
                on = cid in picked
                if item.isSelected() != on:
                    item.setSelected(on)
                if on and first is None:
                    first = item
            if first is not None:
                self.tree.setCurrentItem(first, 0, self.tree.selectionModel().SelectionFlag.NoUpdate)
                self.tree.scrollToItem(first)
        finally:
            self._syncing = False

    def _on_rows_picked(self) -> None:
        if not self._syncing:
            self._send(unfold=False)

    def _activate(self) -> None:
        self._send(unfold=True)

    def _send(self, unfold: bool) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        self._pushing = True
        try:
            self.show_ids.emit(ids, unfold)
        finally:
            self._pushing = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj is self.tree and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate()
                return True
            if obj is self.search and key == Qt.Key.Key_Escape and self.search.text():
                self.search.clear()
                return True
            if obj is self.search and key in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._go_to_list()
                return True
        return super().eventFilter(obj, event)

    def _go_to_list(self) -> None:
        """From the box to the list, onto the first card whose title matches; picking
        it there selects it on the canvas, and Enter opens it."""
        ids = self.row_ids()
        first = next((i for i in ids if i in self._found), ids[0] if ids else None)
        self.tree.setFocus(Qt.FocusReason.OtherFocusReason)
        if first is not None:
            self.tree.setCurrentItem(self._rows[first])
