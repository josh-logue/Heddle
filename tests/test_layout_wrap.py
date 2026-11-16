"""Auto-arrange's row limit (`wrap`): a chain carries on in a new row, starting at the
left, after `wrap` steps. Cards at one step (a branch) count once."""
from heddle.layout import H_GAP, ROW_GAP, V_GAP, Node, arrange


def N(i, x=0, y=0, color="", w=100, h=50, group=False):
    return Node(i, w, h, x, y, color, group)


def chain(ids):
    return list(zip(ids, ids[1:]))


def test_six_card_chain_with_limit_five_wraps_the_last_card_under_the_first():
    # The reference shape: five scenes in a row, the sixth starts row two at the left.
    heights = [142, 142, 142, 140, 125, 65]
    ids = ["rowan", "mabel", "greta", "warden", "east", "west"]
    nodes = [N(i, x=k * 300, w=230, h=h) for k, (i, h) in enumerate(zip(ids, heights))]
    p = arrange(nodes, chain(ids), wrap=5)
    for k, i in enumerate(ids[:5]):
        assert p[i][0] == k * (230 + H_GAP)
    # Single cards in a row are centred in the row's height (as today).
    assert p["rowan"][1] == 0 and p["east"][1] == (142 - 125) / 2
    assert p["west"] == (0, 142 + ROW_GAP)


def test_no_limit_or_a_roomy_limit_is_exactly_todays_layout():
    nodes = [N(c) for c in "abcdef"]
    today = arrange(nodes, chain("abcdef"))
    assert arrange(nodes, chain("abcdef"), wrap=0) == today
    assert arrange(nodes, chain("abcdef"), wrap=6) == today
    assert arrange(nodes, chain("abcdef"), wrap=99) == today


def test_long_chain_wraps_into_several_rows_restarting_at_the_left():
    p = arrange([N(c) for c in "abcdefg"], chain("abcdefg"), wrap=3)
    step = 100 + H_GAP
    row = 50 + ROW_GAP
    assert p == {"a": (0, 0), "b": (step, 0), "c": (2 * step, 0),
                 "d": (0, row), "e": (step, row), "f": (2 * step, row),
                 "g": (0, 2 * row)}


def test_a_branch_counts_once_and_is_never_split_across_rows():
    # a -> (b, c) -> d -> e: four steps, five cards. Limit 4 keeps it on one row.
    nodes = [N("a"), N("b", y=0), N("c", y=100), N("d"), N("e")]
    edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "e")]
    p = arrange(nodes, edges, wrap=4)
    assert p["e"][0] == 3 * (100 + H_GAP)
    # Limit 2: the branch column sits whole on row one; row one is as tall as it.
    p = arrange(nodes, edges, wrap=2)
    assert p["b"][0] == p["c"][0] == 100 + H_GAP and p["c"][1] == p["b"][1] + 50 + V_GAP
    row_two = 2 * 50 + V_GAP + ROW_GAP
    assert p["d"] == (0, row_two) and p["e"] == (100 + H_GAP, row_two)


def test_label_gaps_stay_inside_rows_and_none_is_carried_over_a_wrap():
    labels = {("b", "c"): (300.0, 20.0), ("c", "d"): (10.0, 20.0)}
    p = arrange([N(c) for c in "abcd"], chain("abcd"), wrap=2, labels=labels)
    assert p["c"] == (0, 50 + ROW_GAP)  # b -> c is the wrap: its label gap isn't used
    assert p["d"][0] == 100 + H_GAP     # a short label needs no more than H_GAP


def test_vertical_wraps_into_columns():
    p = arrange([N(c) for c in "abc"], chain("abc"), vertical=True, wrap=2)
    assert p == {"a": (0, 0), "b": (0, 50 + H_GAP), "c": (100 + ROW_GAP, 0)}


def test_color_lanes_keep_their_order_on_every_row():
    # Red, blue, red, blue: two lanes, red first; after the wrap red is still on top.
    nodes = [N("a", color="red"), N("b", color="blue"), N("c", color="red"), N("d", color="blue")]
    p = arrange(nodes, chain("abcd"), by_color=True, wrap=2)
    lane = 50 + V_GAP
    row_two = 2 * 50 + V_GAP + ROW_GAP
    assert p["a"] == (0, 0) and p["b"] == (100 + H_GAP, lane)
    assert p["c"] == (0, row_two) and p["d"] == (100 + H_GAP, row_two + lane)


def test_color_lanes_empty_in_a_row_take_no_room():
    nodes = [N("a", color="red"), N("b", color="red"), N("c", color="blue")]
    p = arrange(nodes, chain("abc"), by_color=True, wrap=2)
    # Row one holds only red, so it's one lane tall; row two holds only blue.
    assert p["c"] == (0, 50 + ROW_GAP)


def test_separate_chains_each_wrap_and_stack():
    nodes = [N("a"), N("b"), N("c"), N("x", y=500), N("y", y=500)]
    p = arrange(nodes, chain("abc") + [("x", "y")], wrap=2)
    row = 50 + ROW_GAP
    assert p["c"] == (0, row)
    assert p["x"] == (0, 2 * row) and p["y"] == (100 + H_GAP, 2 * row)


def test_unconnected_cards_wrap_after_the_limit():
    p = arrange([N(c, x=k) for k, c in enumerate("abcde")], [], wrap=2)
    step, row = 100 + V_GAP, 50 + V_GAP
    assert p == {"a": (0, 0), "b": (step, 0), "c": (0, row), "d": (step, row), "e": (0, 2 * row)}


def test_grid_is_never_wider_than_the_limit():
    nodes = [N(c, x=k) for k, c in enumerate("abcdefghi")]  # a 3 x 3 grid without a limit
    assert {x for x, _ in arrange(nodes, [], grid=True).values()} == {0, 130, 260}
    assert {x for x, _ in arrange(nodes, [], grid=True, wrap=2).values()} == {0, 130}
    assert {x for x, _ in arrange(nodes, [], grid=True, wrap=5).values()} == {0, 130, 260}


def test_mixed_block_caps_plain_cards_per_row():
    nodes = [N("g1", w=400, h=200, group=True), N("g2", x=500, w=400, h=200, group=True)]
    nodes += [N(c, x=1000 + k) for k, c in enumerate("abcd")]
    p = arrange(nodes, [], wrap=2)
    rows = {}
    for c in "abcd":
        rows.setdefault(p[c][1], []).append(c)
    assert all(len(r) <= 2 for r in rows.values()) and len(rows) == 2
    assert p["g1"][1] == p["g2"][1] == 0  # the groups keep their row
