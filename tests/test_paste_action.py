"""Edit → Paste / Ctrl+V: the menu action passes Qt's "checked" flag (False), which
must not be taken for a paste position (it used to raise AttributeError)."""
import sys

from warpingweft.model import CardData


def test_copy_and_paste_several_cards_through_the_actions(window, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    s = window.scene
    cards = [s.add_card(CardData(title=f"C{n}", x=n * 260)) for n in range(5)]
    s.mark_modified()
    window.show()
    qapp.processEvents()
    for c in cards:
        c.setSelected(True)
    window.focus_canvas()
    window.act_copy.trigger()
    window.act_paste.trigger()                     # what Ctrl+V / Edit → Paste does
    qapp.processEvents()
    assert errors == []
    assert len(s.cards) == 10
    pasted = [i for i in s.cards.values() if i.isSelected()]
    assert sorted(i.card.title for i in pasted) == [f"C{n}" for n in range(5)]
    assert not {i.card.id for i in pasted} & {c.card.id for c in cards}


def test_paste_ignores_anything_that_isnt_a_position(window):
    s = window.scene
    s.add_card(CardData(title="A")).setSelected(True)
    window.copy()
    assert window.paste(False) == 1                # (a stray "checked" flag)
