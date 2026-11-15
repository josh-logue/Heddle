"""The Card panel edits the selected card in place: typing then pausing saves it as one
undo step, undo shows through, switching cards keeps what was typed, and a dialog
opened meanwhile starts from it."""
import pytest
from PySide6.QtCore import Qt

from warpingweft.model import KIND_GROUP, KIND_STRAND, CardData
from tests.conftest import wait_until


@pytest.fixture
def panel(window, qapp):
    window.card_panel._timer.setInterval(30)  # don't wait the full pause in tests
    window.card_dock.show()
    qapp.processEvents()
    return window.card_panel


def select(scene, *items):
    from PySide6.QtWidgets import QApplication
    scene.clearSelection()
    for i in items:
        i.setSelected(True)
    QApplication.processEvents()  # the panel follows once the selection burst is over


def test_it_follows_the_selection(window, panel):
    s = window.scene
    a = s.add_card(CardData(title="Arrival", description="She lands"))
    b = s.add_card(CardData(title="Second", x=400))
    select(s, a)
    assert panel.title_edit.text() == "Arrival" and panel.desc_edit.toPlainText() == "She lands"
    select(s, b)
    assert panel.title_edit.text() == "Second"
    select(s, a, b)
    assert panel.heading.text() == "2 cards selected" and panel.dialog_btn.text() == "Edit 2 Cards…"
    select(s)
    assert panel.heading.text() == "No card selected"


def test_typing_then_pausing_is_one_undo_step(window, panel, qapp):
    s = window.scene
    a = s.add_card(CardData(title="Arrival"))
    s.mark_modified()
    s.reset_history()
    select(s, a)
    panel.title_edit.setText("Arrival at the docks")
    panel.title_edit.textEdited.emit("Arrival at the docks")   # as typing does
    panel.desc_edit.setPlainText("Rain.  ")
    wait_until(lambda: a.card.title == "Arrival at the docks")
    assert a.card.description == "Rain."                       # tidied as the dialog does
    assert panel.desc_edit.toPlainText() == "Rain.  "          # ...but what you typed stays
    s.flush_history()
    assert s.undo()
    assert s.cards[a.card.id].card.title == "Arrival"
    wait_until(lambda: panel.title_edit.text() == "Arrival")  # the undo shows in the panel
    assert not s.undo()                                       # it was a single step


def test_switching_cards_keeps_what_was_typed(window, panel):
    s = window.scene
    a = s.add_card(CardData(title="A"))
    b = s.add_card(CardData(title="B", x=400))
    select(s, a)
    panel._fields.tags_input.add_value("draft")             # timer started, not yet saved
    select(s, b)
    assert a.card.tags == ["draft"]
    assert panel.title_edit.text() == "B"


def test_a_dialog_opened_meanwhile_starts_from_the_typing(window, panel, monkeypatch):
    s = window.scene
    a = s.add_card(CardData(title="A"))
    select(s, a)
    panel.title_edit.setText("Typed")
    panel.title_edit.textEdited.emit("Typed")
    seen = []
    import warpingweft.scene as sc
    monkeypatch.setattr(sc.CardDialog, "exec", lambda self: seen.append(self.title_edit.text()) or 0)
    s.edit_card(a)
    assert seen == ["Typed"] and a.card.title == "Typed"


def test_groups_and_strand_cards(window, panel):
    s = window.scene
    g = s.add_card(CardData(title="Council", kind=KIND_GROUP))
    select(s, g)
    assert panel.heading.text() == "Group" and panel.dialog_btn.text() == "Edit Group…"
    assert panel.desc_edit.parent() is None or not panel.desc_edit.isVisibleTo(panel)
    strand = s.add_card(CardData(title="Greta", kind=KIND_STRAND, strand_kind="characters", strand="Greta", x=600))
    select(s, strand)
    assert panel._fields is None and "Strands panel" in panel.message.text()


def test_a_deleted_card_empties_the_panel(window, panel):
    s = window.scene
    a = s.add_card(CardData(title="A"))
    select(s, a)
    s.remove_cards([a])
    s.mark_modified()
    assert panel.card_id is None and panel.heading.text() == "No card selected"


def wheel_over(widget, qapp, steps=-3):
    """Send a wheel event (negative steps scroll down) to the middle of `widget`;
    returns whether the widget accepted it."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(), QPoint(0, 120 * steps),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    qapp.sendEvent(widget, event)
    qapp.processEvents()
    return event.isAccepted()


def test_scrolling_over_pov_or_status_scrolls_the_panel_not_the_choice(window, panel, qapp):
    """The wheel over POV or Status used to cycle through their choices, quietly
    reassigning the card while you only meant to scroll the panel. (An editable combo
    showing a POV can sit on the blank entry, so scrolling up cleared it.)"""
    s = window.scene
    s.add_card(CardData(title="Other", characters=["Mabel", "Greta"], x=400))
    a = s.add_card(CardData(title="Arrival", characters=["Rowan"], pov="Rowan", status="Draft"))
    select(s, a)
    for combo in (panel._fields.pov_combo, panel._fields.status_combo):
        before = combo.currentText()
        for steps in (-3, 3):                # down, then up
            # Left unaccepted, a real wheel event goes on to the scroll area. (Qt doesn't
            # pass on events sent from code, so a test can't watch the panel scroll.)
            assert not wheel_over(combo, qapp, steps)
            assert combo.currentText() == before
        # ...nor does the wheel grab focus (QComboBox's default WheelFocus would).
        assert combo.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert a.card.pov == "Rowan" and a.card.status == "Draft"
