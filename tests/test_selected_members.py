"""A group that moves carries all its cards, selected or not. Only a mouse drag or a
nudge, which already move every selected card themselves, may skip the selected ones;
moves made in code (arrange, remove from group, the snap after a drop) must not leave a
selected card behind outside its group's frame."""
from PySide6.QtCore import QPointF

from heddle.model import KIND_GROUP, BoardData, CardData
from heddle.scene import BoardScene


def nested_board() -> BoardScene:
    a = CardData(id="A", title="A", kind=KIND_GROUP, x=0, y=0)
    x = CardData(id="x", title="x", parent="A", x=20, y=60)
    b = CardData(id="B", title="B", kind=KIND_GROUP, parent="A", x=600, y=60)
    c = CardData(id="c", title="c", parent="B", x=620, y=120)
    s = BoardScene()
    s.load_board_data(BoardData(cards=[a, x, b, c]))
    s.reset_history()
    return s


def offset(s: BoardScene, child: str, group: str) -> QPointF:
    return s.cards[child].pos() - s.cards[group].pos()


def test_arranging_carries_a_selected_card_inside_a_nested_group(qapp):
    s = nested_board()
    s.cards["c"].setSelected(True)
    before = offset(s, "c", "B")
    s.auto_arrange_group(s.cards["A"])
    assert offset(s, "c", "B") == before
    assert s.cards["B"].body_scene_rect().contains(s.cards["c"].card_scene_rect())


def test_removing_a_nested_group_carries_its_selected_card(qapp):
    s = nested_board()
    s.cards["c"].setSelected(True)
    before = offset(s, "c", "B")
    s.remove_from_group(s.cards["B"])
    assert s.cards["B"].card.parent == ""
    assert offset(s, "c", "B") == before


def test_moving_a_group_in_code_carries_a_selected_member(qapp):
    s = nested_board()
    s.cards["c"].setSelected(True)
    before = offset(s, "c", "B")
    s.cards["B"].moveBy(100, 40)
    assert offset(s, "c", "B") == before


def test_snap_after_a_drop_keeps_a_selected_members_offset(qapp):
    s = nested_board()
    s.snap_to_grid = True
    b, c = s.cards["B"], s.cards["c"]
    b.setSelected(True)
    c.setSelected(True)
    with s.moving_selection():         # as Qt's drag moves every selected card
        for item in (b, c):
            item.moveBy(7, 9)          # off the grid
    before = offset(s, "c", "B")
    s.handle_drop(b)
    assert b.pos().x() % 25 == 0 and b.pos().y() % 25 == 0
    assert offset(s, "c", "B") == before


def test_nudging_a_group_and_its_selected_member_moves_the_member_once(qapp):
    s = nested_board()
    b, c = s.cards["B"], s.cards["c"]
    b.setSelected(True)
    c.setSelected(True)
    before = offset(s, "c", "B")
    s.nudge_selected(10, 0)
    assert offset(s, "c", "B") == before
    s.nudge_selected(25, 0, snap=True)
    assert offset(s, "c", "B") == before


def test_a_mouse_drag_of_a_group_and_its_selected_card_moves_the_card_once(window, qapp):
    from tests.test_group_nesting import drag, filled_group, title_bar
    window.resize(1600, 1000)
    window.show()
    window.view.resetTransform()
    window.view.scale(0.6, 0.6)
    s = window.scene
    g = filled_group(s, "G", 0)
    member = s.members_of(g)[0]
    window.view.centerOn(600, 300)
    qapp.processEvents()
    g.setSelected(True)
    member.setSelected(True)
    before = member.pos() - g.pos()
    start = title_bar(g)
    drag(window, qapp, start, start + QPointF(300, 0))
    assert g.pos().x() > 200
    assert member.pos() - g.pos() == before
