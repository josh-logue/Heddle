"""Auto-arranging a group that grows pushes what it would now cover out of the way, in
the direction it grew (right or down: arranging keeps the frame's top-left), instead
of leaving the frame over its neighbours. The push carries on through anything the
moved items then hit, and up through the groups it sits in. One undo step."""
from heddle.layout import V_GAP
from heddle.model import KIND_GROUP, BoardData, CardData


def load(scene, cards):
    scene.load_board_data(BoardData(cards=cards))
    scene.reset_history()  # as opening a file does
    return {cid: scene.cards[cid] for cid in scene.cards}


def rect(scene, cid):
    return scene.cards[cid].card_scene_rect()


def column(prefix, parent, n, x=40, y=60):
    """n cards stacked in one column (a tall, narrow group once fitted)."""
    return [CardData(id=f"{prefix}{k}", title=f"{prefix}{k}", parent=parent, x=x, y=y + k * 110)
            for k in range(n)]


def row(prefix, parent, n, x=40, y=60):
    """n cards side by side (a wide, shallow group once fitted)."""
    return [CardData(id=f"{prefix}{k}", title=f"{prefix}{k}", parent=parent, x=x + k * 260, y=y)
            for k in range(n)]


def overlaps(scene, a, b):
    return rect(scene, a).intersects(rect(scene, b))


def arrange(scene, gid):
    scene.auto_arrange_group(scene.cards[gid])
    scene.mark_modified()


def test_growing_right_pushes_a_neighbour_right(scene):
    # Five stacked cards become a 3-wide grid: the frame grows right over "beside".
    load(scene, [CardData(id="g", title="G", kind=KIND_GROUP, arrange_grid=True),
                 *column("c", "g", 5),
                 CardData(id="beside", title="Beside", x=380, y=100),
                 CardData(id="far", title="Far", x=3000, y=100),
                 CardData(id="below", title="Below", x=40, y=900)])
    beside_y = rect(scene, "beside").y()
    far, below = rect(scene, "far"), rect(scene, "below")
    arrange(scene, "g")
    g = rect(scene, "g")
    assert g.right() > 380 + 230, "the test needs the group to grow over the card"
    assert not overlaps(scene, "g", "beside")
    assert rect(scene, "beside").x() >= g.right() + V_GAP - 0.5
    assert rect(scene, "beside").y() == beside_y  # pushed sideways only
    assert rect(scene, "far") == far and rect(scene, "below") == below  # not in the way


def test_growing_down_pushes_a_neighbour_down(scene):
    # Five cards in a row become one column: the frame grows down over "under".
    load(scene, [CardData(id="g", title="G", kind=KIND_GROUP, arrange_vertical=True),
                 *row("c", "g", 5),
                 CardData(id="under", title="Under", x=100, y=400)])
    under_x = rect(scene, "under").x()
    arrange(scene, "g")
    g = rect(scene, "g")
    assert g.bottom() > 400, "the test needs the group to grow over the card"
    assert not overlaps(scene, "g", "under")
    assert rect(scene, "under").y() >= g.bottom() + V_GAP - 0.5
    assert rect(scene, "under").x() == under_x  # pushed down only


def test_push_carries_on_through_what_it_hits(scene):
    load(scene, [CardData(id="g", title="G", kind=KIND_GROUP, arrange_grid=True),
                 *column("c", "g", 5),
                 CardData(id="a", title="A", x=380, y=100),
                 CardData(id="b", title="B", x=640, y=120)])
    arrange(scene, "g")
    assert not overlaps(scene, "g", "a")
    assert not overlaps(scene, "a", "b")
    assert not overlaps(scene, "g", "b")


def test_a_pushed_group_brings_its_cards(scene):
    load(scene, [CardData(id="g", title="G", kind=KIND_GROUP, arrange_grid=True),
                 *column("c", "g", 5),
                 CardData(id="h", title="H", kind=KIND_GROUP),
                 CardData(id="h1", title="H1", parent="h", x=420, y=120)])
    arrange(scene, "g")
    assert not overlaps(scene, "g", "h")
    assert scene.cards["h"].card_scene_rect().contains(rect(scene, "h1"))


def test_push_carries_up_through_enclosing_groups(scene):
    # Inner grows inside Outer, pushing Sibling; Outer then grows over Top.
    load(scene, [CardData(id="outer", title="Outer", kind=KIND_GROUP),
                 CardData(id="inner", title="Inner", kind=KIND_GROUP, parent="outer",
                          arrange_grid=True),
                 *column("c", "inner", 5, x=60, y=120),
                 CardData(id="sibling", title="Sibling", parent="outer", x=420, y=140),
                 CardData(id="top", title="Top", x=760, y=140)])
    assert not overlaps(scene, "outer", "top")
    arrange(scene, "inner")
    assert not overlaps(scene, "inner", "sibling")
    assert scene.cards["sibling"].card.parent == "outer"
    assert rect(scene, "outer").contains(rect(scene, "sibling"))
    assert not overlaps(scene, "outer", "top")


def test_overlaps_that_were_already_there_are_left_alone(scene):
    # "under_g" already sits under the group's frame: arranging doesn't fling it away.
    load(scene, [CardData(id="g", title="G", kind=KIND_GROUP, arrange_grid=True),
                 *column("c", "g", 5),
                 CardData(id="under_g", title="Stuck", x=60, y=200)])
    before = rect(scene, "under_g")
    assert overlaps(scene, "g", "under_g")
    arrange(scene, "g")
    assert rect(scene, "under_g") == before


def test_arrange_and_push_is_one_undo_step(scene):
    load(scene, [CardData(id="g", title="G", kind=KIND_GROUP, arrange_grid=True),
                 *column("c", "g", 5),
                 CardData(id="beside", title="Beside", x=380, y=100)])
    before = rect(scene, "beside")
    arrange(scene, "g")
    assert rect(scene, "beside") != before
    scene.undo()
    assert rect(scene, "beside") == before
