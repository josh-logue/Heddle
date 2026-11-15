"""The Card panel edits the selected card in place: typing then pausing saves it as one
undo step, undo shows through, switching cards keeps what was typed, and a dialog
opened meanwhile starts from it."""
import pytest

from warpingweft.model import KIND_GROUP, KIND_STRAND, CardData
from tests.conftest import wait_until


@pytest.fixture
def panel(window, qapp):
    window.card_panel._timer.setInterval(30)  # don't wait the full pause in tests
    window.card_dock.show()
    qapp.processEvents()
    return window.card_panel


def select(scene, *items):
    scene.clearSelection()
    for i in items:
        i.setSelected(True)


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
    s.clearSelection()
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
