"""Card commands that act on the selection, for the keyboard shortcuts and the Card menu.
Mixed into BoardScene (scene.py).

Each one works out what it acts on from the selection, does it as one undo step
(mark_modified folds the calls of one action together) and, when there's nothing to act
on, says so in the status bar instead of failing silently. Toggles on a mixed selection
go one way: if any target is open (or in the story), they all close (or leave it).
"""
from __future__ import annotations

from .card_item import CardItem
from .edge_item import EdgeItem

PATH_MODES = ("both", "before", "after")


class CommandsMixin:
    """Part of BoardScene: it uses the scene's own attributes and methods."""

    def _selected_cards(self) -> list[CardItem]:
        return [i for i in self.selectedItems() if isinstance(i, CardItem)]

    def command_groups(self) -> list[CardItem]:
        """What a group command acts on: the selected groups or, if no group is
        selected, the groups the selected cards are in."""
        cards = self._selected_cards()
        groups = [c for c in cards if c.is_group]
        if groups:
            return groups
        seen, out = set(), []
        for c in cards:
            parent = self.parent_of(c)
            if parent is not None and parent.card.id not in seen:
                seen.add(parent.card.id)
                out.append(parent)
        return out

    def toggle_collapse_selected(self) -> bool:
        """C: collapse the selected groups (or the groups of the selected cards), or
        expand them if they're all collapsed already. The folded groups end up
        selected, so pressing C again opens them."""
        groups = self.command_groups()
        if not groups:
            self.notice.emit("Select a group (or a card in one) to collapse or expand it")
            return False
        collapse = any(not g.card.collapsed for g in groups)
        changed = self.set_collapsed(groups, collapse)
        if collapse:  # hidden cards drop out of the selection: select their groups instead
            self.clearSelection()
            for g in groups:
                if g.isVisible():
                    g.setSelected(True)
        return changed

    def toggle_collapse_all(self) -> bool:
        """Shift+C: collapse every group, or expand them all if none is open."""
        groups = [i for i in self.cards.values() if i.is_group]
        if not groups:
            self.notice.emit("This board has no groups")
            return False
        return self.set_collapsed(groups, any(not g.card.collapsed for g in groups))

    def toggle_details_selected(self) -> bool:
        """D: open the selected cards' details, or close them if they're all open.
        Like the ▸ button, this isn't an edit (see show_details)."""
        items = self._selected_cards()
        if not items:
            self.notice.emit("Select a card to show or hide its details")
            return False
        show = any(not i.details_visible for i in items)
        # Top to bottom when opening, so each card pushes what's below it in turn.
        items.sort(key=lambda c: (c.pos().y(), c.pos().x()), reverse=not show)
        for item in items:
            self.show_details(item, show)
        return True

    def toggle_all_details(self) -> bool:
        """Shift+D: show every card's details, or hide them all if all are showing."""
        if not self.cards:
            return False
        self.set_all_details(any(not i.details_visible for i in self.cards.values()))
        return True

    def connect_from_selected(self) -> bool:
        """L: Connect to… from the one selected card or group; click the target."""
        cards = self._selected_cards()
        if len(cards) != 1:
            self.notice.emit("Select one card or group to connect from it")
            return False
        self.start_click_connection(cards[0])
        return True

    def reverse_selected_arrows(self) -> int:
        """R: reverse every selected arrow. Returns how many were selected."""
        edges = [i for i in self.selectedItems() if isinstance(i, EdgeItem)]
        if not edges:
            self.notice.emit("Select an arrow to reverse it")
            return 0
        for edge in edges:
            if edge.scene() is self:  # (reversing re-creates the arrow item)
                self.reverse_edge(edge)
        return len(edges)

    def toggle_outside_selected(self) -> bool:
        """O: leave the selected cards out of the story, or put them back if they're
        all out already. Strand cards are always outside it, so they're skipped."""
        items = [i for i in self._selected_cards() if not i.is_strand]
        if not items:
            self.notice.emit("Select a card to leave it out of the story (or put it back)")
            return False
        out = any(not i.card.outside_story for i in items)
        for item in items:
            self.set_outside_story(item, out)
        return True

    def arrange_selected_groups(self) -> int:
        """Ctrl+Shift+A: auto-arrange the selected groups (or the groups of the
        selected cards), inner groups first so outer ones fit their new size."""
        groups = [g for g in self.command_groups() if self.members_of(g)]
        if not groups:
            self.notice.emit("Select a group with cards in it to arrange it")
            return 0
        groups.sort(key=lambda g: -sum(1 for _ in self.ancestors(g)))
        for g in groups:
            self.auto_arrange_group(g)
        self.mark_modified()
        return len(groups)

    def cycle_paths_mode(self) -> str:
        """Shift+H: step the path highlight from before-and-after to only what leads
        here, only what follows, and back. With no path highlight, start one on the
        selected card at "only what leads here" (H gives before and after)."""
        if self.highlight_owner() == "paths" and self.highlight.focus in self.cards:
            item = self.cards[self.highlight.focus]
            mode = PATH_MODES[(PATH_MODES.index(self._paths_mode) + 1) % len(PATH_MODES)]
        else:
            cards = self._selected_cards()
            if len(cards) != 1:
                self.notice.emit("Select one card to highlight its paths")
                return ""
            item, mode = cards[0], "before"
        return self.highlight_paths(item, mode)
