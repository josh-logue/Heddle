"""Optional features as board options (saved with the board, undoable), a card's
"not part of the story" flag, and the app setting for the bars over the canvas."""
from PySide6.QtWidgets import QMenu

from warpingweft import settings
from warpingweft.board_options import SECTIONS, BoardOptionsDialog
from warpingweft.checks import run_checks
from warpingweft.graph import StoryGraph
from warpingweft.model import (
    DISPLAY_DEFAULTS, DISPLAY_TOGGLES, FORMAT_VERSION, KIND_GROUP, BoardData, CardData, ConnectionData,
    clean_display,
)


# ----- model ----------------------------------------------------------------------------------
def test_options_default_on_and_are_cleaned():
    assert FORMAT_VERSION == 12
    for key in ("show_tags", "show_introductions", "show_group_count", "show_shadows",
                "show_handles", "show_arrow_labels", "show_grid", "story_tools"):
        assert DISPLAY_DEFAULTS[key] is True and key in DISPLAY_TOGGLES
    assert DISPLAY_DEFAULTS["follow_paths"] is False
    cleaned = clean_display({"show_grid": False, "story_tools": "no", "bogus": True})
    assert cleaned["show_grid"] is False and cleaned["story_tools"] is True and "bogus" not in cleaned


def test_outside_story_round_trips():
    board = BoardData(cards=[CardData(id="a", outside_story=True), CardData(id="b", outside_story="yes")],
                      display={**DISPLAY_DEFAULTS, "show_tags": False})
    back = BoardData.from_dict(board.to_dict())
    assert [c.outside_story for c in back.cards] == [True, False]
    assert back.display["show_tags"] is False


def test_dialog_covers_every_option():
    listed = {key for _, options in SECTIONS for key, _, _ in options}
    assert listed == set(DISPLAY_TOGGLES)


# ----- card face ---------------------------------------------------------------------------------
def test_tag_pills_can_be_hidden(scene):
    a = scene.add_card(CardData(title="A", tags=["Act 1", "Subplot"]))
    tall = a.card_scene_rect().height()
    assert a._tag_pills
    assert scene.set_display_option("show_tags", False)
    assert not a._tag_pills and a.card_scene_rect().height() < tall



def test_introduction_star_can_be_hidden_but_still_filters(scene, settle):
    a = scene.add_card(CardData(title="A", characters=["Mara"]))
    b = scene.add_card(CardData(title="B", x=300))
    scene.add_connection(a, b)
    settle()
    assert a.shows_introductions()
    scene.set_display_option("show_introductions", False)
    assert not a.shows_introductions()
    assert scene.introductions == {a.card.id: ["Mara"]}  # the Introduces filter still works


def test_group_count_shadows_and_grid_are_options(scene):
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP))
    for key in ("show_group_count", "show_shadows", "show_grid"):
        assert g.board_option(key) is True
        assert scene.set_display_option(key, False)
        assert g.board_option(key) is False


def test_grid_is_not_drawn_when_hidden(scene):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    def colours():
        img = QImage(200, 200, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        scene.drawBackground(p, QRectF(0, 0, 200, 200))
        p.end()
        return {img.pixel(x, y) for x in range(0, 200, 3) for y in range(0, 200, 3)}
    assert len(colours()) > 1
    scene.set_display_option("show_grid", False)
    assert len(colours()) == 1  # just the canvas colour


def test_handles_can_be_hidden(scene):
    from PySide6.QtCore import QPointF
    a = scene.add_card(CardData(title="A"))
    port = a.port_center() - QPointF(1, 0)
    assert a.has_port and a._part_at(port) == "port"
    scene.set_display_option("show_handles", False)
    assert not a.has_port and a._part_at(port) != "port"


def test_arrow_labels_can_be_hidden(scene):
    a = scene.add_card(CardData(title="A"))
    b = scene.add_card(CardData(title="B", x=500))
    edge = scene.add_connection(a, b)
    edge.set_label("if she refuses")
    edge.adjust()
    assert not edge._label_rect.isNull()
    scene.set_display_option("show_arrow_labels", False)
    assert edge._label_rect.isNull() and edge.toolTip() == "if she refuses"


# ----- story tools ----------------------------------------------------------------------------------
def test_story_tools_off_hides_story_features(window, qapp):
    s = window.scene
    a = s.add_card(CardData(title="A", characters=["Mara"]))
    b = s.add_card(CardData(title="B", x=300))
    s.add_connection(a, b)
    s.mark_modified()
    aid = a.card.id
    window.show()
    window.checks_dock.show()
    qapp.processEvents()
    window.act_story_tools.setChecked(False)
    qapp.processEvents()
    assert s.display["story_tools"] is False
    assert s.introductions == {} and not a.shows_introductions()
    for act in (window.act_read, window.act_thread, window.act_checks, window.act_routes, window.act_reader):
        assert not act.isVisible()
    assert not window.checks_dock.isVisible()
    menu = QMenu()
    s._add_path_actions(menu, a)
    labels = [x.text().split("\t")[0] for x in menu.actions()]  # (the key follows a tab)
    assert "Read from here" not in labels and "Not part of the story" not in labels
    s.undo()  # undoable like any board option
    qapp.processEvents()
    assert s.display["story_tools"] is True and window.act_checks.isVisible()
    assert s.cards[aid].shows_introductions()  # (undo rebuilds the cards)


def test_follow_paths_is_saved_with_the_board(window, qapp):
    s = window.scene
    window.act_follow_paths.setChecked(True)
    assert s.display["follow_paths"] is True
    assert s.to_board_data().display["follow_paths"] is True
    s.undo()
    qapp.processEvents()
    assert not window.act_follow_paths.isChecked()


# ----- not part of the story ---------------------------------------------------------------------------
def story(outside: set[str], group_outside=False):
    cards = [CardData(id=i, title=i.upper(), x=n * 300, characters=["Mara"] if i == "n" else [],
                      outside_story=i in outside) for n, i in enumerate("abn")]
    cards.append(CardData(id="g", kind=KIND_GROUP, title="Notes", outside_story=group_outside))
    cards.append(CardData(id="m", title="M", parent="g", y=400))
    conns = [ConnectionData("a", "b"), ConnectionData("b", "n"), ConnectionData("n", "m")]
    return StoryGraph(cards, conns)


def test_cards_outside_the_story_are_left_out():
    g = story({"n"})
    assert g.outside == {"n"}
    assert g.succ["b"] == [] and g.featuring("Mara") == []    # its arrows and characters don't count
    assert [r.key for r in g.routes()] == [("a", "b")]
    report = run_checks(g)
    assert all("n" not in f.cards for f in report.findings)    # not reported as having no arrows
    assert g.introductions() == {}


def test_a_group_outside_the_story_takes_its_cards_with_it():
    g = story(set(), group_outside=True)
    assert g.outside == {"g", "m"}
    assert "m" not in g.succ["n"]


def test_flag_from_the_menu_is_undoable_and_drawn_dashed(scene, settle):
    a = scene.add_card(CardData(title="A"))
    b = scene.add_card(CardData(title="B", x=300))
    scene.add_connection(a, b)
    settle()
    menu = QMenu()
    scene._add_path_actions(menu, a)
    toggle = next(x for x in menu.actions() if x.text().startswith("Not part of the story\t"))
    assert not toggle.isChecked()
    toggle.trigger()
    settle()
    assert a.card.outside_story and scene.story_graph().outside == {a.card.id}
    scene.undo()
    assert not scene.cards[a.card.id].card.outside_story


def test_card_editor_has_the_flag(qapp):
    from warpingweft.dialogs import CardDialog
    d = CardDialog(CardData(title="A", outside_story=True))
    assert d.outside_check.isChecked()
    d.outside_check.setChecked(False)
    assert d.result_data().outside_story is False
    d.set_story_tools(False)
    assert not d._form.isRowVisible(d.outside_check)


# ----- Board Options dialog ------------------------------------------------------------------------------
def test_board_options_dialog_is_one_undo_step(window, qapp, monkeypatch):
    s = window.scene

    def choose(dialog):
        dialog.checks["show_tags"].setChecked(False)
        dialog.checks["show_grid"].setChecked(False)
        dialog.routing.setCurrentIndex(dialog.routing.findData("curved"))
        return True
    monkeypatch.setattr(BoardOptionsDialog, "exec", choose)
    assert window.edit_board_options()
    assert (s.display["show_tags"], s.display["show_grid"], s.display["arrow_routing"]) == (False, False, "curved")
    assert not window.act_show_tags.isChecked() and not window.act_show_grid.isChecked()
    s.undo()
    qapp.processEvents()
    assert (s.display["show_tags"], s.display["show_grid"], s.display["arrow_routing"]) == (True, True, "straight")


# ----- bars over the canvas (app setting) -------------------------------------------------------------------
def test_banners_can_be_turned_off(window, qapp, tick_filter):
    s = window.scene
    s.add_card(CardData(title="A", tags=["x"]))
    s.add_card(CardData(title="B", x=300))
    s.mark_modified()
    window.show()
    qapp.processEvents()
    tick_filter(window, "tags", "x")
    assert window.filter_banner.isVisible()
    settings.set("show_banners", False)
    window._apply_settings()
    assert not window.filter_banner.isVisible()
    assert window.filter_label.text().startswith("Filter active")  # the status bar still says so
    s.set_highlight({next(iter(s.cards))}, label="Lit", owner="paths")
    assert not window.highlight_banner.isVisible()


def test_introduces_filter_is_hidden_without_story_tools(window, qapp):
    s = window.scene
    s.add_card(CardData(title="A", characters=["Mara"]))
    s.mark_modified()
    window.show()
    window.filter_dock.show()
    qapp.processEvents()

    def categories():
        tree = window.filter_panel.tree
        return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert "Introduces" in categories()
    s.set_display_option("story_tools", False)
    window.filter_panel.refresh()
    assert "Introduces" not in categories() and "Characters" in categories()
