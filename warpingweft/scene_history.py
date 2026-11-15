"""Undo snapshots, and turning the board into data and back (saving, loading, undo and redo
all rebuild from BoardData). Mixed into BoardScene (scene.py)."""
from __future__ import annotations

from dataclasses import replace


from .card_item import CardItem
from .model import (
    DISPLAY_DEFAULTS,
    BoardData, CardData,
    ConnectionData,
    RENAMABLE_FIELDS, clean_display, copy_route, RouteData, StrandInfo,
)

from .scene_consts import (
    BASE_SCENE_RECT, _CARD_FIELDS, _CONN_FIELDS, _ROUTE_FIELDS, _STRAND_FIELDS,
)


class HistoryMixin:
    """Part of BoardScene: it uses the scene's own attributes and methods."""

    # ----- undo / redo --------------------------------------------------------
    def _snapshot(self) -> tuple:
        """A compact, immutable record of the board for the undo history.

        Each card is a tuple of its field values. The values are the very string and
        number objects the live card holds (nothing is copied), and a card that hasn't
        changed since the last snapshot reuses that snapshot's tuple, so in typical
        editing each undo step costs little more than one reference per card. Equal
        boards produce equal snapshots, and comparing them is quick because unchanged
        cards are the same objects."""
        prev, cache = self._snap_cache, {}
        cards = []
        offsets = self._details_offsets()
        for item in self.cards.values():
            c = item.card
            if not item.is_group:  # a plain card's position lives in pos(); groups keep an anchor
                c.x, c.y = item.pos().x(), item.pos().y()
            t = tuple(tuple(v) if isinstance(v, list) else v
                      for v in (getattr(c, f) for f in _CARD_FIELDS))
            if c.id in offsets:  # moved only to make room for open details: not an edit
                dx, dy = offsets[c.id]
                t = tuple(c.x - dx if f == "x" else c.y - dy if f == "y" else v
                          for f, v in zip(_CARD_FIELDS, t))
            old = prev.get(c.id)
            if old == t:
                t = old
            cache[c.id] = t
            cards.append(t)
        edges = []
        for e in self.edges:  # arrows are shared between snapshots the same way
            t = tuple(getattr(e.conn, f) for f in _CONN_FIELDS)
            old = prev.get(("edge", e.conn.id))
            if old == t:
                t = old
            cache[("edge", e.conn.id)] = t
            edges.append(t)
        edges = tuple(edges)
        self._snap_cache = cache
        meta = (tuple(self.custom_colors),
                tuple((k, tuple(v)) for k, v in sorted(self.saved_values.items()) if v),
                tuple(sorted(self.display.items())),
                tuple(tuple(tuple(v) if isinstance(v, list) else v
                            for v in (getattr(r, f) for f in _ROUTE_FIELDS))
                      for r in self.routes.values()),
                tuple(tuple(getattr(s, f) for f in _STRAND_FIELDS) for s in self.strand_info.values()))
        return (tuple(cards), edges, meta)

    @staticmethod
    def _board_from_snapshot(state: tuple) -> BoardData:
        cards, edges, (colors, saved, display, routes, strands) = state
        return BoardData(
            cards=[CardData(**{f: list(v) if isinstance(v, tuple) else v
                               for f, v in zip(_CARD_FIELDS, t)}) for t in cards],
            connections=[ConnectionData(**dict(zip(_CONN_FIELDS, e))) for e in edges],
            custom_colors=list(colors),
            saved_values={k: list(v) for k, v in saved},
            display=dict(display),
            routes=[RouteData(**{f: list(v) if isinstance(v, tuple) else v
                                 for f, v in zip(_ROUTE_FIELDS, t)}) for t in routes],
            strands=[StrandInfo(**dict(zip(_STRAND_FIELDS, t))) for t in strands])

    def reset_history(self) -> None:
        """Forget undo history (new or opened board); the current board counts as saved."""
        self._commit_pending = False
        self._nudge_timer.stop()
        self._removed_details.clear()
        self._remember_strands()
        self.history.reset(self._snapshot())
        self.history_changed.emit()

    def _current_strands(self) -> dict[tuple[str, str], str]:
        return {(f, name.casefold()): name for f in RENAMABLE_FIELDS for name in self.all_values(f)}

    def _remember_strands(self) -> None:
        self._strand_names = self._current_strands()
        self._let_go.clear()

    def _keep_dropped_strands(self) -> None:
        """Strands belong to the board, not to the cards using them: a strand that an edit
        left unused (taken off its last card, or that card deleted) is kept as a saved
        strand. Only a rename or Remove Unused Strands takes one off the list."""
        now = self._current_strands()
        for key, name in self._strand_names.items():
            if key not in now and key not in self._let_go:
                self.saved_values[key[0]] = [*self.saved_values.get(key[0], []), name]

    def flush_history(self) -> None:
        """Commit any pending edit to the history now."""
        if self._nudge_timer.isActive():  # a nudge burst still settling
            self._nudge_timer.stop()
            self._commit_pending = True
            self.end_move()
        if self._commit_pending:
            self._commit_pending = False
            self._keep_dropped_strands()
            self._remember_strands()
            self.history.commit(self._snapshot())
            self.history_changed.emit()

    def undo(self) -> bool:
        self.flush_history()
        leaving = self.history.current  # the board as it is now (just recorded)
        return self._restore(self.history.undo(), leaving)

    def redo(self) -> bool:
        self.flush_history()
        leaving = self.history.current
        return self._restore(self.history.redo(), leaving)

    def _restore(self, state: tuple | None, leaving: tuple | None = None) -> bool:
        """Rebuild the board from a snapshot. `leaving` (the snapshot of the board as
        it is) is what's put back if that fails, instead of copying the board first."""
        if state is None:
            return False
        self.cancel_connection()  # abandon a half-drawn connection
        details = {cid for cid, item in self.cards.items() if item.details_visible}
        details |= self._removed_details - self.cards.keys()
        selected = {cid for cid, item in self.cards.items() if item.isSelected()}
        highlight = self._highlight
        self._restoring = True
        try:
            fallback = (lambda: self._board_from_snapshot(leaving)) if leaving is not None else None
            self.load_board_data(self._board_from_snapshot(state), fallback)
            # The snapshot has the cards as they are closed: reopening makes room again.
            reopen = [self.cards[cid] for cid in details & self.cards.keys()]
            reopen.sort(key=lambda i: (i.is_group, i.pos().y(), i.pos().x()))
            for item in reopen:
                self.show_details(item, True)
            for cid in selected & self.cards.keys():
                self.cards[cid].setSelected(True)
            if highlight is not None and highlight.owner == "thread":
                self.show_thread(self._thread_name)  # renumbered for the board as it now is
            elif highlight is not None:  # keep showing it for the cards that still exist
                ids, edge_ids, focus, label, owner = highlight
                if ids & self.cards.keys():
                    self.set_highlight(ids & self.cards.keys(), edge_ids,
                                       focus if focus in self.cards else None, label, owner)
            self._remember_strands()  # undo may take back a strand: that's not dropping it
            self.modified.emit()  # refresh filter, title, autosave — but don't commit
        finally:
            self._restoring = False
        self.history_changed.emit()
        return True

    # ----- persistence ------------------------------------------------------
    def to_board_data(self) -> BoardData:
        cards = []
        offsets = self._details_offsets()  # room made for open details isn't saved
        for item in self.cards.values():
            if not item.is_group:  # a group keeps its own details-independent anchor
                item.card.x, item.card.y = item.pos().x(), item.pos().y()
            dx, dy = offsets.get(item.card.id, (0.0, 0.0))
            cards.append(replace(item.card, x=item.card.x - dx, y=item.card.y - dy))
        return BoardData(cards=cards, connections=[replace(e.conn) for e in self.edges],
                         custom_colors=list(self.custom_colors),
                         saved_values={k: list(v) for k, v in self.saved_values.items() if v},
                         display=dict(self.display),
                         routes=[copy_route(r) for r in self.routes.values()],
                         strands=[replace(s) for s in self.strand_info.values()])

    def clear_board(self) -> None:
        self._end_click_mode()
        self._temp_line = self._connect_source = self._drop_target = self._group_hint = None
        self._strand_hover = None
        self._room_loans, self._room_at = {}, {}
        self._ghost = None  # clear() below deletes it
        self._thread_line = None  # likewise
        self.clear()
        self.cards.clear()
        self._children.clear()
        self._card_rank.clear()
        self.edges.clear()
        self.custom_colors.clear()
        self.setSceneRect(BASE_SCENE_RECT)
        self._moving = False
        self.saved_values = {}
        self.display = dict(DISPLAY_DEFAULTS)
        self.routes = {}
        self.strand_info = {}
        self._graph = None
        if self._highlight is not None:  # its cards are gone
            self._highlight = None
            self.highlight_changed.emit("")

    def load_board_data(self, board: BoardData, fallback=None) -> None:
        """Replace the board. All-or-nothing: the cards are built before anything is
        cleared, and if a later step still fails the previous board is put back
        before the error is re-raised, so a bad file can never leave a half-loaded board.
        `fallback()`, if given, makes that previous board only when it's needed (undo
        already has it), saving a copy of the whole board on every undo."""
        items = [CardItem(card) for card in board.cards]  # may raise; board untouched
        previous = self.to_board_data() if fallback is None else None
        try:
            self._populate(board, items)
        except Exception:
            if previous is None:
                previous = fallback()
            self.clear_board()
            self._populate(previous, [CardItem(card) for card in previous.cards])
            raise

    def _populate(self, board: BoardData, items: list[CardItem]) -> None:
        self.clear_board()
        self.custom_colors = list(board.custom_colors)
        self.saved_values = {k: list(v) for k, v in board.saved_values.items()}
        self.display = clean_display(board.display)
        self.routes = {tuple(r.key): copy_route(r) for r in board.routes if r.key and not r.is_blank()}
        self.strand_info = {s.key: replace(s) for s in board.strands
                            if s.kind and s.name and not s.is_blank()}
        for item in items:
            self.add_card(item.card, item)
        # Drop broken memberships: missing parent, parent not a group, or loops.
        for item in self.cards.values():
            parent = self.parent_of(item)
            if item.card.parent and (parent is None or not parent.is_group):
                self.set_parent(item, "")
        for item in self.cards.values():
            seen = {item.card.id}
            p = self.parent_of(item)
            while p is not None:
                if p.card.id in seen:
                    self.set_parent(item, "")
                    break
                seen.add(p.card.id)
                p = self.parent_of(p)
        self._update_z()
        self._refit_ids({i.card.id for i in self.cards.values() if i.is_group})
        self._loading_edges = True
        try:
            for conn in board.connections:
                source, target = self.cards.get(conn.source), self.cards.get(conn.target)
                if source and target:
                    self.add_connection(source, target, conn_id=conn.id, like=conn)
        finally:
            self._loading_edges = False
        for e in self.edges:  # arrows both ways between two cards sit side by side
            if e.has_reverse():
                e.adjust()
        self.apply_collapse()  # folded groups hide their cards, and arrows meet the folds
        self.update_scene_rect()
        if not self._restoring:
            # (Undo/redo signal a change straight after rebuilding, which works the
            # introductions out; doing it here as well would do it twice.)
            self.update_introductions()
