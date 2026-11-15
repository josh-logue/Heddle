"""Keyboard shortcuts for the card commands (the Card menu): C collapses or expands
groups, Shift+C all of them, D / Shift+D details, L connect, R reverses arrows, O "not
part of the story", Shift+H steps the path highlight and Ctrl+Shift+A arranges groups.
They act only while the canvas has keyboard focus, so typing letters in the Card Panel
doesn't touch the board, and no two actions share a key."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from conftest import wait_until
from warpingweft.model import KIND_GROUP, BoardData, CardData
from warpingweft.shortcuts import KEYS

NONE = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL_SHIFT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier


def setup(window, qapp):
    """Year (group) holds a and b; Inner (group) holds c; x is loose; x → a → b."""
    cards = [
        CardData(id="Y", title="Year", kind=KIND_GROUP, x=0, y=0),
        CardData(id="a", title="a", parent="Y", x=20, y=60),
        CardData(id="b", title="b", parent="Y", x=900, y=400),
        CardData(id="I", title="Inner", kind=KIND_GROUP, x=0, y=900),
        CardData(id="c", title="c", parent="I", x=20, y=960),
        CardData(id="x", title="x", x=-600, y=60),
    ]
    s = window.scene
    s.load_board_data(BoardData(cards=cards))
    s.add_connection(s.cards["x"], s.cards["a"])
    s.add_connection(s.cards["a"], s.cards["b"])
    s.mark_modified()
    s.reset_history()
    window.show()
    window.activateWindow()
    window.focus_canvas()
    qapp.processEvents()
    return s


def press(window, qapp, key, mods=NONE):
    QTest.keyClick(window.view.viewport(), key, mods)
    qapp.processEvents()


def select(s, *ids):
    s.clearSelection()
    for i in ids:
        s.cards[i].setSelected(True)


def test_c_folds_the_selected_group_and_again_unfolds_it(window, qapp):
    s = setup(window, qapp)
    select(s, "Y")
    press(window, qapp, Qt.Key.Key_C)
    assert s.cards["Y"].card.collapsed and not s.cards["a"].isVisible()
    press(window, qapp, Qt.Key.Key_C)
    assert not s.cards["Y"].card.collapsed and s.cards["a"].isVisible()


def test_c_on_a_card_folds_its_group_and_selects_the_group(window, qapp):
    s = setup(window, qapp)
    select(s, "a")
    press(window, qapp, Qt.Key.Key_C)
    assert s.cards["Y"].card.collapsed
    assert s.selectedItems() == [s.cards["Y"]]  # so C again opens it
    press(window, qapp, Qt.Key.Key_C)
    assert not s.cards["Y"].card.collapsed


def test_c_with_nothing_to_fold_says_so(window, qapp):
    s = setup(window, qapp)
    select(s, "x")  # a loose card
    press(window, qapp, Qt.Key.Key_C)
    assert not any(g.card.collapsed for g in s.cards.values() if g.is_group)
    assert "group" in window.statusBar().currentMessage()


def test_shift_c_folds_every_group_then_unfolds_them(window, qapp):
    s = setup(window, qapp)
    s.set_collapsed([s.cards["I"]], True)  # one already folded: Shift+C folds the rest
    press(window, qapp, Qt.Key.Key_C, SHIFT)
    assert s.cards["Y"].card.collapsed and s.cards["I"].card.collapsed
    press(window, qapp, Qt.Key.Key_C, SHIFT)
    assert not s.cards["Y"].card.collapsed and not s.cards["I"].card.collapsed


def test_d_toggles_the_selections_details_and_shift_d_everyones(window, qapp):
    s = setup(window, qapp)
    select(s, "x", "a")
    press(window, qapp, Qt.Key.Key_D)
    assert s.cards["x"].details_visible and s.cards["a"].details_visible
    assert not s.cards["c"].details_visible
    press(window, qapp, Qt.Key.Key_D)
    assert not s.cards["x"].details_visible and not s.cards["a"].details_visible
    press(window, qapp, Qt.Key.Key_D, SHIFT)
    assert all(i.details_visible for i in s.cards.values())
    press(window, qapp, Qt.Key.Key_D, SHIFT)
    assert not any(i.details_visible for i in s.cards.values())
    assert not s.history.can_undo()  # details aren't an edit


def test_l_starts_connect_to_from_the_selected_card(window, qapp):
    s = setup(window, qapp)
    select(s, "x")
    press(window, qapp, Qt.Key.Key_L)
    assert s.is_click_connecting()
    press(window, qapp, Qt.Key.Key_Escape)
    assert not s.is_click_connecting()
    select(s, "x", "a")  # not with two selected
    press(window, qapp, Qt.Key.Key_L)
    assert not s.is_click_connecting()


def test_r_reverses_the_selected_arrows_in_one_undo_step(window, qapp):
    s = setup(window, qapp)
    s.clearSelection()
    for e in s.edges:
        e.setSelected(True)
    press(window, qapp, Qt.Key.Key_R)
    pairs = {(e.source.card.id, e.target.card.id) for e in s.edges}
    assert pairs == {("a", "x"), ("b", "a")}
    wait_until(lambda: s.history.can_undo())
    s.undo()
    assert {(e.source.card.id, e.target.card.id) for e in s.edges} == {("x", "a"), ("a", "b")}


def test_o_toggles_not_part_of_the_story_and_hides_with_story_tools(window, qapp):
    s = setup(window, qapp)
    select(s, "x", "a")
    press(window, qapp, Qt.Key.Key_O)
    assert s.cards["x"].card.outside_story and s.cards["a"].card.outside_story
    press(window, qapp, Qt.Key.Key_O)
    assert not s.cards["x"].card.outside_story
    s.set_display_option("story_tools", False)
    qapp.processEvents()
    assert not window.act_outside.isVisible()
    press(window, qapp, Qt.Key.Key_O)
    assert not s.cards["x"].card.outside_story


def test_shift_h_steps_the_path_highlight(window, qapp):
    s = setup(window, qapp)
    select(s, "a")
    press(window, qapp, Qt.Key.Key_H)
    assert s.highlight_label().startswith("Paths through")
    press(window, qapp, Qt.Key.Key_H, SHIFT)
    assert s.highlight_label().startswith("What leads to")
    assert s.highlight.cards >= {"x", "a"} and "b" not in s.highlight.cards
    press(window, qapp, Qt.Key.Key_H, SHIFT)
    assert s.highlight_label().startswith("What follows")
    press(window, qapp, Qt.Key.Key_H, SHIFT)
    assert s.highlight_label().startswith("Paths through")


def test_ctrl_shift_a_arranges_the_group_in_one_undo_step(window, qapp):
    s = setup(window, qapp)
    far = s.cards["b"].pos()
    select(s, "a")  # a card: its group is arranged
    press(window, qapp, Qt.Key.Key_A, CTRL_SHIFT)
    assert s.cards["b"].pos() != far
    wait_until(lambda: s.history.can_undo())
    s.undo()
    assert s.cards["b"].pos() == far


def test_letters_typed_in_the_card_panel_dont_reach_the_board(window, qapp):
    s = setup(window, qapp)
    window.card_dock.show()
    select(s, "a")
    qapp.processEvents()
    field = window.card_panel.title_edit
    field.setFocus()
    qapp.processEvents()
    for key in (Qt.Key.Key_C, Qt.Key.Key_D, Qt.Key.Key_L, Qt.Key.Key_O, Qt.Key.Key_R):
        QTest.keyClick(field, key)
    qapp.processEvents()
    assert field.text().endswith("cdlor")
    assert not s.cards["Y"].card.collapsed and not s.cards["a"].details_visible
    assert not s.cards["a"].card.outside_story and not s.is_click_connecting()


def test_every_key_is_bound_and_no_two_actions_share_one(window):
    card_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Card")
    card_keys = {a.shortcut().toString() for a in card_menu.actions() if not a.isSeparator()}
    table = {QKeySequence(k).toString() for k in KEYS.values()}
    assert card_keys <= table  # the Card menu's keys all come from shortcuts.KEYS
    seen: dict[str, str] = {}
    for act in [*window.actions(), *window.view.actions()]:
        for seq in act.shortcuts():
            key = seq.toString()
            assert key not in seen, f"{key}: {seen[key]} and {act.text()}"
            seen[key] = act.text()
    assert table <= set(seen)  # and every key in the table belongs to an action


def test_alt_c_opens_the_card_menu(window, qapp):
    window.show()
    window.activateWindow()
    qapp.processEvents()
    assert window.menu_peek._menu_for("c").text() == "&Card"


# ----- K2: the right-click menus show the keys ------------------------------------------
def menu_texts(menu):
    out = []
    for act in menu.actions():
        if act.menu() is not None:
            out += menu_texts(act.menu())
        elif not act.isSeparator():
            out.append(act.text())
    return out


def test_right_click_menus_show_the_same_keys_as_the_shortcuts(window, qapp):
    s = setup(window, qapp)
    s.highlight_paths(s.cards["a"])  # so "Clear highlight" (Esc) is offered too
    native = QKeySequence.SequenceFormat.NativeText
    real = {seq.toString(native) for act in [*window.actions(), *window.view.actions()]
            for seq in act.shortcuts()}
    edge = next(iter(s.edges))
    menus = {"group": s.build_context_menu(s.cards["Y"], s.cards["Y"].pos()),
             "card": s.build_context_menu(s.cards["x"], s.cards["x"].pos()),
             "arrow": s.build_context_menu(edge, edge.boundingRect().center()),
             "canvas": s.build_context_menu(None, s.cards["x"].pos())}
    texts = {name: menu_texts(m) for name, m in menus.items()}
    for name, labels in texts.items():
        for label in labels:
            if "\t" in label:
                key = label.split("\t")[1]
                assert key in real | {"Enter", "Esc"}, f"{name}: {label!r} shows a key nothing has"
    assert "Collapse group\tC" in texts["group"] and "Auto-arrange cards\tCtrl+Shift+A" in texts["group"]
    assert "Connect to…\tL" in texts["card"] and "Show details\tD" in texts["card"]
    assert "Not part of the story\tO" in texts["card"] and "Before and after\tH" in texts["card"]
    assert "Read from here\tCtrl+Shift+R" in texts["card"] and "Clear highlight\tEsc" in texts["card"]
    assert "Reverse direction\tR" in texts["arrow"] and "Edit arrow…\tEnter" in texts["arrow"]
    assert "Paste here\tCtrl+V" in texts["canvas"]


def test_a_menu_item_with_a_key_still_acts_when_clicked(window, qapp):
    s = setup(window, qapp)
    menu = s.build_context_menu(s.cards["Y"], s.cards["Y"].pos())
    next(a for a in menu.actions() if a.text() == "Collapse group\tC").trigger()
    assert s.cards["Y"].card.collapsed
