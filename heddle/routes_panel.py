"""Side panel listing every route through the story, from a start to an end.

Each route is a row, collapsed by default: click it to light the route up on the
board; expand it (▸) to see its cards and its own fields (name, tags, characters,
POV, locations, status, notes), edit them, or have it inherit its cards' strands.
Fields whose route no longer exists (an arrow or card was removed) are kept and
listed under "Missing routes" until you delete them."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from . import theme
from .model import RENAMABLE_FIELDS, RouteData, copy_route, title_labels
from .route_dialog import RouteDialog
from .routes import (
    INHERITED_FIELDS, RouteListing, default_title, key_cards, list_routes, loop_details, merged_fields,
    route_title, search_text, steps_text,
)

OWNER = "routes"            # marks the canvas highlight as this panel's
REFRESH_DELAY_MS = 300      # re-list this long after the board settles


class RouteRow(QFrame):
    """One route: a header (expand arrow, title, size) and a body built when first
    expanded."""

    def __init__(self, panel: RoutesPanel, key: tuple[str, ...], missing: bool = False):
        super().__init__()
        self.panel, self.key, self.missing = panel, key, missing
        self.setObjectName("routeRow")
        self.expanded = False
        self.body: QWidget | None = None

        self.arrow = QToolButton()
        self.arrow.setArrowType(Qt.ArrowType.RightArrow)
        self.arrow.setAutoRaise(True)
        self.arrow.setToolTip("Show or hide this route's cards and fields")
        self.arrow.clicked.connect(self.toggle)
        self.title = QLabel()
        bold = QFont()
        bold.setBold(True)
        self.title.setFont(bold)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.meta = QLabel()
        self.meta.setEnabled(False)
        header = QWidget()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setToolTip("Click to light up this route on the board" if not missing
                          else "This route no longer exists: an arrow or card on it was removed")
        header.mousePressEvent = self._header_clicked
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.arrow)
        row.addWidget(self.title, 1)
        row.addWidget(self.meta)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(2)
        self._layout.addWidget(header)
        self.update_header()

    # ----- header -------------------------------------------------------------------
    def update_header(self) -> None:
        cards, data = self.panel.card_map(), self.panel.scene.route_data(self.key)
        self.title.setText(route_title(self.key, cards, data, self.panel.stops.get(self.key),
                                       self.panel.title_map()))
        self.title.setToolTip(" → ".join(self.panel.steps(self.key)))
        n = len(key_cards(self.key))
        bits = [f"{n} card" + ("" if n == 1 else "s")]
        if any("+" in part for part in self.key):
            bits.append("↻")
        if data is not None and data.inherit:
            bits.append("inherits")
        if self.missing:
            bits.append("missing")
        self.meta.setText(" · ".join(bits))

    def _header_clicked(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.missing:
            self.panel.highlight(self.key)

    def refresh(self) -> None:
        """Show the route's current titles and fields (the list itself is unchanged)."""
        self.update_header()
        if self.body is not None:
            self._layout.removeWidget(self.body)
            self.body.hide()
            self.body.deleteLater()
            self.body = None
            if self.expanded:
                self.set_expanded(True)  # rebuilt with the new values

    # ----- expanding --------------------------------------------------------------------
    def toggle(self) -> None:
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self.arrow.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if expanded and self.body is None:
            self.body = self._build_body()
            self._layout.addWidget(self.body)
        if self.body is not None:
            self.body.setVisible(expanded)
        if expanded:
            self.panel.expanded.add(self.key)
        else:
            self.panel.expanded.discard(self.key)

    def _build_body(self) -> QWidget:
        cards, data = self.panel.card_map(), self.panel.scene.route_data(self.key)
        muted = theme.current().card_muted.name()
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 0, 0, 6)
        v.setSpacing(4)

        steps = QLabel("<br>".join(f"{n}. {escape(t)}" for n, t in
                                   enumerate(self.panel.steps(self.key), 1)))
        steps.setTextFormat(Qt.TextFormat.RichText)
        steps.setWordWrap(True)
        loops = loop_details(self.key, cards, self.panel.stops.get(self.key), self.panel.title_map())
        if loops:  # long loops are summarised above: their cards are listed on hover
            steps.setToolTip("\n\n".join(loops))
        v.addWidget(steps)

        lines = []
        if data is not None and data.name.strip():
            lines.append(f"<b>Name</b>: {escape(data.name.strip())}")
        for name, view in merged_fields(data, key_cards(self.key), cards).items():
            if not (view.own or view.inherited):
                continue
            label = dict(INHERITED_FIELDS)[name]
            text = escape(", ".join(view.own))
            if view.inherited:
                extra = escape(", ".join(view.inherited))
                text += (" " if text else "") + f"<span style='color:{muted}'>+ {extra} (from cards)</span>"
            lines.append(f"<b>{label}</b>: {text}")
        if data is not None and data.notes.strip():
            notes = escape(data.notes.strip()).replace("\n", "<br>")
            lines.append(f"<b>Notes</b>: {notes}")
        fields = QLabel("<br>".join(lines) if lines else
                        f"<span style='color:{muted}'>No fields set. Edit fields… to name or tag this route.</span>")
        fields.setTextFormat(Qt.TextFormat.RichText)
        fields.setWordWrap(True)
        fields.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.fields_label = fields
        v.addWidget(fields)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        if self.missing:
            delete = QPushButton("Delete fields")
            delete.setToolTip("Forget this missing route's fields (undo with Ctrl+Z)")
            delete.clicked.connect(lambda: self.panel.scene.delete_route_data(self.key))
            buttons.addWidget(delete)
        else:
            self.inherit_check = QCheckBox("Inherit card strands")
            self.inherit_check.setToolTip("Also show every tag, character, POV, location and "
                                          "status its cards have (they follow the cards)")
            self.inherit_check.setChecked(data is not None and data.inherit)
            self.inherit_check.toggled.connect(lambda on: self.panel.set_inherit(self.key, on))
            v.addWidget(self.inherit_check)
            edit = QPushButton("Edit fields…")
            edit.clicked.connect(lambda: self.panel.edit(self.key))
            buttons.addWidget(edit)
            if data is not None:
                clear = QPushButton("Clear fields")
                clear.setToolTip("Remove this route's name, strands and notes (undo with Ctrl+Z)")
                clear.clicked.connect(lambda: self.panel.scene.delete_route_data(self.key))
                buttons.addWidget(clear)
        buttons.addStretch(1)
        v.addLayout(buttons)
        return body


class RoutesPanel(QWidget):
    show_cards = Signal(list)  # CardItems to select and bring into view

    def __init__(self, scene, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene = scene
        self.listing = RouteListing([], 0, [])
        self.rows: dict[tuple[str, ...], RouteRow] = {}
        self.expanded: set[tuple[str, ...]] = set()  # rows left open, kept across refreshes
        self._shown: tuple | None = None      # (rows listed, their content) last shown
        # Worked out once per refresh, then reused by headers, bodies and the filter.
        self._cards: dict | None = None
        self._titles: dict[str, str] | None = None
        self._steps: dict[tuple[str, ...], list[str]] = {}
        self.stops: dict[tuple[str, ...], tuple] = {}  # listed routes' stops, loops in story order
        self._search: dict[tuple[str, ...], str] = {}

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        bold = QFont()
        bold.setBold(True)
        self.summary.setFont(bold)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter routes by name, card or strand")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self._new_list()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self._list)

        hint = QLabel("Click a route to light it up. Expand it (▸) to see its cards and give it "
                      "its own fields. A loop counts as one stop.")
        hint.setWordWrap(True)
        hint.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.summary)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(hint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DELAY_MS)
        self._timer.timeout.connect(self.refresh)
        scene.modified.connect(self.schedule)
        scene.history_changed.connect(self.schedule)  # a board opened / started
        self.refresh()

    # ----- public -------------------------------------------------------------------
    def schedule(self) -> None:
        """Re-list soon, if the panel is showing (it catches up when shown)."""
        if self.isVisible():
            self._timer.start()

    def card_map(self) -> dict:
        if self._cards is None:
            self._cards = {cid: item.card for cid, item in self.scene.cards.items()}
        return self._cards

    def title_map(self) -> dict[str, str]:
        """Titles as listed (repeated titles name their group), cached per refresh."""
        if self._titles is None:
            self._titles = title_labels(self.card_map().values())
        return self._titles

    def steps(self, key) -> list[str]:
        """The route's steps as shown (long loops summarised), cached per refresh."""
        key = tuple(key)
        if key not in self._steps:
            self._steps[key] = steps_text(key, self.card_map(), self.stops.get(key), self.title_map())
        return self._steps[key]

    def refresh(self) -> RouteListing:
        self._timer.stop()
        self._cards = None
        self._titles = None
        self._steps.clear()
        self._search.clear()
        graph = self.scene.story_graph()
        self.listing = list_routes(graph, self.scene.routes)
        self.stops = {r.key: r.stops for r in self.listing.routes}
        self._fill(self.listing)
        return self.listing

    def highlight(self, key) -> None:
        route = self.scene.story_graph().route_for_key(tuple(key))
        if route is None:
            return
        cards, data = self.card_map(), self.scene.route_data(route.key)
        arrows = self.scene.story_graph().route_arrows(route)
        self.scene.set_highlight(set(route.cards), arrows, None,
                                 f"Route: {route_title(route.key, cards, data, route.stops, self.title_map())}",
                                 OWNER)
        self.show_cards.emit([self.scene.cards[i] for i in route.cards if i in self.scene.cards])

    def edit(self, key) -> bool:
        """Open the route's field editor; True if it was accepted."""
        key = tuple(key)
        data = self.scene.route_data(key)
        data = copy_route(data) if data is not None else RouteData(key=list(key))
        cards = self.card_map()
        suggestions = {f: self.scene.all_values(f) for f in RENAMABLE_FIELDS}
        dialog = RouteDialog(data, self.steps(key),
                             default_title(key, cards, self.stops.get(key), self.title_map()),
                             suggestions, self)
        if not dialog.exec():
            return False
        self.scene.set_route_data(dialog.route_data())
        return True

    def set_inherit(self, key, on: bool) -> None:
        key = tuple(key)
        data = self.scene.route_data(key)
        data = copy_route(data) if data is not None else RouteData(key=list(key))
        data.inherit = on
        self.scene.set_route_data(data)

    # ----- internals --------------------------------------------------------------------
    def _signature(self, listing: RouteListing) -> tuple[tuple, tuple]:
        """(which rows are listed, what they show). Card titles are taken once per
        card, not once per route, so long routes sharing cards stay cheap."""
        cards = self.card_map()
        keys = (tuple(r.key for r in listing.routes), tuple(tuple(d.key) for d in listing.missing))
        on_routes: set[str] = set()
        for r in listing.routes:
            on_routes.update(r.cards)
        for d in listing.missing:
            on_routes.update(key_cards(d.key))
        labels = self.title_map()  # a repeated title's group shows too
        titles = tuple(sorted((i, labels.get(i)) for i in on_routes))

        def fields(key):
            data = self.scene.route_data(key)
            inherited = ()
            if data is not None and data.inherit:
                inherited = tuple((n, tuple(v.inherited)) for n, v in
                                  merged_fields(data, key_cards(key), cards).items())
            return data and repr(data), inherited

        content = (listing.total, theme.current().dark, titles,
                   tuple(fields(k) for k in keys[0] + keys[1]))
        return keys, content

    def _fill(self, listing: RouteListing) -> None:
        n = listing.total
        if n == 0 and not listing.missing:
            self.summary.setText("No routes yet: connect cards with arrows, and each way from a "
                                 "start to an end is listed here.")
        else:
            text = f"{n} route" + ("" if n == 1 else "s")
            if listing.truncated:
                text += f" (showing {len(listing.routes)})"
            if listing.missing:
                text += f" · {len(listing.missing)} missing"
            self.summary.setText(text)
        # Most edits (moving a card, say) don't change the list: leave it alone then,
        # so its scroll position and open rows aren't disturbed.
        shown = self._signature(listing)
        if shown == self._shown:
            return
        same_rows = self._shown is not None and shown[0] == self._shown[0]
        self._shown = shown
        if same_rows:
            # Same routes, new titles or fields: update the rows where they are.
            for row in self.rows.values():
                row.refresh()
            self._apply_filter(self.filter_edit.text())
            return
        scroll = self.scroll.verticalScrollBar().value()
        # Build the new list off-screen and swap it in whole (the scroll area deletes
        # the old one): far cheaper than hiding and removing rows one at a time.
        self._new_list()
        self.rows = {}
        for route in listing.routes:
            self._add_row(route.key, missing=False)
        if listing.missing:
            heading = QLabel("Missing routes")
            heading.setToolTip("Routes with fields that no longer exist: an arrow or card on "
                               "them was removed. Reconnect them, or delete their fields.")
            bold = QFont()
            bold.setBold(True)
            heading.setFont(bold)
            heading.setContentsMargins(4, 10, 4, 2)
            self._list_layout.addWidget(heading)
            for data in listing.missing:
                self._add_row(tuple(data.key), missing=True)
        self._list_layout.addStretch(1)
        self.expanded &= set(self.rows)
        self._apply_filter(self.filter_edit.text())
        self.scroll.setWidget(self._list)
        self.scroll.verticalScrollBar().setValue(scroll)

    def _new_list(self) -> None:
        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)

    def _add_row(self, key, missing: bool) -> None:
        row = RouteRow(self, key, missing)
        self.rows[key] = row
        self._list_layout.addWidget(row)
        if key in self.expanded:
            row.set_expanded(True)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for key, row in self.rows.items():
            if needle:
                if key not in self._search:
                    self._search[key] = search_text(key, self.card_map(), self.scene.route_data(key),
                                                    self.title_map())
                visible = needle in self._search[key]
            else:
                visible = True
            if row.isHidden() == visible:  # only touch rows that change
                row.setVisible(visible)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        minimized = self.window() is not None and self.window().isMinimized()
        if not minimized and self.scene.highlight_owner() == OWNER:
            self.scene.clear_highlight()
