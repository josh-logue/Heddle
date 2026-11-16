"""Side panel that walks one route through the story, card by card.

Start it on a card ("Read from here"). It shows that card's text and offers the
next steps along its arrows: one Next button, or a button per branch at a choice.
Back retraces the route actually taken (not just any card that leads here). The
route so far is highlighted on the canvas and the view follows each step.
"""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

OWNER = "reader"  # marks the canvas highlight as the reader's own
MAX_CHOICE_KEYS = 9  # number keys 1-9 pick a branch


class PathReader(QWidget):
    show_card = Signal(object)  # CardItem the view should move to and select

    def __init__(self, scene, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene = scene
        self.route: list[str] = []       # card ids, in the order read
        self.via: list[str] = []         # label of the arrow that led to each step ("" if none)
        self._start_choices: list[str] = []  # reading a group: its first cards, before step 1
        self._start_title = ""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # for the arrow / number keys
        # Space means "next" here: the canvas's Space-to-pan leaves it alone while
        # the reader has focus, even with the pointer over the canvas.
        self.setProperty("usesSpaceKey", True)

        self.trail = QLabel()
        self.trail.setWordWrap(True)
        self.trail.setTextFormat(Qt.TextFormat.RichText)
        self.trail.setEnabled(False)  # muted
        self.step_label = QLabel()
        self.step_label.setEnabled(False)

        self.title = QLabel()
        title_font = QFont()
        title_font.setPointSizeF(13)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.title.setWordWrap(True)
        self.via_label = QLabel()
        self.via_label.setWordWrap(True)
        self.via_label.setTextFormat(Qt.TextFormat.RichText)
        self.meta = QLabel()
        self.meta.setWordWrap(True)
        self.meta.setTextFormat(Qt.TextFormat.RichText)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        self.notes.setEnabled(False)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(2, 2, 2, 2)
        for w in (self.via_label, self.title, self.meta, self.body, self.notes):
            cv.addWidget(w)
        cv.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.choices_box = QVBoxLayout()
        self.choices_box.setSpacing(4)
        self.end_label = QLabel()
        self.end_label.setEnabled(False)
        self.end_label.setWordWrap(True)

        self.back_btn = QPushButton("← Back")
        self.restart_btn = QPushButton("Restart")
        self.back_btn.clicked.connect(self.back)
        self.restart_btn.clicked.connect(self.restart)
        for b in (self.back_btn, self.restart_btn):
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nav = QHBoxLayout()
        nav.addWidget(self.back_btn)
        nav.addWidget(self.restart_btn)
        nav.addStretch()
        nav.addWidget(self.step_label)

        hint = QLabel("→ / Space: next · 1–9: pick a branch · ← / Backspace: back")
        hint.setEnabled(False)
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.trail)
        layout.addWidget(scroll, 1)
        layout.addLayout(self.choices_box)
        layout.addWidget(self.end_label)
        layout.addLayout(nav)
        layout.addWidget(hint)
        self._choice_buttons: list[QPushButton] = []
        self._labels: dict[str, str] | None = None
        self.render()

    # ----- starting & stepping ----------------------------------------------------
    def start(self, card_id: str) -> None:
        """Begin reading at a card. A group starts at its first cards: one of
        them is picked up straight away, or the reader offers the choice."""
        graph = self.scene.story_graph()
        self.route, self.via, self._start_choices = [], [], []
        if graph.is_container(card_id):
            entries = self._ordered(graph, graph.entry_cards(card_id))
            if len(entries) == 1:
                self._step_to(entries[0], "")
                return
            self._start_choices = entries
            self._start_title = self.scene.cards[card_id].card.title or "Untitled"
            self.render()
            return
        self._step_to(card_id, "")

    def choices(self) -> list[tuple[str, str]]:
        """(card id, arrow label) for each possible next step, in story order."""
        graph = self.scene.story_graph()
        if not self.route:
            return [(c, "") for c in self._start_choices]
        current = self.route[-1]
        out = []
        for nxt in self._ordered(graph, graph.succ.get(current, [])):
            labels = [self.scene_conn_label(a) for a in graph.step_arrows(current, nxt)]
            out.append((nxt, next((label for label in labels if label), "")))
        return out

    def choose(self, index: int) -> bool:
        options = self.choices()
        if not 0 <= index < len(options):
            return False
        card_id, label = options[index]
        self._step_to(card_id, label)
        return True

    def next(self) -> bool:
        """Follow the only way on; at a branch, use choose()."""
        return len(self.choices()) == 1 and self.choose(0)

    def back(self) -> bool:
        if len(self.route) <= 1 and not (self.route and self._start_choices):
            return False
        self.route.pop()
        self.via.pop()
        if self.route:
            self._show(self.route[-1])
        self.render()
        return True

    def restart(self) -> None:
        if self._start_choices:
            self.route, self.via = [], []
            self.render()
        elif self.route:
            self.route, self.via = self.route[:1], self.via[:1]
            self._show(self.route[0])
            self.render()

    def stop(self) -> None:
        """Forget the route and remove the reader's highlight (if it's still showing)."""
        self.route, self.via, self._start_choices = [], [], []
        if self.scene.highlight_owner() == OWNER:
            self.scene.clear_highlight()
        self.render()

    def refresh(self) -> None:
        """The board changed: the route ends at the first step whose card is gone or
        that the board no longer joins to the one before (its arrow was deleted or
        reversed). Then redraw."""
        if not self.route and not self._start_choices:
            return
        graph = self.scene.story_graph()
        keep = 0
        while keep < len(self.route) and self.route[keep] in self.scene.cards:
            if keep and self.route[keep] not in graph.succ.get(self.route[keep - 1], ()):
                break
            keep += 1
        self.route, self.via = self.route[:keep], self.via[:keep]
        self._start_choices = [c for c in self._start_choices if c in self.scene.cards]
        # Redraw the route's highlight only if it's still the one showing: another
        # highlight (a thread, paths, a story check) or one cleared with Esc stays as
        # it is. Taking a step in the reader brings the reader's highlight back.
        self.render(rehighlight=self.scene.highlight_owner() == OWNER)

    # ----- internals -----------------------------------------------------------------
    def scene_conn_label(self, conn_id: str) -> str:
        edge = next((e for e in self.scene.edges if e.conn.id == conn_id), None)
        return " ".join(edge.conn.label.split()) if edge is not None else ""

    def _ordered(self, graph, ids) -> list[str]:
        rank = {i: n for n, i in enumerate(graph.arrow_order())}
        return sorted(ids, key=lambda i: rank.get(i, len(rank)))

    def _step_to(self, card_id: str, label: str) -> None:
        self.route.append(card_id)
        self.via.append(label)
        self._show(card_id)
        self.render()

    def _show(self, card_id: str) -> None:
        item = self.scene.cards.get(card_id)
        if item is not None:
            self.show_card.emit(item)

    def _title(self, card_id: str) -> str:
        """As listed: a repeated title names its group (labels taken once per render)."""
        item = self.scene.cards.get(card_id)
        if item is None:
            return "?"
        if self._labels is None:
            self._labels = self.scene.title_labels()
        return self._labels.get(card_id) or item.card.title or "Untitled"

    def render(self, rehighlight: bool = True) -> None:
        self._labels = None  # titles may have changed since the last render
        for b in self._choice_buttons:
            self.choices_box.removeWidget(b)
            b.hide()  # deleteLater is deferred: don't leave the old button painted meanwhile
            b.deleteLater()
        self._choice_buttons = []
        reading = bool(self.route or self._start_choices)
        self.back_btn.setEnabled(len(self.route) > 1 or (bool(self.route) and bool(self._start_choices)))
        self.restart_btn.setEnabled(len(self.route) > 1 or bool(self.route and self._start_choices))
        if not reading:
            self.trail.setText("")
            self.step_label.setText("")
            self.via_label.setText("")
            self.title.setText("Not reading")
            self.meta.setText("")
            self.body.setText("Right-click a card → <i>Read from here</i> (or select it and press "
                              "Ctrl+Shift+R) to walk through the story from it.")
            self.body.setTextFormat(Qt.TextFormat.RichText)
            self.notes.setText("")
            self.end_label.setText("")
            return
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.trail.setText(" → ".join(escape(self._title(c)) for c in self.route) or
                           f"Reading “{escape(self._start_title)}”")
        self.step_label.setText(f"Step {len(self.route)}" if self.route else "")

        if self.route:
            card = self.scene.cards[self.route[-1]].card
            via = self.via[-1]
            self.via_label.setText(f"<i>via “{escape(via)}”</i>" if via else "")
            self.title.setText(card.title or "Untitled")
            meta = []
            if card.pov:
                meta.append(f"<b>POV</b> {escape(card.pov)}")
            others = [c for c in card.characters if c.casefold() != card.pov.casefold()]
            if others:
                meta.append(f"<b>Characters</b> {escape(', '.join(others))}")
            if card.locations:
                meta.append(f"<b>Locations</b> {escape(', '.join(card.locations))}")
            if card.status:
                meta.append(f"<b>Status</b> {escape(card.status)}")
            self.meta.setText(" · ".join(meta))
            self.body.setText(card.description or "(no description)")
            self.notes.setText(f"<b>Notes</b><br>{escape(card.notes)}".replace("\n", "<br>")
                               if card.notes else "")
        else:  # reading a group: pick where to begin
            self.via_label.setText("")
            self.title.setText(self._start_title)
            self.meta.setText("")
            self.body.setText("This group has several first cards. Where do you want to begin?")
            self.notes.setText("")

        options = self.choices()
        visited = set(self.route)
        for n, (card_id, label) in enumerate(options):
            text = self._title(card_id)
            if label:
                text = f"“{label}” → {text}"
            elif self.route:
                text = f"→ {text}"
            if card_id in visited:
                text += "  (visited)"
            if n < MAX_CHOICE_KEYS and len(options) > 1:
                text = f"{n + 1}.  {text}"
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("text-align: left; padding: 4px 8px;")
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _=False, i=n: self.choose(i))
            self.choices_box.addWidget(b)
            self._choice_buttons.append(b)
        if not options:
            self.end_label.setText("The end of this path: no arrows lead on from here.")
        elif len(options) > 1 and self.route:
            self.end_label.setText(f"The story branches here ({len(options)} ways on).")
        else:
            self.end_label.setText("")
        if rehighlight:
            self._highlight_route()

    def _highlight_route(self) -> None:
        graph = self.scene.story_graph()
        ids = set(self.route) | set(self._start_choices if not self.route else ())
        if not ids:
            return
        arrows: set[str] = set()
        for a, b in zip(self.route, self.route[1:]):
            arrows.update(graph.step_arrows(a, b))
        arrows |= graph.markers_for(self.route)
        n = len(self.route)
        label = f"Reading a path · step {n}" if n else "Reading a path"
        self.scene.set_highlight(ids, arrows, self.route[-1] if self.route else None, label, OWNER)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.next():
                event.accept()
                return
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Backspace):
            if self.back():
                event.accept()
                return
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            if self.choose(key - Qt.Key.Key_1):
                event.accept()
                return
        super().keyPressEvent(event)
