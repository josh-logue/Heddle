"""Routes: every way from a start to an end listed (matching the Story Checks count),
each with its own fields (saved with the board, undoable), an option to inherit
its cards' values, and fields of routes that no longer exist kept as "missing"."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from warpingweft.graph import StoryGraph
from warpingweft.model import (
    FORMAT_VERSION, BoardData, CardData, ConnectionData, RouteData, load_board, save_board,
)
from warpingweft.routes import (
    MAX_LISTED, inherited_values, list_routes, matches, merged_fields, route_title, steps_text,
)


def C(i, **kw):
    kw.setdefault("title", i.upper())
    return CardData(id=i, **kw)


def graph(cards, arrows):
    return StoryGraph(cards, [ConnectionData(s, t) for s, t in arrows])


DIAMOND = ([C("a", x=0), C("b", x=100, y=0), C("c", x=100, y=200), C("d", x=200)],
           [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])


# ----- listing routes (graph) ---------------------------------------------------------------
def test_routes_match_the_count_in_reading_order():
    g = graph(*DIAMOND)
    keys = [r.key for r in g.routes()]
    assert keys == [("a", "b", "d"), ("a", "c", "d")]  # upper branch first
    assert len(keys) == g.count_paths().count


def test_a_loop_is_one_stop():
    cards = [C(i, x=n * 100) for n, i in enumerate("abcd")]
    g = graph(cards, [("a", "b"), ("b", "c"), ("c", "b"), ("c", "d")])
    (route,) = g.routes()
    assert route.key == ("a", "b+c", "d")
    assert route.stops[1] == ("b", "c") and route.has_loop
    assert g.count_paths().count == 1


def test_routes_through_groups_use_their_cards():
    group = CardData(id="g", kind="group", title="G")
    cards = [C("a", x=0), group, C("m", x=100, parent="g"), C("n", x=200, parent="g"), C("z", x=300)]
    g = graph(cards, [("a", "g"), ("m", "n"), ("g", "z")])
    assert [r.key for r in g.routes()] == [("a", "m", "n", "z")]


def test_limit_and_long_chains():
    # 2^6 routes through six diamonds in a row
    cards, arrows, prev = [C("s")], [], "s"
    for k in range(6):
        u, d, j = f"u{k}", f"d{k}", f"j{k}"
        cards += [C(u, x=k * 3 + 1, y=0), C(d, x=k * 3 + 1, y=9), C(j, x=k * 3 + 2)]
        arrows += [(prev, u), (prev, d), (u, j), (d, j)]
        prev = j
    g = graph(cards, arrows)
    assert len(g.routes()) == 64 == g.count_paths().count
    assert len(g.routes(limit=10)) == 10
    # no recursion limit on a very long chain
    chain = [C(f"c{i}", x=i) for i in range(3000)]
    g = graph(chain, [(f"c{i}", f"c{i + 1}") for i in range(2999)])
    (route,) = g.routes()
    assert len(route.cards) == 3000


def test_route_for_key_checks_the_route_is_complete():
    g = graph(*DIAMOND)
    assert g.route_for_key(("a", "b", "d")).key == ("a", "b", "d")
    assert g.route_for_key(("a", "b")) is None          # doesn't reach an end
    assert g.route_for_key(("b", "d")) is None          # doesn't begin at a start
    assert g.route_for_key(("a", "d")) is None          # no such step
    assert g.route_for_key(("a", "x", "d")) is None     # unknown card
    assert g.route_for_key(()) is None


def test_route_arrows_are_only_its_steps():
    cards = [C("a", x=0), C("b", x=100), C("c", x=200)]
    conns = [ConnectionData("a", "b", id="ab"), ConnectionData("b", "c", id="bc"),
             ConnectionData("a", "c", id="ac")]  # a shortcut: its own route
    g = StoryGraph(cards, conns)
    long = g.route_for_key(("a", "b", "c"))
    assert g.route_arrows(long) == {"ab", "bc"}
    assert g.route_arrows(g.route_for_key(("a", "c"))) == {"ac"}


# ----- route helpers ---------------------------------------------------------------------------
def test_titles_steps_and_inherited_values():
    cards = {"a": C("a", title="Start", tags=["Dark", "x"], pov="Mara", status="Draft"),
             "b": C("b", title="", tags=["dark", "Y"], characters=["Rowan"], locations=["Keep"]),
             "c": C("c", title="End", status="Draft")}
    key = ("a", "b+c")
    assert route_title(key, cards, None) == "Start → Untitled"
    assert route_title(key, cards, RouteData(key=list(key), name=" Main ")) == "Main"
    assert steps_text(key, cards) == ["Start", "↻ Untitled, End"]
    got = inherited_values(["a", "b", "c"], cards)
    assert got["tags"] == ["Dark", "x", "Y"]               # repeats dropped, first spelling kept
    assert got["characters"] == ["Mara", "Rowan"] and got["pov"] == ["Mara"]
    assert got["locations"] == ["Keep"] and got["status"] == ["Draft"]


def test_merged_fields_only_when_inheriting():
    cards = {"a": C("a", tags=["Dark", "Main"])}
    own = RouteData(key=["a"], tags=["main"])
    assert merged_fields(own, ["a"], cards)["tags"].inherited == []
    own.inherit = True
    view = merged_fields(own, ["a"], cards)["tags"]
    assert view.own == ["main"] and view.inherited == ["Dark"]  # already-own values not repeated


def test_filter_matches_names_cards_and_values():
    cards = {"a": C("a", title="Harbour", tags=["Storm"]), "b": C("b", title="Tower")}
    key = ("a", "b")
    data = RouteData(key=list(key), name="Sea road", notes="wet", inherit=True)
    for text in ("", "sea", "TOWER", "storm", "wet"):
        assert matches(text, key, cards, data)
    assert not matches("castle", key, cards, data)
    data.inherit = False
    assert not matches("storm", key, cards, data)


def test_listing_keeps_saved_routes_and_finds_missing_ones():
    g = graph(*DIAMOND)
    saved = {("a", "c", "d"): RouteData(key=["a", "c", "d"], name="Low road"),
             ("a", "x", "d"): RouteData(key=["a", "x", "d"], name="Gone")}
    listing = list_routes(g, saved, limit=1)
    assert [r.key for r in listing.routes] == [("a", "b", "d"), ("a", "c", "d")]  # saved one beyond the limit
    assert listing.total == 2 and not listing.truncated
    assert [m.name for m in listing.missing] == ["Gone"]


# ----- saving --------------------------------------------------------------------------------
def test_route_data_is_cleaned():
    r = RouteData(key=["a", "", 3, " b "], name=None, tags="x, y,x", pov="Mara",
                  characters=["mara"], inherit="yes")
    assert r.key == ["a", "b"] and r.name == "" and r.tags == ["x", "y"]
    assert r.pov == "mara" and r.characters == ["mara"] and r.inherit is False
    assert RouteData(key=["a"]).is_blank() and not RouteData(key=["a"], inherit=True).is_blank()


def test_routes_round_trip_and_blank_ones_are_not_saved(tmp_path):
    board = BoardData(cards=[C("a"), C("b")], connections=[ConnectionData("a", "b")],
                      routes=[RouteData(key=["a", "b"], name="Only way", tags=["T"], inherit=True),
                              RouteData(key=["b", "a"])])
    path = tmp_path / "b.json"
    save_board(board, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == FORMAT_VERSION == 12
    assert [r["key"] for r in raw["routes"]] == [["a", "b"]]
    loaded = load_board(path)
    assert loaded.routes == [RouteData(key=["a", "b"], name="Only way", tags=["T"], inherit=True)]


def test_older_boards_and_bad_entries_load():
    assert BoardData.from_dict({"version": 3, "cards": []}).routes == []
    raw = {"version": 4, "cards": [], "routes": [
        "junk", {"key": []}, {"key": ["a"], "name": "One"}, {"key": ["a"], "name": "Dup"}, {"key": ["b"]}]}
    assert [r.name for r in BoardData.from_dict(raw).routes] == ["One"]


# ----- the scene ------------------------------------------------------------------------------
@pytest.fixture
def chain(scene, settle):
    a = scene.add_card(CardData(title="A", x=0, tags=["Dark"]))
    b = scene.add_card(CardData(title="B", x=300, characters=["Mara"]))
    scene.add_connection(a, b)
    settle()
    return a, b


def test_route_fields_are_undoable(scene, chain, qapp):
    a, b = chain
    key = (a.card.id, b.card.id)
    scene.set_route_data(RouteData(key=list(key), name="Road"))
    qapp.processEvents()
    assert scene.route_data(key).name == "Road"
    scene.undo()
    assert scene.route_data(key) is None
    scene.redo()
    assert scene.route_data(key).name == "Road"
    assert scene.to_board_data().routes[0].name == "Road"


def test_blank_fields_forget_the_route(scene, chain, qapp):
    a, b = chain
    key = (a.card.id, b.card.id)
    scene.set_route_data(RouteData(key=list(key), notes="x"))
    scene.set_route_data(RouteData(key=list(key)))
    assert scene.routes == {}


def test_renaming_a_value_renames_it_on_routes(scene, chain, qapp):
    a, b = chain
    key = (a.card.id, b.card.id)
    scene.set_route_data(RouteData(key=list(key), tags=["Dark", "Solo"], pov="Mara"))
    scene.rename_value("tags", "solo", "Alone")
    scene.rename_value("characters", "Mara", "Maura")
    data = scene.route_data(key)
    assert data.tags == ["Dark", "Alone"] and data.pov == "Maura" and data.characters == ["Maura"]
    assert "Alone" in scene.all_values("tags")  # route values are offered as suggestions


# ----- the panel ---------------------------------------------------------------------------------
def open_panel(window, qapp):
    window.show()
    window.routes_dock.show()
    qapp.processEvents()
    return window.routes_panel


def test_lists_routes_collapsed_by_default(window, qapp, scene, chain):
    p = open_panel(window, qapp)
    a, b = chain
    c = scene.add_card(CardData(title="C", x=300, y=300))
    scene.add_connection(a, c)
    scene.mark_modified()
    p.refresh()
    assert list(p.rows) == [(a.card.id, b.card.id), (a.card.id, c.card.id)]
    assert p.summary.text() == "2 routes"
    for row in p.rows.values():
        assert not row.expanded and row.body is None  # built only when first opened
    assert p.rows[(a.card.id, b.card.id)].title.text() == "A → B"


def test_expanding_shows_cards_and_fields_and_survives_refresh(window, qapp, scene, chain):
    p = open_panel(window, qapp)
    a, b = chain
    key = (a.card.id, b.card.id)
    row = p.rows[key]
    row.arrow.click()
    assert row.expanded and row.body.isVisible()
    assert "No fields set" in row.fields_label.text()
    scene.set_route_data(RouteData(key=list(key), name="Road", tags=["Main"]))
    p.refresh()
    row = p.rows[key]
    assert row.expanded and "Road" in row.title.text()
    assert "Main" in row.fields_label.text()


def test_inherit_toggle_shows_card_values(window, qapp, scene, chain):
    p = open_panel(window, qapp)
    a, b = chain
    key = (a.card.id, b.card.id)
    p.rows[key].set_expanded(True)
    p.rows[key].inherit_check.setChecked(True)
    assert scene.route_data(key).inherit
    p.refresh()
    text = p.rows[key].fields_label.text()
    assert "Dark" in text and "Mara" in text and "from cards" in text
    assert "inherits" in p.rows[key].meta.text()
    # inherited values follow the cards
    b.card.characters = ["Rowan"]
    b.apply_data(b.card)
    scene.mark_modified()
    p.refresh()
    assert "Rowan" in p.rows[key].fields_label.text()
    p.rows[key].inherit_check.setChecked(False)
    assert scene.route_data(key) is None  # nothing else set: forgotten


def test_edit_fields_dialog(window, qapp, scene, chain, monkeypatch):
    from warpingweft import route_dialog
    p = open_panel(window, qapp)
    a, b = chain
    key = (a.card.id, b.card.id)

    def fake_exec(dialog):
        assert dialog.name_edit.placeholderText() == "A → B"
        dialog.name_edit.setText("High road")
        dialog.tags_input.add_value("Main")
        dialog.pov_combo.setCurrentText("Mara")
        dialog.inherit_check.setChecked(True)
        return True

    monkeypatch.setattr(route_dialog.RouteDialog, "exec", fake_exec)
    assert p.edit(key)
    data = scene.route_data(key)
    assert (data.name, data.tags, data.pov, data.inherit) == ("High road", ["Main"], "Mara", True)
    monkeypatch.setattr(route_dialog.RouteDialog, "exec", lambda d: False)
    assert not p.edit(key) and scene.route_data(key).name == "High road"


def test_broken_routes_keep_their_fields_as_missing(window, qapp, scene, chain, settle):
    p = open_panel(window, qapp)
    a, b = chain
    key = (a.card.id, b.card.id)
    scene.set_route_data(RouteData(key=list(key), name="Road"))
    settle()
    scene.remove_edge(scene.edges[0])
    settle()
    p.refresh()
    assert p.rows[key].missing and "missing" in p.rows[key].meta.text()
    assert "1 missing" in p.summary.text()
    assert scene.route_data(key) is not None  # still saved
    scene.undo()  # the arrow is back: so is the route
    p.refresh()
    assert not p.rows[key].missing
    scene.redo()
    p.refresh()
    p.rows[key].set_expanded(True)
    assert scene.delete_route_data(key)
    p.refresh()
    assert key not in p.rows


def test_clicking_a_route_lights_it_up(window, qapp, scene, chain):
    p = open_panel(window, qapp)
    a, b = chain
    key = (a.card.id, b.card.id)
    row = p.rows[key]
    header = row.title.parentWidget()
    QTest.mouseClick(header, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert scene.highlight_owner() == "routes"
    assert scene.highlight_label() == "Route: A → B"
    assert a.highlight is True and b.highlight is True
    assert scene.edges[0].conn.id in scene._highlight[1]
    window.routes_dock.hide()
    qapp.processEvents()
    assert scene.highlight_owner() != "routes"  # closing the panel clears its highlight


def test_filter_hides_rows(window, qapp, scene, chain):
    p = open_panel(window, qapp)
    a, b = chain
    c = scene.add_card(CardData(title="Cellar", x=300, y=300))
    scene.add_connection(a, c)
    scene.mark_modified()
    p.refresh()
    p.filter_edit.setText("cellar")
    visible = [k for k, r in p.rows.items() if not r.isHidden()]
    assert visible == [(a.card.id, c.card.id)]
    p.filter_edit.clear()
    assert all(not r.isHidden() for r in p.rows.values())


def test_moving_cards_leaves_the_list_alone(window, qapp, scene, chain):
    p = open_panel(window, qapp)
    a, _ = chain
    rows = dict(p.rows)
    a.setPos(a.pos().x() + 50, a.pos().y())
    scene.mark_modified()
    p.refresh()
    assert p.rows == rows  # same widgets: scroll position and open rows untouched


def test_big_boards_list_a_capped_number(window, qapp, scene):
    p = open_panel(window, qapp)
    prev = scene.add_card(CardData(title="S"))
    for k in range(10):  # 2^10 = 1024 routes
        up = scene.add_card(CardData(title=f"U{k}", x=k * 600 + 300, y=0))
        down = scene.add_card(CardData(title=f"D{k}", x=k * 600 + 300, y=400))
        join = scene.add_card(CardData(title=f"J{k}", x=k * 600 + 600, y=200))
        for s, t in ((prev, up), (prev, down), (up, join), (down, join)):
            scene.add_connection(s, t)
        prev = join
    scene.mark_modified()
    p.refresh()
    assert len(p.rows) == MAX_LISTED
    assert p.summary.text() == f"1024 routes (showing {MAX_LISTED})"


def test_empty_board_says_how_to_get_routes(window, qapp):
    p = open_panel(window, qapp)
    assert "No routes yet" in p.summary.text() and not p.rows


def test_shortcut_and_menu(window, qapp):
    window.show()
    qapp.processEvents()
    assert window.act_routes.shortcut().toString() == "Ctrl+Shift+O"
    window.act_routes.trigger()
    qapp.processEvents()
    assert window.routes_dock.isVisible()
    window.act_routes.trigger()
    qapp.processEvents()
    assert not window.routes_dock.isVisible()
