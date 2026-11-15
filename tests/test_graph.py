"""The story graph: flow through groups, reachability, order, cycles and path counts."""
from warpingweft.graph import StoryGraph, longest_path_layers
from warpingweft.model import KIND_GROUP, CardData, ConnectionData


def card(cid, x=0.0, y=0.0, parent="", group=False):
    return CardData(id=cid, title=cid, x=x, y=y, parent=parent,
                    kind=KIND_GROUP if group else "card")


def arrows(*pairs):
    return [ConnectionData(s, t, id=f"{s}>{t}") for s, t in pairs]


def graph(cards, pairs):
    return StoryGraph(cards, arrows(*pairs))


def test_chain():
    g = graph([card("A", 0), card("B", 300), card("C", 600)], [("A", "B"), ("B", "C")])
    assert g.downstream("A") == {"B", "C"} and g.upstream("C") == {"A", "B"}
    assert g.downstream("C") == set() and g.upstream("A") == set()
    assert g.arrow_order() == ["A", "B", "C"]
    assert g.count_paths().count == 1 and not g.count_paths().has_cycles
    assert g.cycles() == []


def test_branch_and_merge():
    g = graph([card("A"), card("B", 300, 200), card("C", 300, 0), card("D", 600)],
              [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    assert g.count_paths().count == 2
    # Same step: top to bottom (C is above B).
    assert g.arrow_order() == ["A", "C", "B", "D"]
    assert g.upstream("D") == {"A", "B", "C"}


def test_cycle_is_found_and_counted_once():
    g = graph([card("A"), card("B", 300), card("C", 600), card("D", 900)],
              [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D")])
    assert g.cycles() == [["A", "B", "C"]]
    pc = g.count_paths()
    assert pc.count == 1 and pc.has_cycles
    assert "A" in g.downstream("A")  # a cycle leads back to it
    assert g.arrow_order()[-1] == "D"


def test_arrow_into_a_group_reaches_its_first_cards_and_leaves_from_its_last():
    cards = [card("X", 0), card("G", 200, group=True), card("P", 220, 50, "G"),
             card("Q", 520, 50, "G"), card("Y", 900)]
    g = graph(cards, [("X", "G"), ("P", "Q"), ("G", "Y")])
    assert "G" not in g.nodes()                    # a group with cards isn't a stop
    assert g.succ["X"] == ["P"] and g.pred["Y"] == ["Q"]
    assert g.downstream("X") == {"P", "Q", "Y"}
    assert g.upstream("Y") == {"X", "P", "Q"}
    assert g.arrow_order() == ["X", "P", "Q", "Y"]
    # Focus on the group itself: what comes before / after its contents.
    assert g.downstream("G") == {"Y"} and g.upstream("G") == {"X"}
    # The arrows into and out of the group light up with the cards they link.
    assert g.arrows_within({"X", "P"}) == {"X>G"}
    assert g.arrows_within({"P", "Q", "Y"}) == {"P>Q", "G>Y"}


def test_group_without_inner_arrows_leads_to_all_its_cards():
    cards = [card("X"), card("G", 200, group=True), card("P", 220, 0, "G"), card("Q", 220, 200, "G")]
    g = graph(cards, [("X", "G")])
    assert sorted(g.succ["X"]) == ["P", "Q"]
    assert g.count_paths().count == 2


def test_nested_groups_expand_down_to_cards():
    cards = [card("X"), card("G", 200, group=True), card("H", 220, 0, "G", group=True),
             card("P", 240, 20, "H"), card("Q", 600, 0, "G"), card("Y", 1000)]
    # P (inside H) leads to Q: inside G, H comes first and Q last.
    g = graph(cards, [("X", "G"), ("P", "Q"), ("G", "Y")])
    assert g.succ["X"] == ["P"] and g.pred["Y"] == ["Q"]
    assert g.containers_of({"P"}) == {"H", "G"}
    assert g.contents("G") == {"H", "P", "Q"}


def test_group_that_is_one_big_loop_is_entered_at_its_top_left_card():
    cards = [card("X"), card("G", 200, group=True), card("P", 220, 0, "G"), card("Q", 220, 300, "G")]
    g = graph(cards, [("X", "G"), ("P", "Q"), ("Q", "P")])
    assert g.succ["X"] == ["P"]
    assert g.cycles() == [["P", "Q"]]


def test_empty_group_is_an_ordinary_stop():
    g = graph([card("A"), card("E", 300, group=True), card("B", 600)], [("A", "E"), ("E", "B")])
    assert "E" in g.nodes() and g.arrow_order() == ["A", "E", "B"]


def test_board_without_arrows():
    g = graph([card("B", 300, 0), card("A", 0, 0), card("C", 0, 200)], [])
    assert g.arrow_order() == ["A", "B", "C"]  # reading order
    assert g.count_paths().count == 0 and g.routes() == []
    assert g.downstream("A") == set()


def test_bad_arrows_are_ignored():
    g = StoryGraph([card("A"), card("B", 300)],
                   [ConnectionData("A", "B", id="1"), ConnectionData("A", "B", id="2"),
                    ConnectionData("A", "A", id="3"), ConnectionData("A", "zzz", id="4")])
    assert list(g.arrows) == ["1"] and g.succ["A"] == ["B"]


def test_separate_chains_follow_reading_order():
    g = graph([card("C", 0, 400), card("D", 300, 400), card("A", 0, 0), card("B", 300, 0)],
              [("A", "B"), ("C", "D")])
    assert g.arrow_order() == ["A", "B", "C", "D"]


def test_longest_path_layers_drop_back_edges():
    succ = {"a": ["b"], "b": ["c"], "c": ["a"]}
    layers = longest_path_layers(["a", "b", "c"], succ, lambda i: i)
    assert sorted(layers.values()) == [0, 1, 2]
