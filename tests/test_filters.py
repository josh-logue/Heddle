from warpingweft.filters import NONE_KEY, NONE_LABEL, card_keys, collect_options, matches
from warpingweft.model import CardData

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
    assert matches(B, s) and not matches(B, s, characters_all=True)
    assert matches(A, s, characters_all=True)


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
