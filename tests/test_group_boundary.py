"""Arrows between a group and a card inside it: group → card marks a first card,
card → group marks a last card. Drawn across the frame's inner gap, and used by
the story graph as the group's entry / exit cards."""
from PySide6.QtCore import QPointF

from warpingweft.card_item import HEADER_HEIGHT
from warpingweft.graph import StoryGraph
from warpingweft.model import KIND_GROUP, CardData, ConnectionData, save_board


def group_with(scene, *titles, vertical=False):
    """A group holding cards laid out left to right (or top to bottom)."""
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP, arrange_vertical=vertical))
    cards = []
    for n, t in enumerate(titles):
        x, y = (0, 60 + 200 * n) if vertical else (300 * n, 60)
        cards.append(scene.add_card(CardData(title=t, x=x, y=y, parent=g.card.id)))
    scene._refit_ids({g.card.id})
    return g, cards


def title_y(r) -> float:
    """Side arrows run along the card's title bar."""
    return r.top() + HEADER_HEIGHT / 2


def pt(p) -> QPointF:
    """A QPointF, or a path element (which has plain .x / .y attributes)."""
    return p if isinstance(p, QPointF) else QPointF(p.x, p.y)


def close(a, b) -> bool:
    a, b = pt(a), pt(b)
    return abs(a.x() - b.x()) < 0.6 and abs(a.y() - b.y()) < 0.6


# ----- drawing ---------------------------------------------------------------------------
def test_first_card_arrow_runs_from_the_inner_left_border(scene):
    g, (p, q) = group_with(scene, "P", "Q")
    e = scene.add_connection(g, p)
    assert e is not None and e.is_boundary() and not e._line.isEmpty()
    body, r = g.body_scene_rect(), p.card_scene_rect()
    assert close(e._line.elementAt(0), QPointF(body.left(), title_y(r)))
    assert close(e._arrow[0], QPointF(r.left(), title_y(r)))  # the tip touches the card


def test_last_card_arrow_runs_out_to_the_inner_right_border(scene):
    g, (p, q) = group_with(scene, "P", "Q")
    e = scene.add_connection(q, g)
    body, r = g.body_scene_rect(), q.card_scene_rect()
    assert close(e._line.elementAt(0), QPointF(r.right(), title_y(r)))
    assert close(e._arrow[0], QPointF(body.right(), title_y(r)))


def test_top_to_bottom_groups_use_the_top_and_bottom_borders(scene):
    g, (p, q) = group_with(scene, "P", "Q", vertical=True)
    first, last = scene.add_connection(g, p), scene.add_connection(q, g)
    body = g.body_scene_rect()
    assert abs(first._line.elementAt(0).y - body.top()) < 0.6
    assert abs(first._arrow[0].y() - p.card_scene_rect().top()) < 0.6
    assert abs(last._arrow[0].y() - body.bottom()) < 0.6


def test_a_single_card_can_be_both_first_and_last(scene):
    g, (p,) = group_with(scene, "P")
    first, last = scene.add_connection(g, p), scene.add_connection(p, g)
    body = g.body_scene_rect()
    assert abs(first._line.elementAt(0).x - body.left()) < 0.6
    assert abs(last._arrow[0].x() - body.right()) < 0.6


def test_another_card_in_the_way_moves_the_arrow_to_a_clear_side(scene):
    g, (p, q) = group_with(scene, "P", "Q")
    e = scene.add_connection(g, q)           # Q has P to its left: come in from the top
    body, r = g.body_scene_rect(), q.card_scene_rect()
    assert close(e._line.elementAt(0), QPointF(r.center().x(), body.top()))
    assert close(e._arrow[0], QPointF(r.center().x(), r.top()))


def test_arrows_follow_the_card_and_frame(scene):
    g, (p, q) = group_with(scene, "P", "Q")
    e = scene.add_connection(g, p)
    p.moveBy(0, 40)
    g.refit()
    r = p.card_scene_rect()
    assert close(e._arrow[0], QPointF(r.left(), title_y(r)))


# ----- connecting ------------------------------------------------------------------------
def test_dragging_into_a_group_keeps_the_groups_arrow(scene):
    g, (p,) = group_with(scene, "P")
    outside = scene.add_card(CardData(title="X", x=0, y=600))
    scene.add_connection(g, outside)
    g.resize_to(900, 500)
    outside.setPos(320, 80)               # dropped inside the frame
    outside.setSelected(True)
    scene.handle_drop(outside)
    assert outside.card.parent == g.card.id
    assert len(scene.edges) == 1 and scene.edges[0].is_boundary()


def test_click_connect_from_a_group_to_its_card(scene):
    g, (p,) = group_with(scene, "P")
    scene.start_click_connection(g)
    scene.finish_connection(p.card_scene_rect().center())
    assert [(e.source, e.target) for e in scene.edges] == [(g, p)]


def test_dragging_a_handle_onto_the_own_groups_header_marks_a_last_card(scene):
    g, (p,) = group_with(scene, "P")
    header = QPointF(g.card_scene_rect().center().x(), g.card_scene_rect().top() + 10)
    scene.begin_connection(p, p.port_scene_pos())
    scene.update_connection(header)
    assert g._drop_highlight
    scene.finish_connection(header)
    assert [(e.source, e.target) for e in scene.edges] == [(p, g)]


def test_dropping_inside_the_own_group_away_from_its_edge_still_creates_a_card(scene):
    g, (p,) = group_with(scene, "P")
    g.resize_to(900, 500)
    drop = p.port_scene_pos() + QPointF(200, 0)
    assert not g.on_frame_edge(drop)
    scene.begin_connection(p, p.port_scene_pos())
    scene.update_connection(drop)
    assert not g._drop_highlight and scene._ghost is not None and scene._ghost.isVisible()
    scene.finish_connection(drop, __import__("PySide6.QtCore").QtCore.Qt.KeyboardModifier.ControlModifier)
    assert len(scene.cards) == 3 and scene.edges[0].source is p and scene.edges[0].target.card.parent == g.card.id


def test_boundary_arrows_survive_save_and_reload(window, tmp_path):
    s = window.scene
    g, (p, q) = group_with(s, "P", "Q")
    s.add_connection(g, p)
    s.add_connection(q, g)
    path = tmp_path / "marks.json"
    save_board(s.to_board_data(), path)
    window.open_path(path)
    pairs = {(e.source.card.title, e.target.card.title) for e in window.scene.edges}
    assert pairs == {("G", "P"), ("Q", "G")}
    assert all(e.is_boundary() and not e._line.isEmpty() for e in window.scene.edges)


# ----- story graph ---------------------------------------------------------------------------
def cards_and(*pairs):
    cards = [CardData(id="X", x=-500), CardData(id="G", kind=KIND_GROUP),
             CardData(id="P", x=0, y=0, parent="G"), CardData(id="Q", x=300, y=0, parent="G"),
             CardData(id="R", x=0, y=300, parent="G"), CardData(id="Y", x=900)]
    return StoryGraph(cards, [ConnectionData(s, t, id=f"{s}>{t}") for s, t in pairs])


def test_marked_first_and_last_cards_replace_the_automatic_choice():
    # Inside G: P -> Q, and R on its own. Unmarked, X would lead to P and R.
    plain = cards_and(("X", "G"), ("P", "Q"), ("G", "Y"))
    assert sorted(plain.succ["X"]) == ["P", "R"] and sorted(plain.pred["Y"]) == ["Q", "R"]
    g = cards_and(("X", "G"), ("P", "Q"), ("G", "Y"), ("G", "P"), ("Q", "G"))
    assert g.first_cards("G") == ["P"] and g.last_cards("G") == ["Q"]
    assert g.succ["X"] == ["P"] and g.pred["Y"] == ["Q"]
    assert g.downstream("X") == {"P", "Q", "Y"}       # R isn't on the route any more
    assert g.upstream("Y") == {"X", "P", "Q"}


def test_marker_arrows_are_not_story_steps():
    g = cards_and(("G", "P"), ("Q", "G"), ("P", "Q"))
    assert g.boundary_arrows == {"G>P", "Q>G"}
    assert g.succ["P"] == ["Q"] and g.pred["P"] == [] and g.succ["Q"] == []
    assert g.cycles() == []
    # They light up with the card they mark.
    assert g.arrows_within({"P"}) == {"G>P"} and g.arrows_within({"Q"}) == {"Q>G"}


def test_a_first_card_deep_inside_a_nested_group():
    cards = [CardData(id="X", x=-500), CardData(id="G", kind=KIND_GROUP),
             CardData(id="H", kind=KIND_GROUP, parent="G"), CardData(id="P", parent="H"),
             CardData(id="Q", x=300, parent="G")]
    g = StoryGraph(cards, [ConnectionData("X", "G", id="1"), ConnectionData("G", "P", id="2")])
    assert g.succ["X"] == ["P"]


def test_highlight_lights_the_marker_arrows_on_the_path(scene):
    g, (p, q) = group_with(scene, "P", "Q")
    x = scene.add_card(CardData(title="X", x=-600, y=60))
    scene.add_connection(x, g)
    scene.add_connection(g, p)
    scene.add_connection(p, q)
    graph = scene.story_graph()
    ids = {x.card.id} | graph.downstream(x.card.id)
    assert ids == {x.card.id, p.card.id, q.card.id}
    scene.set_highlight(ids, graph.arrows_within(ids))
    assert all(e.highlight for e in scene.edges)
