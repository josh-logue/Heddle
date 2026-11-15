"""Making room: cards pushed aside when a card's details open (and given back when they
close), and neighbours pushed out of a grown group's way. Mixed into BoardScene
(scene.py)."""
from __future__ import annotations


from PySide6.QtCore import QRectF

from .card_item import CardItem

from .scene_consts import (
    PUSH_GAP,
)


class RoomMixin:
    """Part of BoardScene: it uses the scene's own attributes and methods."""

    def _make_room(self, grown: CardItem, before: dict[str, QRectF],
                   moves: list | None = None) -> None:
        """`grown` (a group arranged, or a card or group whose details opened) has grown
        right or down from its frame in `before`: push its neighbours the same way, then
        do the same for each enclosing group that grew as a result (`before` holds their
        old frames too). Each push is added to `moves` as (id, dx, dy), if given."""
        level = grown
        while level is not None:
            self._push_aside(level, before[level.card.id], moves)
            parent = self.parent_of(level)
            if parent is not None:
                self._refit_ids({parent.card.id})
            level = parent

    # ----- room for open details ----------------------------------------------
    def show_details(self, item: CardItem, visible: bool) -> None:
        """Open or close a card's (or group's) details. Opening grows it downwards and
        pushes what it would cover out of the way, as arranging does; closing moves
        those cards back, unless they've been moved since. None of this is an edit:
        undo history and the saved file keep the positions the cards have with details
        closed (see _details_offsets). Arrows stay put (CardItem.anchor_scene_rect)."""
        if visible == item.details_visible:
            return
        if not visible:
            item.set_details_visible(False)
            self._give_back(item.card.id)
            return
        before = {g.card.id: g.card_scene_rect() for g in (item, *self.ancestors(item))}
        item.set_details_visible(True)
        moves: list[tuple[str, float, float]] = []
        self._make_room(item, before, moves)
        if moves:
            self._room_loans[item.card.id] = moves

    def _carried(self, item: CardItem) -> list[CardItem]:
        """What moves when `item` moves: itself and, for a group, everything inside."""
        return [item, *self.descendants(item)] if item.is_group else [item]

    def _note_room_move(self, item: CardItem) -> None:
        """Remember where a move made for open details left these cards, so a card moved
        by hand afterwards can be told apart (that move is a real edit)."""
        for x in self._carried(item):
            self._room_at[x.card.id] = (x.pos().x(), x.pos().y())

    def _room_valid(self, cid: str) -> bool:
        """Still where the last push (or give-back) left it? Otherwise it was moved by
        hand: from then on its position is its own, and it isn't moved back."""
        item, at = self.cards.get(cid), self._room_at.get(cid)
        if item is None or at is None:
            return False
        if (item.pos().x(), item.pos().y()) != at:
            del self._room_at[cid]
            return False
        return True

    def _details_offsets(self) -> dict[str, tuple[float, float]]:
        """{card id: how far it has been pushed to make room for open details}, for
        cards not moved by hand since (a group's cards move with it)."""
        out: dict[str, tuple[float, float]] = {}
        for moves in self._room_loans.values():
            for cid, dx, dy in moves:
                item = self.cards.get(cid)
                if item is None:
                    continue
                for x in self._carried(item):
                    xid = x.card.id
                    if self._room_valid(xid):
                        ox, oy = out.get(xid, (0.0, 0.0))
                        out[xid] = (ox + dx, oy + dy)
        return out

    def _give_back(self, cid: str) -> None:
        """Details closed: move back what opening them pushed (latest push first)."""
        touched: set[str] = set()
        for mid, dx, dy in reversed(self._room_loans.pop(cid, [])):
            item = self.cards.get(mid)
            if item is None or not self._room_valid(mid):
                continue
            item.moveBy(-dx, -dy)
            self._note_room_move(item)
            if item.card.parent:
                touched.add(item.card.parent)
        if touched:
            self._refit_ids(touched)

    def _push_aside(self, grown: CardItem, old: QRectF, moves: list | None = None) -> None:
        """Move the cards and groups beside `grown` (same parent) that its frame now
        covers out of the way: right if they were right of its old frame, down if
        they were below it (whichever is the shorter move if both), leaving the usual
        gap. Whatever a moved item then covers moves on in turn. Items that already
        overlapped the old frame stay where they are."""
        parent_id = grown.card.parent
        siblings = [c for c in self.cards.values()
                    if c is not grown and c.card.parent == parent_id]
        movers = [(grown, old, grown.card_scene_rect())]
        tol = 0.5
        for _ in range(len(siblings) * 4 + 4):  # every push moves strictly on: this ends
            if not movers:
                break
            mover, was, now = movers.pop(0)
            for s in siblings:
                r = s.card_scene_rect()
                if s is mover or not r.intersects(now) or r.intersects(was):
                    continue
                right = now.right() + PUSH_GAP - r.left() if r.left() >= was.right() - tol else None
                down = now.bottom() + PUSH_GAP - r.top() if r.top() >= was.bottom() - tol else None
                if right is None and down is None:
                    continue
                if down is None or (right is not None and right <= down):
                    dx, dy = right, 0.0
                else:
                    dx, dy = 0.0, down
                s.moveBy(dx, dy)
                if moves is not None:
                    moves.append((s.card.id, dx, dy))
                    self._note_room_move(s)
                movers.append((s, r, s.card_scene_rect()))
