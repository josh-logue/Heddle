"""Review finding E: canvas-editing shortcuts (Del, Ctrl+A/X/C/V/D/E, H) act on the
board only while the canvas has keyboard focus, not while a side panel's list does.
Their menu entries still work from anywhere."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from heddle.model import BoardData, CardData, save_board

CTRL = Qt.KeyboardModifier.ControlModifier


def setup(window, qapp):
    s = window.scene
    a = s.add_card(CardData(title="A", characters=["Mabel"]))
    b = s.add_card(CardData(title="B", x=400))
    s.add_connection(a, b)
    s.mark_modified()
    window.show()
    window.activateWindow()
    qapp.processEvents()
    return s, a, b


def focus(widget, qapp):
    widget.setFocus()
    qapp.processEvents()
    assert QApplication.focusWidget() is widget


def panel_lists(window, qapp):
    """The focusable lists in each side panel."""
    window.filter_dock.show()
    window.checks_dock.show()
    qapp.processEvents()
    return [window.filter_panel.tree, window.checks_panel.tree]


def test_canvas_shortcuts_do_nothing_while_a_panel_list_has_focus(window, qapp):
    s, a, b = setup(window, qapp)
    for widget in panel_lists(window, qapp):
        a.setSelected(True)
        focus(widget, qapp)
        for key, mods in ((Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier),
                          (Qt.Key.Key_X, CTRL), (Qt.Key.Key_D, CTRL), (Qt.Key.Key_H, Qt.KeyboardModifier.NoModifier)):
            QTest.keyClick(widget, key, mods)
        assert len(s.cards) == 2 and not s.has_highlight(), widget
        s.clearSelection()
        QTest.keyClick(widget, Qt.Key.Key_A, CTRL)
        assert not s.selectedItems()


def test_the_reader_panel_does_not_trigger_them_either(window, qapp):
    s, a, b = setup(window, qapp)
    window.read_from(a)
    qapp.processEvents()
    assert QApplication.focusWidget() is window.path_reader
    a.setSelected(True)
    QTest.keyClick(window.path_reader, Qt.Key.Key_Delete)
    assert len(s.cards) == 2


def test_they_work_with_the_canvas_focused(window, qapp):
    s, a, b = setup(window, qapp)
    window.focus_canvas()
    qapp.processEvents()
    vp = window.view.viewport()
    QTest.keyClick(vp, Qt.Key.Key_A, CTRL)
    assert a.isSelected() and b.isSelected()
    s.clearSelection()
    a.setSelected(True)
    QTest.keyClick(vp, Qt.Key.Key_H)
    assert s.highlight_owner() == "paths"
    QTest.keyClick(vp, Qt.Key.Key_D, CTRL)
    assert len(s.cards) == 3
    s.clearSelection()
    b.setSelected(True)
    QTest.keyClick(vp, Qt.Key.Key_Delete)
    assert b.card.id not in s.cards


def test_menu_entries_still_work_from_a_panel(window, qapp):
    s, a, b = setup(window, qapp)
    focus(panel_lists(window, qapp)[0], qapp)
    a.setSelected(True)
    window.act_delete.trigger()          # what clicking Edit → Delete Selected does
    assert a.card.id not in s.cards


@pytest.mark.parametrize("how", ["new", "open", "checks"])
def test_the_canvas_gets_focus_back(window, qapp, tmp_path, how):
    s, a, b = setup(window, qapp)
    tree = panel_lists(window, qapp)[1]
    focus(tree, qapp)
    if how == "new":
        window.setWindowModified(False)
        window.new_board()
    elif how == "open":
        path = tmp_path / "b.json"
        save_board(BoardData(cards=[CardData(title="X")]), path)
        window.setWindowModified(False)
        window.open_path(path)
    else:
        window.checks_panel.recheck()
        dead_end = tree.topLevelItem(0).child(0)   # "B" leads nowhere
        window.checks_panel._on_clicked(dead_end)
    qapp.processEvents()
    assert QApplication.focusWidget() is window.view
