"""File format v3 (POV, arrow style/color, board display options) and the
highlight layer that path, thread and check features draw with."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from warpingweft.card_item import DIMMED_OPACITY
from warpingweft.model import (
    DISPLAY_DEFAULTS, FORMAT_VERSION, KIND_GROUP, BoardData, CardData, ConnectionData,
    clone_fragment, save_board,
)


# ----- file format v3 -----------------------------------------------------------------
def test_v3_fields_round_trip():
    board = BoardData(
        cards=[CardData(id="a", pov="Rowan", characters=["Mabel"]), CardData(id="b")],
        connections=[ConnectionData("a", "b", "flashback", style="dashed", color="#B8475B")],
        display={"show_pov": False, "show_characters": True, "arrow_routing": "curved"})
    raw = board.to_dict()
    assert raw["version"] == FORMAT_VERSION == 12
    back = BoardData.from_dict(raw)
    assert back.cards[0].pov == "Rowan" and back.cards[0].characters == ["Mabel", "Rowan"]
    e = back.connections[0]
    assert (e.style, e.color, e.label) == ("dashed", "#b8475b", "flashback")
    assert back.display == {**DISPLAY_DEFAULTS,  # options added later get their defaults
                            "show_pov": False, "show_characters": True, "arrow_routing": "curved"}


def test_v2_file_loads_with_defaults():
    raw = {"app": "StoryBoard", "version": 2, "cards": [{"id": "a"}, {"id": "b"}],
           "connections": [{"source": "a", "target": "b", "label": "x", "id": "c1"}]}
    board = BoardData.from_dict(raw)
    assert board.cards[0].pov == ""
    assert (board.connections[0].style, board.connections[0].color) == ("solid", "")
    assert board.display == DISPLAY_DEFAULTS
    assert board.source_version == 2 and not board.from_newer_version


def test_bad_v3_values_are_cleaned():
    raw = {"version": 3, "cards": [{"id": "a", "pov": 7, "characters": ["rowan"]},
                                   {"id": "b", "pov": " Rowan ", "characters": ["rowan"]}],
           "connections": [{"source": "a", "target": "b", "style": "wavy", "color": "red"}],
           "display": {"show_pov": "yes", "arrow_routing": "zigzag", "extra": 1}}
    board = BoardData.from_dict(raw)
    assert board.cards[0].pov == "7"                 # numbers become text, like other fields
    assert board.cards[1].pov == "rowan"             # one spelling, the card's own
    assert board.cards[1].characters == ["rowan"]
    assert (board.connections[0].style, board.connections[0].color) == ("solid", "")
    assert board.display == DISPLAY_DEFAULTS


def test_newer_version_is_noticed():
    board = BoardData.from_dict({"version": FORMAT_VERSION + 1, "cards": []})
    assert board.from_newer_version
    assert BoardData.from_dict({"cards": []}).source_version == 1  # no version: v1


def test_copy_keeps_arrow_style():
    frag = BoardData(cards=[CardData(id="a"), CardData(id="b")],
                     connections=[ConnectionData("a", "b", "x", style="dotted", color="#3f9e6e")])
    out = clone_fragment(frag)
    e = out.connections[0]
    assert (e.style, e.color, e.label) == ("dotted", "#3f9e6e", "x")
    assert e.id != frag.connections[0].id and e.source == out.cards[0].id


def test_scene_keeps_styles_through_undo_reverse_paste_and_reload(window, tmp_path):
    s = window.scene
    a, b = s.add_card(CardData(title="A")), s.add_card(CardData(title="B", x=500))
    edge = s.add_connection(a, b, "then")
    s.reset_history()
    edge.conn.style, edge.conn.color = "dashed", "#b8475b"
    s.display["arrow_routing"] = "curved"
    s.mark_modified()
    s.flush_history()

    s.reverse_edge(s.edges[0])
    s.flush_history()
    e = s.edges[0]
    assert (e.source, e.target) == (b, a)
    assert (e.conn.id, e.conn.style, e.conn.color, e.conn.label) == (edge.conn.id, "dashed", "#b8475b", "then")

    assert s.undo() and s.undo()  # back past the reverse and the style change
    e = s.edges[0]
    assert (e.conn.style, e.conn.color) == ("solid", "") and s.display["arrow_routing"] == "straight"
    assert s.redo()
    assert s.edges[0].conn.style == "dashed" and s.display["arrow_routing"] == "curved"

    path = tmp_path / "b.json"
    save_board(s.to_board_data(), path)
    window.open_path(path)
    assert window.scene.edges[0].conn.style == "dashed"
    assert window.scene.display["arrow_routing"] == "curved"

    # Copy + paste both cards: the pasted arrow keeps its style.
    for c in window.scene.cards.values():
        c.setSelected(True)
    frag = window.scene.selection_fragment()
    window.scene.paste_fragment(frag, QPointF(0, 600))
    assert [x.conn.style for x in window.scene.edges] == ["dashed", "dashed"]


def test_new_board_resets_display_options(window):
    window.scene.display["show_characters"] = True
    window.new_board()
    assert window.scene.display == DISPLAY_DEFAULTS


def test_opening_a_newer_board_warns(window, tmp_path, monkeypatch):
    path = tmp_path / "future.json"
    raw = BoardData(cards=[CardData(title="A")]).to_dict()
    raw["version"] = FORMAT_VERSION + 1
    import json
    path.write_text(json.dumps(raw), encoding="utf-8")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    window.open_path(path)
    assert len(window.scene.cards) == 1 and warned and "newer version" in warned[0]


# ----- highlight layer ----------------------------------------------------------------
def board_with_group(s):
    """X -> [G: P -> Q] -> Y, plus an unrelated card Z."""
    x = s.add_card(CardData(title="X", x=-400, y=0))
    g = s.add_card(CardData(title="G", kind=KIND_GROUP))
    p = s.add_card(CardData(title="P", x=0, y=60, parent=g.card.id))
    q = s.add_card(CardData(title="Q", x=300, y=60, parent=g.card.id))
    y = s.add_card(CardData(title="Y", x=900, y=0))
    z = s.add_card(CardData(title="Z", x=0, y=600))
    s._refit_ids({g.card.id})
    for src, dst in ((x, g), (p, q), (g, y)):
        s.add_connection(src, dst)
    return x, g, p, q, y, z


def faded(item):
    return abs(item.opacity() - DIMMED_OPACITY) < 1e-6


def test_highlight_lights_cards_their_groups_and_arrows(scene):
    x, g, p, q, y, z = board_with_group(scene)
    graph = scene.story_graph()
    ids = {x.card.id} | graph.downstream(x.card.id)
    scene.set_highlight(ids, graph.arrows_within(ids), focus_id=x.card.id, label="After X")
    assert ids == {c.card.id for c in (p, q, y)} | {x.card.id}
    assert not any(faded(c) for c in (x, g, p, q, y)) and faded(z)
    assert g.highlight is True              # holds lit cards, so its frame stays lit
    assert all(e.highlight for e in scene.edges)
    assert x._focus and not p._focus
    assert scene.has_highlight() and scene.highlight_label() == "After X"


def test_highlight_and_filter_combine(window):
    s = window.scene
    a, b = s.add_card(CardData(title="A", tags=["keep"])), s.add_card(CardData(title="B", x=400))
    s.set_highlight({a.card.id, b.card.id})
    s.apply_filter(lambda c: "keep" in c.tags)
    assert not faded(a) and faded(b)          # lit, but filtered out
    s.clear_highlight()
    assert faded(b) and a.highlight is None   # the filter still applies
    s.apply_filter(None)
    assert not faded(b)


def test_highlight_survives_edits_and_undo_and_marks_new_cards_unlit(scene):
    a, b = scene.add_card(CardData(title="A")), scene.add_card(CardData(title="B", x=400))
    scene.reset_history()
    scene.set_highlight({a.card.id}, label="Just A")
    a.card.title = "A2"
    a.apply_data(a.card)
    scene.mark_modified()
    scene.flush_history()
    assert scene.has_highlight()
    new = scene.add_card(CardData(title="New", x=0, y=400))
    assert new.highlight is False and faded(new)
    scene.remove_card(new)
    assert scene.undo()                      # rebuilds every item
    assert scene.has_highlight() and scene.cards[a.card.id].highlight is True
    assert faded(scene.cards[b.card.id])


def test_escape_and_banner_clear_the_highlight(window, qapp):
    s = window.scene
    a, b = s.add_card(CardData(title="A")), s.add_card(CardData(title="B", x=400))
    window.show()
    s.set_highlight({a.card.id}, label="Paths through “A”")
    assert window.highlight_banner.isVisible()
    assert "Paths through" in window.highlight_banner.label.text()
    window.view.setFocus()
    QTest.keyClick(window.view.viewport(), Qt.Key.Key_Escape)
    assert not s.has_highlight() and not window.highlight_banner.isVisible()
    assert not faded(b)

    s.set_highlight({a.card.id})
    window.highlight_banner.clear_btn.click()
    assert not s.has_highlight()

    s.set_highlight({a.card.id})
    window.new_board()
    assert not s.has_highlight() and not window.highlight_banner.isVisible()


def test_highlight_banner_sits_below_the_filter_banner(window, tick_filter, qapp):
    s = window.scene
    a = s.add_card(CardData(title="A", tags=["t"]))
    window.show()
    s.set_highlight({a.card.id}, label="Lit")
    top_alone = window.highlight_banner.y()
    tick_filter(window, "tags", "t")
    qapp.processEvents()
    assert window.filter_banner.isVisible()
    assert window.highlight_banner.y() > window.filter_banner.geometry().bottom() > top_alone


def test_graph_cache_follows_changes(scene):
    a, b = scene.add_card(CardData(title="A")), scene.add_card(CardData(title="B", x=400))
    assert scene.story_graph().downstream(a.card.id) == set()
    scene.add_connection(a, b)
    assert scene.story_graph().downstream(a.card.id) == {b.card.id}
    scene.remove_edge(scene.edges[0])
    assert scene.story_graph().downstream(a.card.id) == set()
