"""Auto-arrange leaves room for arrow labels: the space between two steps of a chain
widens to fit the longest label on the arrows between them, so the label can be
read instead of sitting over the cards."""
import pytest

from warpingweft.card_item import PORT_RADIUS
from warpingweft.edge_item import ARROW_LEN
from warpingweft.layout import H_GAP, LABEL_MARGIN, Node, arrange
from warpingweft.model import KIND_GROUP, BoardData, CardData, ConnectionData


def nodes(*ids, color=""):
    return [Node(i, 230, 60, x=k * 300, color=color) for k, i in enumerate(ids)]


def test_unlabelled_steps_keep_the_usual_gap():
    pos = arrange(nodes("a", "b"), [("a", "b")])
    assert pos["b"][0] - (pos["a"][0] + 230) == H_GAP


def test_a_long_label_widens_its_gap_only():
    pos = arrange(nodes("a", "b", "c"), [("a", "b"), ("b", "c")],
                  labels={("a", "b"): (150, 20)})
    assert pos["b"][0] - (pos["a"][0] + 230) == 150 + LABEL_MARGIN
    assert pos["c"][0] - (pos["b"][0] + 230) == H_GAP


def test_a_short_label_needs_no_extra_room():
    pos = arrange(nodes("a", "b"), [("a", "b")], labels={("a", "b"): (20, 20)})
    assert pos["b"][0] - (pos["a"][0] + 230) == H_GAP


def test_widest_label_between_two_steps_wins():
    ns = nodes("a", "b", "c")
    pos = arrange(ns, [("a", "b"), ("a", "c")], labels={("a", "b"): (90, 20), ("a", "c"): (140, 20)})
    assert pos["b"][0] - 230 == 140 + LABEL_MARGIN == pos["c"][0] - 230


def test_top_to_bottom_needs_room_for_the_label_height():
    pos = arrange(nodes("a", "b"), [("a", "b")], vertical=True, labels={("a", "b"): (150, 20)})
    assert pos["b"][1] - (pos["a"][1] + 60) == H_GAP  # a label's height fits the usual gap


def test_color_lanes_leave_room_too():
    ns = [Node("a", 230, 60, color="r"), Node("b", 230, 60, x=300, color="g")]
    pos = arrange(ns, [("a", "b")], by_color=True, labels={("a", "b"): (150, 20)})
    assert pos["b"][0] - 230 == 150 + LABEL_MARGIN


def test_arranging_a_group_fits_its_labels(scene):
    scene.load_board_data(BoardData(
        cards=[CardData(id="g", title="g", kind=KIND_GROUP),
               CardData(id="a", title="a", parent="g", x=40, y=60),
               CardData(id="b", title="b", parent="g", x=300, y=60)],
        connections=[ConnectionData(source="a", target="b", id="ab", label="sworn enemies since the flood")]))
    scene.auto_arrange_group(scene.cards["g"])
    edge = scene.edges[0]
    label = edge._label_rect
    assert not label.isNull()
    for cid in "ab":
        assert not label.intersects(scene.cards[cid].card_scene_rect())
    gap = scene.cards["b"].card_scene_rect().left() - scene.cards["a"].card_scene_rect().right()
    assert gap >= label.width() + LABEL_MARGIN - 0.5


def test_hidden_labels_need_no_room(scene):
    board = BoardData(
        cards=[CardData(id="g", title="g", kind=KIND_GROUP),
               CardData(id="a", title="a", parent="g", x=40, y=60),
               CardData(id="b", title="b", parent="g", x=300, y=60)],
        connections=[ConnectionData(source="a", target="b", id="ab", label="sworn enemies since the flood")])
    board.display["show_arrow_labels"] = False
    scene.load_board_data(board)
    scene.auto_arrange_group(scene.cards["g"])
    gap = scene.cards["b"].card_scene_rect().left() - scene.cards["a"].card_scene_rect().right()
    assert gap == H_GAP


def test_room_is_made_even_when_the_cards_start_on_top_of_each_other(scene):
    """Cards too close to draw the arrow between them (here, stacked) still have its
    label measured, so arranging pulls them far enough apart to read it."""
    scene.load_board_data(BoardData(
        cards=[CardData(id="g", title="g", kind=KIND_GROUP),
               CardData(id="a", title="a", parent="g", x=40, y=60),
               CardData(id="b", title="b", parent="g", x=40, y=60)],
        connections=[ConnectionData(source="a", target="b", id="ab", label="sworn enemies since the flood")]))
    scene.auto_arrange_group(scene.cards["g"])
    gap = scene.cards["b"].card_scene_rect().left() - scene.cards["a"].card_scene_rect().right()
    assert gap >= scene.edges[0].label_size()[0] + LABEL_MARGIN - 0.5
    assert not scene.edges[0]._label_rect.intersects(scene.cards["b"].card_scene_rect())


def clearances(scene, routing):
    board = BoardData(
        cards=[CardData(id="g", title="g", kind=KIND_GROUP),
               CardData(id="a", title="a", parent="g", x=40, y=60),
               CardData(id="b", title="b", parent="g", x=300, y=60)],
        connections=[ConnectionData(source="a", target="b", id="ab", label="uneasy allies")])
    board.display["arrow_routing"] = routing
    scene.load_board_data(board)
    scene.auto_arrange_group(scene.cards["g"])
    a, b = scene.cards["a"].card_scene_rect(), scene.cards["b"].card_scene_rect()
    label = scene.edges[0]._label_rect
    return label.left() - (a.right() + PORT_RADIUS), b.left() - ARROW_LEN - label.right()


@pytest.mark.parametrize("routing", ["straight", "curved", "avoid"])
def test_label_sits_centred_in_the_visible_arrow(scene, routing):
    """The source's handle covers the start of the arrow and the arrowhead its end:
    the label is centred between the two, with clear space either side."""
    left, right = clearances(scene, routing)
    assert abs(left - right) <= 1
    assert left >= 13
