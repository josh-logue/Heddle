from heddle.filters import NONE_KEY, NONE_LABEL, card_keys, collect_options, matches
from heddle.model import CardData

A = CardData(title="A", tags=["Act 1"], characters=["Mara", "Rowan"], status="Draft", color="#4a7fc1")
B = CardData(title="B", tags=["Act 2"], characters=["Mara"], color="#d9822b")
C = CardData(title="C", tags=[], characters=["Scribe"], status="draft", color="#4a7fc1")


def sel(**kw):
    base = {c: set() for c in ("tags", "color", "characters", "locations", "status")}
    base.update({k: set(v) for k, v in kw.items()})
    return base


def test_no_selection_matches_everything():
    assert all(matches(c, sel()) for c in (A, B, C))


def test_values_in_one_category_are_ored():
    s = sel(tags={"act 1", "act 2"})
    assert matches(A, s) and matches(B, s) and not matches(C, s)


def test_categories_are_anded():
    s = sel(tags={"act 1", "act 2"}, characters={"rowan"})
    assert [matches(c, s) for c in (A, B, C)] == [True, False, False]


def test_characters_all_mode():
    s = sel(characters={"mara", "rowan"})
    assert matches(B, s) and not matches(B, s, match_all={"characters"})
    assert matches(A, s, match_all={"characters"})


def test_match_all_per_category():
    """Tags and locations can need every ticked entry too, each on its own: all
    these tags, but any of these characters."""
    d = CardData(title="D", tags=["Act 1", "Act 2"], characters=["Mara"], locations=["Dock", "Mill"])
    s = sel(tags={"act 1", "act 2"}, characters={"mara", "rowan"})
    assert [matches(c, s, match_all={"tags"}) for c in (A, B, d)] == [False, False, True]
    assert [matches(c, s) for c in (A, B, d)] == [True, True, True]
    assert matches(d, s, match_all={"tags", "characters"}) is False  # d lacks Rowan
    loc = sel(locations={"dock", "mill"})
    e = CardData(title="E", locations=["Dock"])
    assert matches(e, loc) and not matches(e, loc, match_all={"locations"})
    assert matches(d, loc, match_all={"locations"})


def test_match_all_introductions():
    s = {"introduces": {"mara", "rowan"}}
    extras = {"introduces": {A.id: ["Mara", "Rowan"], B.id: ["Mara"]}}
    assert matches(B, s, extras=extras) and not matches(B, s, {"introduces"}, extras)
    assert matches(A, s, {"introduces"}, extras)


def test_match_all_ignored_for_single_value_categories():
    """A card has one colour, POV and status: "all" of two would match nothing, so
    those stay "any" even if asked."""
    s = sel(status={"draft", "done"}, color={"#4a7fc1", "#d9822b"})
    assert matches(A, s, match_all={"status", "color", "pov"})


def test_match_all_with_none_matches_nothing():
    s = sel(tags={NONE_KEY, "act 1"})
    assert not any(matches(c, s, match_all={"tags"}) for c in (A, B, C))


def test_match_all_leaves_strand_cards_lit_by_their_own_strand():
    """A strand card stands for one strand, so it can never have two: it stays lit
    when its strand is one of the ticked ones."""
    card = CardData(title="Act 1", kind="strand", strand_kind="tags", strand="Act 1")
    s = sel(tags={"act 1", "act 2"})
    assert matches(card, s, match_all={"tags"})


def test_none_key_matches_empty_fields():
    assert card_keys(C, "tags") == {NONE_KEY} and card_keys(B, "status") == {NONE_KEY}
    s = sel(status={NONE_KEY})
    assert matches(B, s) and not matches(A, s)


def test_matching_is_case_insensitive():
    s = sel(status={"draft"})
    assert matches(A, s) and matches(C, s)


def test_collect_options_counts_sorts_and_puts_none_last():
    opts = collect_options([A, B, C])
    assert opts["status"] == (("draft", "Draft", 2), (NONE_KEY, NONE_LABEL, 1))
    assert [d for _, d, _ in opts["characters"]] == ["Mara", "Rowan", "Scribe"]
    assert dict((k, n) for k, _, n in opts["characters"])["mara"] == 2
    assert opts["tags"][-1] == (NONE_KEY, NONE_LABEL, 1)
    assert ("#4a7fc1", "Blue", 2) in opts["color"]      # preset colours shown by name
