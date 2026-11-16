"""Find and replace in card text (one undo step), and search that covers strands:
searching "Greta" finds every card she's on, not just ones whose text names her."""
from heddle.filters import search_cards
from heddle.model import KIND_GROUP, KIND_STRAND, CardData, StrandInfo, count_replacements, replace_text
from heddle.replace_dialog import ReplaceDialog
from heddle.scene import BoardScene


def test_search_finds_strands_after_text():
    cards = [CardData(id="a", title="Opening", characters=["Greta"]),
             CardData(id="b", title="Greta arrives"),
             CardData(id="c", title="Fair", locations=["Gretaby Hall"]),
             CardData(id="d", kind=KIND_STRAND, title="Greta", strand_kind="characters", strand="Greta"),
             CardData(id="e", title="Elsewhere")]
    found = {cid: (label, snippet) for cid, label, snippet in search_cards(cards, "greta")}
    assert found["a"] == ("Character", "Greta")
    assert found["b"][0] == "Title"
    assert found["c"] == ("Location", "Gretaby Hall")
    assert "d" in found and "e" not in found


def test_search_looks_in_strand_descriptions():
    cards = [CardData(id="a", title="Council", characters=["Greta"])]
    info = {("characters", "greta"): StrandInfo(kind="characters", name="Greta",
                                                description="Treasurer of the Town Wards")}
    assert search_cards(cards, "treasurer") == []
    assert search_cards(cards, "treasurer", info) == [("a", "Greta’s description", "Treasurer of the Town Wards")]


def test_replace_text_ignores_case_by_default_and_skips_strand_cards():
    cards = [CardData(title="Rrpresentative"), CardData(title="rrpresentative", notes="RRPRESENTATIVE"),
             CardData(kind=KIND_STRAND, title="Rrpresentative", strand_kind="tags", strand="Rrpresentative"),
             CardData(kind=KIND_GROUP, title="G", description="Rrpresentative")]
    assert count_replacements(cards, "rrpresentative", ["title", "description", "notes"]) == (3, 2)
    changed = replace_text(cards, "rrpresentative", "Representative", ["title", "description", "notes"])
    assert len(changed) == 2
    assert [c.title for c in cards[:3]] == ["Representative", "Representative", "Rrpresentative"]
    assert cards[1].notes == "Representative"
    assert cards[3].description == "Rrpresentative"           # groups have no description


def test_match_case_and_special_characters():
    card = CardData(title="Cost (approx.) $5 · cost")
    assert replace_text([card], "cost", "Price", ["title"], match_case=True)
    assert card.title == "Cost (approx.) $5 · Price"
    replace_text([card], "(approx.) $5", r"\1 about $5", ["title"])
    assert card.title == r"Cost \1 about $5 · Price"           # taken literally, both ways


def test_replacing_on_the_board_is_one_undo_step(qapp):
    s = BoardScene()
    items = [s.add_card(CardData(title=f"Rrpresentative {n}", x=n * 400)) for n in range(3)]
    s.mark_modified()
    s.reset_history()
    assert s.replace_in_cards("Rrpresentative", "Representative", ["title"]) == 3
    s.flush_history()
    assert all(i.card.title.startswith("Representative") for i in items)
    assert s.undo()
    assert sorted(i.card.title for i in s.cards.values()) == [f"Rrpresentative {n}" for n in range(3)]


def test_replacing_only_in_selected_cards(qapp):
    s = BoardScene()
    a = s.add_card(CardData(title="Old A"))
    b = s.add_card(CardData(title="Old B", x=400))
    assert s.replace_in_cards("Old", "New", ["title"], ids=[a.card.id]) == 1
    assert (a.card.title, b.card.title) == ("New A", "Old B")


def test_the_dialog_previews_the_count(qapp):
    cards = [CardData(id="a", title="Old"), CardData(id="b", title="Old Old")]
    d = ReplaceDialog(cards, ["a"])
    d.find_edit.setText("old")
    assert d.preview.text() == "3 matches in 2 cards (one undo step)"
    d.selected_box.setChecked(True)
    assert d.preview.text() == "1 match in 1 card (one undo step)" and d.selected_only()
    d.find_edit.setText("nothing")
    assert d.preview.text() == "No matches"
