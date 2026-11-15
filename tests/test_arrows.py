"""F6: arrow line styles and colors, the arrow editor, and curved / card-avoiding routing."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath

import warpingweft.arrow_dialog as ad
import warpingweft.scene as sc
from warpingweft import theme
from warpingweft.edge_item import AVOID_SAMPLES
from warpingweft.model import KIND_GROUP, CardData, save_board
from conftest import wait_until


def two_cards(scene, dx=600, dy=0):
    a = scene.add_card(CardData(title="A", x=0, y=0))
    b = scene.add_card(CardData(title="B", x=dx, y=dy))
    return a, b, scene.add_connection(a, b)


def samples(path: QPainterPath):
    return [path.pointAtPercent(k / AVOID_SAMPLES) for k in range(AVOID_SAMPLES + 1)]


def crosses(path: QPainterPath, rect: QRectF) -> bool:
    return any(rect.contains(p) for p in samples(path))


def is_curve(path: QPainterPath) -> bool:
    return any(path.elementAt(i).type.name.startswith("Curve") for i in range(path.elementCount()))


# ----- styles & colors -------------------------------------------------------------------
def test_set_arrow_style_is_one_undo_step_and_leaves_unset_values(scene):
    a, b, e1 = two_cards(scene)
    c = scene.add_card(CardData(title="C", x=0, y=400))
    e2 = scene.add_connection(a, c, "keep me")
    e2.conn.color = "#3f9e6e"
    scene.reset_history()
    assert scene.set_arrow_style([e1, e2], style="dotted") == 2
    scene.flush_history()
    assert (e1.conn.style, e2.conn.style) == ("dotted", "dotted")
    assert e2.conn.color == "#3f9e6e" and e2.conn.label == "keep me"   # untouched
    assert scene.set_arrow_style([e1], style="dotted") == 0            # no change
    assert scene.undo()
    assert [e.conn.style for e in scene.edges] == ["solid", "solid"]
    assert not scene.history.can_undo()


def test_draw_color_order(scene):
    a, b, e = two_cards(scene)
    t = theme.current()
    assert e.draw_color() == t.edge_line
    e.conn.color = "#b8475b"
    assert e.draw_color().name() == "#b8475b"
    e.set_highlight(True)
    assert e.draw_color() == t.highlight
    e.setSelected(True)
    assert e.draw_color() == t.selected


# ----- the arrow editor ------------------------------------------------------------------------
def test_arrow_dialog_for_one_arrow(qapp):
    from warpingweft.model import ConnectionData
    conn = ConnectionData("a", "b", "if she refuses", style="dashed", color="#b8475b")
    d = ad.ArrowDialog([conn], ["#123456"])
    assert d.label_edit.text() == "if she refuses"
    assert d.style() == "dashed" and d.color() == "#b8475b"
    d.style_buttons["dotted"].click()
    d._select_color("")
    d.label_edit.setText("  then  ")
    assert (d.label(), d.style(), d.color()) == ("then", "dotted", "")


def test_arrow_dialog_for_mixed_arrows_leaves_unset_values(qapp):
    from warpingweft.model import ConnectionData
    conns = [ConnectionData("a", "b", style="dashed"), ConnectionData("b", "c", color="#3f9e6e")]
    d = ad.ArrowDialog(conns)
    assert d.label() is None and d.style() is None and d.color() is None
    assert d.label_edit.parent() is None   # no Label row for several arrows


def test_edit_arrows_applies_the_dialog_and_adds_custom_colors(scene, monkeypatch):
    a, b, e = two_cards(scene)

    def fake_exec(self):
        self.style_buttons["dashed"].click()
        self._select_color("#abcdef")
        self.added_custom_colors.append("#abcdef")
        self.label_edit.setText("later")
        self.accept()
        return self.result()
    monkeypatch.setattr(ad.ArrowDialog, "exec", fake_exec)
    scene.edit_connection_label(e)            # double-click / Enter on one arrow
    assert (e.conn.style, e.conn.color, e.conn.label) == ("dashed", "#abcdef", "later")
    assert "#abcdef" in scene.custom_colors


def test_enter_with_several_arrows_selected_edits_them_together(window, monkeypatch):
    s = window.scene
    a, b, e1 = two_cards(s)
    c = s.add_card(CardData(title="C", x=0, y=400))
    e2 = s.add_connection(a, c)
    seen = []
    monkeypatch.setattr(sc.BoardScene, "edit_arrows", lambda self, edges: seen.append(set(edges)))
    e1.setSelected(True)
    e2.setSelected(True)
    assert s.edit_selection()
    assert seen == [{e1, e2}]


# ----- routing ------------------------------------------------------------------------------
def test_curved_arrows_run_between_facing_sides(scene):
    a, b, e = two_cards(scene, 600, 100)
    scene.set_display_option("arrow_routing", "curved")
    assert is_curve(e._line)
    rb, ra = b.card_scene_rect(), a.card_scene_rect()
    tip = e._arrow[0]
    assert abs(tip.x() - rb.left()) < 0.5 and abs(tip.y() - rb.center().y()) < 0.5
    first = e._line.elementAt(0)
    assert abs(first.x - ra.right()) < 0.5 and abs(first.y - ra.center().y()) < 0.5
    # The label sits on the curve, halfway along the part not covered by the handle.
    e.set_label("x")
    from warpingweft.card_item import PORT_RADIUS
    line = e._line
    halfway = line.pointAtPercent(line.percentAtLength((PORT_RADIUS + line.length()) / 2))
    assert e._label_rect.center() == halfway


def test_curves_run_top_to_bottom_when_the_target_is_below(scene):
    a, b, e = two_cards(scene, 50, 400)
    scene.set_display_option("arrow_routing", "curved")
    rb = b.card_scene_rect()
    assert abs(e._arrow[0].y() - rb.top()) < 0.5


def test_cards_too_close_to_curve_fall_back_to_straight(scene):
    a, b, e = two_cards(scene, 120, 30)   # overlapping
    scene.set_display_option("arrow_routing", "curved")
    assert not is_curve(e._line)


def test_opposite_curved_arrows_sit_side_by_side(scene):
    a, b, e1 = two_cards(scene)
    e2 = scene.add_connection(b, a)
    scene.set_display_option("arrow_routing", "curved")
    y1 = e1._line.pointAtPercent(0.5).y()
    y2 = e2._line.pointAtPercent(0.5).y()
    assert abs(y1 - y2) > 10


def test_avoid_routes_around_a_card_in_the_way(scene):
    a, b, e = two_cards(scene, 700, 40)
    blocker = scene.add_card(CardData(title="In the way", x=350, y=10))
    r = blocker.card_scene_rect()
    scene.set_display_option("arrow_routing", "curved")
    assert crosses(e._line, r)
    scene.set_display_option("arrow_routing", "avoid")
    assert not crosses(e._line, r)
    assert e._arrow[0].x() == b.card_scene_rect().left()  # still arrives at the target


def test_avoid_reroutes_after_a_card_moves_into_the_way(window, qapp):
    s = window.scene
    a, b, e = two_cards(s, 700, 40)
    stray = s.add_card(CardData(title="Stray", x=350, y=500))
    s.set_display_option("arrow_routing", "avoid")
    stray.setPos(350, 10)            # dragged into the arrow's path
    s.handle_drop(stray)
    wait_until(lambda: not s._reroute_timer.isActive())
    assert not crosses(e._line, stray.card_scene_rect())


def test_group_marker_arrows_stay_straight(scene):
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP))
    p = scene.add_card(CardData(title="P", x=0, y=60, parent=g.card.id))
    scene._refit_ids({g.card.id})
    e = scene.add_connection(g, p)
    scene.set_display_option("arrow_routing", "curved")
    assert not is_curve(e._line) and not e._line.isEmpty()


def test_routing_is_undoable_saved_and_shown_in_the_menu(window, tmp_path):
    s = window.scene
    a, b, e = two_cards(s, 600, 100)
    s.reset_history()
    window.routing_actions["curved"].trigger()
    s.flush_history()
    assert s.display["arrow_routing"] == "curved" and is_curve(s.edges[0]._line)
    assert window.routing_actions["curved"].isChecked()
    assert s.undo()
    assert s.display["arrow_routing"] == "straight" and not is_curve(s.edges[0]._line)
    assert window.routing_actions["straight"].isChecked()
    assert s.redo()

    path = tmp_path / "curvy.json"
    save_board(s.to_board_data(), path)
    window.setWindowModified(False)
    window.new_board()
    assert window.routing_actions["straight"].isChecked()
    window.open_path(path)
    assert window.routing_actions["curved"].isChecked()
    assert is_curve(window.scene.edges[0]._line)   # laid out curved straight after loading


def test_a_level_arrow_still_routes_round_a_card_in_the_way(scene):
    """With both cards at the same height the plain curve is a flat line, whose
    bounding box has no height: cards in the way used to be missed, so the arrow
    ran straight through them."""
    from warpingweft.model import BoardData, CardData, ConnectionData
    board = BoardData(cards=[CardData(id="a", title="a", x=0, y=0),
                             CardData(id="b", title="b", x=700, y=0),
                             CardData(id="mid", title="mid", x=350, y=0)],
                      connections=[ConnectionData(source="a", target="b", id="ab")])
    board.display["arrow_routing"] = "avoid"
    scene.load_board_data(board)
    edge = scene.edges[0]
    edge.adjust()
    mid = scene.cards["mid"].card_scene_rect()
    points = [edge._line.pointAtPercent(k / 50) for k in range(51)]
    assert not any(mid.contains(p) for p in points)
