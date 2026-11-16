"""The Card List lists every card on the board as a tree of its groups, in story order
(reading order with story tools off), and follows the canvas both ways. A card folded
inside a collapsed group selects the group, leaving the board alone, until Enter
unfolds it."""
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from heddle.graph import StoryGraph
from heddle.model import KIND_GROUP, KIND_STRAND, BoardData, CardData, ConnectionData
from tests.conftest import wait_until


def story_board() -> BoardData:
    """Act (group) holds b and Scene (group) holding c; a leads into the act, which
    leads to d. A strand card and a card outside the story sit at the top."""
    cards = [
        CardData(id="d", title="Ending", x=1400, y=0),
        CardData(id="A", title="Act", kind=KIND_GROUP, x=400, y=0),
        CardData(id="b", title="Meeting", parent="A", x=420, y=60),
        CardData(id="S", title="Scene", kind=KIND_GROUP, parent="A", x=420, y=300),
        CardData(id="c", title="Chase", parent="S", x=440, y=360),
        CardData(id="a", title="Opening", x=0, y=200),
        CardData(id="r", title="Rowan", kind=KIND_STRAND, strand_kind="characters", strand="Rowan",
                 x=0, y=-400),
        CardData(id="n", title="Notes", outside_story=True, x=900, y=-400),
    ]
    conns = [ConnectionData("a", "b", id="ab"), ConnectionData("b", "c", id="bc"),
             ConnectionData("c", "d", id="cd")]
    return BoardData(cards=cards, connections=conns)


@pytest.fixture
def panel(window, qapp):
    window.scene.load_board_data(story_board())
    window.card_list._timer.setInterval(10)
    window.show()  # the list only builds while it's on screen
    window.card_list_dock.show()
    qapp.processEvents()
    return window.card_list


def texts(panel) -> list[str]:
    return [panel._rows[i].text(0) for i in panel.row_ids()]


def depth(panel, cid) -> int:
    n, item = 0, panel._rows[cid].parent()
    while item is not None:
        n, item = n + 1, item.parent()
    return n


def pick(panel, qapp, *ids) -> None:
    """Click the rows as a user would (Ctrl-click for the rest)."""
    tree = panel.tree
    for n, cid in enumerate(ids):
        item = panel._rows[cid]
        tree.scrollToItem(item)
        rect = tree.visualItemRect(item)
        mods = Qt.KeyboardModifier.ControlModifier if n else Qt.KeyboardModifier.NoModifier
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, mods, rect.center())
    qapp.processEvents()


def selected(scene) -> set[str]:
    return {i.card.id for i in scene.selectedItems() if hasattr(i, "card")}


# ----- the ordering helper (pure) ---------------------------------------------------------
def test_outline_puts_groups_where_their_first_card_comes():
    board = story_board()
    out = StoryGraph(board.cards, board.connections).outline()
    # Chain by chain in reading order of each chain's top-left card; along a chain,
    # the Act comes where its first card (Meeting) does.
    assert out[""] == ["r", "n", "a", "A", "d"]
    assert out["A"] == ["b", "S"] and out["S"] == ["c"]


def test_outline_by_position_reads_top_to_bottom_left_to_right():
    board = story_board()
    out = StoryGraph(board.cards, board.connections).outline(by_story=False)
    assert out[""] == ["r", "n", "A", "d", "a"]


def test_outline_ignores_a_card_that_names_itself_as_its_group():
    cards = [CardData(id="g", title="Odd", kind=KIND_GROUP, parent="g")]
    assert StoryGraph(cards, []).outline() == {"": ["g"]}


# ----- the panel -----------------------------------------------------------------------
def test_it_lists_every_card_nested_as_on_the_board(panel):
    assert panel.row_ids() == ["r", "n", "a", "A", "b", "S", "c", "d"]
    assert depth(panel, "b") == 1 and depth(panel, "c") == 2 and depth(panel, "r") == 0
    assert texts(panel)[2:4] == ["Opening", "Act · 2"]      # a group counts its own cards
    assert panel._rows["r"].text(0) == "☺ Rowan"            # strand cards are marked
    assert panel._rows["n"].font(0).italic()                # outside the story
    assert panel._rows["A"].font(0).bold()
    assert panel.summary.text() == "6 cards · 2 groups"


def test_story_tools_off_lists_in_reading_order(window, panel):
    window.scene.set_display_option("story_tools", False)
    wait_until(lambda: panel.row_ids()[-1] == "a")  # the lowest card comes last


def test_it_follows_edits_undo_and_a_new_board(window, panel):
    s = window.scene
    s.reset_history()
    s.cards["d"].card.title = "Finale"
    s.mark_modified()
    wait_until(lambda: panel._rows["d"].text(0) == "Finale")
    added = s.add_card(CardData(title="Epilogue", x=2000, y=900))
    s.set_parent(added, "A")
    s.mark_modified()
    wait_until(lambda: added.card.id in panel._rows)
    assert depth(panel, added.card.id) == 1 and panel._rows["A"].text(0) == "Act · 3"
    s.flush_history()
    assert s.undo()
    wait_until(lambda: added.card.id not in panel._rows)
    window.scene.load_board_data(BoardData(cards=[CardData(id="z", title="Fresh")]))
    window.scene.reset_history()  # as opening a board does
    wait_until(lambda: panel.row_ids() == ["z"])


def test_it_waits_while_hidden_and_catches_up_when_shown(window, panel, qapp):
    window.card_list_dock.hide()
    qapp.processEvents()
    window.scene.add_card(CardData(id="late", title="Late"))
    window.scene.mark_modified()
    qapp.processEvents()
    assert not panel._timer.isActive() and "late" not in panel._rows
    window.card_list_dock.show()
    qapp.processEvents()
    assert "late" in panel._rows


def test_clicking_a_row_selects_and_centres_the_card(window, panel, qapp):
    s = window.scene
    window.view.centerOn(-3000, -3000)
    pick(panel, qapp, "d")
    assert selected(s) == {"d"}
    centre = window.view.mapToScene(window.view.viewport().rect().center())
    assert (centre - s.cards["d"].card_scene_rect().center()).manhattanLength() < 5
    assert panel.tree.hasFocus() or not window.isActiveWindow()  # the keyboard stays in the list
    pick(panel, qapp, "a", "b")
    assert selected(s) == {"a", "b"}


def test_selecting_on_the_canvas_picks_the_rows(window, panel, qapp):
    s = window.scene
    s.clearSelection()
    s.cards["c"].setSelected(True)
    s.cards["n"].setSelected(True)
    qapp.processEvents()
    assert panel.selected_ids() == ["n", "c"]
    s.clearSelection()
    qapp.processEvents()
    assert panel.selected_ids() == []


def test_one_click_is_one_selection_change(window, panel, qapp):
    changes = []
    window.scene.selectionChanged.connect(lambda: changes.append(selected(window.scene)))
    pick(panel, qapp, "b")
    qapp.processEvents()
    assert changes[-1] == {"b"} and panel.selected_ids() == ["b"]
    assert len([c for c in changes if c]) == 1  # no echo back and forth


def test_a_card_in_a_collapsed_group_selects_the_group_and_leaves_the_board(window, panel, qapp):
    s = window.scene
    s.set_collapsed([s.cards["A"]], True)
    s.flush_history()
    s.reset_history()
    window.setWindowModified(False)
    wait_until(lambda: panel._rows["A"].text(0) == "⊞ Act · 2")
    pick(panel, qapp, "c")
    assert selected(s) == {"A"}                 # the folded group stands for it
    assert s.cards["A"].card.collapsed and not s.cards["c"].isVisible()
    assert not s.history.can_undo() and not window.isWindowModified()
    assert panel.selected_ids() == ["c"]        # the list keeps the row picked
    assert "collapsed group “Act”" in window.statusBar().currentMessage()
    # Enter unfolds it, selects the card and hands the keyboard to the canvas.
    QTest.keyClick(panel.tree, Qt.Key.Key_Return)
    wait_until(lambda: window.view.hasFocus() or not window.isActiveWindow())
    assert not s.cards["A"].card.collapsed and s.cards["c"].isVisible()
    assert selected(s) == {"c"}
    s.flush_history()
    assert s.undo() and s.cards["A"].card.collapsed  # one undo step folds it again


def test_double_click_focuses_the_canvas(window, panel, qapp):
    window.show()
    window.activateWindow()
    qapp.processEvents()
    item = panel._rows["d"]
    rect = panel.tree.visualItemRect(item)
    pick(panel, qapp, "d")  # a real double-click starts with a press on the row
    QTest.mouseDClick(panel.tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      rect.center())
    wait_until(lambda: window.view.hasFocus() or not window.isActiveWindow())
    assert selected(window.scene) == {"d"}


def test_the_trees_own_folding_and_the_selection_survive_a_rebuild(window, panel, qapp):
    s = window.scene
    panel._rows["A"].setExpanded(False)
    s.clearSelection()
    s.cards["d"].setSelected(True)
    qapp.processEvents()
    s.cards["a"].card.title = "Prologue"
    s.mark_modified()
    wait_until(lambda: panel._rows["a"].text(0) == "Prologue")
    assert not panel._rows["A"].isExpanded()
    assert panel.selected_ids() == ["d"]


def test_rows_work_after_undo_rebuilds_every_card(window, panel, qapp):
    s = window.scene
    s.reset_history()
    s.cards["b"].card.title = "Meeting at dawn"
    s.mark_modified()
    s.flush_history()
    wait_until(lambda: panel._rows["b"].text(0) == "Meeting at dawn")
    assert s.undo()
    wait_until(lambda: panel._rows["b"].text(0) == "Meeting")
    pick(panel, qapp, "b")
    assert selected(s) == {"b"}


def test_text_typed_in_the_card_panel_is_kept_when_picking_another_card(window, panel, qapp):
    card_panel = window.card_panel
    window.card_dock.show()
    s = window.scene
    pick(panel, qapp, "a")
    assert card_panel.title_edit.text() == "Opening"
    card_panel.title_edit.setText("Opening night")
    card_panel.title_edit.textEdited.emit("Opening night")
    pick(panel, qapp, "d")
    assert s.cards["a"].card.title == "Opening night"


def test_the_panel_is_in_the_panels_menu_with_its_key(window):
    act = window.act_card_list
    assert act in window.panels_menu.actions()
    assert act.shortcut().toString() == "Ctrl+Shift+L"
    assert window.dockWidgetArea(window.card_list_dock) == window.dockWidgetArea(window.card_dock)


def test_a_large_board_lists_quickly(window, qapp):
    cards = []
    for g in range(50):
        cards.append(CardData(id=f"g{g}", title=f"Group {g}", kind=KIND_GROUP, x=g * 900, y=0))
        cards += [CardData(id=f"c{g}-{n}", title=f"Card {n}", parent=f"g{g}", x=g * 900 + 20, y=60 + n * 200)
                  for n in range(20)]
    conns = [ConnectionData(f"c{g}-{n}", f"c{g}-{n + 1}", id=f"e{g}-{n}") for g in range(50) for n in range(19)]
    window.scene.load_board_data(BoardData(cards=cards, connections=conns))
    window.show()
    window.card_list_dock.show()
    qapp.processEvents()
    panel = window.card_list
    assert len(panel.row_ids()) == 1050
    panel._shown = None
    start = time.perf_counter()
    panel.refresh()
    assert time.perf_counter() - start < 1.0  # a rebuild, graph included; well under on a normal machine


# ----- L2: sorting, the find box, the filter ------------------------------------------
def test_natural_order_ignores_case_and_reads_numbers():
    from heddle.card_list import natural_key
    titles = ["card 10", "Card 2", "apple", "Card 1"]
    assert sorted(titles, key=natural_key) == ["apple", "Card 1", "Card 2", "card 10"]


def test_sorting_by_title_or_position_is_remembered(window, panel, qapp):
    from heddle.card_list import SORT_KEY
    from heddle import settings
    panel.sort.setCurrentIndex(panel.sort.findData("title"))
    assert panel.row_ids() == ["A", "b", "S", "c", "d", "n", "a", "r"]  # A–Z, within groups
    assert settings.store().value(SORT_KEY) == "title"
    panel.sort.setCurrentIndex(panel.sort.findData("position"))
    assert panel.row_ids()[-1] == "a"
    other = type(panel)(window.scene)  # a new window's list starts the same way
    assert other.sort_mode() == "position"
    other.deleteLater()


def test_the_find_box_narrows_to_matches_and_their_groups(window, panel, qapp):
    panel._rows["A"].setExpanded(False)          # folded in the list...
    panel.search.setText("cha")
    assert panel.row_ids() == ["A", "S", "c"]     # Chase, with the groups around it
    assert panel._rows["S"].isExpanded() and panel._rows["A"].isExpanded()  # ...opened to show it
    grey = panel._rows["A"].foreground(0).color()
    assert grey != panel._rows["c"].foreground(0).color()  # groups listed only for context are greyed
    assert panel.summary.text() == "1 of 6 cards"
    QTest.keyClick(panel.search, Qt.Key.Key_Down)  # ↓ goes to the first match, which the canvas follows
    assert selected(window.scene) == {"c"}
    window.scene.clearSelection()  # (a selected card's group opens to show it)
    qapp.processEvents()
    QTest.keyClick(panel.search, Qt.Key.Key_Escape)
    assert panel.search.text() == "" and len(panel.row_ids()) == 8
    assert not panel._rows["A"].isExpanded()      # the list's own folding comes back


def test_a_selected_card_the_find_box_leaves_out_is_picked_again_after(window, panel, qapp):
    s = window.scene
    s.clearSelection()
    s.cards["d"].setSelected(True)
    qapp.processEvents()
    panel.search.setText("opening")
    assert panel.selected_ids() == []      # Ending isn't listed now; nothing breaks
    panel.search.clear()
    assert panel.selected_ids() == ["d"]


def test_filtered_out_cards_are_greyed_or_hidden(window, panel, qapp):
    s = window.scene
    s.cards["b"].card.tags = ["Act 1"]
    s.mark_modified()
    window.filter_panel.refresh()
    window.filter_panel._selection["tags"].add("act 1")
    window.filter_panel.apply()
    wait_until(lambda: panel.hide_dimmed.isVisible())
    normal = panel._rows["b"].foreground(0).color()
    wait_until(lambda: panel._rows["d"].foreground(0).color() != normal)
    assert "Hidden by the filter" in panel._rows["d"].toolTip(0)
    panel.hide_dimmed.setChecked(True)
    # Meeting is left, in its (dimmed) Act; everything else is hidden.
    assert panel.row_ids() == ["A", "b"]
    assert panel.summary.text() == "1 of 6 cards"
    window.filter_panel.clear_selection()
    wait_until(lambda: len(panel.row_ids()) == 8)
    assert not panel.hide_dimmed.isVisible()


# ----- L3: status column, searching all text, Go to Card --------------------------------
def test_the_status_column_is_an_option_remembered(window, panel, qapp):
    from heddle import settings
    from heddle.card_list import STATUS_KEY
    window.scene.cards["b"].card.status = "Draft"
    window.scene.mark_modified()
    wait_until(lambda: panel._rows["b"].text(1) == "Draft")
    assert panel.tree.isColumnHidden(1)           # off at first
    panel.act_status.setChecked(True)
    assert not panel.tree.isColumnHidden(1)
    assert panel._rows["A"].text(1) == ""         # groups have no status of their own
    assert settings.store().value(STATUS_KEY, type=bool)


def test_search_all_text_finds_descriptions_and_strands_and_says_where(window, panel, qapp):
    s = window.scene
    s.cards["d"].card.description = "The lighthouse goes dark."
    s.cards["b"].card.characters = ["Mabel"]
    s.mark_modified()
    qapp.processEvents()
    panel.search.setText("lighthouse")
    assert panel.row_ids() == []                  # titles only, at first
    assert panel.search.placeholderText() == "Find a card by title"
    panel.act_full_text.setChecked(True)
    assert panel.row_ids() == ["d"]
    assert panel._rows["d"].toolTip(0).startswith("Found in description:")
    assert panel.search.placeholderText() == "Find a card"
    panel.search.setText("mabel")
    assert panel.row_ids() == ["A", "b"]          # with the group around it, greyed
    panel.search.setText("chase")                 # a title match says nothing extra
    assert not panel._rows["c"].toolTip(0).startswith("Found in")


def go_to(window, qapp, text):
    dialog = window.go_to_card()
    qapp.processEvents()
    dialog.edit.setText(text)
    return dialog


def test_go_to_card_ranks_title_starts_first_then_words_then_text(window, panel, qapp):
    s = window.scene
    s.load_board_data(BoardData(cards=[
        CardData(id="1", title="Harbour at night", x=0),
        CardData(id="2", title="The harbour", x=300),
        CardData(id="3", title="Overharbouring", x=600),
        CardData(id="4", title="Market", description="Down by the harbour", x=900),
        CardData(id="5", title="Unrelated", x=1200),
    ]))
    s.reset_history()
    dialog = go_to(window, qapp, "harb")
    assert dialog.row_ids() == ["1", "2", "3", "4"]
    assert "Description" in dialog.list.item(3).text()
    dialog.edit.setText("")
    assert dialog.row_ids() == ["1", "4", "3", "2", "5"]  # everything, A–Z
    dialog.edit.setText("zzz")
    assert dialog.row_ids() == [] and dialog.hint.text() == "No card matches"
    dialog.reject()


def test_go_to_card_jumps_into_a_collapsed_group_and_focuses_the_canvas(window, panel, qapp):
    s = window.scene
    s.set_collapsed([s.cards["A"]], True)
    s.flush_history()
    dialog = go_to(window, qapp, "chase")
    QTest.keyClick(dialog.edit, Qt.Key.Key_Return)
    qapp.processEvents()
    assert not dialog.isVisible()
    assert not s.cards["A"].card.collapsed and selected(s) == {"c"}
    assert "Went to “Chase”" in window.statusBar().currentMessage()
    wait_until(lambda: window.view.hasFocus() or not window.isActiveWindow())


def test_go_to_card_arrow_keys_move_through_the_list_while_typing(window, panel, qapp):
    dialog = go_to(window, qapp, "")
    first = dialog.chosen_id()
    QTest.keyClick(dialog.edit, Qt.Key.Key_Down)
    assert dialog.chosen_id() == dialog.row_ids()[1] != first
    assert dialog.edit.hasFocus() or not dialog.isActiveWindow()
    QTest.keyClick(dialog.edit, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert selected(window.scene) == set()       # Esc goes nowhere


def test_go_to_card_names_the_group_of_a_repeated_title(window, qapp):
    s = window.scene
    s.load_board_data(BoardData(cards=[
        CardData(id="E", title="East Ward", kind=KIND_GROUP, x=0, y=0),
        CardData(id="w1", title="Warden", parent="E", x=20, y=60),
        CardData(id="w2", title="Warden", x=900, y=0),
    ]))
    s.reset_history()
    dialog = go_to(window, qapp, "warden")
    texts_ = {dialog.list.item(n).data(Qt.ItemDataRole.UserRole): dialog.list.item(n).text()
              for n in range(dialog.list.count())}
    assert texts_["w1"] == "Warden · East Ward"
    dialog.reject()


def test_go_to_card_is_in_the_edit_menu_with_ctrl_p(window):
    assert window.act_go_to.shortcut().toString() == "Ctrl+P"
    edit = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Edit")
    assert window.act_go_to in edit.actions()
