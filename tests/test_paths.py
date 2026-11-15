"""F2: path highlighting (H, menus, follow-selection) and the Path Reader."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from warpingweft.model import KIND_GROUP, CardData
from warpingweft.path_reader import OWNER


def story(scene):
    """A → B, then a branch: B → C ("if she refuses"), B → D ("if she agrees");
    C → E and D → E; plus an unrelated card Z."""
    cards = {}
    for name, x, y in (("A", 0, 0), ("B", 400, 0), ("C", 800, -200), ("D", 800, 200),
                       ("E", 1200, 0), ("Z", 0, 800)):
        cards[name] = scene.add_card(CardData(title=name, x=x, y=y))
    for a, b, label in (("A", "B", ""), ("B", "C", "if she refuses"), ("B", "D", "if she agrees"),
                        ("C", "E", ""), ("D", "E", "")):
        scene.add_connection(cards[a], cards[b], label)
    return cards


def lit(scene):
    return {i.card.title for i in scene.cards.values() if i.highlight}


# ----- highlighting -------------------------------------------------------------------------
def test_highlight_paths_before_after_and_both(scene):
    c = story(scene)
    label = scene.highlight_paths(c["C"])
    assert lit(scene) == {"A", "B", "C", "E"}
    assert "2 before, 1 after" in label and "“C”" in label
    lit_edges = {(e.source.card.title, e.target.card.title) for e in scene.edges if e.highlight}
    assert lit_edges == {("A", "B"), ("B", "C"), ("C", "E")}
    scene.highlight_paths(c["C"], "before")
    assert lit(scene) == {"A", "B", "C"}
    scene.highlight_paths(c["C"], "after")
    assert lit(scene) == {"C", "E"}
    assert scene.highlight_owner() == "paths"


def test_highlight_paths_of_a_group_includes_its_cards(scene):
    x = scene.add_card(CardData(title="X", x=-500, y=0))
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP))
    scene.add_card(CardData(title="P", x=0, y=60, parent=g.card.id))
    y = scene.add_card(CardData(title="Y", x=800, y=0))
    scene.add_card(CardData(title="Z", x=0, y=800))
    scene._refit_ids({g.card.id})
    scene.add_connection(x, g)
    scene.add_connection(g, y)
    label = scene.highlight_paths(g)
    assert lit(scene) == {"X", "G", "P", "Y"}
    assert "1 before, 1 after" in label


def test_h_toggles_paths_for_the_selected_card(window):
    s = window.scene
    c = story(s)
    window.act_paths.trigger()                 # nothing selected
    assert not s.has_highlight()
    c["B"].setSelected(True)
    window.act_paths.trigger()
    assert s.highlight_owner() == "paths" and "“B”" in s.highlight_label()
    window.act_paths.trigger()                 # again: off
    assert not s.has_highlight()


def test_follow_selection_mode(window):
    s = window.scene
    c = story(s)
    window.act_follow_paths.setChecked(True)
    c["D"].setSelected(True)
    assert lit(s) == {"A", "B", "D", "E"}
    s.clearSelection()
    assert not s.has_highlight()
    window.act_follow_paths.setChecked(False)
    c["D"].setSelected(True)
    assert not s.has_highlight()


# ----- the path reader ------------------------------------------------------------------------
def test_reading_follows_arrows_branches_and_back(window):
    s, r = window.scene, window.path_reader
    c = story(s)
    window.read_from(c["A"])
    assert not window.reader_dock.isHidden()            # the panel was opened
    assert r.route == [c["A"].card.id] and c["A"].isSelected()
    assert r.next()                                     # A → B: one way on
    assert r.route[-1] == c["B"].card.id and c["B"].isSelected()
    options = r.choices()
    assert [(s.cards[i].card.title, label) for i, label in options] == [
        ("C", "if she refuses"), ("D", "if she agrees")]   # top to bottom
    assert not r.next()                                 # a branch: Next alone can't choose
    assert "branches" in r.end_label.text()
    assert r.choose(1)
    assert r.route[-1] == c["D"].card.id and "if she agrees" in r.via_label.text()
    assert r.next() and r.route[-1] == c["E"].card.id
    assert "end of this path" in r.end_label.text() and r.choices() == []
    assert r.back() and r.route[-1] == c["D"].card.id   # retraces the route taken
    r.restart()
    assert r.route == [c["A"].card.id]


def test_reader_highlights_the_route_and_its_arrows(scene, window):
    s, r = window.scene, window.path_reader
    c = story(s)
    window.read_from(c["A"])
    r.next()
    r.choose(0)
    assert s.highlight_owner() == OWNER and lit(s) == {"A", "B", "C"}
    lit_edges = {(e.source.card.title, e.target.card.title) for e in s.edges if e.highlight}
    assert lit_edges == {("A", "B"), ("B", "C")}
    assert s._highlight[2] == c["C"].card.id   # the current card is the focus


def test_reader_marks_visited_cards_in_a_loop(window):
    s, r = window.scene, window.path_reader
    a = s.add_card(CardData(title="A"))
    b = s.add_card(CardData(title="B", x=400))
    s.add_connection(a, b)
    s.add_connection(b, a, "again")
    window.read_from(a)
    r.next()
    texts = [b.text() for b in r._choice_buttons]
    assert texts == ["“again” → A  (visited)"]


def test_reading_a_group_offers_its_first_cards(window):
    s, r = window.scene, window.path_reader
    g = s.add_card(CardData(title="G", kind=KIND_GROUP))
    p = s.add_card(CardData(title="P", x=0, y=60, parent=g.card.id))
    q = s.add_card(CardData(title="Q", x=0, y=300, parent=g.card.id))
    s._refit_ids({g.card.id})
    window.read_from(g)
    assert r.route == [] and [s.cards[i].card.title for i, _ in r.choices()] == ["P", "Q"]
    r.choose(1)
    assert r.route == [q.card.id]
    assert r.back() and r.route == []                  # back to the choice of first card
    s.add_connection(g, p)                             # mark P as the first card
    window.read_from(g)
    assert r.route == [p.card.id]                      # only one: starts there


def test_keyboard_in_the_reader(window, qapp):
    s, r = window.scene, window.path_reader
    c = story(s)
    window.show()
    window.read_from(c["A"])
    QTest.keyClick(r, Qt.Key.Key_Right)
    QTest.keyClick(r, Qt.Key.Key_2)
    assert r.route[-1] == c["D"].card.id
    QTest.keyClick(r, Qt.Key.Key_Backspace)
    assert r.route[-1] == c["B"].card.id


def test_deleting_a_card_on_the_route_trims_it(window):
    s, r = window.scene, window.path_reader
    c = story(s)
    window.read_from(c["A"])
    r.next()
    r.choose(0)
    s.remove_card(c["C"])
    s.mark_modified()
    assert r.route == [c["A"].card.id, c["B"].card.id]
    s.remove_card(c["A"])
    s.mark_modified()
    assert r.route == []


def test_closing_the_reader_ends_its_highlight_but_not_others(window, qapp):
    s, r = window.scene, window.path_reader
    c = story(s)
    window.show()
    window.read_from(c["A"])
    assert s.highlight_owner() == OWNER
    window.reader_dock.close()
    qapp.processEvents()
    assert not s.has_highlight() and r.route == []
    s.highlight_paths(c["B"])
    window.read_from(c["A"])
    window.reader_dock.close()
    qapp.processEvents()
    assert not s.has_highlight()   # reading replaced the paths highlight, then ended


def test_card_menu_signal_and_new_board_stop_reading(window):
    s, r = window.scene, window.path_reader
    c = story(s)
    s.read_requested.emit(c["B"])
    assert r.route == [c["B"].card.id]
    window.new_board()
    assert r.route == [] and not s.has_highlight()
