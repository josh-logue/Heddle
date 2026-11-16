from heddle.layout import H_GAP, ROW_GAP, V_GAP, Node, arrange


def N(i, x=0, y=0, color="", w=100, h=50):
    return Node(i, w, h, x, y, color)


def test_chain_runs_left_to_right_with_gaps():
    p = arrange([N("a"), N("b"), N("c")], [("a", "b"), ("b", "c")])
    assert p == {"a": (0, 0), "b": (100 + H_GAP, 0), "c": (2 * (100 + H_GAP), 0)}


def test_branches_stack_and_merge_is_centred():
    p = arrange([N("a"), N("b", y=0), N("c", y=100), N("d")],
                [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
    assert p["b"][0] == p["c"][0] and p["c"][1] == p["b"][1] + 50 + V_GAP
    assert p["d"][0] > p["b"][0]
    assert abs((p["d"][1] + 25) - (p["b"][1] + p["c"][1] + 50) / 2) < 1e-6


def test_cycles_are_tolerated():
    p = arrange([N("a"), N("b"), N("c")], [("a", "b"), ("b", "c"), ("c", "a")])
    assert set(p) == {"a", "b", "c"}
    assert len({x for x, _ in p.values()}) == 3      # still spread over three steps


def test_self_loops_and_unknown_ids_are_ignored():
    p = arrange([N("a"), N("b")], [("a", "a"), ("a", "zzz"), ("a", "b")])
    assert p["b"][0] == 100 + H_GAP


def test_separate_chains_stack_in_current_order():
    p = arrange([N("x", y=500), N("y", y=500), N("a"), N("b")], [("a", "b"), ("x", "y")])
    assert p["a"][1] == 0 and p["x"][1] == 50 + ROW_GAP


def test_vertical_transposes_the_layout():
    p = arrange([N("a"), N("b"), N("c")], [("a", "b"), ("b", "c")], vertical=True)
    assert p == {"a": (0, 0), "b": (0, 50 + H_GAP), "c": (0, 2 * (50 + H_GAP))}


def test_colour_lanes_put_each_colour_on_its_own_row():
    nodes = [N("intro", color="p"), N("elect", color="o"), N("adjust", color="p"), N("pack", color="r")]
    p = arrange(nodes, [("intro", "elect"), ("elect", "adjust"), ("adjust", "pack")], by_color=True)
    assert p["intro"][1] == p["adjust"][1] == 0
    assert p["elect"][1] == 50 + V_GAP and p["pack"][1] == 2 * (50 + V_GAP)
    xs = [p[i][0] for i in ("intro", "elect", "adjust", "pack")]
    assert xs == sorted(xs) and len(set(xs)) == 4


# ----- fewer crossed arrows ------------------------------------------------------------------
def crossed(p, edges):
    """Pairs of arrows between the same two columns whose ends swap order."""
    n = 0
    for k, (a1, b1) in enumerate(edges):
        for a2, b2 in edges[k + 1:]:
            if p[a1][0] == p[a2][0] and p[b1][0] == p[b2][0]:
                n += (p[a1][1] - p[a2][1]) * (p[b1][1] - p[b2][1]) < 0
    return n


def test_simple_crossing_is_untangled():
    # a is above b, but a's target sits below b's target
    nodes = [N("a", y=0), N("b", y=100), N("d", y=0), N("c", y=100)]
    edges = [("a", "c"), ("b", "d")]
    p = arrange(nodes, edges)
    assert crossed(p, edges) == 0 and p["c"][1] < p["d"][1]


def test_tangled_branches_are_untangled_across_several_steps(monkeypatch):
    # two parallel plotlines whose cards were placed in criss-crossing order
    nodes = [N("s", y=0),
             N("a1", y=0), N("b1", y=100),
             N("b2", y=0), N("a2", y=100),
             N("a3", y=0), N("b3", y=100),
             N("end", y=0)]
    edges = [("s", "a1"), ("s", "b1"), ("a1", "a2"), ("b1", "b2"),
             ("a2", "a3"), ("b2", "b3"), ("a3", "end"), ("b3", "end")]
    p = arrange(nodes, edges)
    assert crossed(p, edges) == 0
    # and with rows by colour too
    coloured = [Node(n.id, n.w, n.h, n.x, n.y, "x") for n in nodes]
    assert crossed(arrange(coloured, edges, by_color=True), edges) == 0
    # control: keeping the cards' current order (no untangling) does cross
    import heddle.layout as layout
    original = layout._order_in_layers
    monkeypatch.setattr(layout, "_order_in_layers",
                        lambda *a, **k: original(*a, **{**k, "sweeps": 0}))
    assert crossed(arrange(nodes, edges), edges) > 0


def test_clean_manual_order_is_kept():
    # already crossing-free: the cards' current top-to-bottom order is preserved
    nodes = [N("s"), N("lower", y=100), N("upper", y=0)]
    p = arrange(nodes, [("s", "upper"), ("s", "lower")])
    assert p["upper"][1] < p["lower"][1]


# ----- cards without arrows ----------------------------------------------------------------
LOOSE = [N(str(k), x=k * 10) for k in range(5)]


def test_unconnected_cards_follow_the_arrow_direction():
    h = arrange(LOOSE, [])
    assert {y for _, y in h.values()} == {0} and [h[str(k)][0] for k in range(5)] == [k * 130 for k in range(5)]
    v = arrange(LOOSE, [], vertical=True)
    assert {x for x, _ in v.values()} == {0} and [v[str(k)][1] for k in range(5)] == [k * 80 for k in range(5)]


def test_unconnected_cards_grid():
    g = arrange(LOOSE, [], grid=True)              # 5 cards -> 3 columns
    assert g["2"] == (260, 0) and g["3"] == (0, 80)
    gv = arrange(LOOSE, [], grid=True, vertical=True)  # fills columns first
    assert gv["2"] == (0, 160) and gv["3"] == (130, 0)


def test_loose_block_goes_after_chains():
    nodes = [N("a"), N("b", x=200), N("x", y=500), N("y", x=50, y=500)]
    p = arrange(nodes, [("a", "b")])
    assert p["x"] == (0, 50 + ROW_GAP) and p["y"] == (100 + V_GAP, 50 + ROW_GAP)


def test_loose_cards_split_by_colour():
    cc = [N("r1", x=0, color="red"), N("b1", x=1, color="blue"), N("r2", x=2, color="red")]
    p = arrange(cc, [], by_color=True)
    assert p["r1"][1] == p["r2"][1] == 0 and p["b1"][1] == 50 + V_GAP
