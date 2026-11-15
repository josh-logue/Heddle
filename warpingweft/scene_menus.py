"""The board's right-click menus. Mixed into BoardScene (scene.py)."""
from __future__ import annotations


from PySide6.QtCore import QPointF
from PySide6.QtGui import QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QMenu,
)

from . import theme
from .card_item import CardItem
from .arrow_dialog import STYLE_LABELS, style_icon
from .edge_item import EdgeItem
from .model import (
    ARROW_STYLES, CARD_COLORS, COLOR_NAMES,
)
from .shortcuts import ENTER, ESC, KEYS, menu_text as k
from .widgets import swatch_icon

STD = QKeySequence.StandardKey
# The row limits offered on a group's right-click menu (any other is set in the group editor).
WRAP_CHOICES = (3, 4, 5, 6, 8, 10)



class MenusMixin:
    """Part of BoardScene: it uses the scene's own attributes and methods.

    Items that have a keyboard shortcut show it (k(): the key after a tab, from
    shortcuts.KEYS). The menu acts on the item clicked, the key on the selection, which
    is the same thing once the clicked card is selected (_add_clipboard_actions does that)."""

    def contextMenuEvent(self, event) -> None:
        if self._suppress_menu or self._click_connecting:
            self._suppress_menu = False
            event.accept()
            return
        menu = self.build_context_menu(self._item_at(event.scenePos()), event.scenePos())
        menu.exec(event.screenPos())
        event.accept()

    def _add_wrap_menu(self, menu: QMenu, group: CardItem) -> None:
        """The group's row limit for auto-arranging: a submenu of common choices, plus
        the current one if it was set to something else in the group editor."""
        sub = menu.addMenu("Wrap rows after")
        choices = sorted({0, *WRAP_CHOICES, group.card.arrange_wrap})
        picks = QActionGroup(sub)
        for n in choices:
            act = sub.addAction("No limit" if n == 0 else f"{n} step{'s' if n != 1 else ''}")
            act.setCheckable(True)
            act.setChecked(n == group.card.arrange_wrap)
            picks.addAction(act)
            act.triggered.connect(lambda _checked=False, n=n: self._set_wrap(group, n))

    def _set_wrap(self, group: CardItem, n: int) -> None:
        if group.card.arrange_wrap != n:
            group.card.arrange_wrap = n
            self.mark_modified()

    def build_context_menu(self, item, pos: QPointF) -> QMenu:
        """The right-click menu for `item` (a card, group, arrow or None for the canvas)
        at scene position `pos`. Separate from showing it, so tests can look inside."""
        menu = QMenu()
        if isinstance(item, CardItem) and item.is_group:
            menu.addAction(k("Edit group…", ENTER), lambda: self.edit_card(item))
            # Acts on every selected group when this one is part of the selection.
            folding = ([g for g in self.selectedItems() if isinstance(g, CardItem) and g.is_group]
                       if item.isSelected() else [item])
            menu.addAction(k("Expand group" if item.collapsed else "Collapse group", KEYS["collapse"]),
                           lambda: self.set_collapsed(folding, not item.collapsed))
            menu.addAction(k("Hide details" if item.details_visible else "Show details", KEYS["details"]),
                           lambda: self.show_details(item, not item.details_visible))
            menu.addAction(k("Connect to…", KEYS["connect"]), lambda: self.start_click_connection(item))
            self._add_path_actions(menu, item)
            menu.addAction("Add card here", lambda: self.create_card_at(pos, group=item))
            self._add_clipboard_actions(menu, item, pos)
            arrange_act = menu.addAction(k("Auto-arrange cards", KEYS["arrange"]),
                                         lambda: (self.auto_arrange_group(item), self.mark_modified()))
            arrange_act.setEnabled(bool(self.members_of(item)))
            color_act = menu.addAction("Rows by color when arranging")
            color_act.setCheckable(True)
            color_act.setChecked(item.card.arrange_by_color)
            color_act.toggled.connect(lambda on: (setattr(item.card, "arrange_by_color", on),
                                                  self.mark_modified()))
            vertical_act = menu.addAction("Arrange top to bottom")
            vertical_act.setCheckable(True)
            vertical_act.setChecked(item.card.arrange_vertical)
            vertical_act.toggled.connect(lambda on: (setattr(item.card, "arrange_vertical", on),
                                                     self.mark_modified()))
            grid_act = menu.addAction("Unconnected cards in a grid")
            grid_act.setCheckable(True)
            grid_act.setChecked(item.card.arrange_grid)
            grid_act.toggled.connect(lambda on: (setattr(item.card, "arrange_grid", on),
                                                 self.mark_modified()))
            self._add_wrap_menu(menu, item)
            if item.manually_sized:
                menu.addAction("Fit frame to cards", lambda: (item.reset_size(), self.mark_modified()))
            menu.addSeparator()
            if self.parent_of(item) is not None:
                menu.addAction("Remove from group",
                               lambda: (self.remove_from_group(item), self.mark_modified()))
            menu.addAction("Ungroup (keep cards)",
                           lambda: (self.release_members(item), self.mark_modified()))
            menu.addAction("Delete group (keep cards)",
                           lambda: (self.remove_card(item), self.mark_modified()))
            menu.addAction(k("Delete group and its cards", STD.Delete), lambda: self.delete_group_with_contents(item))
        elif isinstance(item, CardItem):
            if item.is_strand:
                menu.addAction("Show in Strands",
                               lambda: self.strand_card_opened.emit(item.card.strand_kind, item.card.strand))
            menu.addAction(k("Edit card…", ENTER), lambda: self.edit_card(item))
            menu.addAction(k("Hide details" if item.details_visible else "Show details", KEYS["details"]),
                           lambda: self.show_details(item, not item.details_visible))
            menu.addAction(k("Connect to…", KEYS["connect"]), lambda: self.start_click_connection(item))
            if not item.is_strand:  # (strand cards are outside the story)
                self._add_path_actions(menu, item)
            self._add_clipboard_actions(menu, item, pos)
            menu.addSeparator()
            if self.parent_of(item) is not None:
                menu.addAction("Remove from group",
                               lambda: (self.remove_from_group(item), self.mark_modified()))
            menu.addAction(k("Delete card", STD.Delete), lambda: (self.remove_card(item), self.mark_modified()))
        elif isinstance(item, EdgeItem):
            # Right-clicking one of several selected arrows acts on all of them.
            targets = [e for e in self.selectedItems() if isinstance(e, EdgeItem)] \
                if item.isSelected() else [item]
            n = len(targets)
            menu.addAction(k("Edit arrow…" if n == 1 else f"Edit {n} arrows…", ENTER),
                           lambda: self.edit_arrows(targets))
            style_menu = menu.addMenu("Line style")
            for key in ARROW_STYLES:
                act = style_menu.addAction(style_icon(key), STYLE_LABELS[key],
                                           lambda k=key: self.set_arrow_style(targets, style=k))
                act.setCheckable(True)
                act.setChecked(all(e.conn.style == key for e in targets))
            color_menu = menu.addMenu("Color")
            choices = [("", "Default")] + [(c, COLOR_NAMES[c]) for c in CARD_COLORS] \
                + [(c, c) for c in self.custom_colors]
            for value, name in choices:
                icon = swatch_icon(value or theme.current().edge_line.name())
                act = color_menu.addAction(icon, name,
                                           lambda v=value: self.set_arrow_style(targets, color=v))
                act.setCheckable(True)
                act.setChecked(all(e.conn.color == value for e in targets))
            color_menu.addSeparator()
            color_menu.addAction("Custom…", lambda: self.edit_arrows(targets))
            menu.addSeparator()
            menu.addAction(k("Reverse direction" if n == 1 else f"Reverse {n} arrows", KEYS["reverse"]),
                           lambda: [self.reverse_edge(e) for e in list(targets)])
            menu.addSeparator()
            menu.addAction(k("Delete connection" if n == 1 else f"Delete {n} connections", STD.Delete),
                           lambda: (self.remove_edges(targets), self.mark_modified()))
        else:
            menu.addAction("Add card here", lambda: self.create_card_at(pos))
            self._add_clipboard_actions(menu, None, pos)
        return menu

    def _add_clipboard_actions(self, menu: QMenu, item: CardItem | None, pos: QPointF) -> None:
        """Copy / Duplicate for the clicked card (and the rest of the selection, if it's
        part of one), and Paste here. The clipboard itself is handled by the window."""
        menu.addSeparator()
        if item is not None:
            if not item.isSelected():  # right-clicking an unselected card acts on just it
                self.clearSelection()
                item.setSelected(True)
            n = sum(1 for i in self.selectedItems() if isinstance(i, CardItem))
            suffix = f" {n} cards" if n > 1 else ""
            if n > 1:
                menu.addAction(k(f"Edit {n} selected cards…", ENTER), self.edit_selected_cards)
            menu.addAction(k(f"Copy{suffix}", STD.Copy), self.copy_requested.emit)
            menu.addAction(k(f"Duplicate{suffix}", KEYS["duplicate"]), self.duplicate_selected)
        # (Ctrl+V pastes at the mouse pointer too, so "here" holds for the key as well.)
        paste = menu.addAction(k("Paste here", STD.Paste), lambda: self.paste_requested.emit(pos))
        paste.setEnabled(self.can_paste())

    def _add_path_actions(self, menu: QMenu, item: CardItem) -> None:
        sub = menu.addMenu("Highlight paths")
        sub.addAction(k("Before and after", KEYS["paths"]), lambda: self.highlight_paths(item, "both"))
        sub.addAction("Only what leads here", lambda: self.highlight_paths(item, "before"))
        sub.addAction("Only what follows", lambda: self.highlight_paths(item, "after"))
        if not self.display.get("story_tools", True):
            if self._highlight is not None:
                menu.addAction(k("Clear highlight", ESC), self.clear_highlight)
            return
        outside = menu.addAction(k("Not part of the story", KEYS["outside_story"]),
                                 lambda: self.set_outside_story(item, not item.card.outside_story))
        outside.setCheckable(True)
        outside.setChecked(item.card.outside_story)
        menu.addAction(k("Read from here", KEYS["read"]), lambda: self.read_requested.emit(item))
        if item.card.characters:
            threads = menu.addMenu("Character thread")
            for name in item.card.characters:
                threads.addAction(name, lambda n=name: self.show_thread(n))
        if self._highlight is not None:
            menu.addAction(k("Clear highlight", ESC), self.clear_highlight)
