"""Efficiency review, stage B: selecting everything is one selection change, the Card
panel catches up once after a burst of selection changes (it used to rescan the whole
selection and rebuild for every card), a burst of nudges signals one change until it
settles, and a route's key is worked out once."""
from conftest import wait_until
from warpingweft.graph import Route
from warpingweft.model import KIND_GROUP, CardData


def test_select_all_is_one_selection_change(window, qapp):
    s = window.scene
    cards = [s.add_card(CardData(title=f"C{i}", x=i * 400)) for i in range(6)]
    for a, b in zip(cards, cards[1:]):
        s.add_connection(a, b)
    g = s.add_card(CardData(title="Folded", kind=KIND_GROUP, x=0, y=600))
    inside = s.add_card(CardData(title="Inside", parent=g.card.id, x=20, y=660))
    s.set_collapsed([g], True)
    qapp.processEvents()
    changes = []
    s.selectionChanged.connect(lambda: changes.append(1))
    window._select_all()
    assert len(changes) == 1                                   # was one per card and arrow
    selected = set(s.selectedItems())
    assert selected == {*cards, g, *s.edges}
    assert not inside.isSelected()                             # folded away: not selectable


def test_card_panel_catches_up_once_after_a_burst_of_selection_changes(window, qapp, monkeypatch):
    s, panel = window.scene, window.card_panel
    window.card_dock.show()
    cards = [s.add_card(CardData(title=f"C{i}", x=i * 300)) for i in range(20)]
    qapp.processEvents()
    rebuilds = []
    real = panel._rebuild
    monkeypatch.setattr(panel, "_rebuild", lambda: rebuilds.append(1) or real())
    for c in cards:
        c.setSelected(True)
    qapp.processEvents()
    assert len(rebuilds) == 1                                  # was 20
    assert panel.heading.text() == "20 cards selected"


def test_typing_is_kept_when_the_selection_moves_on_before_the_panel_catches_up(window, qapp):
    s, panel = window.scene, window.card_panel
    window.card_dock.show()
    a = s.add_card(CardData(title="A"))
    b = s.add_card(CardData(title="B", x=400))
    a.setSelected(True)
    qapp.processEvents()
    panel.title_edit.setText("A typed")
    panel.title_edit.textEdited.emit("A typed")                 # as typing does
    s.clearSelection()
    b.setSelected(True)                                         # no events in between
    assert a.card.title == "A typed"
    qapp.processEvents()
    assert panel.title_edit.text() == "B"


def test_a_burst_of_nudges_signals_one_change_until_it_settles(scene, qapp):
    scene._nudge_timer.setInterval(40)    # don't wait the full pause in tests
    a = scene.add_card(CardData(title="A"))
    a.setSelected(True)
    qapp.processEvents()
    changes = []
    scene.modified.connect(lambda: changes.append(1))
    for _ in range(5):
        scene.nudge_selected(10, 0)
    assert len(changes) == 1                                   # was one per step
    wait_until(lambda: len(changes) == 2)                      # the burst settles: one more
    assert scene.history.can_undo() and not scene.is_moving()


def test_a_routes_key_is_worked_out_once():
    route = Route(stops=(("a",), ("c", "b"), ("d",)))
    assert route.key == ("a", "b+c", "d")
    assert route.key is route.key
    assert route == Route(stops=(("a",), ("c", "b"), ("d",)))  # equality ignores the cached key
