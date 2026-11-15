"""Review finding F: with "Curved, avoiding cards" routing, arrows are drawn as plain
curves while cards are dragged or nudged (routing around cards on every mouse move
was slow) and routed around cards once the move ends."""
import time

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from warpingweft.edge_item import AVOID_SAMPLES
from warpingweft.model import CardData
from conftest import wait_until


def crosses(edge, item) -> bool:
    rect = item.card_scene_rect()
    return any(rect.contains(edge._line.pointAtPercent(k / AVOID_SAMPLES))
               for k in range(AVOID_SAMPLES + 1))


def blocked_board(scene):
    """A → B with a card sitting right in the way, routing set to avoid cards."""
    a = scene.add_card(CardData(title="A", x=0, y=0))
    b = scene.add_card(CardData(title="B", x=700, y=40))
    blocker = scene.add_card(CardData(title="In the way", x=350, y=10))
    edge = scene.add_connection(a, b)
    scene.set_display_option("arrow_routing", "avoid")
    assert not crosses(edge, blocker)
    return a, b, blocker, edge


def settled(scene) -> None:
    """Wait until moves, nudge bursts and the re-route they schedule are all over."""
    wait_until(lambda: not scene.is_moving() and not scene._nudge_timer.isActive()
               and not scene._reroute_timer.isActive())


def test_plain_curves_while_moving_then_routed_around(scene):
    a, b, blocker, edge = blocked_board(scene)
    scene.begin_move()
    b.moveBy(0, 5)                           # a drag step
    assert crosses(edge, blocker)            # plain curve: straight through, for now
    scene.end_move()
    settled(scene)
    assert not crosses(edge, blocker)


def test_a_click_without_moving_does_not_reroute(scene):
    a, b, blocker, edge = blocked_board(scene)
    settled(scene)                           # let switching modes finish its own re-route
    assert not scene._reroute_timer.isActive()
    scene.begin_move()
    scene.end_move(moved=False)
    assert not scene._reroute_timer.isActive()


def test_nudges_route_simply_until_the_burst_settles(scene):
    a, b, blocker, edge = blocked_board(scene)
    scene.reset_history()
    b.setSelected(True)
    scene.nudge_selected(0, 10)
    assert scene.is_moving() and crosses(edge, blocker)
    settled(scene)
    assert not scene.is_moving() and not crosses(edge, blocker)
    assert scene.history.can_undo()          # still one undo step for the burst


def test_a_real_mouse_drag(window, qapp):
    s = window.scene
    a, b, blocker, edge = blocked_board(s)
    window.resize(1400, 800)
    window.show()
    window.view.reset_zoom()
    window.view.centerOn(blocker)
    qapp.processEvents()
    vp = window.view.viewport()
    grab = b.card_scene_rect().center() + QPointF(0, 10)    # its body, not the handle
    start = window.view.mapFromScene(grab)
    end = window.view.mapFromScene(grab + QPointF(0, 30))

    def send(kind, at, buttons):
        p = QPointF(at)
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        QApplication.sendEvent(vp, QMouseEvent(kind, p, vp.mapToGlobal(p), button, buttons,
                                               Qt.KeyboardModifier.NoModifier))

    left = Qt.MouseButton.LeftButton
    send(QEvent.Type.MouseButtonPress, start, left)
    send(QEvent.Type.MouseMove, (start + end) / 2, left)
    send(QEvent.Type.MouseMove, end, left)
    assert s.is_moving() and crosses(edge, blocker)
    send(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
    assert not s.is_moving()
    settled(s)
    assert not crosses(edge, blocker)


def test_losing_the_mouse_mid_drag_ends_the_move(window, qapp):
    s = window.scene
    a, b, blocker, edge = blocked_board(s)
    window.show()
    qapp.processEvents()
    s.begin_move()
    # What the scene tells the card when the mouse is taken from it (e.g. a dialog opened).
    s.sendEvent(b, QEvent(QEvent.Type.UngrabMouse))
    assert not s.is_moving()


def test_dragging_stays_quick_on_a_big_board(scene):
    items = [scene.add_card(CardData(title=f"C{i}", x=(i % 25) * 300, y=(i // 25) * 200))
             for i in range(500)]
    for i in range(499):
        if i % 25 != 24:
            scene.add_connection(items[i], items[i + 1])
    hub = items[262]
    for k in (0, 24, 480, 499, 100, 400):
        scene.add_connection(hub, items[k])   # long arrows across the board
    scene.set_display_option("arrow_routing", "avoid")
    scene.begin_move()
    start = time.perf_counter()
    for _ in range(20):
        hub.moveBy(1, 0)
    per_move = (time.perf_counter() - start) / 20
    scene.end_move()
    assert per_move < 0.005, f"{per_move * 1000:.1f} ms per move"   # was ~23 ms
