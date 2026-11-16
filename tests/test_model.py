import json
import math

import pytest

from heddle.model import (
    APP_ID, CARD_COLORS, BoardData, CardData, ConnectionData, board_values, clean_list, count_values, load_board,
    rename_in_list, rename_value, save_board,
)


# ----- clean_list ----------------------------------------------------------------
def test_clean_list_splits_strips_and_dedupes_case_insensitively():
    assert clean_list("Mara, rowan ,, MARA, Rowan") == ["Mara", "rowan"]
    assert clean_list(["a", " b ", 3, None, "A"]) == ["a", "b"]
    assert clean_list(None) == [] and clean_list(42) == []


# ----- loading older or hand-written files ---------------------------------------------
def test_comma_strings_split_and_missing_custom_colors_are_recovered(tmp_path):
    raw = {"cards": [{"id": "c1", "title": "Old", "characters": "Mara, Rowan", "color": "#123456"}]}
    p = tmp_path / "old.json"
    p.write_text(json.dumps(raw))
    board = load_board(p)
    assert board.cards[0].characters == ["Mara", "Rowan"]
    # no custom_colors list: non-preset colors in use are recovered
    assert board.custom_colors == ["#123456"]


def test_the_app_name_in_a_file_is_not_checked(tmp_path):
    """Boards saved before a rename keep their old "app" value until saved again."""
    p = tmp_path / "other.json"
    p.write_text(json.dumps({"app": "Something else", "version": 12,
                             "cards": [{"id": "a", "title": "Rowan"}]}), encoding="utf-8")
    assert [c.title for c in load_board(p).cards] == ["Rowan"]
    assert BoardData().to_dict()["app"] == APP_ID == "Heddle"  # saves use the current name


def test_unknown_keys_are_ignored_for_forward_compatibility():
    board = BoardData.from_dict({"cards": [{"title": "x", "from_the_future": 1}], "extra": True})
    assert board.cards[0].title == "x"


def test_not_a_board_raises():
    with pytest.raises(ValueError):
        BoardData.from_dict({"nope": []})


# ----- damaged values are coerced, never crash later ------------------------------------
def test_card_fields_are_coerced_to_proper_types():
    c = CardData(**{"id": None, "title": 7, "description": None, "color": "red", "status": ["x"],
                    "notes": {"a": 1}, "parent": 3, "x": "12", "y": math.nan, "width": math.inf,
                    "height": True, "tags": None, "kind": None,
                    "arrange_by_color": "false", "arrange_vertical": 1, "arrange_grid": "yes"})
    assert c.id and c.title == "7" and c.description == "" and c.color == CARD_COLORS[0]
    assert c.status == "" and c.notes == "" and c.parent == "3"
    assert (c.x, c.y, c.width, c.height) == (0.0, 0.0, 0.0, 0.0)
    assert c.tags == [] and c.kind == "card"
    assert c.arrange_by_color is c.arrange_vertical is c.arrange_grid is False
    assert CardData(color="#ABCDEF").color == "#abcdef"


def test_connection_fields_are_coerced():
    e = ConnectionData(source=None, target=5, label=None, id="")
    assert (e.source, e.target, e.label) == ("", "5", "") and e.id


def test_duplicate_ids_and_bad_lists_in_a_file_are_repaired():
    b = BoardData.from_dict({"cards": [{"id": "d"}, {"id": "d"}], "connections": "junk",
                             "custom_colors": ["#123456", "red", 5]})
    assert len({c.id for c in b.cards}) == 2 and b.connections == []
    assert b.custom_colors == ["#123456"]


# ----- rename & merge -------------------------------------------------------------------
@pytest.fixture
def cards():
    return [CardData(characters=["Rowan", "Bob"], status="Draft", tags=["intro"]),
            CardData(characters=["rowan"], status="draft"),
            CardData(characters=["Mara", "Rowan2"], status="Final")]


def test_rename_is_case_insensitive_and_only_touches_matches(cards):
    changed = rename_value(cards, "characters", "ROWAN", "Rówan")
    assert [c.characters for c in cards] == [["Rówan", "Bob"], ["Rówan"], ["Mara", "Rowan2"]]
    assert len(changed) == 2


def test_rename_into_existing_value_merges_with_typed_spelling(cards):
    rename_value(cards, "characters", "Bob", "ROWAN")
    assert cards[0].characters == ["ROWAN"] and cards[1].characters == ["ROWAN"]


def test_case_only_rename(cards):
    rename_value(cards, "characters", "rowan", "ROWAN")
    assert cards[0].characters[0] == "ROWAN" and cards[1].characters == ["ROWAN"]


def test_rename_status(cards):
    assert len(rename_value(cards, "status", "DRAFT", "Revised")) == 2
    assert [c.status for c in cards] == ["Revised", "Revised", "Final"]


def test_rename_noops_and_invalid_field(cards):
    assert rename_value(cards, "tags", "missing", "x") == []
    assert rename_value(cards, "tags", "intro", "   ") == []
    with pytest.raises(ValueError):
        rename_value(cards, "color", "a", "b")


def test_rename_in_list_merges():
    assert rename_in_list(["Forest", "Lake", "forest2"], "lake", "FOREST") == ["FOREST", "forest2"]


# ----- counting values -------------------------------------------------------------------
def test_count_values_rules():
    cs = [CardData(tags=["Plot", "plot", "Act"]), CardData(tags=["PLOT"]), CardData(status="Draft")]
    counted = count_values(cs, "tags", extra=["act", "Saved"])
    assert counted == {"plot": ("Plot", 2), "act": ("Act", 1), "saved": ("Saved", 0)}
    assert count_values(cs, "status") == {"draft": ("Draft", 1)}


# ----- saved values & board values ----------------------------------------------------------
def test_board_values_combines_cards_and_extras_first_spelling_wins():
    cs = [CardData(tags=["b", "A"]), CardData(tags=["a", "c"])]
    assert board_values(cs, "tags", ["C", "d"]) == ["A", "b", "c", "d"]
    assert board_values(cs, "status") == []


def test_saved_values_round_trip(tmp_path):
    b = BoardData(cards=[CardData(tags=["x"])], saved_values={"locations": ["Forest", "forest"]})
    p = tmp_path / "b.json"
    save_board(b, p)
    loaded = load_board(p)
    assert loaded.saved_values == {"locations": ["Forest"]}
    assert loaded.all_values("locations") == ["Forest"] and loaded.all_values("tags") == ["x"]


# ----- atomic save -------------------------------------------------------------------------
def test_failed_save_leaves_original_and_no_temp_file(tmp_path, monkeypatch):
    import heddle.model as model
    p = tmp_path / "b.json"
    save_board(BoardData(cards=[CardData(title="original")]), p)

    def locked(src, dst):
        raise PermissionError(13, "in use")
    monkeypatch.setattr(model.os, "replace", locked)
    with pytest.raises(PermissionError):
        save_board(BoardData(cards=[CardData(title="new")]), p)
    assert load_board(p).cards[0].title == "original"
    assert not (tmp_path / "b.json.tmp").exists()
