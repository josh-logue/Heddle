"""A group's row limit (`arrange_wrap`): saved on the group, set from the group editor
or the right-click menu, and used by auto-arrange. Arranging and changing it are
each one undo step."""
import json

from heddle.layout import H_GAP, ROW_GAP
from heddle.model import (
    ARRANGE_WRAP_MAX, KIND_GROUP, BoardData, CardData, ConnectionData, load_board, save_board,
)

NAMES = ["Rowan", "Mabel", "Greta", "Warden", "East Ward", "Lantern"]


def load_chain(scene, wrap=0):
    cards = [CardData(id="g", title="Chapter", kind=KIND_GROUP, arrange_wrap=wrap)]
    cards += [CardData(id=f"c{k}", title=n, parent="g", x=40 + k * 300, y=60) for k, n in enumerate(NAMES)]
    conns = [ConnectionData(source=f"c{k}", target=f"c{k + 1}") for k in range(len(NAMES) - 1)]
    scene.load_board_data(BoardData(cards=cards, connections=conns))
    scene.reset_history()


def pos(scene, cid):
    r = scene.cards[cid].card_scene_rect()
    return r.x(), r.y()


def test_model_cleans_the_row_limit():
    assert CardData().arrange_wrap == 0
    assert CardData(arrange_wrap=5).arrange_wrap == 5
    for bad in (-3, "5", None, True, float("nan"), [5]):
        assert CardData(arrange_wrap=bad).arrange_wrap == 0
    assert CardData(arrange_wrap=1000).arrange_wrap == ARRANGE_WRAP_MAX
    assert CardData(arrange_wrap=4.7).arrange_wrap == 4


def test_row_limit_round_trips_through_a_file_and_old_files_have_none(tmp_path):
    path = tmp_path / "b.json"
    save_board(BoardData(cards=[CardData(id="g", kind=KIND_GROUP, arrange_wrap=5)]), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["cards"][0]["arrange_wrap"] == 5
    assert load_board(path).cards[0].arrange_wrap == 5
    del raw["cards"][0]["arrange_wrap"]
    raw["version"] = 11
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_board(path).cards[0].arrange_wrap == 0


def test_auto_arrange_wraps_the_sixth_card_under_the_first_with_limit_five(scene):
    load_chain(scene, wrap=5)
    scene.auto_arrange_group(scene.cards["g"])
    xs = [pos(scene, f"c{k}")[0] for k in range(5)]
    width = scene.cards["c0"].card_scene_rect().width()
    assert all(abs((b - a) - (width + H_GAP)) < 0.01 for a, b in zip(xs, xs[1:]))
    tallest = max(scene.cards[f"c{k}"].card_scene_rect().height() for k in range(5))
    x6, y6 = pos(scene, "c5")
    assert abs(x6 - xs[0]) < 0.01
    assert abs(y6 - (pos(scene, "c0")[1] + tallest + ROW_GAP)) < 0.01


def test_no_limit_keeps_one_row(scene):
    load_chain(scene)
    scene.auto_arrange_group(scene.cards["g"])
    assert len({round(pos(scene, f"c{k}")[1]) for k in range(6)}) == 1


def test_arranging_with_a_limit_is_one_undo_step(scene):
    load_chain(scene, wrap=3)
    before = {f"c{k}": pos(scene, f"c{k}") for k in range(6)}
    scene.auto_arrange_group(scene.cards["g"])
    scene.mark_modified()
    assert pos(scene, "c3") != before["c3"]
    assert scene.undo()
    assert {f"c{k}": pos(scene, f"c{k}") for k in range(6)} == before
    assert scene.cards["g"].card.arrange_wrap == 3


def test_group_editor_sets_the_row_limit(qapp):
    from heddle.dialogs import CardDialog
    d = CardDialog(CardData(title="G", kind=KIND_GROUP, arrange_wrap=5))
    assert d.wrap_spin.value() == 5
    assert d.wrap_spin.maximum() == ARRANGE_WRAP_MAX
    assert d.wrap_spin.specialValueText() == "No limit"
    d.wrap_spin.setValue(0)
    assert d.result_data().arrange_wrap == 0
    d.wrap_spin.setValue(4)
    assert d.result_data().arrange_wrap == 4


def menu_named(menu, text):
    return next(a.menu() for a in menu.actions() if a.menu() and a.text() == text)


def test_right_click_submenu_sets_the_row_limit_as_one_undo_step(scene):
    load_chain(scene)
    group = scene.cards["g"]
    menu = scene.build_context_menu(group, group.pos())
    sub = menu_named(menu, "Wrap rows after")
    labels = [a.text() for a in sub.actions() if not a.isSeparator()]
    assert labels[0] == "No limit" and "5 steps" in labels
    assert next(a for a in sub.actions() if a.text() == "No limit").isChecked()
    next(a for a in sub.actions() if a.text() == "5 steps").trigger()
    assert scene.cards["g"].card.arrange_wrap == 5
    assert scene.undo()
    assert scene.cards["g"].card.arrange_wrap == 0


def test_submenu_shows_an_unusual_limit_already_set(scene):
    load_chain(scene, wrap=7)
    group = scene.cards["g"]
    menu = scene.build_context_menu(group, group.pos())  # kept: the submenu belongs to it
    sub = menu_named(menu, "Wrap rows after")
    checked = [a.text() for a in sub.actions() if a.isChecked()]
    assert checked == ["7 steps"]
