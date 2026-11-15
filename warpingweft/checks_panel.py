"""Side panel listing story checks: dead ends, extra starts, loops, loose cards,
starts, endings and the number of routes. Clicking a result finds its cards."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import settings
from .checks import DEFAULT_ENDING_WORD, KINDS, WARNING, Report, run_checks, summary

OWNER = "checks"            # marks the canvas highlight as the checks panel's
RECHECK_DELAY_MS = 300      # re-run this long after the board settles
ENDING_KEY = "checks/ending_word"
ROLE_IDS = Qt.ItemDataRole.UserRole       # card ids a row stands for
ROLE_KIND = Qt.ItemDataRole.UserRole + 1


class ChecksPanel(QWidget):
    show_cards = Signal(list)  # CardItems to select and bring into view

    def __init__(self, scene, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene = scene
        self.report = Report()
        self._collapsed: set[str] = {"start", "ending"}  # the plain lists start folded
        self._shown: tuple | None = None  # what the list shows now (skip identical rebuilds)

        self.scope = QComboBox()
        self.scope.setToolTip("Check the whole board, or just the cards in one group")
        self.scope.currentIndexChanged.connect(lambda _: self.recheck())
        self.ending = QLineEdit(str(settings.store().value(ENDING_KEY, DEFAULT_ENDING_WORD)))
        self.ending.setPlaceholderText(DEFAULT_ENDING_WORD)
        self.ending.setToolTip("Cards with this tag or status are endings, so they aren't "
                               "reported as dead ends")
        self.ending.editingFinished.connect(self._ending_changed)
        form = QFormLayout()
        form.addRow("Check", self.scope)
        form.addRow("Endings are tagged", self.ending)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        bold = QFont()
        bold.setBold(True)
        self.summary.setFont(bold)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemCollapsed.connect(lambda it: self._collapsed.add(it.data(0, ROLE_KIND)))
        self.tree.itemExpanded.connect(lambda it: self._collapsed.discard(it.data(0, ROLE_KIND)))

        hint = QLabel("Click a result to find its cards. Mark a deliberate ending with the "
                      "tag or status above so it isn't counted as a dead end.")
        hint.setWordWrap(True)
        hint.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree, 1)
        layout.addWidget(hint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RECHECK_DELAY_MS)
        self._timer.timeout.connect(self.recheck)
        scene.modified.connect(self.schedule)
        scene.history_changed.connect(self.schedule)  # a board opened / started
        self.recheck()

    # ----- public -------------------------------------------------------------
    def schedule(self) -> None:
        """Re-check soon, if the panel is showing (it catches up when shown)."""
        if self.isVisible():
            self._timer.start()

    def ending_word(self) -> str:
        return self.ending.text().strip() or DEFAULT_ENDING_WORD

    def recheck(self) -> Report:
        self._timer.stop()
        self._fill_scopes()
        graph = self.scene.story_graph()
        scope = self.scope.currentData()
        self.report = run_checks(graph, scope, self.ending_word())
        self.summary.setText(summary(self.report))
        self._fill_tree(graph)
        return self.report

    # ----- internals ---------------------------------------------------------------
    def _ending_changed(self) -> None:
        settings.store().setValue(ENDING_KEY, self.ending_word())
        self.recheck()

    def _fill_scopes(self) -> None:
        """Whole board, then each group by title; keeps the current choice if it
        still exists."""
        current = self.scope.currentData()
        groups = sorted((i for i in self.scene.cards.values() if i.is_group),
                        key=lambda g: (g.card.title or "").casefold())
        labels = self.scene.title_labels()  # groups with the same name name their parent
        wanted = [("Whole board", None)] + [(f"Group: {labels.get(g.card.id, 'Untitled')}", g.card.id)
                                            for g in groups]
        have = [(self.scope.itemText(i), self.scope.itemData(i)) for i in range(self.scope.count())]
        if have == wanted:
            return
        self.scope.blockSignals(True)
        self.scope.clear()
        for text, data in wanted:
            self.scope.addItem(text, data)
        index = next((n for n, (_, d) in enumerate(wanted) if d == current), 0)
        self.scope.setCurrentIndex(index)
        self.scope.blockSignals(False)

    def _fill_tree(self, graph) -> None:
        # Most edits (moving a card, say) don't change the results: leave the list
        # alone then, so its scroll position and current row aren't lost.
        shown = tuple((f.kind, f.cards, f.message) for f in self.report.findings)
        if shown == self._shown:
            return
        self._shown = shown
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        for kind, (title, severity) in KINDS.items():
            found = self.report.of_kind(kind)
            if not found:
                continue
            mark = "⚠" if severity == WARNING else "•"
            top = QTreeWidgetItem(self.tree, [f"{mark}  {title} ({len(found)})"])
            top.setFont(0, bold)
            top.setData(0, ROLE_KIND, kind)
            top.setData(0, ROLE_IDS, [c for f in found for c in f.cards])
            for f in found:
                child = QTreeWidgetItem(top, [f.message])
                child.setData(0, ROLE_KIND, kind)
                child.setData(0, ROLE_IDS, list(f.cards))
                child.setToolTip(0, f.message)
            top.setExpanded(kind not in self._collapsed)
        self.tree.verticalScrollBar().setValue(scroll)

    def _on_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        ids = [i for i in (item.data(0, ROLE_IDS) or []) if i in self.scene.cards]
        if not ids:
            return
        kind = item.data(0, ROLE_KIND)
        graph = self.scene.story_graph()
        arrows = graph.arrows_within(ids) if kind == "cycle" else set()
        label = item.text(0).lstrip("⚠• ").strip()
        self.scene.set_highlight(set(ids), arrows, ids[0] if len(ids) == 1 else None,
                                 f"Check: {label}", OWNER)
        self.show_cards.emit([self.scene.cards[i] for i in ids])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.recheck()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        minimized = self.window() is not None and self.window().isMinimized()
        if not minimized and self.scene.highlight_owner() == OWNER:
            self.scene.clear_highlight()
