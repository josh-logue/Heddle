"""Minimap: an overview of the board in the canvas's corner that steers the view,
minimises (button or Ctrl+Shift+M) but never closes, and stays cheap to redraw."""
import time

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from conftest import wait_until
from warpingweft import theme
from warpingweft.minimap import MAP_SIZE, REBUILD_DELAY_MS
from warpingweft.model import CardData


def shown(window, qapp):
    window.show()
    qapp.processEvents()
    return window.minimap


def spread_board(scene):
    a = scene.add_card(CardData(title="A", x=0, y=0))
    b = scene.add_card(CardData(title="B", x=3000, y=0))
    c = scene.add_card(CardData(title="C", x=0, y=2000))
    scene.mark_modified()
    return a, b, c


def settle(qapp):
    """Let a pending minimap redraw happen (however long a busy machine takes)."""
    qapp.processEvents()
    mm = next(w for w in qapp.topLevelWidgets() if hasattr(w, "minimap") and w.isVisible()).minimap
    wait_until(lambda: not mm._rebuild_timer.isActive(), REBUILD_DELAY_MS + 5000)
    qapp.processEvents()


def pixel(mm, scene_point, nudge=QPointF()):
    """Colour the minimap shows at a board point (optionally nudged, in map pixels)."""
    img = mm.grab().toImage()
    p = (mm.scene_to_map(scene_point) + nudge).toPoint()
    return QColor(img.pixel(round(p.x() * img.devicePixelRatio()), round(p.y() * img.devicePixelRatio())))


def test_sits_in_the_bottom_right_corner_and_follows_resizes(window, qapp):
    mm = shown(window, qapp)
    v = window.view
    assert mm.size() == MAP_SIZE
    assert mm.geometry().right() < v.width() and v.width() - mm.geometry().right() < 20
    assert mm.geometry().bottom() < v.height() and v.height() - mm.geometry().bottom() < 20
    window.resize(1300, 800)
    qapp.processEvents()
    assert v.width() - mm.geometry().right() < 20 and v.height() - mm.geometry().bottom() < 20


def test_mapping_round_trips(window, qapp, scene):
    mm = shown(window, qapp)
    spread_board(scene)
    settle(qapp)
    for p in (QPointF(0, 0), QPointF(1500, 700), QPointF(-40, 2100)):
        back = mm.map_to_scene(mm.scene_to_map(p))
        assert abs(back.x() - p.x()) < 1e-6 and abs(back.y() - p.y()) < 1e-6


def test_the_whole_board_and_the_screen_are_on_the_map(window, qapp, scene):
    mm = shown(window, qapp)
    cards = spread_board(scene)
    window.view.centerOn(-5000, -5000)  # looking at empty space far away
    settle(qapp)
    area = mm.map_rect().adjusted(-0.01, -0.01, 0.01, 0.01)
    for item in cards:
        assert area.contains(mm.scene_to_map(item.card_scene_rect().center()))
    assert area.contains(mm.scene_to_map(window.view.visible_scene_rect().center()))


def test_click_moves_the_view_there(window, qapp, scene):
    mm = shown(window, qapp)
    a, b, c = spread_board(scene)
    window.view.centerOn(a.card_scene_rect().center())
    settle(qapp)
    target = c.card_scene_rect().center()
    QTest.mouseClick(mm, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     mm.scene_to_map(target).toPoint())
    qapp.processEvents()
    centre = window.view.visible_scene_rect().center()
    tolerance = 2 / mm._transform(mm.extent())[0]  # a couple of map pixels
    assert abs(centre.x() - target.x()) < tolerance and abs(centre.y() - target.y()) < tolerance


def test_dragging_the_box_pans_without_jumping(window, qapp, scene):
    mm = shown(window, qapp)
    spread_board(scene)
    window.view.centerOn(1500, 1000)
    settle(qapp)
    before = window.view.visible_scene_rect().center()
    start = mm.scene_to_map(before + QPointF(100, 50)).toPoint()  # inside the box, off-centre
    QTest.mousePress(mm, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    qapp.processEvents()
    pressed = window.view.visible_scene_rect().center()
    s = mm._transform(mm.extent())[0]
    assert abs(pressed.x() - before.x()) < 2 / s  # grabbing the box doesn't recentre it
    QTest.mouseMove(mm, start + QPoint(10, 0))
    QTest.mouseRelease(mm, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(10, 0))
    qapp.processEvents()
    after = window.view.visible_scene_rect().center()
    assert after.x() - before.x() > 5 / s  # moved right by about 10 map pixels
    assert abs(after.y() - before.y()) < 2 / s


def test_box_tracks_pan_and_zoom(window, qapp, scene):
    shown(window, qapp)
    spread_board(scene)
    settle(qapp)
    moves = []
    window.view.viewport_changed.connect(lambda: moves.append(window.view.visible_scene_rect()))
    window.view.pan_by(-200, 0)
    assert moves and moves[-1].center() == window.view.visible_scene_rect().center()
    window.view.zoom_by(0.5)
    assert len(moves) >= 2 and moves[-1].width() > moves[0].width()
    # what the box is drawn from is exactly what's on screen
    assert window.view.visible_scene_rect() == window.view.mapToScene(
        window.view.viewport().rect()).boundingRect()


def test_wheel_on_the_map_zooms_the_board(window, qapp, scene):
    mm = shown(window, qapp)
    spread_board(scene)
    settle(qapp)
    from PySide6.QtCore import QPointF as P
    from PySide6.QtGui import QWheelEvent
    before = window.view.current_scale()
    pos = P(mm.map_rect().center())
    ev = QWheelEvent(pos, P(mm.mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    mm.wheelEvent(ev)
    assert window.view.current_scale() < before


def test_double_click_fits_the_board(window, qapp, scene):
    mm = shown(window, qapp)
    spread_board(scene)
    window.view.zoom_by(3)
    settle(qapp)
    QTest.mouseDClick(mm, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      mm.map_rect().center().toPoint())
    qapp.processEvents()
    visible = window.view.visible_scene_rect()
    for item in scene.cards.values():
        assert visible.contains(item.card_scene_rect())


def test_bursts_of_changes_redraw_once(window, qapp, scene):
    mm = shown(window, qapp)
    item = scene.add_card(CardData(title="A"))
    settle(qapp)
    mm.repaint()
    start = mm.rebuild_count
    for i in range(50):
        item.setPos(i, 0)
        scene.modified.emit()
    qapp.processEvents()
    settle(qapp)
    mm.repaint()
    assert mm.rebuild_count - start == 1


def test_panning_alone_reuses_the_picture(window, qapp, scene):
    mm = shown(window, qapp)
    spread_board(scene)
    window.view.centerOn(1500, 1000)
    settle(qapp)
    mm.repaint()
    start = mm.rebuild_count
    window.view.pan_by(30, 30)  # box stays inside the cards' extent: same mapping
    mm.repaint()
    assert mm.rebuild_count == start


def test_cards_show_in_their_colours_and_states(window, qapp, scene):
    mm = shown(window, qapp)
    a = scene.add_card(CardData(title="A", x=0, y=0, width=400, height=300, color="#d04040"))
    b = scene.add_card(CardData(title="B", x=2000, y=0, width=400, height=300, color="#d04040"))
    scene.mark_modified()
    window.view.centerOn(-6000, -6000)  # keep the on-screen box away from the cards
    settle(qapp)
    assert pixel(mm, a.card_scene_rect().center()).red() > 180
    # faded (by a filter or a highlight): the card washes out toward the background
    b.dimmed = True
    b._apply_opacity()
    settle(qapp)
    lit, faded = pixel(mm, a.card_scene_rect().center()), pixel(mm, b.card_scene_rect().center())
    bg = theme.current().canvas_bg
    assert abs(faded.green() - bg.green()) < abs(lit.green() - bg.green())


def test_selected_cards_get_an_outline(window, qapp, scene):
    mm = shown(window, qapp)
    a = scene.add_card(CardData(title="A", x=0, y=0, width=400, height=300, color="#40a040"))
    scene.add_card(CardData(title="B", x=2000, y=1000))
    scene.mark_modified()
    window.view.centerOn(-6000, -6000)
    settle(qapp)
    r = a.card_scene_rect()
    edge = QPointF(r.left(), r.center().y())
    just_outside = QPointF(-1.5, 0)  # the outline sits just outside the block
    before = pixel(mm, edge, just_outside)
    a.setSelected(True)
    settle(qapp)
    after = pixel(mm, edge, just_outside)
    assert after != before
    sel = theme.current().selected
    assert abs(after.red() - sel.red()) < 60  # the selection colour (orange)


def test_follows_the_theme(window, qapp, scene):
    mm = shown(window, qapp)
    window.set_dark_mode(False)
    qapp.processEvents()
    corner = QPoint(MAP_SIZE.width() // 2, 3)  # frame background, nothing drawn there
    light = QColor(mm.grab().toImage().pixel(corner))
    window.set_dark_mode(True)
    qapp.processEvents()
    dark = QColor(mm.grab().toImage().pixel(corner))
    assert dark.lightness() < light.lightness()


def test_button_shows_only_while_hovering_the_expanded_map(window, qapp):
    from PySide6.QtCore import QEvent
    mm = shown(window, qapp)
    assert not mm.button.isVisible()             # doesn't cover the map's corner
    qapp.sendEvent(mm, QEvent(QEvent.Type.Enter))
    assert mm.button.isVisible()
    qapp.sendEvent(mm, QEvent(QEvent.Type.Leave))
    assert not mm.button.isVisible()
    mm.set_expanded(False)
    assert mm.button.isVisible()                 # minimised: the button is all there is


def test_minimise_and_expand_with_the_button(window, qapp):
    from PySide6.QtCore import QEvent
    mm = shown(window, qapp)
    assert mm.is_expanded()
    qapp.sendEvent(mm, QEvent(QEvent.Type.Enter))
    mm.button.click()
    qapp.processEvents()
    assert not mm.is_expanded() and mm.isVisible()  # minimised, still there
    assert mm.width() < 40 and mm.height() < 40
    assert not window.act_minimap.isChecked()
    mm.button.click()
    qapp.processEvents()
    assert mm.is_expanded() and mm.size() == MAP_SIZE and window.act_minimap.isChecked()


def test_hotkey_minimises_but_never_closes(window, qapp):
    mm = shown(window, qapp)
    window.focus_canvas()
    qapp.processEvents()
    for expected in (False, True, False):
        QTest.keyClick(window.view.viewport(), Qt.Key.Key_M,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        qapp.processEvents()
        assert mm.is_expanded() is expected
        assert mm.isVisible()
    assert window.act_minimap.shortcut().toString() == "Ctrl+Shift+M"


def test_minimised_state_is_remembered(qapp):
    from warpingweft.main_window import MainWindow
    first = MainWindow()
    first.minimap.set_expanded(False)
    first.setWindowModified(False)
    first.close()
    first.deleteLater()
    second = MainWindow()
    try:
        assert not second.minimap.is_expanded()
        assert not second.act_minimap.isChecked()
    finally:
        second.setWindowModified(False)
        second.close()
        second.deleteLater()


def test_clicks_never_reach_the_board_or_take_focus(window, qapp, scene):
    mm = shown(window, qapp)
    item = scene.add_card(CardData(title="A"))
    item.setSelected(True)
    window.focus_canvas()
    qapp.processEvents()
    QTest.mouseClick(mm, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     mm.map_rect().center().toPoint())
    qapp.processEvents()
    assert item.isSelected()                       # no rubber-band click on the board
    assert mm.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert mm.button.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_space_does_not_start_panning_over_the_minimap(window, qapp, monkeypatch):
    mm = shown(window, qapp)
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, "widgetAt", staticmethod(lambda *a: mm))
    monkeypatch.setattr("warpingweft.view.QCursor.pos",
                        staticmethod(lambda: mm.mapToGlobal(mm.rect().center())))
    assert window.view._pointer_over_canvas() is False


def test_not_in_exported_images(window, qapp, scene):
    """The minimap is a widget over the view, not a scene item, so exports skip it."""
    shown(window, qapp)
    assert window.minimap not in scene.items()
    assert window.minimap.parentWidget() is window.view


def test_redraw_is_cheap_on_a_big_board(window, qapp, scene):
    mm = shown(window, qapp)
    for i in range(1000):
        scene.add_card(CardData(title=f"C{i}", x=(i % 40) * 260, y=(i // 40) * 180))
    scene.mark_modified()
    settle(qapp)
    mm.repaint()
    t0 = time.perf_counter()
    for _ in range(5):
        mm._dirty = True
        mm.repaint()
    per = (time.perf_counter() - t0) / 5
    assert per < 0.05, f"{per * 1000:.1f} ms per redraw"
