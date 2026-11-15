"""Opening a card's details (▸) grows it downwards. Its arrows (and its handle) stay
where they were: they're anchored to the card as it looks closed. What the open card
would now cover is pushed down out of the way, as auto-arrange does, and closing the
details moves it back. The pushes aren't edits: undo history and the saved file keep
the positions the cards have with details closed."""
import pytest

from warpingweft.layout import V_GAP

from warpingweft.model import KIND_GROUP, KIND_STRAND, BoardData, CardData, ConnectionData


def path_of(edge):
    p = edge._line
    return [(round(p.elementAt(k).x, 3), round(p.elementAt(k).y, 3)) for k in range(p.elementCount())]


def load(scene, cards, conns=(), routing="straight"):
    board = BoardData(cards=cards, connections=list(conns))
    board.display["arrow_routing"] = routing
    scene.load_board_data(board)


def detailed(cid, x, y, parent=""):
    return CardData(id=cid, title=cid, x=x, y=y, parent=parent, characters=["Ann", "Bo"],
                    locations=["Quay"], status="Draft", notes="A long note " * 8)


@pytest.mark.parametrize("routing", ["straight", "curved", "avoid"])
def test_arrows_stay_put_when_details_open(scene, routing):
    load(scene, [detailed("a", 0, 0), detailed("b", 400, 60), detailed("c", 0, 300)],
         [ConnectionData(source="a", target="b", id="ab"), ConnectionData(source="c", target="a", id="ca")],
         routing)
    edges = {e.conn.id: e for e in scene.edges}
    before = {k: path_of(e) for k, e in edges.items()}
    heights = {cid: scene.cards[cid].card_scene_rect().height() for cid in "abc"}
    for cid in "abc":
        scene.cards[cid].set_details_visible(True)
    assert all(scene.cards[c].card_scene_rect().height() > heights[c] for c in "abc")
    assert {k: path_of(e) for k, e in edges.items()} == before
    for cid in "abc":
        scene.cards[cid].set_details_visible(False)
    assert {k: path_of(e) for k, e in edges.items()} == before


def test_a_strand_card_keeps_its_arrows_and_handle(scene):
    load(scene, [CardData(id="s1", kind=KIND_STRAND, strand_kind="characters", strand="Ann", x=0, y=0),
                 CardData(id="s2", kind=KIND_STRAND, strand_kind="characters", strand="Bo", x=400, y=0)],
         [ConnectionData(source="s1", target="s2", id="e", label="knows")], "curved")
    edge, s1 = scene.edges[0], scene.cards["s1"]
    before, port = path_of(edge), s1.port_scene_pos() if hasattr(s1, "port_scene_pos") else None
    port_local = s1.port_center()
    s1.set_details_visible(True)
    scene.cards["s2"].set_details_visible(True)
    assert path_of(edge) == before
    assert s1.port_center() == port_local
    del port


def test_opening_a_neighbour_does_not_reroute_an_arrow_round_it(scene):
    # "mid" sits just above the line a → b: opened, it grows down across the arrow's
    # way, but arrows are routed round cards as they look closed.
    load(scene, [CardData(id="a", title="a", x=0, y=0), CardData(id="b", title="b", x=700, y=0),
                 detailed("mid", 350, -150)],
         [ConnectionData(source="a", target="b", id="ab")], "avoid")
    edge = scene.edges[0]
    before = path_of(edge)
    mid = scene.cards["mid"]
    mid.set_details_visible(True)
    assert mid.card_scene_rect().bottom() > 40, "the test needs mid to grow across the arrow"
    edge.adjust()
    assert path_of(edge) == before


def pos(scene, cid):
    p = scene.cards[cid].pos()
    return (p.x(), p.y())


def rect(scene, cid):
    return scene.cards[cid].card_scene_rect()


def column(scene):
    """Three detailed cards stacked close together, and one off to the side."""
    load(scene, [detailed("a", 0, 0), detailed("b", 0, 110), detailed("c", 0, 220),
                 CardData(id="side", title="side", x=600, y=150)])


def test_opening_pushes_what_is_below_down_and_closing_moves_it_back(scene):
    column(scene)
    before = {cid: pos(scene, cid) for cid in ("a", "b", "c", "side")}
    scene.show_details(scene.cards["a"], True)
    a, b, c = rect(scene, "a"), rect(scene, "b"), rect(scene, "c")
    assert b.top() >= a.bottom() + V_GAP - 0.5 and not b.intersects(c)
    assert pos(scene, "b")[0] == before["b"][0]  # straight down
    assert pos(scene, "side") == before["side"]  # not in the way
    scene.show_details(scene.cards["a"], False)
    assert {cid: pos(scene, cid) for cid in before} == before


def test_room_for_details_is_not_an_edit(scene):
    column(scene)
    scene.reset_history()
    saved = [(c.id, c.x, c.y) for c in scene.to_board_data().cards]
    scene.show_details(scene.cards["a"], True)
    assert pos(scene, "b") != (0.0, 110.0)
    assert [(c.id, c.x, c.y) for c in scene.to_board_data().cards] == saved
    scene.mark_modified()  # even if something asks for a commit, there's nothing to undo
    scene.flush_history()
    assert not scene.history.can_undo()


def test_a_card_moved_by_hand_stays_where_it_was_put(scene):
    column(scene)
    scene.show_details(scene.cards["a"], True)
    scene.cards["c"].setPos(400, 600)  # moved by hand while a is open
    scene.show_details(scene.cards["a"], False)
    assert pos(scene, "c") == (400.0, 600.0)
    assert pos(scene, "b") == (0.0, 110.0)  # still moved back
    saved = {c.id: (c.x, c.y) for c in scene.to_board_data().cards}
    assert saved["c"] == (400.0, 600.0)  # the hand move is real


def test_room_is_made_through_enclosing_groups(scene):
    load(scene, [CardData(id="g", title="g", kind=KIND_GROUP), detailed("in", 40, 60, "g"),
                 CardData(id="next", title="next", x=40, y=170, parent="g"),
                 CardData(id="below", title="below", x=40, y=360)])
    g_before, below_before = rect(scene, "g"), pos(scene, "below")
    assert not g_before.intersects(rect(scene, "below"))
    scene.show_details(scene.cards["in"], True)
    assert not rect(scene, "in").intersects(rect(scene, "next"))
    assert rect(scene, "g").contains(rect(scene, "next"))
    assert not rect(scene, "g").intersects(rect(scene, "below"))
    scene.show_details(scene.cards["in"], False)
    assert pos(scene, "below") == below_before
    assert rect(scene, "g") == g_before


def test_show_all_details_makes_room_and_hide_all_gives_it_back(scene):
    column(scene)
    before = {cid: pos(scene, cid) for cid in ("a", "b", "c", "side")}
    scene.set_all_details(True)
    rects = [rect(scene, cid) for cid in ("a", "b", "c")]
    assert not any(r1.intersects(r2) for i, r1 in enumerate(rects) for r2 in rects[i + 1:])
    scene.set_all_details(False)
    assert {cid: pos(scene, cid) for cid in before} == before


def test_undo_while_details_are_open_makes_room_again(scene):
    column(scene)
    scene.reset_history()
    scene.show_details(scene.cards["a"], True)
    scene.cards["side"].setPos(700, 150)  # a real edit
    scene.mark_modified()
    scene.flush_history()
    scene.undo()
    assert pos(scene, "side") == (600.0, 150.0)
    assert scene.cards["a"].details_visible
    assert not rect(scene, "a").intersects(rect(scene, "b"))
    scene.show_details(scene.cards["a"], False)
    assert pos(scene, "b") == (0.0, 110.0)
