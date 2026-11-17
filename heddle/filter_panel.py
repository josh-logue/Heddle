"""Side panel listing card details as checkboxes; non-matching cards are dimmed.

Strand groups (model.StrandGroup) are listed first in their kind's categories (character
groups under Characters, POV and Introduces too), with their strands under them; ticking a
group ticks every strand in it that cards use, and it shows partly ticked when only some
are. Groups are only a way of ticking strands: the filter itself (filters.matches) never
sees them, so "match all" with a group ticked needs every strand in it."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QStyle, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import settings, theme
from .filters import (
    CATEGORIES, LABELS, MATCH_ALL_CATEGORIES, NONE_KEY, card_keys, collect_options, describe_counts,
    matches,
)
from .model import RENAMABLE_FIELDS
from .rename_dialog import FIELD_LABELS
from .widgets import swatch_icon

ROLE_CAT = Qt.ItemDataRole.UserRole
ROLE_KEY = Qt.ItemDataRole.UserRole + 1
ROLE_GROUP = Qt.ItemDataRole.UserRole + 2   # a group row's name
ROLE_MEMBERS = Qt.ItemDataRole.UserRole + 3  # a group row's ticks: its strands' keys on cards
ROLE_FOLD = Qt.ItemDataRole.UserRole + 4    # what folding the row is remembered as
# The kind of strand group each category lists: POV and Introduces are characters.
GROUP_KINDS = {"tags": "tags", "characters": "characters", "pov": "characters",
               "introduces": "characters", "locations": "locations", "status": "status"}
# Which categories need every ticked entry: a habit, so remembered per machine (the
# ticks themselves aren't kept), as a comma-separated list of category names.
MATCH_ALL_KEY = "filter/match_all"
# The plural nouns used in the hint and the canvas bar ("all tags").
_NOUNS = {"tags": "tags", "characters": "characters", "introduces": "introductions",
          "locations": "locations"}


def load_match_all() -> set[str]:
    raw = str(settings.store().value(MATCH_ALL_KEY, "") or "")
    return {c for c in raw.split(",") if c in MATCH_ALL_CATEGORIES}


class FilterPanel(QWidget):
    # shown, total, active
    filter_changed = Signal(object, bool)  # FilterCounts, whether a filter is on

    def __init__(self, scene, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene = scene
        self._options: dict | None = None
        self._groups: tuple | None = None  # the strand groups listed (see _group_rows)
        self._story_tools = True  # whether the Introduces category (a story tool) is listed
        self._selection: dict[str, set[str]] = {c: set() for c in CATEGORIES}
        self._collapsed: set[str] = set()
        self._stale = True  # options need recounting before the panel is next shown
        self._match_all: set[str] = load_match_all()
        self.mode_buttons: dict[str, QToolButton] = {}  # rebuilt with the tree

        self.summary = QLabel()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_selection)
        header = QHBoxLayout()
        header.addWidget(self.summary, 1)
        header.addWidget(self.clear_btn)

        # Two columns: headings put their "match any / all" button in the second, while
        # entries span both, so long names aren't cut short by it.
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.apply_theme()
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemCollapsed.connect(lambda it: self._collapsed.add(it.data(0, ROLE_FOLD)))
        self.tree.itemExpanded.connect(lambda it: self._collapsed.discard(it.data(0, ROLE_FOLD)))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        scene.value_renamed.connect(self.on_value_renamed)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setEnabled(False)  # renders in the muted/disabled text color

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.hint)
        self._update_hint()

        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    # ----- public -----------------------------------------------------------
    def apply_theme(self) -> None:
        self.tree.setStyleSheet(theme.checkbox_stylesheet())

    def refresh(self) -> None:
        """Re-read card values (cheap when nothing changed) and reapply the filter.
        Skipped while the panel is hidden and no filter is on, since there's nothing
        to show or dim; it catches up when the panel is shown again."""
        if not self.isVisible() and not self.is_active():
            self._stale = True
            self.apply()  # cheap: un-dims everything and keeps the banner/status in step
            return
        self._stale = False
        # (Strand cards have no values of their own: they'd only swell the "(none)" counts.)
        options = collect_options((item.card for item in self.scene.cards.values() if not item.is_strand),
                                  self._extras())
        story = bool(self.scene.display.get("story_tools", True))
        groups = self._group_rows()
        if options != self._options or story != self._story_tools or groups != self._groups:
            self._options = options
            self._story_tools = story
            self._groups = groups
            self._rebuild()
        self.apply()

    def reset(self) -> None:
        """Forget all selections, e.g. when a different board is loaded. The
        any / all choices stay: they're remembered per machine."""
        self._selection = {c: set() for c in CATEGORIES}
        self._options = None
        self.refresh()

    def match_all(self) -> set[str]:
        """The categories where a card needs every ticked entry."""
        return set(self._match_all)

    def set_match_all(self, cat: str, on: bool) -> None:
        """Make `cat` need every ticked entry (on) or any of them, and remember it."""
        if cat not in MATCH_ALL_CATEGORIES or (cat in self._match_all) == on:
            return
        if on:
            self._match_all.add(cat)
        else:
            self._match_all.discard(cat)
        settings.store().setValue(MATCH_ALL_KEY, ",".join(c for c in MATCH_ALL_CATEGORIES
                                                          if c in self._match_all))
        button = self.mode_buttons.get(cat)
        if button is not None:
            self._style_mode_button(button, cat)
        self._update_hint()
        self.apply()

    def _group_rows(self) -> tuple:
        """{kind: ((name, (member keys…)), …)} as a tuple, for noticing when groups change."""
        return tuple((kind, tuple((g.name, tuple(m.casefold() for m in g.members))
                                  for g in self.scene.groups_of(kind)))
                     for kind in RENAMABLE_FIELDS)

    def match_note(self) -> str:
        """For the canvas bar: the "all" categories where it changes the result
        (2+ entries ticked), e.g. "all tags, all characters"; "" when none."""
        return ", ".join(f"all {_NOUNS[c]}" for c in MATCH_ALL_CATEGORIES
                         if c in self._match_all and len(self._selection.get(c, ())) > 1)

    def clear_selection(self) -> None:
        self._selection = {c: set() for c in CATEGORIES}
        self._sync_checks()
        self._update_titles()
        self.apply()

    def _rows(self):
        """Every row under the headings: groups, their strands, and the other entries."""
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                yield child
                for k in range(child.childCount()):
                    yield child.child(k)

    def _sync_checks(self) -> None:
        """Show the selection on every box: a strand under two groups, and outside them,
        is one tick; a group is ticked, partly ticked or not by its strands."""
        self.tree.blockSignals(True)
        for item in self._rows():
            if not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                continue
            selected = self._selection[item.data(0, ROLE_CAT)]
            members = item.data(0, ROLE_MEMBERS)
            if members is not None:
                n = sum(1 for k in members if k in selected)
                state = (Qt.CheckState.Checked if n == len(members) else
                         Qt.CheckState.PartiallyChecked if n else Qt.CheckState.Unchecked)
            else:
                state = Qt.CheckState.Checked if item.data(0, ROLE_KEY) in selected else Qt.CheckState.Unchecked
            if item.checkState(0) != state:
                item.setCheckState(0, state)
        self.tree.blockSignals(False)

    def is_active(self) -> bool:
        return any(self._selection.values())

    def selected_count(self) -> int:
        """How many values are ticked, across all categories."""
        return sum(len(s) for s in self._selection.values())

    def apply(self) -> None:
        selection = {c: set(s) for c, s in self._selection.items()}
        match_all = set(self._match_all)
        active = self.is_active()
        extras = self._extras()
        predicate = (lambda card: matches(card, selection, match_all, extras)) if active else None
        counts = self.scene.apply_filter(predicate)
        self.summary.setText(f"Showing {describe_counts(counts)}" if active
                             else f"{describe_counts(counts, filtered=False)} · no filter")
        self.clear_btn.setEnabled(active)
        self.filter_changed.emit(counts, active)

    def _extras(self):
        """Values worked out from the arrows rather than typed on cards."""
        return {"introduces": self.scene.introductions}

    # ----- internals --------------------------------------------------------
    def _rebuild(self) -> None:
        scroll = self.tree.verticalScrollBar().value()  # stay where you were scrolled to
        self.tree.blockSignals(True)
        self.tree.clear()  # (deletes the heading buttons too)
        self.mode_buttons = {}
        bold = QFont()
        bold.setBold(True)
        italic = QFont()
        italic.setItalic(True)
        folder = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        cards = [item.card for item in self.scene.cards.values() if not item.is_strand]
        extras = self._extras()
        for cat in CATEGORIES:
            if cat == "introduces" and not self._story_tools:
                self._selection[cat].clear()  # a story tool: not offered while they're off
                continue
            options = self._options[cat]
            self._selection[cat] &= {key for key, _, _ in options}  # drop vanished values

            top = QTreeWidgetItem(self.tree)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            top.setFont(0, bold)
            top.setData(0, ROLE_CAT, cat)
            top.setData(0, ROLE_FOLD, cat)
            if not options:
                empty = QTreeWidgetItem(top, ["No cards yet"])
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                empty.setFont(0, italic)
                empty.setFirstColumnSpanned(True)
            elif cat in MATCH_ALL_CATEGORIES:
                self.tree.setItemWidget(top, 1, self._mode_button(cat))
            by_key = {key: (key, display, count) for key, display, count in options}
            grouped: set[str] = set()
            for group in self.scene.groups_of(GROUP_KINDS[cat]) if cat in GROUP_KINDS else ():
                # Only the strands cards use: the others have nothing to show.
                members = [by_key[m.casefold()] for m in group.members if m.casefold() in by_key]
                if not members:
                    continue
                keys = tuple(key for key, _, _ in members)
                n = sum(1 for card in cards if card_keys(card, cat, extras) & set(keys))
                fold = f"{cat}/{group.name.casefold()}"
                row = QTreeWidgetItem(top, [f"{group.name}   ({n})"])
                row.setFirstColumnSpanned(True)
                row.setIcon(0, folder)
                row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                row.setData(0, ROLE_CAT, cat)
                row.setData(0, ROLE_GROUP, group.name)
                row.setData(0, ROLE_MEMBERS, keys)
                row.setData(0, ROLE_FOLD, fold)
                row.setToolTip(0, f"Strand group: ticking it ticks all {len(keys)} of its strands "
                                  f"on cards ({n} card{'' if n == 1 else 's'} have one)")
                for member in members:
                    self._entry(row, cat, *member, italic)
                grouped.update(keys)
                row.setExpanded(fold not in self._collapsed)
            for key, display, count in options:
                if key not in grouped:
                    self._entry(top, cat, key, display, count, italic)
            top.setExpanded(cat not in self._collapsed)
        self.tree.blockSignals(False)
        self._sync_checks()
        self._update_hint()  # (it mentions groups once there are any)
        self._update_titles()
        self.tree.verticalScrollBar().setValue(scroll)

    @staticmethod
    def _entry(parent, cat: str, key: str, display: str, count: int, italic: QFont) -> QTreeWidgetItem:
        """One value's checkbox row (its tick is set by _sync_checks)."""
        child = QTreeWidgetItem(parent, [f"{display}   ({count})"])
        child.setFirstColumnSpanned(True)
        child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        child.setCheckState(0, Qt.CheckState.Unchecked)
        child.setData(0, ROLE_CAT, cat)
        child.setData(0, ROLE_KEY, key)
        if key == NONE_KEY:
            child.setFont(0, italic)
        if cat == "color":
            child.setIcon(0, swatch_icon(key))
        return child

    def _mode_button(self, cat: str) -> QToolButton:
        """The "match any / match all" switch at the right of a heading."""
        button = QToolButton()
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the tree keeps the keyboard
        self._style_mode_button(button, cat)
        button.toggled.connect(lambda on, c=cat: self.set_match_all(c, on))
        self.mode_buttons[cat] = button
        return button

    def _style_mode_button(self, button: QToolButton, cat: str) -> None:
        on = cat in self._match_all
        noun = _NOUNS[cat]
        button.blockSignals(True)
        button.setChecked(on)
        button.blockSignals(False)
        button.setText("match all" if on else "match any")
        button.setToolTip(f"Showing only cards with every ticked {noun[:-1]}: click to show cards "
                          f"with any of them" if on else
                          f"Showing cards with any ticked {noun[:-1]}: click to show only cards "
                          f"with all of them")

    def _update_hint(self) -> None:
        alls = [_NOUNS[c] for c in MATCH_ALL_CATEGORIES if c in self._match_all]
        if not alls:
            text = "Ticked entries in one category match any of them; separate categories must all match."
        else:
            listed = alls[0] if len(alls) == 1 else ", ".join(alls[:-1]) + " and " + alls[-1]
            text = (f"Cards need every ticked entry in {listed}, and any ticked entry elsewhere; "
                    "separate categories must all match.")
            if any(self.scene.groups_of(GROUP_KINDS[c]) for c in MATCH_ALL_CATEGORIES if c in self._match_all):
                text += " A ticked strand group there needs every strand in it."
        self.hint.setText(text)

    def _update_titles(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            cat = top.data(0, ROLE_CAT)
            n = len(self._selection[cat])
            top.setText(0, f"{LABELS[cat]}   · {n} selected" if n else LABELS[cat])

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = self._menu_for(item) if item is not None else None
        if menu is not None and not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _menu_for(self, item) -> QMenu | None:
        """A row's right-click menu: follow or rename its strand. None for a group row
        (groups are renamed in the Strands panel)."""
        if item.data(0, ROLE_GROUP) is not None:
            return None
        cat = item.data(0, ROLE_CAT)
        key = item.data(0, ROLE_KEY)
        value = ""
        if key not in (None, NONE_KEY) and cat in (self._options or {}):
            value = next((d for k, d, _ in self._options[cat] if k == key), "")
        # POV and Introduces values are characters: rename / follow them as such.
        field = "characters" if cat in ("characters", "pov", "introduces") else cat
        menu = QMenu(self)
        if value and field == "characters":
            menu.addAction(f"Show thread of “{value}”", lambda: self.scene.show_thread(value))
        if field in RENAMABLE_FIELDS:  # color can't be renamed
            noun = FIELD_LABELS[field].lower()
            menu.addAction(f"Rename {noun} “{value}”…" if value else f"Rename a {noun}…",
                           lambda: self._rename(field, value))
        return menu

    def _rename(self, cat: str, value: str) -> None:
        self.scene.open_rename_dialog(cat, value)

    def on_value_renamed(self, cat: str, old: str, new: str) -> None:
        """Keep a checked filter value checked under its new name (runs before refresh)."""
        # Renaming a character renames it as a POV (and an introduction) too.
        for c in (cat, "pov", "introduces") if cat == "characters" else (cat,):
            if old.casefold() in self._selection.get(c, ()):
                self._selection[c].discard(old.casefold())
                self._selection[c].add(new.casefold())

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        key, members = item.data(0, ROLE_KEY), item.data(0, ROLE_MEMBERS)
        if key is None and members is None:
            return
        cat = item.data(0, ROLE_CAT)
        keys = set(members) if members is not None else {key}
        # A partly ticked group clicked becomes ticked (Qt's toggle): every strand in it.
        if item.checkState(0) == Qt.CheckState.Checked:
            self._selection[cat] |= keys
        else:
            self._selection[cat] -= keys
        self._sync_checks()  # the same strand elsewhere, and the groups around it
        self._update_titles()
        self.apply()
