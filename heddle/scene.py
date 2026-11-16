"""The board canvas: owns cards, groups and connections; handles connecting,
group membership (drag in/out), and menus."""
from __future__ import annotations

import copy
import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QGraphicsLineItem, QGraphicsPathItem, QGraphicsScene, QMessageBox,
)

from . import theme
from .card_item import CARD_WIDTH, CORNER, GROUP_PAD, GROUP_Z, CardItem
from .arrow_dialog import ArrowDialog
from .dialogs import CardDialog
from .edge_item import EdgeItem
from .filters import FilterCounts
from .graph import StoryGraph
from .history import History
from .layout import Node, arrange
from .model import (
    ARROW_STYLES, BULK_LIST_FIELDS, CARD_COLORS, DISPLAY_DEFAULTS,
    KIND_GROUP, BoardData, CardData,
    ConnectionData,
    board_values,
    new_id, RENAMABLE_FIELDS, apply_bulk_edit, clone_fragment, copy_route, replace_text, RouteData, StrandInfo,
    title_labels,
)
from .multi_edit import MultiEditDialog
from .scene_consts import (  # noqa: F401 (re-exported: other modules use scene.GRID etc.)
    GRID, BASE_SCENE_RECT, SCENE_MARGIN, PUSH_GAP, PASTE_OFFSET, NUDGE_STEP, NUDGE_FINE,
    NUDGE_SETTLE_MS, NUDGE_KEYS, _CARD_FIELDS, _CONN_FIELDS, _ROUTE_FIELDS, _STRAND_FIELDS,
    MERGED_DESCRIPTIONS, _LAYOUT_OPTIONS, _LOOK_OPTIONS, MAJOR_EVERY, ARRANGE_GAP,
    ARRANGE_COLUMNS, NEW_CARD_MIN_DRAG, REROUTE_DELAY_MS, DRAG_LIFT, Highlight,
)
from .scene_history import HistoryMixin
from .scene_strands import StrandsMixin
from .scene_room import RoomMixin
from .scene_menus import MenusMixin
from .scene_commands import CommandsMixin




class BoardScene(HistoryMixin, StrandsMixin, RoomMixin, MenusMixin, CommandsMixin, QGraphicsScene):
    modified = Signal()
    value_renamed = Signal(str, str, str)  # field, old value, new value
    history_changed = Signal()  # undo/redo availability or saved-state changed
    connect_mode_changed = Signal(bool)  # click-to-connect started / ended
    highlight_changed = Signal(str)      # the highlight's description; "" when cleared
    read_requested = Signal(object)      # card menu "Read from here": the window opens the reader
    copy_requested = Signal()            # context menu: the window owns the clipboard
    paste_requested = Signal(QPointF)
    strand_card_opened = Signal(str, str)  # a strand card double-clicked: (kind, name) to show
    notice = Signal(str)                   # a short message for the status bar
    # An editor dialog is about to open: the Card panel saves what's typed first, so
    # the dialog starts from it and nothing typed is lost or written over afterwards.
    dialog_opening = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(BASE_SCENE_RECT)
        self.cards: dict[str, CardItem] = {}
        self.edges: list[EdgeItem] = []
        self.custom_colors: list[str] = []
        self.saved_values: dict[str, list[str]] = {}  # values kept without any card using them
        self.display: dict = dict(DISPLAY_DEFAULTS)    # this board's display options
        # Fields given to routes (Routes panel), by route key; only routes with something set.
        self.routes: dict[tuple[str, ...], RouteData] = {}
        # Strands' descriptions and pictures (Strands panel), by (kind, casefolded
        # name); only strands with something set. Picture paths are absolute here.
        self.strand_info: dict[tuple[str, str], StrandInfo] = {}
        # While exporting an image: "plain" (canvas colour, no grid), "transparent"
        # (no background), or None (normal drawing).
        self.export_background: str | None = None
        self._highlight: Highlight | None = None  # the highlight showing, if any
        self._paths_mode = "both"  # the last path highlight's direction (Shift+H steps it)
        self._graph: StoryGraph | None = None  # built on demand; dropped on every change
        self.modified.connect(self._forget_graph)
        self._reroute_timer = QTimer(self)
        self._reroute_timer.setSingleShot(True)
        self._reroute_timer.setInterval(REROUTE_DELAY_MS)
        self._reroute_timer.timeout.connect(self._reroute_if_needed)
        self.modified.connect(self._schedule_reroute)
        # "Avoiding cards" routing is slow (a search per arrow), so the board is routed
        # again only if it may have changed shape since every arrow was last routed:
        # the shape then, and whether any card has moved or resized since (even if it
        # went back: arrows touching it were drawn against the shape in between).
        self._routed_shape: tuple | None = None
        self._routes_dirty = False
        self._reroute_wanted = False  # a change arrived mid-move: route when it ends
        # Characters each card introduces (worked out from the arrows, not saved), kept
        # up to date on every change; and the character thread being shown, if any.
        self.introductions: dict[str, list[str]] = {}
        self._thread_name = ""
        self._thread_ids: list[str] = []   # the cards the dashed thread line joins, in order
        self._thread_line_due = False      # a card on it moved: redraw once events settle
        self._thread_line: QGraphicsPathItem | None = None
        self.modified.connect(self.update_introductions)
        self.modified.connect(self.update_scene_rect)
        self._connect_source: CardItem | None = None
        self._temp_line: QGraphicsLineItem | None = None
        self._ghost: QGraphicsPathItem | None = None  # outline of the card a drop would create
        self._new_card_size: tuple[float, float] | None = None
        self._drop_target: CardItem | None = None
        self._group_hint: CardItem | None = None
        self._strand_hover: CardItem | None = None  # outlined while a strand is dragged over it
        self._lifted: dict = {}  # items raised for a drag -> their usual z
        self._click_connecting = False
        self.can_paste = lambda: False  # replaced by the window: is there something to paste?
        self._suppress_menu = False  # the right-click that cancelled connect mode
        # Arrow-key nudges: the undo step is recorded once the keys go quiet.
        self._nudge_timer = QTimer(self)
        self._nudge_timer.setSingleShot(True)
        self._nudge_timer.setInterval(NUDGE_SETTLE_MS)
        self._nudge_timer.timeout.connect(self._end_nudge)
        # True while cards are being dragged or nudged: "avoiding cards" arrows are
        # drawn as plain curves meanwhile (re-routing on every mouse move is slow),
        # and routed around cards once the move ends.
        self._moving = False
        # Above zero while every selected card is being moved by the same step (a
        # mouse drag or a nudge): a moving group then leaves its selected cards alone,
        # since they're moving themselves. Any other move carries them.
        self._selection_moves = 0
        self._loading_edges = False  # arrows being added in bulk: placed once afterwards
        self.snap_to_grid = False  # cards land on the grid when dropped, nudged or created
        self.history = History()
        # group id -> ids of its direct members (kept by set_parent), and each card's
        # place in the order cards were added, so members_of needn't scan the board.
        self._children: dict[str, set[str]] = {}
        self._card_rank: dict[str, int] = {}
        self._next_rank = 0
        # card id (or ("edge", id)) -> its tuple in the last snapshot, for sharing
        self._snap_cache: dict = {}
        self._removed_details: set[str] = set()  # ids of deleted cards that had details shown
        # Room made for open details (show_details): the pushes each open card made,
        # and where those pushes left the cards they moved.
        self._room_loans: dict[str, list[tuple[str, float, float]]] = {}
        self._room_at: dict[str, tuple[float, float]] = {}
        self._commit_pending = False
        self._restoring = False
        # Every strand on the board when the history last recorded it, by (kind,
        # casefolded name), and the ones an edit deliberately took off (renamed or
        # removed as unused): see _keep_dropped_strands.
        self._strand_names: dict[tuple[str, str], str] = {}
        self._let_go: set[tuple[str, str]] = set()
        self.reset_history()

    def mark_modified(self) -> None:
        self.modified.emit()
        # One user action can call this several times (e.g. edit + regroup + arrange);
        # committing once the event loop is idle again folds them into a single undo step.
        if not self._restoring and not self._commit_pending:
            self._commit_pending = True
            QTimer.singleShot(0, self.flush_history)

    def _dialog_parent(self):
        views = self.views()
        return views[0].window() if views else None

    # ----- group relationships ----------------------------------------------
    def members_of(self, group: CardItem) -> list[CardItem]:
        """The group's direct members, in the order they were added to the board."""
        ids = self._children.get(group.card.id)
        if not ids:
            return []
        rank = self._card_rank
        return [self.cards[i] for i in sorted(ids, key=rank.__getitem__)]

    # ----- collapsed groups ---------------------------------------------------------
    def visible_end(self, item: CardItem) -> CardItem:
        """What stands for `item` on the canvas: itself, or the outermost collapsed
        group it's inside (whose folded frame its arrows meet)."""
        shown = item
        for a in self.ancestors(item):
            if a.card.collapsed:
                shown = a
        return shown

    def set_collapsed(self, groups, collapsed: bool) -> bool:
        """Fold groups to their title bars (their cards hidden, still in place) or
        unfold them: one undo step. Unfolding pushes neighbours aside, as arranging
        does. Story tools don't change: the story doesn't care what's folded."""
        groups = [g for g in groups if g.is_group and g.card.collapsed != collapsed]
        if not groups:
            return False
        before = {i.card.id: i.card_scene_rect() for g in groups for i in (g, *self.ancestors(g))}
        for g in groups:
            g.card.collapsed = collapsed
        self._refit_ids({g.card.id for g in groups})  # the frame folds (or opens) first...
        self.apply_collapse()                          # ...then arrows meet it
        if not collapsed:
            for g in groups:
                self._make_room(g, before)
        self.update_scene_rect()
        self.mark_modified()
        return True

    def reveal(self, items) -> bool:
        """Unfold every collapsed group hiding one of `items` (a search match, a story
        check result, a reader step), as one undo step. True if anything unfolded."""
        hidden_in = {a for i in items for a in self.ancestors(i) if a.card.collapsed}
        return self.set_collapsed(list(hidden_in), False) if hidden_in else False

    def apply_collapse(self) -> None:
        """Show or hide every card by whether a group around it is collapsed, then
        redraw arrows: those whose ends both fold into the same group are hidden, and
        those meeting the same collapsed groups are drawn once, marked ×N."""
        for item in self.cards.values():
            shown = self.visible_end(item) is item
            if item.isVisible() != shown:
                item.setVisible(shown)
        self._place_edges()

    def _place_edges(self) -> None:
        pairs: dict[tuple, list[EdgeItem]] = {}
        for e in self.edges:
            a, b = e.ends()
            if a is b:
                e.merged = 0
                e.setVisible(False)
            else:
                pairs.setdefault((a, b), []).append(e)
        for (a, b), edges in pairs.items():
            for n, e in enumerate(edges):
                merged = len(edges) if n == 0 and len(edges) > 1 else 0
                e.setVisible(n == 0)
                if n == 0 and (merged != e.merged or e.drawn_ends != (a, b)):
                    e.merged = merged
                    e.adjust()
                e.merged = merged

    def _refresh_visibility(self, item: CardItem) -> None:
        """A card changed group: it (and its contents) may now be folded away or out."""
        changed = False
        for x in (item, *self.descendants(item)):
            shown = self.visible_end(x) is x
            if x.isVisible() != shown:
                x.setVisible(shown)
                changed = True
        if changed:
            self._place_edges()

    def folded_edges(self, group: CardItem) -> list[EdgeItem]:
        """Arrows of the cards folded away inside a collapsed group (drawn to its frame)."""
        inside = self.descendants(group)
        return [e for m in inside for e in m.edges]

    def has_collapsed(self) -> bool:
        return any(i.card.collapsed for i in self.cards.values())

    def set_search_hits(self, ids) -> None:
        """Collapsed groups show how many search matches are hidden inside them."""
        ids = set(ids)
        counts: dict[str, int] = {}
        for cid in ids:
            item = self.cards.get(cid)
            if item is not None and not item.isVisible():
                shown = self.visible_end(item)
                counts[shown.card.id] = counts.get(shown.card.id, 0) + 1
        for item in self.cards.values():
            n = counts.get(item.card.id, 0)
            if item.search_hits != n:
                item.search_hits = n
                item.update()

    def _park_in_collapsed(self, group: CardItem, item: CardItem) -> None:
        """A card dropped on a collapsed group's title bar goes under its other cards
        (where it'll be when the group unfolds), not on the title bar."""
        others = [m for m in self.members_of(group) if m is not item]
        if others:
            box = others[0].card_scene_rect()
            for m in others[1:]:
                box = box.united(m.card_scene_rect())
            item.setPos(box.left(), box.bottom() + ARRANGE_GAP)
        else:
            item.setPos(group.pos().x() + GROUP_PAD, group.pos().y() + group.header_area_height() + GROUP_PAD)

    def set_parent(self, item: CardItem, group_id: str) -> None:
        """Put a card in a group ("" for none). Every membership change goes through
        here, so the children index (members_of) stays right."""
        old = item.card.parent
        if old == group_id:
            return
        self._unindex_parent(item.card.id, old)
        item.card.parent = group_id
        if group_id:
            self._children.setdefault(group_id, set()).add(item.card.id)
        self._graph = None
        self._refresh_visibility(item)

    def card_data_replaced(self, item: CardItem, old_parent: str) -> None:
        """A card's data object was swapped (an edit): keep the index if its group changed."""
        new = item.card.parent
        if new != old_parent and self.cards.get(item.card.id) is item:
            self._unindex_parent(item.card.id, old_parent)
            if new:
                self._children.setdefault(new, set()).add(item.card.id)

    def _unindex_parent(self, card_id: str, parent: str) -> None:
        kids = self._children.get(parent)
        if kids is not None:
            kids.discard(card_id)
            if not kids:
                del self._children[parent]

    def check_children_index(self) -> bool:
        """True if the index matches a full scan (for tests)."""
        scan: dict[str, set[str]] = {}
        for item in self.cards.values():
            if item.card.parent:
                scan.setdefault(item.card.parent, set()).add(item.card.id)
        return scan == self._children

    def parent_of(self, item: CardItem) -> CardItem | None:
        return self.cards.get(item.card.parent) if item.card.parent else None

    def ancestors(self, item: CardItem) -> Iterator[CardItem]:
        seen = {item.card.id}
        parent = self.parent_of(item)
        while parent is not None and parent.card.id not in seen:
            seen.add(parent.card.id)
            yield parent
            parent = self.parent_of(parent)

    def descendants(self, group: CardItem) -> set[CardItem]:
        out: set[CardItem] = set()
        stack = [group]
        while stack:
            for m in self.members_of(stack.pop()):
                if m not in out:
                    out.add(m)
                    stack.append(m)
        return out

    def group_at(self, point: QPointF, exclude: set[CardItem]) -> CardItem | None:
        """Innermost group whose frame contains point (items() is z-sorted, and
        deeper groups have higher z)."""
        for item in self.items(point):
            if isinstance(item, CardItem) and item.is_group and item not in exclude \
                    and item.card_scene_rect().contains(point):
                return item
        return None

    def _update_z(self) -> None:
        for item in self.cards.values():
            if item.is_group:
                depth = sum(1 for _ in self.ancestors(item))
                item.setZValue(GROUP_Z + 0.1 * min(depth, 30))
            else:
                item.setZValue(0)

    def _refit_ids(self, ids: set[str]) -> None:
        # Deepest first so each refit sees up-to-date child frames (refit also cascades up).
        items = [self.cards[i] for i in ids if i in self.cards and self.cards[i].is_group]
        items.sort(key=lambda g: -sum(1 for _ in self.ancestors(g)))
        for g in items:
            g.refit()

    # ----- drag into / out of groups ---------------------------------------
    def _dragged_roots(self, item: CardItem) -> list[CardItem]:
        """What a drag of `item` moves: the selection if it's part of it, else just it
        (minus anything inside a moving group, which is carried along)."""
        moved = [i for i in self.selectedItems() if isinstance(i, CardItem)] if item.isSelected() else [item]
        return self._move_roots(moved)

    def _group_for_drop(self, item: CardItem, pointer: QPointF) -> CardItem | None:
        """The group under the pointer that a dragged selection would go into (never
        one of the moving groups, nor anything inside them)."""
        exclude: set[CardItem] = set()
        for m in self._dragged_roots(item):
            exclude |= {m} | self.descendants(m)
        return self.group_at(pointer, exclude)

    def update_drop_hint(self, item: CardItem, pointer: QPointF | None = None) -> None:
        """While dragging: outline the group what's being dragged would go into."""
        if pointer is not None:
            target = self._group_for_drop(item, pointer)
            if target is not None and all(m.card.parent == target.card.id for m in self._dragged_roots(item)):
                target = None  # all staying put; nothing to announce
        else:
            target = self.group_at(item.card_scene_rect().center(), {item} | self.descendants(item))
            if target is not None and target.card.id == item.card.parent:
                target = None
        if target is not self._group_hint:
            if self._group_hint is not None:
                self._group_hint.set_drop_highlight(False)
            if target is not None:
                target.set_drop_highlight(True)
            self._group_hint = target

    def clear_drop_hint(self) -> None:
        if self._group_hint is not None:
            self._group_hint.set_drop_highlight(False)
        self._group_hint = None

    @staticmethod
    def snapped(value: float) -> float:
        """The nearest grid line."""
        return round(value / GRID) * GRID

    @staticmethod
    def _next_line(value: float, direction: float) -> float:
        """The next grid line beyond `value` in `direction` (+ / − / 0 for none)."""
        if direction > 0:
            return (math.floor(value / GRID + 1e-9) + 1) * GRID
        if direction < 0:
            return (math.ceil(value / GRID - 1e-9) - 1) * GRID
        return value

    def _snap_items(self, items) -> None:
        """Put each card's (or group frame's) top-left corner on the grid. A group's
        cards come along, so they keep their places inside it."""
        for item in items:
            p = item.pos()
            target = QPointF(self.snapped(p.x()), self.snapped(p.y()))
            if target != p:
                item.setPos(target)

    def _move_roots(self, items) -> list[CardItem]:
        """The items not inside another of the items (which carries them along)."""
        chosen = set(items)
        return [m for m in items if not any(a in chosen for a in self.ancestors(m))]

    def lift_for_drag(self, item: CardItem) -> None:
        """A drag has started: draw what's moving (and everything in it, and the arrows
        among them) above the rest of the board until it's dropped."""
        if self._lifted:
            return
        lifted: set[CardItem] = set()
        for m in self._dragged_roots(item):
            lifted |= {m} | self.descendants(m)
        edges = [e for e in self.edges if e.source in lifted and e.target in lifted]
        self._lifted = {x: x.zValue() for x in [*lifted, *edges]}
        for x in self._lifted:
            x.setZValue(x.zValue() + DRAG_LIFT)

    def end_lift(self) -> None:
        """The drag is over: everything goes back to its usual depth."""
        lifted, self._lifted = self._lifted, {}
        for x, z in lifted.items():
            if x.scene() is self:
                x.setZValue(z)

    def handle_drop(self, item: CardItem, pointer: QPointF | None = None) -> None:
        """After a drag: everything that moved (the dragged card or group, or the whole
        selection it's part of) goes into the group under the pointer where you let go,
        or out of its group if the pointer isn't over one. Cards inside a moving group
        stay in it. Without `pointer` (not a mouse drag), each goes by its own centre.
        Then affected groups re-fit."""
        self.clear_drop_hint()
        self.end_lift()
        # Cards whose group is moving along with them keep their membership.
        roots = self._dragged_roots(item)
        if self.snap_to_grid:
            self._snap_items(roots)
        shared = self._group_for_drop(item, pointer) if pointer is not None else None
        affected: set[str] = set()
        for m in roots:
            if pointer is not None:
                target = shared
            else:
                target = self.group_at(m.card_scene_rect().center(), {m} | self.descendants(m))
            new_parent = target.card.id if target is not None else ""
            if m.card.parent:
                affected.add(m.card.parent)
            if new_parent != m.card.parent:
                if target is not None and target.card.collapsed:
                    self._park_in_collapsed(target, m)
                self.set_parent(m, new_parent)
                if new_parent:
                    affected.add(new_parent)
        self._update_z()
        self._refit_ids(affected)
        self.mark_modified()

    # ----- cards & connections ----------------------------------------------
    def add_card(self, card: CardData, item: CardItem | None = None) -> CardItem:
        if card.id in self.cards:
            # Never replace an existing entry: the old card would stay on the canvas but
            # vanish from self.cards (a ghost that's never saved). Give this one a new id.
            card.id = new_id()
        if item is None:
            item = CardItem(card)
        self.addItem(item)
        self.cards[card.id] = item
        self._card_rank[card.id] = self._next_rank
        self._next_rank += 1
        if card.parent:
            self._children.setdefault(card.parent, set()).add(card.id)
            if self.visible_end(item) is not item:
                item.setVisible(False)
        self.ensure_room(item.card_scene_rect())
        self._graph = None
        if self._highlight is not None:  # a highlight is showing: new cards start unlit
            item.set_highlight(False)
        if item.laid_out_with != item.layout_options():
            item.refit()  # it was laid out before joining the board: use the board's options
        if item.is_group:
            item.setZValue(GROUP_Z)
        return item

    def create_card_at(self, pos: QPointF, edit: bool = True, group: CardItem | None = None,
                       color: str | None = None) -> CardItem:
        """Add a card centred on pos. With edit=True the editor opens: the card is
        recorded for undo only once the editor is accepted, and cancelling it removes
        the card again (so a cancelled "new card" never lingers)."""
        color = color or CARD_COLORS[len(self.cards) % len(CARD_COLORS)]
        data = CardData(x=pos.x() - CARD_WIDTH / 2, y=pos.y() - 20, color=color)
        if self.snap_to_grid:
            data.x, data.y = self.snapped(data.x), self.snapped(data.y)
        if group is not None and group.scene() is self:
            data.parent = group.card.id
        item = self.add_card(data)
        if group is not None:
            group.refit()
        self.clearSelection()
        item.setSelected(True)
        if edit:
            QTimer.singleShot(0, lambda: self.edit_card(item, is_new=True))
        else:
            self.mark_modified()
        return item

    # ----- drag a handle onto empty canvas: new connected card -----------------
    def _plain_card_at(self, pos: QPointF) -> bool:
        return any(isinstance(i, CardItem) and not i.is_group for i in self.items(pos))

    def can_create_connected_at(self, source: CardItem, pos: QPointF) -> bool:
        """Would dropping a handle drag from `source` at pos create a new card? Yes
        on empty canvas, or empty space inside a group (its own group away from the
        frame edge, where a drop marks a last card instead), after a real drag
        rather than a slip."""
        if source.card.id not in self.cards or self._plain_card_at(pos):
            return False
        return QLineF(source.port_scene_pos(), pos).length() >= NEW_CARD_MIN_DRAG

    def _default_card_size(self) -> tuple[float, float]:
        if self._new_card_size is None:  # a fresh card's size never changes, so measure once
            r = CardItem(CardData()).card_rect()
            self._new_card_size = (r.width(), r.height())
        return self._new_card_size

    def new_card_rect(self, source: CardItem, pos: QPointF) -> QRectF:
        """Where a card created by dropping at pos goes: the side facing the source
        touches the pointer (so the arrow ends where it was dropped), centred on it
        vertically."""
        w, h = self._default_card_size()
        left = pos.x() - w if pos.x() < source.port_scene_pos().x() else pos.x()
        return QRectF(left, pos.y() - h / 2, w, h)

    def create_connected_card(self, source: CardItem, pos: QPointF, edit: bool = True) -> CardItem:
        """New card at pos (in the group under it, if any), in the source's colour,
        with an arrow from the source. One undo step; with edit=True, cancelling the
        editor removes both the card and the arrow."""
        rect = self.new_card_rect(source, pos)
        group = self.group_at(pos, set())
        item = self.create_card_at(rect.center(), edit=edit, group=group, color=source.card.color)
        item.setPos(rect.topLeft())
        if self.snap_to_grid:
            self._snap_items([item])
        if group is not None:
            self._refit_ids({group.card.id})
        self.add_connection(source, item)
        return item

    def _show_ghost(self, rect: QRectF | None, color: str = "") -> None:
        if rect is None:
            if self._ghost is not None:
                self._ghost.hide()
            return
        if self._ghost is None:
            self._ghost = QGraphicsPathItem()
            self._ghost.setZValue(999)  # above cards, just below the dashed line
            self.addItem(self._ghost)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, rect.width(), rect.height()), CORNER, CORNER)
        self._ghost.setPath(path)
        self._ghost.setPos(rect.topLeft())
        pen_color, fill = QColor(color), QColor(color)
        fill.setAlpha(40)
        self._ghost.setPen(QPen(pen_color, 1.5, Qt.PenStyle.DashLine))
        self._ghost.setBrush(fill)
        self._ghost.show()

    def _remove_ghost(self) -> None:
        if self._ghost is not None:
            self.removeItem(self._ghost)
            self._ghost = None

    def can_connect(self, source: CardItem, target: CardItem) -> bool:
        """Any two different cards or groups can be connected. Between a group and a
        card inside it, the arrow marks a first card (group → card) or a last card
        (card → group) of that group, and is drawn from / to the frame's inner border."""
        return source is not target

    def _connect_target(self, source: CardItem, pos: QPointF, click_mode: bool) -> CardItem | None:
        """The card or group a drop / click at pos would connect `source` to, if any.
        Dragging a card's handle onto its own group connects to the group (a last
        card) only on the group's header or frame edge; empty space inside it is
        where a new card would go instead."""
        target = self.card_at(pos)
        if target is None or not self.can_connect(source, target):
            return None
        if not click_mode and target.contains_card(source) and not target.on_frame_edge(pos):
            return None
        return target

    def add_connection(self, source: CardItem, target: CardItem, label: str = "",
                       conn_id: str | None = None, like: ConnectionData | None = None) -> EdgeItem | None:
        """Add an arrow. `like` copies an existing arrow's label, style and color
        (used when loading, pasting and reversing); otherwise it's a plain arrow."""
        if not self.can_connect(source, target):
            return None
        if any(e.source is source and e.target is target for e in source.edges):
            return None  # already connected this way
        base = like if like is not None else ConnectionData(source="", target="", label=label)
        conn = replace(base, source=source.card.id, target=target.card.id, id=conn_id or new_id())
        edge = EdgeItem(source, target, conn, draw=False)  # drawn below, once on the board
        self._graph = None
        if self._highlight is not None:  # a highlight is showing: new arrows start unlit
            edge.set_highlight(False)
        self.addItem(edge)
        self.edges.append(edge)
        if self._loading_edges:
            edge.adjust()  # (now that it's on the board); reverse pairs are offset afterwards
        else:
            for e in source.edges:  # a reverse edge may now need offsetting
                e.adjust()
        if not self._loading_edges and not (source.isVisible() and target.isVisible()):
            self._place_edges()  # an end is folded away: it meets the collapsed group
        return edge

    def remove_edge(self, edge: EdgeItem) -> None:
        if edge not in self.edges:
            return
        edge.detach()
        self.edges.remove(edge)
        self._graph = None
        self.removeItem(edge)
        for e in edge.source.edges:
            e.adjust()
        if edge.merged or not edge.isVisible():
            self._place_edges()  # a ×N count (or a folded arrow) changes

    def remove_edges(self, edges: list[EdgeItem]) -> None:
        """Remove several arrows, rebuilding the arrow list once."""
        dead = set(edges) & set(self.edges)
        if not dead:
            return
        for edge in dead:
            edge.detach()
            self.removeItem(edge)
        self.edges = [e for e in self.edges if e not in dead]
        self._graph = None
        for card in {n for e in dead for n in (e.source, e.target)}:
            for edge in card.edges:
                edge.adjust()
        if any(e.merged or not e.isVisible() for e in dead):
            self._place_edges()

    def remove_card(self, card: CardItem, with_contents: bool = False) -> None:
        """Remove a card. For a group, its cards are released into the group's own
        parent (they stay where they are) unless with_contents is True."""
        self.remove_cards([card], with_contents)

    def remove_cards(self, items: list[CardItem], with_contents: bool = False) -> None:
        """Remove several cards in one pass. Cards inside a removed group move up to
        the nearest surviving group (or none), unless with_contents removes them too.
        The board-wide work (arrow list, z-order, refits) happens once, not per card."""
        doomed: set[CardItem] = set()
        for card in items:
            if card.card.id in self.cards:
                doomed.add(card)
                if with_contents and card.is_group:
                    doomed |= self.descendants(card)
        if not doomed:
            return
        self._graph = None

        def surviving_parent(item: CardItem) -> str:
            p = self.parent_of(item)
            while p is not None and p in doomed:
                p = self.parent_of(p)
            return p.card.id if p is not None else ""

        affected: set[str] = set()
        for item in self.cards.values():  # one pass: release members of removed groups
            if item in doomed:
                affected.add(surviving_parent(item))
            elif item.card.parent and self.cards.get(item.card.parent) in doomed:
                self.set_parent(item, surviving_parent(item))
                affected.add(item.card.parent)

        dead_edges = {e for c in doomed for e in c.edges}
        survivors = {n for e in dead_edges for n in (e.source, e.target) if n not in doomed}
        for edge in dead_edges:
            edge.detach()
            self.removeItem(edge)
        if dead_edges:
            self.edges = [e for e in self.edges if e not in dead_edges]
        for card in survivors:  # a remaining reverse arrow may no longer need its offset
            for edge in card.edges:
                edge.adjust()
        if self._group_hint in doomed:
            self._group_hint = None
        for card in doomed:
            if card.details_visible:  # so undoing the delete brings it back expanded
                self._removed_details.add(card.card.id)
            self.cards.pop(card.card.id, None)
            self._card_rank.pop(card.card.id, None)
            self._unindex_parent(card.card.id, card.card.parent)
            self._children.pop(card.card.id, None)  # its members were moved or removed
            self.removeItem(card)
        self._update_z()
        self._refit_ids(affected - {""})
        if any(e.merged or not e.isVisible() for e in dead_edges):
            self._place_edges()

    def release_members(self, group: CardItem) -> None:
        """Ungroup: members move up to the group's parent and stay in place."""
        for m in self.members_of(group):
            self.set_parent(m, group.card.parent)
        self._update_z()
        group.refit()
        self._refit_ids({group.card.parent})

    def remove_from_group(self, item: CardItem) -> None:
        group = self.parent_of(item)
        if group is None:
            return
        self.set_parent(item, group.card.parent)
        # Step it just outside the frame so it doesn't look like it's still inside.
        frame = group.card_scene_rect()
        item.setPos(frame.right() + ARRANGE_GAP, item.pos().y())
        self._update_z()
        self._refit_ids({group.card.id, group.card.parent})

    def set_group_members(self, group: CardItem, member_ids: list[str]) -> None:
        """Make exactly member_ids the group's direct members. New members are
        arranged in a grid inside the frame; removed ones are placed beside it."""
        wanted = set(member_ids)
        blocked = {group} | set(self.ancestors(group))
        affected = {group.card.id, group.card.parent}

        frame = group.card_scene_rect()
        out_y = frame.top()
        for m in self.members_of(group):
            if m.card.id not in wanted:
                self.set_parent(m, group.card.parent)
                m.setPos(frame.right() + ARRANGE_GAP * 2, out_y)
                out_y += m.card_scene_rect().height() + ARRANGE_GAP

        to_add = [self.cards[i] for i in member_ids
                  if i in self.cards and self.cards[i] not in blocked
                  and self.cards[i].card.parent != group.card.id]
        if to_add:
            existing = self.members_of(group)
            if existing:
                bbox = existing[0].card_scene_rect()
                for m in existing[1:]:
                    bbox = bbox.united(m.card_scene_rect())
                x0, y = bbox.left(), bbox.bottom() + ARRANGE_GAP
            else:
                x0 = group.pos().x() + GROUP_PAD
                y = group.pos().y() + group.header_area_height() + GROUP_PAD
            x, row_h, col = x0, 0.0, 0
            for m in to_add:
                if m.card.parent:
                    affected.add(m.card.parent)
                self.set_parent(m, group.card.id)
                m.setPos(x, y)  # a nested group drags its own members along
                r = m.card_scene_rect()
                row_h = max(row_h, r.height())
                col += 1
                if col >= ARRANGE_COLUMNS:
                    x, y, row_h, col = x0, y + row_h + ARRANGE_GAP, 0.0, 0
                else:
                    x += r.width() + ARRANGE_GAP
        self._update_z()
        self._refit_ids(affected)

    def auto_arrange_group(self, group: CardItem, by_color: bool | None = None,
                           vertical: bool | None = None, grid: bool | None = None) -> None:
        """Lay out a group's cards by their arrows (chains left-to-right, separate
        chains stacked, unconnected cards in a row or grid; optionally one row per
        card color, optionally rotated to run top-to-bottom, optionally wrapping into
        a new row after the group's row limit), then fit the frame."""
        if by_color is None:
            by_color = group.card.arrange_by_color
        if vertical is None:
            vertical = group.card.arrange_vertical
        if grid is None:
            grid = group.card.arrange_grid
        members = self.members_of(group)
        if not members:
            return
        # Frames before arranging, for pushing aside what the grown frames now cover.
        before = {g.card.id: g.card_scene_rect() for g in (group, *self.ancestors(group))}
        member_ids = {m.card.id for m in members}
        # Arrows to cards inside a nested group count as arrows to that nested group.
        rep: dict[str, str] = {}
        for item in self.cards.values():
            if item.card.id in member_ids:
                rep[item.card.id] = item.card.id
            else:
                for a in self.ancestors(item):
                    if a.card.id in member_ids:
                        rep[item.card.id] = a.card.id
                        break
        edges, labels = [], {}
        for e in self.edges:
            if e.source.card.id in rep and e.target.card.id in rep:
                pair = (rep[e.source.card.id], rep[e.target.card.id])
                edges.append(pair)
                w, h = e.label_size()  # room for the widest label between the two
                if w:
                    old = labels.get(pair, (0.0, 0.0))
                    labels[pair] = (max(old[0], w), max(old[1], h))
        nodes = []
        for m in members:
            r = m.card_scene_rect()
            nodes.append(Node(m.card.id, r.width(), r.height(), r.x(), r.y(), m.card.color.lower(),
                              group=m.is_group))
        positions = arrange(nodes, edges, by_color=by_color, vertical=vertical, grid=grid,
                            labels=labels, wrap=group.card.arrange_wrap)

        group.card.width = group.card.height = 0.0  # back to snug auto-fit
        ox = group.pos().x() + GROUP_PAD
        oy = group.pos().y() + group.header_area_height() + GROUP_PAD
        for m in members:
            x, y = positions[m.card.id]
            m.setPos(ox + x, oy + y)  # nested groups bring their own cards along
        self._refit_ids({group.card.id})
        # Arranging keeps the frame's top-left, so a group can only grow right or down.
        self._make_room(group, before)

    def reverse_edge(self, edge: EdgeItem) -> None:
        source, target, conn = edge.source, edge.target, edge.conn
        self.remove_edge(edge)
        # The arrow keeps its id, label, style and color, just pointing the other way.
        if self.add_connection(target, source, conn_id=conn.id, like=conn) is None:
            self.add_connection(source, target, conn_id=conn.id, like=conn)  # reverse already existed; restore
            self.notice.emit(f"“{target.card.title or 'Untitled'}” already has an arrow to "
                             f"“{source.card.title or 'Untitled'}”: nothing to reverse")
        else:
            self.mark_modified()

    def confirm_delete(self, cards: list[CardItem], edges: list[EdgeItem] = ()) -> bool:
        """Ask before deleting more than one thing at once; a single item goes straight away."""
        if len(cards) + len(edges) <= 1:
            return True
        groups = sum(1 for c in cards if c.is_group)
        parts = [(len(cards) - groups, "card"), (groups, "group"), (len(edges), "connection")]
        summary = ", ".join(f"{n} {noun}{'s' if n != 1 else ''}" for n, noun in parts if n)
        total = len(cards) + len(edges)
        answer = QMessageBox.question(
            self._dialog_parent(), "Delete items",
            f"Delete {total} items ({summary})?\n\nArrows attached to deleted cards are removed "
            "too. You can undo this with Ctrl+Z.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def delete_group_with_contents(self, group: CardItem) -> None:
        doomed = [group, *self.descendants(group)]
        if self.confirm_delete(doomed):
            self.remove_card(group, with_contents=True)
            self.mark_modified()

    # ----- copy / paste / duplicate -------------------------------------------
    def selection_fragment(self) -> BoardData | None:
        """The selected cards as a self-contained board fragment: a selected group
        brings everything inside it, arrows come along when both ends do, and custom
        colours the cards use come along so they paste correctly into other boards."""
        picked = {i for i in self.selectedItems() if isinstance(i, CardItem)}
        if not picked:
            return None
        for item in list(picked):
            if item.is_group:
                picked |= self.descendants(item)
        ids = {i.card.id for i in picked}
        board = self.to_board_data()
        cards = [c for c in board.cards if c.id in ids]
        used = {c.color.lower() for c in cards}
        return BoardData(
            cards=cards,
            connections=[e for e in board.connections if e.source in ids and e.target in ids],
            custom_colors=[c for c in self.custom_colors if c.lower() in used])

    def paste_fragment(self, fragment: BoardData, at: QPointF | None = None) -> list[CardItem]:
        """Add a copy of `fragment` (fresh ids) and select it.

        With `at` (the mouse position), the copy's top-left goes there, and it joins
        the group under that point, as dropping a card there would. Without it, the
        copy sits 30 px from the originals and cards stay in their original group."""
        if not fragment.cards:
            return []
        if at is None:
            board = self._clone_offset(fragment, set(self.cards), PASTE_OFFSET, PASTE_OFFSET)
            target = None
        else:
            left = min(c.x for c in fragment.cards)
            top = min(c.y for c in fragment.cards)
            board = self._clone_offset(fragment, set(), at.x() - left, at.y() - top)
            target = self.group_at(at, set())
        items = [self.add_card(c) for c in board.cards]
        by_id = {i.card.id: i for i in items}
        if target is not None:
            for item in items:
                if not item.card.parent:
                    self.set_parent(item, target.card.id)
        for e in board.connections:
            self.add_connection(by_id[e.source], by_id[e.target], like=e)
        for colour in board.custom_colors:
            if colour not in self.custom_colors:
                self.custom_colors.append(colour)
        self._update_z()
        self._refit_ids({i.card.id for i in items if i.is_group}
                        | {i.card.parent for i in items if i.card.parent})
        self.clearSelection()
        for item in items:
            if item.card.parent not in by_id:  # select the top level of the copy
                item.setSelected(True)
        self.mark_modified()
        return items

    @staticmethod
    def _clone_offset(fragment: BoardData, keep_parents: set[str], dx: float, dy: float) -> BoardData:
        board = clone_fragment(fragment, keep_parents)
        for c in board.cards:
            c.x += dx
            c.y += dy
        return board

    def duplicate_selected(self) -> list[CardItem]:
        fragment = self.selection_fragment()
        return self.paste_fragment(fragment) if fragment else []

    def cut_selected(self) -> BoardData | None:
        """Remove the selected cards (one undo step) and return them as a fragment."""
        fragment = self.selection_fragment()
        if fragment is not None:
            self.remove_cards([i for i in self.selectedItems() if isinstance(i, CardItem)],
                              with_contents=True)
            self.mark_modified()
        return fragment

    def delete_selected(self) -> None:
        selected = self.selectedItems()
        if not selected:
            return
        if not self.confirm_delete([i for i in selected if isinstance(i, CardItem)],
                                   [i for i in selected if isinstance(i, EdgeItem)]):
            return
        self.remove_edges([i for i in selected if isinstance(i, EdgeItem)])
        self.remove_cards([i for i in selected if isinstance(i, CardItem)])
        self.mark_modified()

    def set_display_option(self, key: str, value) -> bool:
        """Change one of this board's display options (saved with the board, and
        undoable). Card-face options re-lay-out the cards they affect, then every
        group refits. Returns False if nothing changed."""
        if not self._apply_display_option(key, value):
            return False
        self.mark_modified()
        return True

    def set_outside_story(self, item: CardItem, on: bool) -> None:
        """Leave a card (or a group and everything in it) out of the story tools, or
        put it back; one undo step."""
        if item.card.outside_story == on:
            return
        item.card.outside_story = on
        self._graph = None
        item.update()  # dashed outline while it's left out
        self.mark_modified()

    def set_display_options(self, values: dict) -> int:
        """Change several display options as one undo step (Board Options dialog).
        Returns how many changed."""
        changed = sum(self._apply_display_option(k, v) for k, v in values.items())
        if changed:
            self.mark_modified()
        return changed

    def _apply_display_option(self, key: str, value) -> bool:
        if key not in DISPLAY_DEFAULTS or self.display.get(key) == value:
            return False
        self.display[key] = value
        if key in _LAYOUT_OPTIONS:
            for item in self.cards.values():
                if not item.is_group:
                    item.refit()
            groups = [g for g in self.cards.values() if g.is_group]
            groups.sort(key=lambda g: -sum(1 for _ in self.ancestors(g)))
            for g in groups:
                g.refit()
            for edge in self.edges:  # cards may have changed size
                edge.adjust()
        if key in _LOOK_OPTIONS:
            for item in self.cards.values():
                item.update()  # their cached pictures are out of date
        if key == "story_tools":
            self.update_introductions()  # none while story tools are off
            if not value and self.highlight_owner() in ("thread", "reader", "routes", "checks"):
                self.clear_highlight()
        if key in ("arrow_routing", "show_arrow_labels"):
            self.reroute_arrows()
        if key == "show_grid":
            self.update()
        return True

    # ----- arrow routing & styles -----------------------------------------------
    def begin_move(self) -> None:
        """Cards are about to be dragged or nudged: route arrows simply meanwhile."""
        self._moving = True

    def end_move(self, moved: bool = True) -> None:
        """The move is over: route "avoiding cards" arrows properly again, shortly
        (unless nothing actually moved, e.g. a click to select)."""
        if self._moving:
            self._moving = False
            wanted, self._reroute_wanted = self._reroute_wanted, False
            if moved or wanted:
                self._schedule_reroute()

    def is_moving(self) -> bool:
        return self._moving

    @contextmanager
    def moving_selection(self):
        """Every selected card is being moved by the same step (Qt's drag, a nudge)."""
        self._selection_moves += 1
        try:
            yield
        finally:
            self._selection_moves -= 1

    def selection_moving(self) -> bool:
        return self._selection_moves > 0

    def _end_nudge(self) -> None:
        """A burst of arrow-key nudges has settled: one undo step, then re-route."""
        self.end_move()
        self.mark_modified()

    def _schedule_reroute(self) -> None:
        if self.display.get("arrow_routing") == "avoid" and self.edges:
            if self._moving:
                # Arrows are drawn plainly until the move ends, and end_move routes them
                # then: a pass now (e.g. mid-way through a burst of nudges) is wasted.
                self._reroute_wanted = True
            else:
                self._reroute_timer.start()

    def _reroute_if_needed(self) -> None:
        """The board settled with "avoid cards" on: route every arrow again, unless
        nothing that routes depend on has changed since they were last all routed
        (an edit to a card's text, tags or colour that leaves its size alone)."""
        if self._routes_dirty or self._routing_shape() != self._routed_shape:
            self.reroute_arrows()

    def _routing_shape(self) -> tuple:
        """Everything arrow routes depend on: where each card is drawn and how big,
        whether it shows, what it's in, the arrows themselves and the board's options."""
        cards = tuple((cid, item.isVisible(), item.card.parent, item.card.arrange_vertical,
                       item.anchor_scene_rect().getRect())
                      for cid, item in self.cards.items())
        edges = tuple((e.conn.id, e.source.card.id, e.target.card.id, e.conn.label) for e in self.edges)
        return cards, edges, tuple(sorted(self.display.items()))

    def _note_routed(self) -> None:
        """Every arrow has just been routed against the board as it is."""
        self._routed_shape = self._routing_shape()
        self._routes_dirty = False

    def card_resized(self, item: CardItem) -> None:
        """A card's drawn size changed: arrows may need to go round it differently."""
        self._routes_dirty = True

    def reroute_arrows(self) -> None:
        """Recompute every arrow's path (after a routing change, or once the board
        settles with "avoid cards" on, since a moved card may now be in the way)."""
        self._reroute_timer.stop()
        for edge in self.edges:
            edge.adjust()
        if not self._moving:  # (while moving, arrows were drawn plainly)
            self._note_routed()

    def set_arrow_style(self, edges, style: str | None = None, color: str | None = None,
                        label: str | None = None) -> int:
        """Set the style / color / label of some arrows (None = leave as is), as one
        undo step. Returns how many arrows changed."""
        changed = 0
        for edge in edges:
            conn = edge.conn
            before = (conn.style, conn.color, conn.label)
            if style in ARROW_STYLES:
                conn.style = style
            if color is not None:
                conn.color = color
            if label is not None and label != conn.label:
                edge.set_label(label)  # re-lays the label box
            if (conn.style, conn.color, conn.label) != before:
                edge.update()
                changed += 1
        if changed:
            self.mark_modified()
        return changed

    def edit_arrows(self, edges) -> int:
        """Open the arrow editor for one or several arrows."""
        edges = [e for e in edges if e.scene() is self]
        if not edges:
            return 0
        dialog = ArrowDialog([e.conn for e in edges], self.custom_colors, self._dialog_parent())
        if not dialog.exec():
            return 0
        for c in dialog.added_custom_colors:
            if c not in self.custom_colors:
                self.custom_colors.append(c)
        changed = self.set_arrow_style(edges, dialog.style(), dialog.color(), dialog.label())
        if dialog.added_custom_colors and not changed:
            self.mark_modified()  # the palette itself changed
        return changed

    def set_all_details(self, visible: bool) -> None:
        """Show / Hide All Details. Cards first (top to bottom, so each pushes what's
        below it before that opens in turn), then groups deepest-first, so frames fit
        the final card sizes. Hiding goes in the reverse order, giving the room back."""
        cards = sorted((c for c in self.cards.values() if not c.is_group),
                       key=lambda c: (c.pos().y(), c.pos().x()))
        groups = [g for g in self.cards.values() if g.is_group]
        groups.sort(key=lambda g: -sum(1 for _ in self.ancestors(g)))
        order = cards + groups
        for item in (order if visible else reversed(order)):
            self.show_details(item, visible)

    def apply_filter(self, predicate) -> FilterCounts:
        """Dim cards and groups for which predicate(card_data) is False (None = show
        all). Each group frame is judged on its own values. Arrows touching a dimmed
        card are dimmed too. Returns how many cards and groups are shown."""
        counts = [0, 0, 0, 0]  # cards shown, cards, groups shown, groups
        for item in self.cards.values():
            ok = predicate is None or predicate(item.card)
            item.set_dimmed(not ok)
            base = 2 if item.is_group else 0
            counts[base] += ok
            counts[base + 1] += 1
        for edge in self.edges:
            edge.refresh_opacity()
        return FilterCounts(*counts)

    # ----- story graph & highlight -------------------------------------------
    def _forget_graph(self) -> None:
        self._graph = None

    def story_graph(self) -> StoryGraph:
        """What comes before/after what, built from the current board (cached until
        the next change)."""
        if self._graph is None:
            self._graph = StoryGraph(self._graph_cards(), [e.conn for e in self.edges])
        return self._graph

    def _graph_cards(self) -> list[CardData]:
        """The cards with current positions, as to_board_data gives them, but as plain
        shallow copies: the graph only reads them, and skipping the dataclass's
        clean-up of every field keeps rebuilding it (on every edit) cheap."""
        offsets = self._details_offsets()  # room made for open details isn't counted
        out = []
        for item in self.cards.values():
            card = copy.copy(item.card)
            if not item.is_group:
                card.x, card.y = item.pos().x(), item.pos().y()
            dx, dy = offsets.get(card.id, (0.0, 0.0))
            card.x, card.y = card.x - dx, card.y - dy
            out.append(card)
        return out

    def has_highlight(self) -> bool:
        return self._highlight is not None

    @property
    def highlight(self) -> Highlight | None:
        """The highlight showing, if any (read-only: use set/clear_highlight)."""
        return self._highlight

    def highlight_label(self) -> str:
        return self._highlight.label if self._highlight is not None else ""

    def highlight_owner(self) -> str:
        return self._highlight.owner if self._highlight is not None else ""

    def highlight_paths(self, item: CardItem, mode: str = "both") -> str:
        """Light up everything that can come before and/or after a card (mode
        "both", "before" or "after"); for a group, before/after its contents.
        Returns the banner text."""
        graph = self.story_graph()
        cid = item.card.id
        before = graph.upstream(cid) if mode in ("both", "before") else set()
        after = graph.downstream(cid) if mode in ("both", "after") else set()
        inside = graph.contents(cid)
        ids = {cid} | inside | before | after
        edges = graph.arrows_within(ids) | graph.markers_for(ids)
        title = self.title_labels().get(cid) or item.card.title or "Untitled"
        n_before, n_after = len(before - {cid} - inside), len(after - {cid} - inside)
        parts = {"both": f"{n_before} before, {n_after} after",
                 "before": f"{n_before} before", "after": f"{n_after} after"}[mode]
        what = {"both": "Paths through", "before": "What leads to", "after": "What follows"}[mode]
        label = f"{what} “{title}” · {parts}"
        self.set_highlight(ids, edges, cid, label, owner="paths")
        self._paths_mode = mode
        return label

    # ----- characters: introductions & threads ----------------------------------
    def ensure_room(self, rect: QRectF) -> None:
        """Grow the board area (never shrink) so `rect` and its margin fit: called
        as cards are added or moved, so even a card dragged far out stays reachable
        while it's moving. Cheap: one containment check when there's room already."""
        need = rect.adjusted(-SCENE_MARGIN / 2, -SCENE_MARGIN / 2, SCENE_MARGIN / 2, SCENE_MARGIN / 2)
        current = self.sceneRect()
        if not current.contains(need):
            self.setSceneRect(current.united(
                rect.adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN)))

    def update_scene_rect(self) -> None:
        """Fit the scrollable board area to the cards and arrows (plus a margin),
        never smaller than BASE_SCENE_RECT. Measured from the cards and arrows
        themselves, not from temporary items such as a drag's dashed line."""
        bounds = QRectF()
        for item in self.cards.values():
            r = item.card_scene_rect()
            bounds = r if bounds.isNull() else bounds.united(r)
        for edge in self.edges:
            r = edge.sceneBoundingRect()
            if not r.isEmpty():
                bounds = r if bounds.isNull() else bounds.united(r)
        rect = QRectF(BASE_SCENE_RECT)
        if not bounds.isNull():
            rect = rect.united(bounds.adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN))
        if rect != self.sceneRect():
            self.setSceneRect(rect)

    def update_introductions(self) -> None:
        """Work out which characters each card introduces (no card on any route
        leading to it features them) and show it on the cards. A character thread
        being shown is renumbered too, since the order may have changed."""
        self.introductions = (self.story_graph().introductions()
                              if self.display.get("story_tools", True) else {})
        for cid, item in self.cards.items():
            item.set_introduces(self.introductions.get(cid, []))
        if self.highlight_owner() == "thread":
            self.show_thread(self._thread_name)

    def show_thread(self, name: str) -> str:
        """Light up the cards featuring a character, numbered in story order and
        joined by a dashed line. Returns the banner text ("" if no card features them)."""
        graph = self.story_graph()
        ids = graph.featuring(name)
        if not ids:
            if self.highlight_owner() == "thread":
                self.clear_highlight()
            return ""
        key = name.strip().casefold()
        display = next(c for c in self.cards[ids[0]].card.characters if c.casefold() == key)
        arrows: set[str] = set()
        for a, b in zip(ids, ids[1:]):
            arrows.update(graph.step_arrows(a, b))
        introduced = [i for i in ids
                      if any(n.casefold() == key for n in self.introductions.get(i, []))]
        noun = "card" if len(ids) == 1 else "cards"
        label = f"Thread: {display} · {len(ids)} {noun}"
        if introduced:
            first = self.title_labels().get(introduced[0]) or "Untitled"
            more = f" (+{len(introduced) - 1} more)" if len(introduced) > 1 else ""
            label += f" · introduced in “{first}”{more}"
        self._clear_thread_extras()
        # The character's own strand cards light up too (they aren't steps of the thread).
        extra = {i.card.id for i in self.strand_cards("characters", display)}
        self.set_highlight(set(ids) | extra, arrows, None, label, owner="thread")
        self._thread_name = display
        for n, cid in enumerate(ids, 1):
            self.cards[cid].set_badge(str(n))
        if len(ids) > 1:  # a dashed line from card to card, in thread order
            self._thread_ids = list(ids)
            line = QGraphicsPathItem(self._thread_path())
            pen = QPen(theme.current().highlight, 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            line.setPen(pen)
            line.setZValue(-0.5)  # above arrows, beneath cards
            line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.addItem(line)
            self._thread_line = line
        return label

    def title_labels(self) -> dict[str, str]:
        """Every card's title as lists show it (model.title_labels)."""
        return title_labels(item.card for item in self.cards.values())

    def title_context(self, card_id: str) -> str:
        """The group to name beside a repeated title ("" if the title is unique)."""
        item = self.cards.get(card_id)
        if item is None:
            return ""
        label = self.title_labels().get(card_id, "")
        bare = item.card.title.strip() or "Untitled"
        return label[len(bare) + 3:] if label != bare else ""

    def _thread_path(self) -> QPainterPath:
        centres = [self.cards[c].card_scene_rect().center() for c in self._thread_ids
                   if c in self.cards]
        path = QPainterPath(centres[0]) if centres else QPainterPath()
        for p in centres[1:]:
            path.lineTo(p)
        return path

    def card_moved(self, item: CardItem) -> None:
        """A card moved (drag, nudge, arrange): the thread line through it follows,
        redrawn once per burst of moves rather than once per card."""
        self._routes_dirty = True  # an arrow may now need to go round it, or no longer
        if self._thread_line is not None and not self._thread_line_due \
                and item.card.id in self._thread_ids:
            self._thread_line_due = True
            QTimer.singleShot(0, self._redraw_thread_line)

    def _redraw_thread_line(self) -> None:
        self._thread_line_due = False
        if self._thread_line is not None:
            self._thread_line.setPath(self._thread_path())

    def _clear_thread_extras(self) -> None:
        if self._thread_line is not None:
            self.removeItem(self._thread_line)
            self._thread_line = None
        self._thread_ids = []
        for item in self.cards.values():
            item.set_badge("")

    def set_highlight(self, card_ids, edge_ids=(), focus_id: str | None = None,
                      label: str = "", owner: str = "") -> None:
        """Light up some cards and arrows and fade the rest (on top of any filter).
        Groups holding a lit card are lit too, so their frames don't fade. View
        state only: not saved, not undoable; Esc or clear_highlight() ends it."""
        if owner != "thread":
            self._clear_thread_extras()
        ids = {i for i in card_ids if i in self.cards}
        edge_ids = set(edge_ids)
        lit = ids | self.story_graph().containers_of(ids)
        for cid, item in self.cards.items():
            item.set_highlight(cid in lit, focus=cid == focus_id)
        for edge in self.edges:
            edge.set_highlight(edge.conn.id in edge_ids)
        self._highlight = Highlight(ids, edge_ids, focus_id, label, owner)
        self.highlight_changed.emit(label or "Highlight")

    @contextmanager
    def export_view(self, keep_highlight: bool):
        """For an image export: no hover effects, no half-drawn connection or new-card
        preview, and (unless keep_highlight) no highlight; all put back afterwards."""
        hover = [(i, i.hover_state) for i in [*self.cards.values(), *self.edges]]
        for item, _ in hover:
            item.hover_state = False if isinstance(item, EdgeItem) else None
        extras = [x for x in (self._ghost, self._temp_line) if x is not None and x.isVisible()]
        for x in extras:
            x.setVisible(False)
        highlight, thread = self._highlight, self._thread_name
        if highlight is not None and not keep_highlight:
            self.clear_highlight()
        try:
            yield
        finally:
            if highlight is not None and not keep_highlight:
                if highlight.owner == "thread":
                    self.show_thread(thread)
                else:
                    self.set_highlight(*highlight)
            for x in extras:
                if x.scene() is self:
                    x.setVisible(True)
            for item, state in hover:
                if item.scene() is self:
                    item.hover_state = state

    def clear_highlight(self) -> None:
        if self._highlight is None:
            return
        self._clear_thread_extras()
        self._highlight = None
        for item in self.cards.values():
            item.set_highlight(None)
        for edge in self.edges:
            edge.set_highlight(None)
        self.highlight_changed.emit("")

    def card_at(self, pos: QPointF) -> CardItem | None:
        for item in self.items(pos):
            if isinstance(item, CardItem):
                return item
        return None

    # ----- drag-to-connect --------------------------------------------------
    def begin_connection(self, source: CardItem, scene_pos: QPointF) -> None:
        self._connect_source = source
        self._temp_line = QGraphicsLineItem(QLineF(source.port_scene_pos(), scene_pos))
        pen = QPen(QColor(source.card.color).darker(110), 2, Qt.PenStyle.DashLine)
        self._temp_line.setPen(pen)
        self._temp_line.setZValue(1000)
        self.addItem(self._temp_line)

    def update_connection(self, scene_pos: QPointF) -> None:
        if self._temp_line is None or self._connect_source is None:
            return
        self._temp_line.setLine(QLineF(self._connect_source.port_scene_pos(), scene_pos))
        target = self._connect_target(self._connect_source, scene_pos, self._click_connecting)
        if target is not self._drop_target:
            if self._drop_target is not None:
                self._drop_target.set_drop_highlight(False)
            if target is not None:
                target.set_drop_highlight(True)
            self._drop_target = target
        # Dragging a handle (not click-to-connect) over empty canvas: preview the card
        # a drop would create.
        source = self._connect_source
        if (target is None and not self._click_connecting
                and self.can_create_connected_at(source, scene_pos)):
            self._show_ghost(self.new_card_rect(source, scene_pos), source.card.color)
        else:
            self._show_ghost(None)

    # Click-to-connect (right-click → Connect to…): the dashed line follows the
    # mouse until the next click, which picks the target; Esc or right-click cancels.
    def start_click_connection(self, source: CardItem) -> None:
        if source.scene() is not self:
            return
        self.cancel_connection()
        self.begin_connection(source, source.port_scene_pos())
        self._click_connecting = True
        for view in self.views():
            view.viewport().setMouseTracking(True)
            view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.connect_mode_changed.emit(True)

    def is_click_connecting(self) -> bool:
        return self._click_connecting

    def cancel_connection(self) -> None:
        if self._connect_source is not None:
            self.finish_connection(None)

    def _end_click_mode(self) -> None:
        if self._click_connecting:
            self._click_connecting = False
            for view in self.views():
                view.viewport().unsetCursor()
            self.connect_mode_changed.emit(False)

    def mouseMoveEvent(self, event) -> None:
        if self._click_connecting:
            self.update_connection(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._click_connecting:
            if event.button() == Qt.MouseButton.LeftButton:
                self.finish_connection(event.scenePos())
            else:
                self.cancel_connection()
                self._suppress_menu = event.button() == Qt.MouseButton.RightButton
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if self._connect_source is not None and key == Qt.Key.Key_Escape:
            self.cancel_connection()
            event.accept()
            return
        if self._highlight is not None and key == Qt.Key.Key_Escape:
            self.clear_highlight()
            event.accept()
            return
        if key in NUDGE_KEYS and self.selectedItems():
            fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            snap = self.snap_to_grid and not fine
            step = NUDGE_FINE if fine else (GRID if snap else NUDGE_STEP)
            dx, dy = NUDGE_KEYS[key]
            if self.nudge_selected(dx * step, dy * step, snap=snap):
                event.accept()  # accepted: the view won't also scroll
                return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.edit_selection():
            event.accept()
            return
        super().keyPressEvent(event)

    # ----- keyboard editing -------------------------------------------------
    def nudge_selected(self, dx: float, dy: float, snap: bool = False) -> bool:
        """Move the selected cards/groups, as dragging would (a group's cards come
        along). Group membership doesn't change; frames refit around the move. A burst
        of nudges (holding an arrow key) becomes a single undo step. With snap, each
        moved card (or group) then lands on the nearest grid line."""
        moved = [i for i in self.selectedItems() if isinstance(i, CardItem)]
        if not moved:
            return False
        self.begin_move()             # plain curves until the burst settles
        if snap:
            # Step to the next grid line in the arrow's direction (13 → 25 → 50), moving
            # each card or group as a whole; selected cards inside a moved group keep
            # their place in it.
            # (A group carries its cards, selected ones included.)
            for item in self._move_roots(moved):
                p = item.pos()
                item.setPos(QPointF(self._next_line(p.x(), dx), self._next_line(p.y(), dy)))
        else:
            with self.moving_selection():
                for item in moved:
                    item.moveBy(dx, dy)
        self._refit_ids({i.card.parent for i in moved} - {""})
        if not self._nudge_timer.isActive():
            # Mark the window unsaved now, once per burst: every listener (story graph,
            # introductions, panels) catches up when the burst settles, not on each step.
            self.modified.emit()
        else:
            self.update_scene_rect()  # (cheap) a card nudged far out keeps its full margin
        self._nudge_timer.start()     # record the undo step once the burst ends
        return True

    def edit_selection(self) -> bool:
        """Enter: edit the one selected card, or the one selected arrow's label.
        Several selected cards open the multi-card editor."""
        selected = self.selectedItems()
        cards = [i for i in selected if isinstance(i, CardItem)]
        if len(selected) == 1 and isinstance(selected[0], EdgeItem):
            self.edit_connection_label(selected[0])
            return True
        if selected and not cards:  # only arrows: edit them together
            self.edit_arrows([i for i in selected if isinstance(i, EdgeItem)])
            return True
        if len(cards) == 1:
            self.edit_card(cards[0])
            return True
        if len(cards) > 1:
            self.edit_selected_cards()
            return True
        return False

    def edit_selected_cards(self) -> int:
        """Edit colour, tags, characters, locations and status of all selected cards at
        once (one undo step). Returns how many cards changed."""
        items = [i for i in self.selectedItems() if isinstance(i, CardItem)]
        if len(items) < 2:
            if items:
                self.edit_card(items[0])
            return 0
        self.dialog_opening.emit()
        cards = [i.card for i in items]
        dialog = MultiEditDialog(len(items), self.custom_colors,
                                 {f: self.all_values(f) for f in RENAMABLE_FIELDS},
                                 {f: board_values(cards, f) for f in BULK_LIST_FIELDS},
                                 self._dialog_parent())
        if not dialog.exec():
            return 0
        changed = apply_bulk_edit(cards, color=dialog.color(), status=dialog.status(),
                                  add=dialog.to_add(), remove=dialog.to_remove())
        ids = {c.id for c in changed}
        for item in items:
            if item.card.id in ids:
                item.apply_data(item.card)   # tags can change a card's height
        self._refit_ids({i.card.parent for i in items if i.card.id in ids} - {""})
        if changed:
            self.mark_modified()
        return len(changed)

    def finish_connection(self, scene_pos: QPointF | None, modifiers=None) -> None:
        """Complete (or, with scene_pos None, abandon) a connection. Dropping a
        dragged handle on empty canvas creates a new connected card there and opens
        its editor (Ctrl+drop: no editor). Click-to-connect never creates cards: a
        click on empty canvas just cancels it."""
        was_click_mode = self._click_connecting
        self._end_click_mode()
        source = self._connect_source
        if self._temp_line is not None:
            self.removeItem(self._temp_line)
        if self._drop_target is not None:
            self._drop_target.set_drop_highlight(False)
        self._remove_ghost()
        self._temp_line = self._connect_source = self._drop_target = None
        if source is None or scene_pos is None:
            return
        target = self._connect_target(source, scene_pos, was_click_mode)
        if target is not None:
            if self.add_connection(source, target) is not None:  # None: already connected
                self.mark_modified()
            return
        if not was_click_mode and self.can_create_connected_at(source, scene_pos):
            if modifiers is None:
                modifiers = QApplication.keyboardModifiers()
            quick = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            self.create_connected_card(source, scene_pos, edit=not quick)

    # ----- editing ----------------------------------------------------------
    def member_candidates(self, card: CardItem) -> list[tuple[str, str, bool]]:
        """(id, label, is_member) for every card that could go in `card` as a group.
        Excludes the card itself and its ancestors (which would create a loop)."""
        blocked = {card} | set(self.ancestors(card))
        out = []
        for c in sorted(self.cards.values(), key=lambda i: (i.card.title or "").casefold()):
            if c in blocked:
                continue
            label = c.card.title or "Untitled"
            if c.is_group:
                label += "  [group]"
            parent = self.parent_of(c)
            if parent is not None and parent is not card:
                label += f"  · in “{parent.card.title or 'Untitled'}”"
            out.append((c.card.id, label, c.card.parent == card.card.id))
        return out

    def apply_card_edit(self, item: CardItem, data: CardData) -> None:
        """A card's fields edited in place (the Card panel): one undo step. Its group
        refits around its new size."""
        if item.card.id not in self.cards:
            return
        item.apply_data(data)
        self._update_z()
        self.mark_modified()

    def edit_card(self, card: CardItem, is_new: bool = False) -> None:
        """Open the card editor. is_new: the card was just created and isn't in the
        undo history yet; cancelling removes it (and any arrow made with it)."""
        if card.scene() is not self:
            return
        self.dialog_opening.emit()
        suggestions = {f: self.all_values(f) for f in RENAMABLE_FIELDS}
        dialog = CardDialog(card.card, self.custom_colors, self._dialog_parent(), suggestions,
                            self.member_candidates(card), self.color_usage(exclude=card))
        dialog.set_story_tools(bool(self.display.get("story_tools", True)))
        if not dialog.exec():
            if is_new and card.card.id in self.cards:
                self.remove_cards([card])
                # Normally a no-op for the history (the board is back to its last
                # recorded state), but correct even if something recorded the card meanwhile.
                self.mark_modified()
            return
        for color in dialog.removed_custom_colors:
            if color in self.custom_colors:
                self.custom_colors.remove(color)
        for color in dialog.added_custom_colors:
            if color not in self.custom_colors:
                self.custom_colors.append(color)
        was_group = card.is_group
        new_data = dialog.result_data()
        if was_group and new_data.kind != KIND_GROUP:
            self.release_members(card)
        card.apply_data(new_data)
        if card.is_group:
            self.set_group_members(card, dialog.member_ids())
            if dialog.arrange_requested:
                self.auto_arrange_group(card)
        self._update_z()
        self.mark_modified()

    # ----- route fields (Routes panel) --------------------------------------------
    def route_data(self, key) -> RouteData | None:
        return self.routes.get(tuple(key))

    def set_route_data(self, data: RouteData) -> None:
        """Store a route's fields (one undo step); blank fields forget the route."""
        key = tuple(data.key)
        if not key:
            return
        before = self.routes.get(key)
        if data.is_blank():
            if before is None:
                return
            del self.routes[key]
        else:
            if before == data:
                return
            self.routes[key] = copy_route(data)
        self.mark_modified()

    def delete_route_data(self, key) -> bool:
        if self.routes.pop(tuple(key), None) is None:
            return False
        self.mark_modified()
        return True

    def replace_in_cards(self, find: str, replacement: str, fields, match_case: bool = False,
                         ids=None) -> int:
        """Find and replace in cards' text (all cards, or those in `ids`): one undo
        step. Returns how many cards changed."""
        items = [self.cards[i] for i in ids if i in self.cards] if ids is not None \
            else list(self.cards.values())
        changed = replace_text([i.card for i in items], find, replacement, fields, match_case)
        if not changed:
            return 0
        for card in changed:
            self.cards[card.id].apply_data(card)  # refits it and the groups around it
        self.mark_modified()
        return len(changed)

    def open_replace_dialog(self) -> int:
        from .replace_dialog import ReplaceDialog
        self.dialog_opening.emit()
        selected = [i.card.id for i in self.selectedItems() if isinstance(i, CardItem)]
        dialog = ReplaceDialog([i.card for i in self.cards.values()], selected, self._dialog_parent())
        if not dialog.exec():
            return 0
        n = self.replace_in_cards(dialog.find_text(), dialog.replacement(), dialog.fields(),
                                  dialog.match_case(), selected if dialog.selected_only() else None)
        self.notice.emit(f"Replaced in {n} card{'s' if n != 1 else ''}" if n else "Nothing to replace")
        return n

    def edit_connection_label(self, edge: EdgeItem) -> None:
        """Double-click / Enter on an arrow: edit its label, style and color."""
        self.edit_arrows([edge])

    # ----- mouse & menus ----------------------------------------------------
    def _item_at(self, pos: QPointF):
        for item in self.items(pos):
            if isinstance(item, (CardItem, EdgeItem)):
                return item
        return None

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._item_at(event.scenePos()) is None:
            self.create_card_at(event.scenePos())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ----- background -------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        t = theme.current()
        if self.export_background == "transparent":
            return
        painter.fillRect(rect, t.canvas_bg)
        if self.export_background == "plain" or not self.display.get("show_grid", True):
            return  # exported images have no grid; nor does a board that hides it
        scale = painter.worldTransform().m11()
        step = GRID if scale >= 0.5 else GRID * MAJOR_EVERY
        left = math.floor(rect.left() / step) * step
        top = math.floor(rect.top() / step) * step
        minor, major = [], []
        x = left
        while x < rect.right():
            line = QLineF(x, rect.top(), x, rect.bottom())
            (major if round(x / GRID) % MAJOR_EVERY == 0 else minor).append(line)
            x += step
        y = top
        while y < rect.bottom():
            line = QLineF(rect.left(), y, rect.right(), y)
            (major if round(y / GRID) % MAJOR_EVERY == 0 else minor).append(line)
            y += step
        painter.setPen(QPen(t.grid_minor, 0))
        painter.drawLines(minor)
        painter.setPen(QPen(t.grid_major, 0))
        painter.drawLines(major)

