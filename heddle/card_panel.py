"""The Card panel: a side panel that edits the selected card in place. Click a card and
type; there's no dialog and no OK. What you type is saved when you pause (or leave the
field, or pick another card), each save one undo step, like a strand's description.

The editor dialog stays for everything this panel doesn't do: new cards, a group's
members, a strand card's strand, colours, and several cards at once (the panel offers
a button for those). The panel always looks its card up by id, because undo rebuilds
every card on the board."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .card_item import CardItem
from .details_form import DetailFields
from .model import KIND_GROUP, KIND_STRAND, CardData

COMMIT_DELAY_MS = 700  # what's typed is saved this long after you stop typing


def tidy(card: CardData, title: str, description: str, values: dict) -> CardData:
    """The card as the panel's fields describe it, tidied as the editor dialog does."""
    return replace(card, title=title.strip() or "Untitled",
                   description=description.strip() if card.kind != KIND_GROUP else card.description,
                   **{**values, "notes": values["notes"].strip()})


class CardPanel(QWidget):
    def __init__(self, scene, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene = scene
        self.card_id: str | None = None   # the card being shown (looked up by id each time)
        self._fields: DetailFields | None = None
        self._form_box: QWidget | None = None

        self.heading = QLabel()
        bold = QFont()
        bold.setBold(True)
        self.heading.setFont(bold)
        self.heading.setWordWrap(True)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setEnabled(False)
        self.dialog_btn = QPushButton()
        self.dialog_btn.setAutoDefault(False)
        self.dialog_btn.clicked.connect(self._open_dialog)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.heading)
        layout.addWidget(self.message)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self.dialog_btn)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COMMIT_DELAY_MS)
        self._timer.timeout.connect(self.commit)
        # Selection changes often come in bursts (paste, undo, Story Checks results each
        # select card by card): the panel follows once the burst is over.
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(0)
        self._selection_timer.timeout.connect(self._follow_selection)
        scene.selectionChanged.connect(self._on_selection)
        scene.modified.connect(self.refresh)
        scene.history_changed.connect(self.refresh)
        self._follow_selection()

    # ----- which card -------------------------------------------------------------------
    def selected_cards(self) -> list[CardItem]:
        try:
            return [i for i in self.scene.selectedItems() if isinstance(i, CardItem)]
        except RuntimeError:  # the scene is being torn down
            return []

    def item(self) -> CardItem | None:
        return self.scene.cards.get(self.card_id) if self.card_id else None

    def _on_selection(self) -> None:
        # What was typed for the last card is kept before switching. Only typing still
        # waiting to be saved: the panel catches up a moment later, so meanwhile (e.g.
        # an undo rebuilding the board) its fields can be out of date, not newly typed.
        if self._timer.isActive():
            self.commit()
        self._selection_timer.start()

    def _follow_selection(self) -> None:
        cards = self.selected_cards()
        self.card_id = cards[0].card.id if len(cards) == 1 else None
        self._rebuild()

    # ----- showing ------------------------------------------------------------------------
    def refresh(self) -> None:
        """The board changed (an edit, undo, redo): show the card as it now is, unless
        what's in the fields already says the same (so typing is never interrupted)."""
        if self._timer.isActive():
            return  # an edit is waiting to be saved: don't overwrite it
        item = self.item()
        if item is None or self._fields is None:
            if self.card_id is not None and item is None:
                self.card_id = None  # deleted, or undone away
            self._rebuild()
            return
        if self._shown() != item.card:
            self._rebuild()

    def _shown(self) -> CardData | None:
        item = self.item()
        if item is None or self._fields is None:
            return None
        return tidy(item.card, self.title_edit.text(), self.desc_edit.toPlainText(), self._fields.values())

    def _rebuild(self) -> None:
        self._timer.stop()
        if self._form_box is not None:
            self._scroll.takeWidget()
            self._form_box.deleteLater()
        self._form_box, self._fields = None, None
        cards = self.selected_cards()
        item = self.item()
        self.dialog_btn.show()
        if item is None:
            self.dialog_btn.setVisible(len(cards) > 1)
            self.dialog_btn.setText(f"Edit {len(cards)} Cards…")
            self.heading.setText(f"{len(cards)} cards selected" if len(cards) > 1 else "No card selected")
            self.message.setText("Edit their colour, tags, characters, locations and status together."
                                 if len(cards) > 1 else "Click a card to edit it here.")
            return
        card = item.card
        if card.kind == KIND_STRAND:
            self.heading.setText(card.title or "Untitled")
            self.message.setText("A strand card shows its strand: give it a description in "
                                 "the Strands panel.")
            self.dialog_btn.setText("Edit Strand Card…")
            return
        parent = self.scene.parent_of(item)
        where = f" in “{parent.card.title or 'Untitled'}”" if parent is not None else ""
        self.heading.setText(("Group" if card.kind == KIND_GROUP else "Card") + where)
        self.message.setText("Changes are saved as you pause typing (Ctrl+Z undoes).")
        self.dialog_btn.setText("Edit Group…" if card.kind == KIND_GROUP else "More…")
        self.dialog_btn.setToolTip("Open the editor for colour, type and everything else"
                                   + (", and the group's cards" if card.kind == KIND_GROUP else ""))

        box = QWidget()
        form = QFormLayout(box)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setContentsMargins(0, 0, 0, 0)
        self.title_edit = QLineEdit(card.title)
        self.title_edit.setPlaceholderText("Title")
        form.addRow("Title", self.title_edit)
        self.desc_edit = QPlainTextEdit(card.description)
        self.desc_edit.setPlaceholderText("What happens…")
        if card.kind != KIND_GROUP:  # groups have no description of their own
            form.addRow("Description", self.desc_edit)
        self._fields = DetailFields(card, self.scene.strand_suggestions(), box)
        form.addRow("Tags", self._fields.tags_input)
        self._fields.add_detail_rows(form)
        self._fields.notes_edit.setMinimumHeight(60)

        self.title_edit.textEdited.connect(self._typed)
        self.desc_edit.textChanged.connect(self._typed)
        for token in (self._fields.tags_input, self._fields.characters_input, self._fields.locations_input):
            token.changed.connect(self._typed)
        self._fields.pov_combo.currentTextChanged.connect(self._typed)
        self._fields.status_combo.currentTextChanged.connect(self._typed)
        self._fields.notes_edit.textChanged.connect(self._typed)
        for w in (self.title_edit, self.desc_edit, self._fields.notes_edit):
            w.installEventFilter(self)
        self._form_box = box
        self._scroll.setWidget(box)

    # ----- saving -------------------------------------------------------------------------
    def _typed(self, *_args) -> None:
        if self._fields is not None:
            self._timer.start()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FocusOut:
            self.commit()
        return False

    def commit(self) -> bool:
        """Save what the fields say (one undo step). True if the card changed."""
        self._timer.stop()
        item = self.item()
        new = self._shown()
        if item is None or new is None or new == item.card:
            return False
        self.scene.apply_card_edit(item, new)
        return True

    def focus_title(self) -> bool:
        if self._fields is None:
            return False
        self.title_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.title_edit.selectAll()
        return True

    def _open_dialog(self) -> None:
        self.commit()
        item = self.item()
        if item is not None:
            self.scene.edit_card(item)
        elif len(self.selected_cards()) > 1:
            self.scene.edit_selected_cards()
