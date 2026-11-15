"""Dragging cards and groups into groups: the dragged item joins the group under the
pointer (not under its own centre, which for a big group can be far from where you
let go), and it's drawn above everything else while it moves."""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtTest import QTest

from warpingweft.model import KIND_GROUP, CardData
from warpingweft.scene import DRAG_LIFT


@pytest.fixture
def board(window, qapp):
    window.resize(1600, 1000)
    window.show()
    window.view.resetTransform()
    window.view.scale(0.6, 0.6)
    qapp.processEvents()
    return window


def drag(window, qapp, start: QPointF, end: QPointF, release=True, during=None):
    """A real mouse drag on the canvas, in scene coordinates."""
    v = window.view
    vp = v.viewport()
    a, b = v.mapFromScene(start), v.mapFromScene(end)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for k in range(1, 11):
        QTest.mouseMove(vp, a + (b - a) * k / 10)
        qapp.processEvents()
    if during is not None:
        during()
    if release:
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
        qapp.processEvents()


def filled_group(scene, title, x, y=0.0, cards=2):
    g = scene.add_card(CardData(title=title, kind=KIND_GROUP, x=x, y=y))
    for n in range(cards):
        scene.add_card(CardData(title=f"{title} {n}", x=x + 40, y=y + 80 + n * 220, parent=g.card.id))
    scene._refit_ids({g.card.id})
    scene._update_z()
    return g


def title_bar(item):
    r = item.card_scene_rect()
    return QPointF(r.left() + 60, r.top() + 15)


def test_a_group_dropped_by_its_title_bar_joins_the_group_under_the_pointer(board, qapp):
    s = board.scene
    target = s.add_card(CardData(title="Short", kind=KIND_GROUP, x=0, y=0, width=900, height=250))
    inner = filled_group(s, "Inner", 1500)
    board.view.centerOn(900, 300)
    qapp.processEvents()
    drop = QPointF(300, 200)                 # the target's lower half
    drag(board, qapp, title_bar(inner), drop)
    assert inner.card.parent == target.card.id
    # (its centre ended up below the old frame: by the old rule it wouldn't have joined)


def test_dropping_outside_any_group_leaves_it(board, qapp):
    s = board.scene
    outer = s.add_card(CardData(title="Outer", kind=KIND_GROUP, x=0, y=0, width=1200, height=900))
    inner = filled_group(s, "Inner", 100, 100)
    s.set_parent(inner, outer.card.id)
    s._refit_ids({outer.card.id})
    s._update_z()
    board.view.centerOn(1200, 400)
    qapp.processEvents()
    drag(board, qapp, title_bar(inner), QPointF(1700, 300))
    assert inner.card.parent == ""


def test_a_card_joins_where_you_let_go(board, qapp):
    s = board.scene
    group = s.add_card(CardData(title="G", kind=KIND_GROUP, x=0, y=0, width=500, height=400))
    card = s.add_card(CardData(title="C", x=900, y=100))
    board.view.centerOn(600, 250)
    qapp.processEvents()
    r = card.card_scene_rect()
    grab = QPointF(r.left() + 15, r.top() + 15)
    # Released with the pointer just inside the group: the card's centre is outside its
    # frame (it'd have stayed out by the old centre rule); the frame grows to fit it.
    drag(board, qapp, grab, QPointF(480, 200))
    assert card.card.parent == group.card.id


def test_a_dragged_selection_all_goes_where_you_let_go(board, qapp):
    """Several selected cards dragged into a group: all of them join it, not just the
    one under the pointer."""
    s = board.scene
    group = s.add_card(CardData(title="G", kind=KIND_GROUP, x=0, y=0, width=700, height=500))
    cards = [s.add_card(CardData(title=f"C{n}", x=1000 + n * 120, y=100 + n * 160)) for n in range(3)]
    for c in cards:
        c.setSelected(True)
    board.view.centerOn(900, 300)
    qapp.processEvents()
    grab = cards[0].card_scene_rect().center()
    seen = {}
    drag(board, qapp, grab, QPointF(250, 150), during=lambda: seen.update(hint=s._group_hint))
    assert seen["hint"] is group
    assert [c.card.parent for c in cards] == [group.card.id] * 3
    # ...and dragged back out onto empty canvas, they all leave it.
    grab = cards[0].card_scene_rect().center()
    drag(board, qapp, grab, grab + QPointF(1500, 0))
    assert [c.card.parent for c in cards] == [""] * 3


def test_a_selection_with_a_group_keeps_its_cards_inside_it(scene):
    target = scene.add_card(CardData(title="T", kind=KIND_GROUP, x=0, y=0, width=900, height=900))
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP, x=1500, y=0))
    inside = scene.add_card(CardData(title="In", x=1540, y=80, parent=g.card.id))
    loose = scene.add_card(CardData(title="Loose", x=2200, y=100))
    for item in (g, inside, loose):
        item.setSelected(True)
    scene.handle_drop(loose, pointer=QPointF(300, 300))
    assert g.card.parent == target.card.id and loose.card.parent == target.card.id
    assert inside.card.parent == g.card.id           # carried along inside its group


def test_a_moving_group_is_never_the_target(scene):
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP, x=0, y=0, width=600, height=600))
    c = scene.add_card(CardData(title="C", x=900, y=100))
    g.setSelected(True)
    c.setSelected(True)
    scene.handle_drop(c, pointer=QPointF(300, 300))  # pointer over G, which is moving too
    assert c.card.parent == "" and g.card.parent == ""


def test_without_a_pointer_each_goes_by_its_centre(scene):
    group = scene.add_card(CardData(title="G", kind=KIND_GROUP, x=0, y=0, width=500, height=400))
    a = scene.add_card(CardData(title="A", x=100, y=100))
    b = scene.add_card(CardData(title="B", x=900, y=100))
    a.setSelected(True)
    b.setSelected(True)
    scene.handle_drop(b)                              # e.g. not a mouse drag
    assert a.card.parent == group.card.id and b.card.parent == ""


def test_what_you_drag_is_drawn_on_top_until_dropped(board, qapp):
    s = board.scene
    old = filled_group(s, "Old", 1500)                # made first: normally drawn under newer groups
    a, b = [i for i in s.cards.values() if i.card.parent == old.card.id]
    s.add_connection(a, b)
    edge = s.edges[-1]
    new = s.add_card(CardData(title="New", kind=KIND_GROUP, x=0, y=0, width=900, height=700))
    s._update_z()
    assert old.zValue() == new.zValue()
    board.view.centerOn(900, 300)
    qapp.processEvents()
    seen = {}

    def check():
        seen["group"] = old.zValue() > new.zValue() + DRAG_LIFT / 2
        seen["cards"] = a.zValue() > old.zValue() and b.zValue() > old.zValue()
        seen["edge"] = edge.zValue() > old.zValue()
        seen["hint"] = s._group_hint is new
    drag(board, qapp, title_bar(old), QPointF(200, 150), during=check)
    assert seen == {"group": True, "cards": True, "edge": True, "hint": True}
    assert old.card.parent == new.card.id
    assert old.zValue() == new.zValue() + 0.1           # back to normal: one level deeper
    assert a.zValue() == 0 and edge.zValue() < 0


def test_a_click_or_a_lost_drag_leaves_depths_alone(board, qapp):
    s = board.scene
    g = filled_group(s, "G", 0)
    z = g.zValue()
    board.view.centerOn(300, 300)
    qapp.processEvents()
    drag(board, qapp, title_bar(g), title_bar(g))       # a click: no movement
    assert g.zValue() == z
    drag(board, qapp, title_bar(g), title_bar(g) + QPointF(200, 0), release=False)
    assert g.zValue() > z
    QTest.qWait(1)
    s.sendEvent(g, QEvent(QEvent.Type.UngrabMouse))    # e.g. a dialog took the mouse mid-drag
    assert g.zValue() == z
    QTest.mouseRelease(board.view.viewport(), Qt.MouseButton.LeftButton)
