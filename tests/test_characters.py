"""F3: first appearances (which characters each card introduces) and character threads."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog

from heddle.filters import collect_options, matches
from heddle.graph import StoryGraph
from heddle.model import KIND_GROUP, CardData, ConnectionData


def graph(cards, pairs):
    return StoryGraph(cards, [ConnectionData(s, t, id=f"{s}>{t}") for s, t in pairs])


def card(cid, *chars, x=0.0, y=0.0, parent="", group=False, pov=""):
    return CardData(id=cid, title=cid, characters=list(chars), x=x, y=y, parent=parent, pov=pov,
                    kind=KIND_GROUP if group else "card")


# ----- first appearances (graph) ------------------------------------------------------------
def test_introductions_along_a_chain():
    g = graph([card("A", "Rowan", x=0), card("B", "rowan", "Mabel", x=300),
               card("C", "Mabel", "Gus", x=600)], [("A", "B"), ("B", "C")])
    assert g.introductions() == {"A": ["Rowan"], "B": ["Mabel"], "C": ["Gus"]}


def test_each_branch_introduces_separately_and_a_merge_does_not():
    cards = [card("S", x=0), card("L", "Mabel", x=300, y=-200), card("R", "Mabel", x=300, y=200),
             card("M", "Mabel", x=600)]
    g = graph(cards, [("S", "L"), ("S", "R"), ("L", "M"), ("R", "M")])
    assert g.introductions() == {"L": ["Mabel"], "R": ["Mabel"]}


def test_pov_counts_as_featuring():
    g = graph([card("A", pov="Delphine", x=0), card("B", "Delphine", x=300)], [("A", "B")])
    assert g.introductions() == {"A": ["Delphine"]}


def test_loops():
    # A (X) -> B -> A: A is reached only from itself, so it still introduces X.
    g = graph([card("A", "X", x=0), card("B", x=300)], [("A", "B"), ("B", "A")])
    assert g.introductions() == {"A": ["X"]}
    # Both on the loop feature X: the one first in story order introduces them.
    g = graph([card("S", x=-300), card("A", "X", x=0), card("B", "X", x=300)],
              [("S", "A"), ("A", "B"), ("B", "A")])
    assert g.introductions() == {"A": ["X"]}
    # A card off the loop that leads into it introduces X instead.
    g = graph([card("S", "X", x=-300), card("A", "X", x=0), card("B", x=300)],
              [("S", "A"), ("A", "B"), ("B", "A")])
    assert g.introductions() == {"S": ["X"]}


def test_cards_without_arrows_introduce_nobody():
    g = graph([card("A", "Mabel"), card("B", "Gus", x=300), card("C", x=600)], [("B", "C")])
    assert g.introductions() == {"B": ["Gus"]}


def test_arrows_into_groups_carry_introductions_inside():
    cards = [card("X", "Rowan", x=-500), card("G", group=True),
             card("P", "Rowan", "Mabel", x=0, y=60, parent="G")]
    g = graph(cards, [("X", "G")])
    assert g.introductions() == {"X": ["Rowan"], "P": ["Mabel"]}


def test_featuring_in_story_order():
    cards = [card("C", "Z", x=600), card("A", "z", x=0), card("B", x=300)]
    g = graph(cards, [("A", "B"), ("B", "C")])
    assert g.featuring("Z") == ["A", "C"]
    assert g.featuring("nobody") == []


# ----- the "Introduces" filter category ------------------------------------------------------
def test_introduces_filter_category():
    cards = [CardData(id="a"), CardData(id="b"), CardData(id="c")]
    extras = {"introduces": {"a": ["Rowan", "Mabel"], "b": ["Mabel"]}}
    opts = collect_options(cards, extras)["introduces"]
    assert [(name, n) for _, name, n in opts] == [("Mabel", 2), ("Rowan", 1), ("(none)", 1)]
    assert [c.id for c in cards if matches(c, {"introduces": {"mabel"}}, extras=extras)] == ["a", "b"]


# ----- on the board ---------------------------------------------------------------------------
def board(scene):
    """Pack (Delphine) → Intro (Ailsa, Rowan) → Election (Rowan, Sable) → After (Rowan);
    plus a loose card featuring Rowan with no arrows."""
    items = {}
    for name, x, chars in (("Pack", 0, ["Delphine"]), ("Intro", 400, ["Ailsa", "Rowan"]),
                           ("Election", 800, ["Rowan", "Sable"]), ("After", 1200, ["Rowan"])):
        items[name] = scene.add_card(CardData(title=name, x=x, y=0, characters=chars))
    items["Loose"] = scene.add_card(CardData(title="Loose", x=0, y=600, characters=["Rowan"]))
    for a, b in (("Pack", "Intro"), ("Intro", "Election"), ("Election", "After")):
        scene.add_connection(items[a], items[b])
    scene.mark_modified()  # as any edit does: introductions are worked out on each change
    return items


def test_cards_show_what_they_introduce(scene):
    c = board(scene)
    assert c["Intro"].introduces == ["Ailsa", "Rowan"]
    assert c["Election"].introduces == ["Sable"] and c["After"].introduces == []
    assert c["Loose"].introduces == []
    c["Intro"].set_details_visible(True)
    texts = [t for _, t, _, _ in c["Intro"]._blocks]
    assert "INTRODUCES ★" in texts and "Ailsa, Rowan" in texts


def test_introductions_follow_edits(scene):
    c = board(scene)
    pack = c["Pack"]
    pack.card.characters.append("Rowan")
    pack.apply_data(pack.card)
    scene.mark_modified()
    assert pack.introduces == ["Delphine", "Rowan"] and c["Intro"].introduces == ["Ailsa"]


def test_introductions_are_ready_after_loading(window, tmp_path):
    from heddle.model import save_board
    board(window.scene)
    path = tmp_path / "chars.json"
    save_board(window.scene.to_board_data(), path)
    window.open_path(path)
    by = {i.card.title: i for i in window.scene.cards.values()}
    assert by["Election"].introduces == ["Sable"]
    assert window.scene.introductions[by["Intro"].card.id] == ["Ailsa", "Rowan"]


def test_filter_panel_finds_introductions(window, tick_filter):
    s = window.scene
    c = board(s)
    window.show()
    tick_filter(window, "introduces", "rowan")
    assert window._filter_state[0][:2] == (1, 5)
    assert not c["Intro"].dimmed and c["After"].dimmed


# ----- threads ------------------------------------------------------------------------------
def badges(scene):
    return {i.card.title: i.badge for i in scene.cards.values() if i.badge}


def test_thread_numbers_lights_and_joins_the_cards(scene):
    board(scene)
    label = scene.show_thread("rowan")
    assert badges(scene) == {"Intro": "1", "Election": "2", "After": "3", "Loose": "4"}
    assert {i.card.title for i in scene.cards.values() if i.highlight} == {"Intro", "Election", "After", "Loose"}
    assert scene._thread_line is not None and scene._thread_line.path().elementCount() == 4
    assert label.startswith("Thread: Rowan · 4 cards") and "introduced in “Intro”" in label
    lit_edges = {(e.source.card.title, e.target.card.title) for e in scene.edges if e.highlight}
    assert lit_edges == {("Intro", "Election"), ("Election", "After")}


def test_clearing_or_replacing_the_thread_removes_badges_and_line(window):
    s = window.scene
    c = board(s)
    s.show_thread("Rowan")
    s.clear_highlight()
    assert badges(s) == {} and s._thread_line is None
    s.show_thread("Rowan")
    s.highlight_paths(c["Pack"])                 # another highlight takes over
    assert badges(s) == {} and s._thread_line is None
    s.show_thread("Rowan")
    window.show()
    window.view.setFocus()
    QTest.keyClick(window.view.viewport(), Qt.Key.Key_Escape)
    assert badges(s) == {} and not s.has_highlight()


def test_thread_renumbers_after_edits_and_undo(scene):
    c = board(scene)
    scene.reset_history()
    scene.show_thread("Sable")
    assert badges(scene) == {"Election": "1"}
    after = c["After"]
    after.card.characters.append("Sable")
    after.apply_data(after.card)
    scene.mark_modified()
    scene.flush_history()
    assert badges(scene) == {"Election": "1", "After": "2"}
    assert scene.undo()
    assert badges(scene) == {"Election": "1"} and scene.highlight_owner() == "thread"


def test_unknown_character_has_no_thread(scene):
    board(scene)
    assert scene.show_thread("Nobody") == "" and not scene.has_highlight()


def test_ctrl_t_asks_which_character(window, monkeypatch):
    s = window.scene
    c = board(s)
    c["Election"].setSelected(True)
    asked = {}

    def fake_get_item(parent, title, label, items, current, editable):
        asked["offered"], asked["current"] = list(items), items[current]
        return "Sable", True
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(fake_get_item))
    window.act_thread.trigger()
    assert asked["current"] == "Rowan"            # the selected card's first character
    assert "Delphine" in asked["offered"]
    assert s.highlight_owner() == "thread" and badges(s) == {"Election": "1"}
