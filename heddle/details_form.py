"""The fields cards and routes share: tags, characters, POV, locations, status and
notes. Used by the card editor and the route editor, so both behave the same."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QPlainTextEdit, QWidget

from . import settings
from .model import BUILTIN_STATUSES
from .token_input import STRAND_GROUPS_KEY, TokenInput

STATUS_PRESETS = ["", *BUILTIN_STATUSES]


class ScrollSafeCombo(QComboBox):
    """A combo box the mouse wheel passes over. These forms sit in scrolling panels,
    and a plain QComboBox both grabs focus on the wheel and steps through its choices,
    so scrolling past POV or Status quietly reassigned the card. The wheel goes to the
    panel instead; pick from the list or type to change the value."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # not WheelFocus

    def wheelEvent(self, event) -> None:
        event.ignore()  # ignored events travel on to the parent: the scroll area


class DetailFields(QObject):
    """Builds the shared widgets from `data` (a CardData or RouteData); the dialog
    places them (add_detail_rows puts Characters … Notes into a form; the tags box
    goes wherever the dialog wants it).

    POV: offers the item's own characters first, then the rest of the board's, and
    removing the POV character's chip clears the POV too."""

    def __init__(self, data, suggestions: dict[str, list[str]], parent: QWidget):
        super().__init__(parent)
        groups = suggestions.get(STRAND_GROUPS_KEY, {})  # strand groups a box can add in one go
        self.tags_input = TokenInput(data.tags, suggestions.get("tags", []), "tag",
                                     groups=groups.get("tags"))
        self.characters_input = TokenInput(data.characters, suggestions.get("characters", []), "character",
                                           groups=groups.get("characters"))
        self.locations_input = TokenInput(data.locations, suggestions.get("locations", []), "location",
                                          groups=groups.get("locations"))

        self._board_characters = list(suggestions.get("characters", []))
        self.pov_combo = ScrollSafeCombo()
        self.pov_combo.setEditable(True)
        self.pov_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.pov_combo.lineEdit().setPlaceholderText("Whose point of view? (optional)")
        self.pov_combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.pov_combo.setToolTip("The point-of-view character. They're added to Characters "
                                  "if they aren't there already.")
        self._refresh_pov_choices()
        self.pov_combo.setCurrentText(data.pov)
        self._pov_characters = {c.casefold() for c in data.characters}
        self.characters_input.changed.connect(self._on_characters_changed)

        self.status_combo = ScrollSafeCombo()
        self.status_combo.setEditable(True)
        preset_keys = {s.casefold() for s in STATUS_PRESETS}
        self.status_combo.addItems(STATUS_PRESETS + [s for s in suggestions.get("status", [])
                                                     if s.casefold() not in preset_keys])
        self.status_combo.setCurrentText(data.status)
        self.notes_edit = QPlainTextEdit(data.notes)
        self.notes_edit.setFixedHeight(90)

    def add_detail_rows(self, form: QFormLayout) -> None:
        """Characters, POV, Locations, Status and Notes, in that order."""
        form.addRow("Characters", self.characters_input)
        form.addRow("POV", self.pov_combo)
        form.addRow("Locations", self.locations_input)
        form.addRow("Status", self.status_combo)
        form.addRow("Notes", self.notes_edit)

    def commit_pending(self) -> None:
        """On OK: add entries still typed in the boxes, if that setting is on."""
        if settings.get("commit_pending_entries"):
            for token_input in (self.tags_input, self.characters_input, self.locations_input):
                token_input.commit_pending()

    def values(self) -> dict:
        """The fields as entered (the caller's data class tidies them up)."""
        return {
            "tags": self.tags_input.values(),
            "characters": self.characters_input.values(),
            "pov": self.pov_combo.currentText().strip(),  # the data class adds them to characters
            "locations": self.locations_input.values(),
            "status": self.status_combo.currentText().strip(),
            "notes": self.notes_edit.toPlainText(),
        }

    # ----- POV ------------------------------------------------------------------
    def _refresh_pov_choices(self) -> None:
        """Offer this item's characters first, then the rest of the board's."""
        text = self.pov_combo.currentText()
        own = self.characters_input.values()
        keys = {c.casefold() for c in own}
        others = sorted((c for c in self._board_characters if c.casefold() not in keys),
                        key=str.casefold)
        self.pov_combo.blockSignals(True)
        self.pov_combo.clear()
        self.pov_combo.addItems([""] + own + others)
        self.pov_combo.setCurrentText(text)
        self.pov_combo.blockSignals(False)

    def _on_characters_changed(self) -> None:
        now = {c.casefold() for c in self.characters_input.values()}
        pov = self.pov_combo.currentText().strip().casefold()
        if pov and pov in self._pov_characters and pov not in now:
            # The POV character's chip was just removed: they're no longer the POV either.
            self.pov_combo.setCurrentText("")
        self._pov_characters = now
        self._refresh_pov_choices()
