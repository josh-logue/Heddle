"""The menu bar is hidden by default: every menu is in the toolbar's ☰ button (with
Panels and Board drop-downs for the most used), shortcuts still work, the toolbar
can't be hidden, and Alt (or a setting) brings the menu bar back."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from warpingweft import settings


def all_actions(menu):
    out = []
    for act in menu.actions():
        out.append(act)
        if act.menu() is not None:
            out += all_actions(act.menu())
    return out


def bar_actions(window):
    out = []
    for top in window.menuBar().actions():
        out += all_actions(top.menu())
    return out


def test_menu_bar_hidden_and_every_item_in_the_menu_button(window, qapp):
    window.show()
    qapp.processEvents()
    assert not window.menuBar().isVisible()
    assert [a.text() for a in window.main_menu.actions()] == ["&File", "&Edit", "&View", "&Help"]
    reachable = set(map(id, all_actions(window.main_menu)))
    missing = [a.text() for a in bar_actions(window) if id(a) not in reachable and not a.isSeparator()]
    assert missing == []
    assert window.menu_button.menu() is window.main_menu and window.menu_button.isVisible()


def test_panels_and_board_buttons(window):
    panels = [a.text() for a in window.panels_menu.actions()]
    assert panels == [window.act_card_panel.text(), window.act_filter.text(), window.act_strands.text(),
                      window.act_routes.text(),
                      window.act_checks.text(), window.act_reader.text(), window.act_minimap.text()]
    board = [a.text() for a in window.board_menu.actions() if not a.isSeparator()]
    assert board == ["Card &Face", "&Arrows", "Ca&nvas", window.act_board_options.text(),
                     window.act_story_tools.text()]


def test_shortcuts_work_with_the_menu_bar_hidden(window, qapp):
    window.show()
    window.focus_canvas()
    qapp.processEvents()
    assert not window.menuBar().isVisible()
    QTest.keyClick(window.view.viewport(), Qt.Key.Key_O,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    qapp.processEvents()
    assert window.routes_dock.isVisible()


def test_the_toolbar_cant_be_lost(window, qapp):
    tb = window._toolbar
    assert not tb.toggleViewAction().isVisible() and window.createPopupMenu() is None
    tb.hide()
    window._save_window_state()                      # a layout saved with it hidden...
    window._restore_window_state()
    assert not tb.isHidden()                          # ...still brings it back


def test_setting_shows_the_menu_bar(window, qapp):
    window.show()
    settings.set("show_menu_bar", True)
    window._apply_settings()
    qapp.processEvents()
    assert window.menuBar().isVisible()


def test_tapping_alt_shows_the_menu_bar_until_tapped_again(window, qapp):
    window.show()
    window.activateWindow()
    qapp.processEvents()
    peek = window.menu_peek
    peek.eventFilter(None, _key(qapp, "press", Qt.Key.Key_Alt))
    peek.eventFilter(None, _key(qapp, "release", Qt.Key.Key_Alt))
    assert window.menuBar().isVisible() and peek.peeking
    peek.eventFilter(None, _key(qapp, "press", Qt.Key.Key_Alt))
    peek.eventFilter(None, _key(qapp, "release", Qt.Key.Key_Alt))
    assert not window.menuBar().isVisible()
    # Esc hides it too, and so does a click elsewhere
    peek.show()
    assert peek.eventFilter(None, _key(qapp, "press", Qt.Key.Key_Escape)) and not window.menuBar().isVisible()
    peek.show()
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton)
    assert not window.menuBar().isVisible()


def test_alt_with_another_key_isnt_a_tap(window, qapp):
    window.show()
    window.activateWindow()
    qapp.processEvents()
    peek = window.menu_peek
    peek.eventFilter(None, _key(qapp, "press", Qt.Key.Key_Alt))
    peek.eventFilter(None, _key(qapp, "press", Qt.Key.Key_Tab, Qt.KeyboardModifier.AltModifier))  # Alt+Tab
    peek.eventFilter(None, _key(qapp, "release", Qt.Key.Key_Alt))
    assert not window.menuBar().isVisible()


def test_alt_letter_opens_that_menu(window, qapp):
    window.show()
    window.activateWindow()
    qapp.processEvents()
    peek = window.menu_peek
    assert peek.eventFilter(None, _key(qapp, "press", Qt.Key.Key_V, Qt.KeyboardModifier.AltModifier))
    assert window.menuBar().isVisible() and window.menuBar().activeAction().text() == "&View"
    window.menuBar().activeAction().menu().close()
    window.menuBar().setActiveAction(None)
    peek._maybe_hide()
    assert not window.menuBar().isVisible()


def _key(qapp, kind, key, mods=Qt.KeyboardModifier.NoModifier):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    etype = QEvent.Type.KeyPress if kind == "press" else QEvent.Type.KeyRelease
    if key == Qt.Key.Key_Alt and kind == "press":
        mods = Qt.KeyboardModifier.AltModifier
    return QKeyEvent(etype, key, mods)


def test_snap_to_grid_is_in_view_not_in_the_boards_menus(window):
    """Snapping is a setting of this computer: the Board button holds only options saved
    with the board."""
    view = next(a.menu() for a in window.menuBar().actions() if a.text() == "&View")
    assert window.act_snap in view.actions()
    in_board = {id(a) for sub in window._board_menus for a in sub.actions()}
    assert id(window.act_snap) not in in_board
