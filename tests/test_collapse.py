"""Collapsed groups: folded to their title bar, their cards hidden but kept in place.
Arrows to hidden cards meet the folded frame (several at once drawn as one, ×N), the
story tools don't change, it's undoable and saved, and finding a hidden card unfolds
its group."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from heddle.model import KIND_CARD, KIND_GROUP, BoardData, CardData, load_board, save_board
from heddle.scene import BoardScene


def board() -> BoardScene:
    """Year (group) holds a, b and Inner (group) holding c; x and y are outside."""
    cards = [
        CardData(id="Y", title="Year", kind=KIND_GROUP, x=0, y=0),
        CardData(id="a", title="a", parent="Y", x=20, y=60),
        CardData(id="b", title="b", parent="Y", x=320, y=60),
        CardData(id="I", title="Inner", kind=KIND_GROUP, parent="Y", x=20, y=300),
        CardData(id="c", title="c", parent="I", x=40, y=360),
        CardData(id="x", title="x", x=1200, y=60),
        CardData(id="y", title="y", x=1200, y=400),
    ]
    s = BoardScene()
    s.load_board_data(BoardData(cards=cards))
    for src, dst in (("x", "a"), ("x", "b"), ("a", "b"), ("c", "y")):
        s.add_connection(s.cards[src], s.cards[dst])
    s.mark_modified()
    s.reset_history()
    return s


def edge(s, src, dst):
    return next(e for e in s.edges if e.source.card.id == src and e.target.card.id == dst)


def test_collapsing_hides_the_cards_and_folds_the_frame(qapp):
    s = board()
    y = s.cards["Y"]
    open_height = y.card_scene_rect().height()
    positions = {i: s.cards[i].pos() for i in "abcI"}
    assert s.set_collapsed([y], True)
    assert y.card.collapsed
    assert not any(s.cards[i].isVisible() for i in "abcI")
    assert y.card_scene_rect().height() < open_height / 3
    assert {i: s.cards[i].pos() for i in "abcI"} == positions    # kept in place
    s.set_collapsed([y], False)
    assert all(s.cards[i].isVisible() for i in "abcI")
    assert y.card_scene_rect().height() == open_height


def test_arrows_meet_the_folded_frame_and_merge(qapp):
    s = board()
    y = s.cards["Y"]
    s.set_collapsed([y], True)
    xa, xb, ab, cy = edge(s, "x", "a"), edge(s, "x", "b"), edge(s, "a", "b"), edge(s, "c", "y")
    assert xa.ends() == (s.cards["x"], y) and xb.ends() == (s.cards["x"], y)
    assert [e.isVisible() for e in (xa, xb)].count(True) == 1         # drawn once...
    shown = xa if xa.isVisible() else xb
    assert shown.merged == 2 and shown._label_text == "×2"            # ...marked ×2
    assert not ab.isVisible()                                         # both ends folded in
    assert cy.isVisible() and cy.ends() == (y, s.cards["y"])          # outermost fold
    assert y.card_scene_rect().adjusted(-2, -2, 2, 2).contains(cy._line.pointAtPercent(0))
    s.set_collapsed([y], False)
    assert all(e.isVisible() and e.merged == 0 for e in (xa, xb, ab, cy))


def test_story_tools_are_unchanged(qapp):
    s = board()
    before = (dict(s.story_graph().succ), s.introductions)
    s.set_collapsed([s.cards["Y"]], True)
    s._graph = None
    assert (dict(s.story_graph().succ), s.introductions) == before


def test_collapsing_is_one_undo_step_and_is_saved(qapp, tmp_path):
    s = board()
    s.set_collapsed([s.cards["Y"]], True)
    s.flush_history()
    path = tmp_path / "folded.json"
    save_board(s.to_board_data(), path)
    loaded = BoardScene()
    loaded.load_board_data(load_board(path))
    assert loaded.cards["Y"].card.collapsed and not loaded.cards["a"].isVisible()
    assert s.undo()
    assert not s.cards["Y"].card.collapsed and s.cards["a"].isVisible()
    assert s.redo()
    assert s.cards["Y"].card.collapsed and not s.cards["a"].isVisible()   # rebuilt cards too


def test_nested_folds_stay_folded_when_the_outer_one_opens(qapp):
    s = board()
    s.set_collapsed([s.cards["I"]], True)
    s.set_collapsed([s.cards["Y"]], True)
    s.set_collapsed([s.cards["Y"]], False)
    assert s.cards["I"].isVisible() and not s.cards["c"].isVisible()
    assert edge(s, "c", "y").ends()[0] is s.cards["I"]


def test_revealing_a_hidden_card_unfolds_every_group_around_it(qapp):
    s = board()
    s.set_collapsed([s.cards["I"], s.cards["Y"]], True)
    assert s.reveal([s.cards["c"]])
    assert s.cards["c"].isVisible() and not s.cards["Y"].card.collapsed
    assert not s.reveal([s.cards["c"]])


def test_search_hits_show_on_the_fold_and_jumping_unfolds(window, qapp):
    s = window.scene
    g = s.add_card(CardData(title="Year", kind=KIND_GROUP))
    for n, title in enumerate(("Warden", "Warden of arms", "Treasurer")):
        s.add_card(CardData(title=title, x=40 + n * 300, y=80, parent=g.card.id))
    s._refit_ids({g.card.id})
    s.set_collapsed([g], True)
    matches = window._search_matches.__func__  # (bound below, with the query set)
    window.search_bar.edit.blockSignals(True)
    window.search_bar.edit.setText("Warden")
    window.search_bar.edit.blockSignals(False)
    s.set_search_hits({m[0].card.id for m in matches(window)})
    assert g.search_hits == 2 and g.card.collapsed            # "3 cards · 2 found"
    window._search_step(1)                                    # Enter: jump to a match
    assert not g.card.collapsed
    s.set_search_hits(set())
    assert g.search_hits == 0


def test_dropping_onto_a_folded_group_tucks_the_card_away(qapp):
    s = board()
    y = s.cards["Y"]
    s.set_collapsed([y], True)
    frame = y.card_scene_rect()
    newcomer = s.add_card(CardData(title="new", x=frame.left() + 40, y=frame.top()))
    s.handle_drop(newcomer, frame.center())
    assert newcomer.card.parent == "Y" and not newcomer.isVisible()
    assert y.card_scene_rect().topLeft() == frame.topLeft()           # the fold doesn't jump
    s.set_collapsed([y], False)
    assert y.body_scene_rect().contains(newcomer.card_scene_rect())


def test_a_folded_group_turned_into_a_card_shows_its_cards(qapp):
    s = board()
    y = s.cards["Y"]
    s.set_collapsed([y], True)
    from dataclasses import replace
    s.release_members(y)
    y.apply_data(replace(y.card, kind=KIND_CARD))
    assert not y.card.collapsed
    assert all(s.cards[i].isVisible() for i in "abI")


def test_clicking_the_fold_button(window, qapp):
    s = window.scene
    window.resize(1400, 900)
    window.show()
    g = s.add_card(CardData(title="Year", kind=KIND_GROUP))
    s.add_card(CardData(title="a", x=40, y=80, parent=g.card.id))
    s._refit_ids({g.card.id})
    window.view.centerOn(g)
    qapp.processEvents()
    spot = window.view.mapFromScene(g.mapToScene(g.fold_rect().center()))
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot)
    assert g.card.collapsed
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot)
    assert not g.card.collapsed
