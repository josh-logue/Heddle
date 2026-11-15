"""Go to Card (Ctrl+P): a small box to type part of a card's title and jump to it,
quicker than finding it on a big board or in the Card List.

Titles that start with what you type come first, then titles with a word starting
with it, then titles containing it, then cards found by their description, notes or
strands (as Ctrl+F search finds them), each marked with where. Enter jumps: the card is
selected and brought into view, its collapsed groups unfold (as a search match's do),
and the keyboard goes to the canvas. Rows remember card ids, never CardItems."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .card_item import STRAND_MARKS
from .card_list import cached_swatch, natural_key
from .filters import search_cards
from .model import KIND_GROUP, KIND_STRAND

MAX_ROWS = 200          # enough to scroll through; typing narrows it faster
ROLE_ID = Qt.ItemDataRole.UserRole
FORWARDED = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)


def rank(title: str, needle: str) -> int | None:
    """How well a title matches: 0 starts with it, 1 a word starts with it, 2 contains
    it, None not at all. `needle` is casefolded with single spaces."""
    t = " ".join(title.split()).casefold()
    if t.startswith(needle):
        return 0
    if f" {needle}" in f" {t}".replace("-", " ").replace("(", " "):
        return 1
    return 2 if needle in t else None


class GoToCardDialog(QDialog):
    card_chosen = Signal(str)  # the id of the card to go to

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to Card")
        self.scene = scene
        self._icons: dict = {}
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type part of a card's title")
        self.edit.textChanged.connect(self._fill)
        self.edit.installEventFilter(self)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(lambda _item: self.accept())
        self.hint = QLabel()
        self.hint.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.edit)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.hint)
        self.resize(420, 360)
        self._fill()

    def chosen_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ROLE_ID) if item is not None else None

    def row_ids(self) -> list[str]:
        return [self.list.item(n).data(ROLE_ID) for n in range(self.list.count())]

    def accept(self) -> None:
        cid = self.chosen_id()
        super().accept()
        if cid is not None:
            self.card_chosen.emit(cid)

    # ----- internals ------------------------------------------------------------------
    def _fill(self, _text: str = "") -> None:
        cards = {cid: item.card for cid, item in self.scene.cards.items()}
        labels = self.scene.title_labels()  # "Warden · East Ward" when titles repeat
        needle = " ".join(self.edit.text().split()).casefold()
        found: list[tuple] = []  # (sort key, id, where it matched)
        if not needle:
            found = [((natural_key(c.title),), cid, "") for cid, c in cards.items()]
        else:
            for cid, c in cards.items():
                r = rank(c.title.strip() or "Untitled", needle)
                if r is not None:
                    found.append(((r, natural_key(c.title)), cid, ""))
            titled = {cid for _, cid, _ in found}
            for cid, label, snippet in search_cards(cards.values(), needle, self.scene.strand_info):
                if cid not in titled:
                    found.append(((3, natural_key(cards[cid].title)), cid, f"{label}: {snippet}"))
        found.sort(key=lambda f: f[0])
        self.list.clear()
        for _, cid, where in found[:MAX_ROWS]:
            card = cards[cid]
            text = labels.get(cid, card.title.strip() or "Untitled")
            if card.kind == KIND_STRAND:
                text = f"{STRAND_MARKS.get(card.strand_kind, '•')} {text}"
            elif card.kind == KIND_GROUP:
                text += "  (group)"
            if where:
                text += f"   — {where}"
            item = QListWidgetItem(cached_swatch(card.color, self._icons), text)
            item.setData(ROLE_ID, cid)
            if where:
                item.setToolTip(where)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        more = len(found) - MAX_ROWS
        self.hint.setText(
            "No card matches" if not found else
            f"{len(found)} card{'s' if len(found) != 1 else ''}"
            + (f" (first {MAX_ROWS} shown: type more to narrow)" if more > 0 else "")
            + " · Enter goes to it, Esc closes")

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in FORWARDED:  # ↑ / ↓ move through the list while you type
                self.list.keyPressEvent(event)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.accept()
                return True
        return super().eventFilter(obj, event)
