"""Code-review medium items: compact loops and faster refreshes in the Routes panel,
the editor form shared by cards and routes, the side-panel helper, and CardItem.faded."""
import pytest
from PySide6.QtCore import Qt

from warpingweft.details_form import STATUS_PRESETS, DetailFields
from warpingweft.model import CardData, RouteData
from warpingweft.routes import COMPACT_LOOP_OVER, loop_details, matches, search_text, steps_text


def cards_named(*names):
    return {n.lower(): CardData(id=n.lower(), title=n) for n in names}


# ----- compact loops --------------------------------------------------------------------------
def test_small_loops_are_listed_big_ones_summarised():
    cards = cards_named("S", "A", "B", "C", "D", "E", "Z")
    small = ("s", "a+b+c+d", "z")            # 4 cards: listed in full
    big = ("s", "a+b+c+d+e", "z")            # 5 cards: summarised
    assert COMPACT_LOOP_OVER == 4
    assert steps_text(small, cards) == ["S", "↻ A, B, C, D", "Z"]
    assert steps_text(big, cards) == ["S", "↻ Loop of 5 cards: A, B, C …", "Z"]
    assert loop_details(small, cards) == []
    assert loop_details(big, cards) == ["Loop of 5 cards: A, B, C, D, E"]


def test_filter_still_finds_cards_hidden_in_a_summary():
    cards = cards_named("S", "A", "B", "C", "D", "Echo", "Z")
    key = ("s", "a+b+c+d+echo", "z")
    assert "Echo" not in " ".join(steps_text(key, cards))
    assert matches("echo", key, cards, None)
    assert "echo" in search_text(key, cards, RouteData(key=list(key), notes="Wet"))


@pytest.fixture
def loop_board(scene, settle):
    """S → a loop of six cards → Z."""
    s = scene.add_card(CardData(title="S"))
    loop = [scene.add_card(CardData(title=f"L{i}", x=300 + i * 300)) for i in range(6)]
    z = scene.add_card(CardData(title="Z", x=2400))
    scene.add_connection(s, loop[0])
    for a, b in zip(loop, loop[1:] + loop[:1]):
        scene.add_connection(a, b)
    scene.add_connection(loop[-1], z)
    settle()
    return s, loop, z


def test_panel_summarises_loops_and_lists_them_on_hover(window, qapp, scene, loop_board):
    window.show()
    window.routes_dock.show()
    qapp.processEvents()
    p = window.routes_panel
    (key,) = p.rows
    row = p.rows[key]
    assert "Loop of 6 cards" in row.title.toolTip()
    row.set_expanded(True)
    steps = row.body.findChildren(type(row.title))[0]
    assert "Loop of 6 cards: L0, L1, L2 …" in steps.text()
    assert "L5" in steps.toolTip()  # every card, on hover


def test_renaming_a_card_updates_rows_in_place(window, qapp, scene, loop_board):
    s, _, _ = loop_board
    window.show()
    window.routes_dock.show()
    qapp.processEvents()
    p = window.routes_panel
    rows = dict(p.rows)
    (row,) = rows.values()
    row.set_expanded(True)
    s.card.title = "Start"
    s.apply_data(s.card)
    scene.mark_modified()
    p.refresh()
    assert p.rows == rows                      # same row widgets: nothing rebuilt
    assert row.title.text().startswith("Start →") and row.expanded and row.body is not None
    assert "Start" in row.body.findChildren(type(row.title))[0].text()


def test_rebuilding_swaps_in_a_new_list(window, qapp, scene, loop_board):
    s, _, z = loop_board
    window.show()
    window.routes_dock.show()
    qapp.processEvents()
    p = window.routes_panel
    old_list = p.scroll.widget()
    scene.add_connection(s, z)                 # a second route: the list changes
    scene.mark_modified()
    p.refresh()
    assert len(p.rows) == 2 and p.scroll.widget() is not old_list
    assert all(r.parentWidget() is p.scroll.widget() for r in p.rows.values())


# ----- shared editor form ------------------------------------------------------------------------
def test_route_editor_pov_matches_the_card_editor(qapp):
    from warpingweft.route_dialog import RouteDialog
    data = RouteData(key=["a", "b"], characters=["Zed"], pov="Zed")
    d = RouteDialog(data, ["A", "B"], "A → B", {"characters": ["Aria", "Mara", "Zed"]})
    choices = [d.pov_combo.itemText(i) for i in range(d.pov_combo.count())]
    assert choices == ["", "Zed", "Aria", "Mara"]          # the route's own characters first
    d.characters_input.remove_value("Zed")
    assert d.pov_combo.currentText() == ""                 # removing the POV's chip clears it
    statuses = [d.status_combo.itemText(i) for i in range(len(STATUS_PRESETS))]
    assert statuses == STATUS_PRESETS


def test_both_editors_use_the_shared_form(qapp):
    from warpingweft.dialogs import CardDialog
    from warpingweft.route_dialog import RouteDialog
    card = CardDialog(CardData(title="A", tags=["T"], notes="  n  "))
    route = RouteDialog(RouteData(key=["a"], tags=["T"]), ["A"], "A", {})
    for dialog in (card, route):
        assert isinstance(dialog.fields, DetailFields)
        assert dialog.tags_input is dialog.fields.tags_input
    assert card.result_data().notes == "n"                 # cards still trim their notes
    assert card.result_data().tags == ["T"] and route.route_data().tags == ["T"]


def test_pending_entries_are_kept_on_ok_in_both(qapp, monkeypatch):
    from warpingweft import settings
    from warpingweft.route_dialog import RouteDialog
    monkeypatch.setattr(settings, "get", lambda key: True)
    d = RouteDialog(RouteData(key=["a"]), ["A"], "A", {})
    d.locations_input.edit.setText("Harbour")
    d.accept()
    assert d.route_data().locations == ["Harbour"]


# ----- side panels -----------------------------------------------------------------------------------
def test_side_panels_are_built_the_same_way(window):
    docks = {window.reader_dock: ("Path Reader", "PathReaderDock"),
             window.checks_dock: ("Story Checks", "StoryChecksDock"),
             window.routes_dock: ("Routes", "RoutesDock"),
             window.filter_dock: ("Filter", "FilterDock")}
    sides = Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
    for dock, (title, name) in docks.items():
        assert dock.windowTitle() == title and dock.objectName() == name
        assert dock.allowedAreas() == sides and dock.isHidden()
        assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    shortcuts = {window.act_filter: "Ctrl+L", window.act_checks: "Ctrl+Shift+K",
                 window.act_routes: "Ctrl+Shift+O", window.act_reader: ""}
    for act, keys in shortcuts.items():
        assert act.shortcut().toString() == keys and act in window.actions()


# ----- CardItem.faded ----------------------------------------------------------------------------------
def test_faded_covers_filter_and_highlight(scene):
    a = scene.add_card(CardData(title="A"))
    b = scene.add_card(CardData(title="B", x=300))
    assert not a.faded
    a.set_dimmed(True)
    assert a.faded and a.opacity() < 1
    a.set_dimmed(False)
    scene.set_highlight({b.card.id})
    assert a.faded and not b.faded
    scene.clear_highlight()
    assert not a.faded and a.opacity() == 1


def test_titles_use_story_order_for_loops_at_either_end():
    from warpingweft.routes import default_title
    cards = cards_named("B", "A", "Z")
    key = ("a+b", "z")                      # the key sorts a loop's ids...
    assert default_title(key, cards, stops=(("b", "a"), ("z",))) == "B → Z"  # ...the route doesn't
    assert default_title(key, cards) == "A → Z"
