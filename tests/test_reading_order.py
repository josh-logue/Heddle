"""Auto-arrange keeps reading order as you'd read the board by eye: lines from top
to bottom, left to right within a line, where things a few pixels out of level
still count as one line (they used to be ordered by their exact top edge)."""
from warpingweft.layout import Node, arrange, reading_rank
from warpingweft.model import KIND_GROUP, CardData


def order(rank):
    return sorted(rank, key=rank.__getitem__)


def test_side_by_side_but_out_of_level_reads_left_to_right():
    # Town Wards before arranging: East Ward on the left sat ~1 px lowest.
    nodes = [Node("first", 240, 460, 75, 117, group=True), Node("second", 240, 460, 480, 103, group=True),
             Node("third", 240, 460, 885, 116, group=True), Node("supreme", 180, 55, 100, 633)]
    assert order(reading_rank(nodes)) == ["first", "second", "third", "supreme"]


def test_a_ragged_column_stays_a_column():
    nodes = [Node("a", 200, 60, 10, 0), Node("b", 200, 60, 0, 70), Node("c", 200, 60, 6, 125),
             Node("d", 200, 60, -4, 180)]      # c overlaps b by 5 px: still below it
    assert order(reading_rank(nodes)) == ["a", "b", "c", "d"]


def test_a_small_card_beside_a_tall_group_is_on_its_line():
    nodes = [Node("tall", 300, 600, 0, 0, group=True), Node("small", 200, 60, 400, 250),
             Node("below", 200, 60, 0, 700)]
    assert order(reading_rank(nodes)) == ["tall", "small", "below"]


def test_student_council_arranges_first_second_third():
    nodes = [Node("first", 240, 460, 75, 117, group=True), Node("second", 240, 460, 480, 103, group=True),
             Node("third", 240, 460, 885, 116, group=True), Node("supreme", 180, 55, 100, 633)]
    p = arrange(nodes, [])                                   # left to right
    assert p["first"][0] < p["second"][0] < p["third"][0]
    assert p["supreme"][1] > p["first"][1]                   # the card goes under the groups


def test_top_to_bottom_reads_the_same_way():
    nodes = [Node("left", 200, 60, 0, 12), Node("right", 200, 60, 300, 0), Node("next", 200, 60, 0, 200)]
    p = arrange(nodes, [], vertical=True)
    assert p["left"][1] < p["right"][1] < p["next"][1]


def test_on_the_board(scene):
    council = scene.add_card(CardData(title="Town Wards", kind=KIND_GROUP))
    years = {}
    for name, x, y in (("East Ward", 75, 117), ("North Ward", 480, 103), ("West Ward", 885, 116)):
        g = scene.add_card(CardData(title=name, kind=KIND_GROUP, parent=council.card.id, x=x, y=y))
        scene.add_card(CardData(title=f"{name} card", parent=g.card.id, x=x + 20, y=y + 60))
        years[name] = g
    scene._update_z()
    scene._refit_ids({g.card.id for g in years.values()} | {council.card.id})
    scene.auto_arrange_group(council)
    xs = [years[n].card_scene_rect().left() for n in ("East Ward", "North Ward", "West Ward")]
    assert xs == sorted(xs)
