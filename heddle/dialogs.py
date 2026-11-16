"""Dialog for editing a card's contents."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from .card_item import readable_text_color
from .model import ARRANGE_WRAP_MAX, CARD_COLORS, KIND_CARD, KIND_GROUP, KIND_STRAND, CardData
from .details_form import DetailFields
from .widgets import SearchableChecklist

SWATCH_COLUMNS = 10


class ColorSwatch(QAbstractButton):
    """Round color button; the checked one gets a ring and a checkmark."""

    def __init__(self, color: str, custom: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.color_name = color
        self.custom = custom
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{color} (custom, right-click to remove)" if custom else color)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.color_name)
        outer = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        inner = outer.adjusted(4, 4, -4, -4)

        if self.isChecked():
            p.setPen(QPen(self.palette().color(QPalette.ColorRole.WindowText), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(outer)
        elif self.underMouse():
            ring = QColor(self.palette().color(QPalette.ColorRole.WindowText))
            ring.setAlpha(70)
            p.setPen(QPen(ring, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(outer)

        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.setBrush(color)
        p.drawEllipse(inner)

        if self.custom:  # small dot marks board-specific colors
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 200))
            p.drawEllipse(QPointF(inner.right() - 3, inner.top() + 3), 2.2, 2.2)

        if self.isChecked():
            c = inner.center()
            s = inner.width() / 2
            check = QPainterPath(QPointF(c.x() - s * 0.45, c.y()))
            check.lineTo(c.x() - s * 0.1, c.y() + s * 0.35)
            check.lineTo(c.x() + s * 0.5, c.y() - s * 0.35)
            p.setPen(QPen(readable_text_color(color), 2.2, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(check)


class MemberList(SearchableChecklist):
    """Searchable checklist of cards (by id) for choosing a group's contents."""

    def __init__(self, candidates: list[tuple[str, str, bool]], parent: QWidget | None = None):
        super().__init__([(label, card_id, checked) for card_id, label, checked in candidates],
                         "Filter cards…", "No other cards on this board yet",
                         lambda n, total: f"{n} of {total} in group", parent)
        self.list.setMinimumHeight(140)

    def checked_ids(self) -> list[str]:
        return self.checked_data()


class CardDialog(QDialog):
    """Edits a card. After exec(), `added_custom_colors` / `removed_custom_colors`
    describe palette changes the caller should apply to the board."""

    def __init__(self, card: CardData, custom_colors: list[str] | tuple[str, ...] = (),
                 parent: QWidget | None = None,
                 suggestions: dict[str, list[str]] | None = None,
                 member_candidates: list[tuple[str, str, bool]] | None = None,
                 color_usage: dict[str, int] | None = None):
        super().__init__(parent)
        # How many other cards / arrows use each colour: those can't leave the palette.
        self._color_usage = {k.lower(): n for k, n in (color_usage or {}).items()}
        self.setWindowTitle("Edit card")
        self.setMinimumWidth(540)
        self._card = card
        self._color = QColor(card.color).name()
        self.added_custom_colors: list[str] = []
        self.removed_custom_colors: list[str] = []
        suggestions = suggestions or {}

        self.title_edit = QLineEdit(card.title)
        # Tags, characters, POV, locations, status, notes: shared with the route editor.
        self.fields = DetailFields(card, suggestions, self)
        self.tags_input = self.fields.tags_input
        self.characters_input = self.fields.characters_input
        self.locations_input = self.fields.locations_input
        self.pov_combo = self.fields.pov_combo
        self.status_combo = self.fields.status_combo
        self.notes_edit = self.fields.notes_edit
        self.tags_input.edit.setPlaceholderText("Type a tag (e.g. Act 1, Subplot B) and press Enter")
        self.desc_edit = QPlainTextEdit(card.description)
        self.desc_edit.setPlaceholderText("What happens in this scene or beat?")
        self.desc_edit.setFixedHeight(110)

        self.card_radio = QRadioButton("Card")
        self.group_radio = QRadioButton("Group")
        self.strand_radio = QRadioButton("Strand")
        self.strand_radio.setToolTip("Stands for a character, location, tag or status: shows its "
                                     "name, and its description (from Strands) in its details")
        self.card_radio.setToolTip("A single scene or story beat")
        self.group_radio.setToolTip("A container that other cards sit on top of")
        kind_group = QButtonGroup(self)
        kind_group.addButton(self.card_radio)
        kind_group.addButton(self.group_radio)
        kind_group.addButton(self.strand_radio)
        {KIND_GROUP: self.group_radio, KIND_STRAND: self.strand_radio}.get(
            card.kind, self.card_radio).setChecked(True)
        kind_row = QWidget()
        kh = QHBoxLayout(kind_row)
        kh.setContentsMargins(0, 0, 0, 0)
        kh.addWidget(self.card_radio)
        kh.addWidget(self.group_radio)
        kh.addWidget(self.strand_radio)
        kh.addStretch()

        self.arrange_requested = False
        self.members = MemberList(member_candidates or [])
        self.members_box = QGroupBox("Cards in this group")
        mv = QVBoxLayout(self.members_box)
        mv.addWidget(self.members)
        arrange_btn = QPushButton("Save && auto-arrange")
        arrange_btn.setAutoDefault(False)
        arrange_btn.setToolTip("Save, then lay the cards out by their arrows: each chain in a "
                               "left-to-right line, separate chains stacked, frame fitted around them")
        arrange_btn.clicked.connect(self._accept_and_arrange)
        self.by_color_check = QCheckBox("Rows by color")
        self.by_color_check.setChecked(card.arrange_by_color)
        self.by_color_check.setToolTip("When auto-arranging, give each card color its own row "
                                       "while keeping arrow order left-to-right")
        self.vertical_check = QCheckBox("Top to bottom")
        self.vertical_check.setChecked(card.arrange_vertical)
        self.vertical_check.setToolTip("When auto-arranging, run chains downward instead of "
                                       "left-to-right (separate chains become columns)")
        self.grid_check = QCheckBox("Grid")
        self.grid_check.setChecked(card.arrange_grid)
        self.grid_check.setToolTip("When auto-arranging, wrap cards that have no arrows into a "
                                   "grid instead of a single row (or column, top to bottom)")
        # The row limit: a long chain carries on in a new row after this many steps.
        self.wrap_spin = QSpinBox()
        self.wrap_spin.setRange(0, ARRANGE_WRAP_MAX)
        self.wrap_spin.setSpecialValueText("No limit")
        self.wrap_spin.setPrefix("Wrap after ")
        self.wrap_spin.setSuffix(" steps")
        self.wrap_spin.setValue(card.arrange_wrap)
        self.wrap_spin.setToolTip("When auto-arranging, start a new row after this many steps "
                                  "(a new column, top to bottom), back at the left. Cards side by "
                                  "side at one step count once. Cards with no arrows wrap too")
        arrange_row = QHBoxLayout()
        arrange_row.addWidget(self.by_color_check)
        arrange_row.addWidget(self.vertical_check)
        arrange_row.addWidget(self.grid_check)
        arrange_row.addWidget(self.wrap_spin)
        arrange_row.addStretch()
        arrange_row.addWidget(arrange_btn)
        mv.addLayout(arrange_row)

        form = QFormLayout()
        self._form = form
        form.addRow("Type", kind_row)
        # Strand cards: which strand it stands for (an existing one, or type a new one).
        self._strand_suggestions = suggestions
        self.strand_kind_combo = QComboBox()
        for key, label in (("characters", "Character"), ("locations", "Location"),
                           ("tags", "Tag"), ("status", "Status")):
            self.strand_kind_combo.addItem(label, key)
        self.strand_kind_combo.setCurrentIndex(max(0, self.strand_kind_combo.findData(
            card.strand_kind or "characters")))
        self.strand_name_combo = QComboBox()
        self.strand_name_combo.setEditable(True)
        self.strand_name_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.strand_name_combo.lineEdit().setPlaceholderText("Pick one, or type a new one")
        self.strand_name_combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._fill_strand_names()
        self.strand_name_combo.setCurrentText(card.strand)
        self.strand_kind_combo.currentIndexChanged.connect(lambda _: self._fill_strand_names())
        strand_row = QWidget()
        sh = QHBoxLayout(strand_row)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.addWidget(self.strand_kind_combo)
        sh.addWidget(self.strand_name_combo, 1)
        self.strand_row = strand_row
        form.addRow("Strand", strand_row)
        form.addRow("Title", self.title_edit)
        form.addRow("Tags", self.tags_input)
        form.addRow("Color", self._build_color_picker(custom_colors))
        form.addRow("Description", self.desc_edit)
        self.outside_check = QCheckBox("Not part of the story")
        self.outside_check.setChecked(card.outside_story)
        self.outside_check.setToolTip(
            "Leave it out of story checks, routes, character introductions and threads (a "
            "group: with everything in it). For notes or reference cards. Its arrows still "
            "show, but don't count.")
        form.addRow("Story", self.outside_check)

        details = QGroupBox("Details (hidden on the card until you click its ▸ toggle)")
        self.fields.add_detail_rows(QFormLayout(details))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.members_box)
        layout.addWidget(details)
        layout.addWidget(buttons)
        self.details_box = details
        self._story_tools = True

        self.group_radio.toggled.connect(self._on_kind_changed)
        self.strand_radio.toggled.connect(self._on_kind_changed)
        self._on_kind_changed()
        self.title_edit.selectAll()
        self.title_edit.setFocus()

    def is_group(self) -> bool:
        return self.group_radio.isChecked()

    def is_strand(self) -> bool:
        return self.strand_radio.isChecked()

    def _fill_strand_names(self) -> None:
        """Offer the board's strands of the chosen kind."""
        text = self.strand_name_combo.currentText()
        kind = self.strand_kind_combo.currentData()
        self.strand_name_combo.blockSignals(True)
        self.strand_name_combo.clear()
        self.strand_name_combo.addItems(sorted(self._strand_suggestions.get(kind, []), key=str.casefold))
        self.strand_name_combo.setCurrentText(text)
        self.strand_name_combo.blockSignals(False)

    def _on_kind_changed(self, *_args) -> None:
        group, strand = self.is_group(), self.is_strand()
        # A strand card is just its strand's name: no title, tags, text or details of its own.
        self._form.setRowVisible(self.strand_row, strand)
        for widget in (self.title_edit, self.tags_input):
            self._form.setRowVisible(widget, not strand)
        self._form.setRowVisible(self.desc_edit, not (group or strand))
        self._form.setRowVisible(self.outside_check, self._story_tools and not strand)
        self.details_box.setVisible(not strand)
        self.members_box.setVisible(group)
        self.setWindowTitle("Edit group" if group else "Edit strand card" if strand else "Edit card")
        if strand:
            self.strand_name_combo.setFocus()
        self.adjustSize()

    def set_story_tools(self, on: bool) -> None:
        """The board's story tools are off: the Story row means nothing then."""
        self._story_tools = on
        self._form.setRowVisible(self.outside_check, on and not self.is_strand())

    def member_ids(self) -> list[str]:
        return self.members.checked_ids()

    def _accept_and_arrange(self) -> None:
        self.arrange_requested = True
        self.accept()

    def accept(self) -> None:
        self.fields.commit_pending()
        super().accept()

    # ----- color picker -----------------------------------------------------
    def _build_color_picker(self, custom_colors) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._swatches: list[ColorSwatch] = []
        self._grid = QGridLayout()
        self._grid.setSpacing(2)
        self._grid.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self._grid)

        bottom = QHBoxLayout()
        self._color_label = QLabel()
        custom_btn = QPushButton("Custom color…")
        custom_btn.clicked.connect(self._pick_custom_color)
        bottom.addWidget(self._color_label)
        bottom.addStretch()
        bottom.addWidget(custom_btn)
        v.addLayout(bottom)

        for c in CARD_COLORS:
            self._add_swatch(c, custom=False)
        for c in custom_colors:
            self._add_swatch(QColor(c).name(), custom=True)
        if self._find_swatch(self._color) is None:
            # Card uses a color not in the palette (e.g. from an older file): offer it.
            self._add_swatch(self._color, custom=True)
            self.added_custom_colors.append(self._color)
        self._select(self._color)
        return box

    def _find_swatch(self, color: str) -> ColorSwatch | None:
        return next((s for s in self._swatches if s.color_name == color), None)

    def _add_swatch(self, color: str, custom: bool) -> ColorSwatch:
        sw = ColorSwatch(color, custom, self)
        sw.clicked.connect(lambda _=False, c=color: self._select(c))
        if custom:
            sw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            sw.customContextMenuRequested.connect(lambda pos, s=sw: self._swatch_menu(s, pos))
        self._group.addButton(sw)
        self._swatches.append(sw)
        self._layout_swatches()
        return sw

    def _layout_swatches(self) -> None:
        for i, sw in enumerate(self._swatches):
            self._grid.addWidget(sw, i // SWATCH_COLUMNS, i % SWATCH_COLUMNS)
        self._grid.setColumnStretch(SWATCH_COLUMNS, 1)

    def _select(self, color: str) -> None:
        self._color = color
        sw = self._find_swatch(color)
        if sw is not None:
            sw.setChecked(True)
        self._color_label.setText(f"Selected: <b>{color}</b>")

    def _pick_custom_color(self) -> None:
        picked = QColorDialog.getColor(QColor(self._color), self, "Custom card color")
        if not picked.isValid():
            return
        name = picked.name()
        if self._find_swatch(name) is None:
            self._add_swatch(name, custom=True)
            if name in self.removed_custom_colors:
                self.removed_custom_colors.remove(name)
            else:
                self.added_custom_colors.append(name)
        self._select(name)

    def _swatch_menu(self, sw: ColorSwatch, pos) -> None:
        menu = QMenu(self)
        allowed, text = self.removal_state(sw.color_name)
        act = menu.addAction(text)
        act.setEnabled(allowed)
        if menu.exec(sw.mapToGlobal(pos)) is act:
            self._remove_swatch(sw)

    def removal_state(self, color: str) -> tuple[bool, str]:
        """Can this custom colour leave the palette, and what the menu should say."""
        others = self._color_usage.get(color.lower(), 0)
        if others:
            # Taking it off the palette wouldn't change those cards, and editing one of
            # them would only put it back: keep it while anything uses it.
            noun = "other card or arrow" if others == 1 else "other cards and arrows"
            return False, f"Can't remove: used by {others} {noun}"
        if color == self._color:
            return False, "Remove from palette (pick another color first)"
        return True, "Remove from this board's palette"

    def _remove_swatch(self, sw: ColorSwatch) -> None:
        self._group.removeButton(sw)
        self._swatches.remove(sw)
        self._grid.removeWidget(sw)
        sw.deleteLater()
        self._layout_swatches()
        if sw.color_name in self.added_custom_colors:
            self.added_custom_colors.remove(sw.color_name)
        else:
            self.removed_custom_colors.append(sw.color_name)

    # ----- result -----------------------------------------------------------
    def result_data(self) -> CardData:
        if self.is_strand():
            name = self.strand_name_combo.currentText().strip() or self.title_edit.text().strip()
            return replace(self._card, kind=KIND_STRAND, strand_kind=self.strand_kind_combo.currentData(),
                           strand=name, title=name, color=self._color)
        return replace(
            self._card,
            kind=KIND_GROUP if self.is_group() else KIND_CARD,
            arrange_by_color=self.by_color_check.isChecked(),
            arrange_vertical=self.vertical_check.isChecked(),
            arrange_grid=self.grid_check.isChecked(),
            arrange_wrap=self.wrap_spin.value(),
            title=self.title_edit.text().strip() or "Untitled",
            color=self._color,
            description=self.desc_edit.toPlainText().strip(),
            outside_story=self.outside_check.isChecked(),
            **{**self.fields.values(), "notes": self.notes_edit.toPlainText().strip()},
        )
