"""Board options: hide card descriptions (View → Card Face → Show Descriptions), and
Compact Cards, which makes a card with nothing else on its face just its title bar."""
import json

from warpingweft.card_item import HEADER_HEIGHT
from warpingweft.model import DISPLAY_DEFAULTS, BoardData, CardData


def texts(item):
    return [b[1] for b in item._blocks]


def test_defaults():
    assert DISPLAY_DEFAULTS["show_description"] is True
    assert DISPLAY_DEFAULTS["compact_cards"] is False


def test_hiding_removes_the_description_and_shows_it_on_hover(scene):
    a = scene.add_card(CardData(title="A", description="Rowan reaches the mill."))
    long = scene.add_card(CardData(title="L", description="Rowan reaches the mill. " * 6, x=300))
    one_line, tall = a.card_scene_rect().height(), long.card_scene_rect().height()
    assert a.toolTip() == ""  # short enough to show whole: no tooltip
    assert scene.set_display_option("show_description", False)
    assert "Rowan reaches the mill." not in texts(a)
    assert "Rowan reaches the mill." in a.toolTip()
    # The blank body is one line high: a one-line card doesn't change, longer ones shrink
    assert a.card_scene_rect().height() == one_line
    assert long.card_scene_rect().height() == one_line < tall
    scene.set_display_option("show_description", True)
    assert "Rowan reaches the mill." in texts(a) and long.card_scene_rect().height() == tall
    assert a.toolTip() == ""


def test_no_description_words_go_too(scene):
    """"No description" is a description placeholder: hidden with descriptions,
    whatever its own option says."""
    empty = scene.add_card(CardData(title="Empty"))
    scene.set_display_option("show_description", False)
    assert "No description" not in texts(empty) and empty.toolTip() == ""


def test_face_rows_stay_and_close_up(scene):
    tagged = scene.add_card(CardData(title="T", tags=["Act 1"], pov="Mara", description="Long text."))
    scene.set_display_option("show_description", False)
    assert [p[1] for p in tagged._tag_pills] == ["Act 1"]
    assert "Mara" in texts(tagged) and "Long text." not in texts(tagged)
    # Same height as a tag-and-POV card without a description and "No description" off
    scene.set_display_option("show_description", True)
    scene.set_display_option("show_no_description", False)
    bare = scene.add_card(CardData(title="B", tags=["Act 1"], pov="Mara", x=300))
    closed_up = bare.card_scene_rect().height()
    scene.set_display_option("show_description", False)
    assert tagged.card_scene_rect().height() == closed_up


def test_empty_face_keeps_a_line_unless_compact(scene):
    plain = scene.add_card(CardData(title="Plain", description="Text"))
    tagged = scene.add_card(CardData(title="Tagged", tags=["Act 1"], x=300))
    scene.set_display_option("show_description", False)
    kept = plain.card_scene_rect().height()
    assert kept > HEADER_HEIGHT
    tagged_h = tagged.card_scene_rect().height()
    assert scene.set_display_option("compact_cards", True)
    assert plain.card_scene_rect().height() == HEADER_HEIGHT       # just the title bar
    assert tagged.card_scene_rect().height() == tagged_h            # the tags are its body


def test_compact_does_nothing_while_descriptions_show(scene):
    plain = scene.add_card(CardData(title="Plain"))
    h = plain.card_scene_rect().height()
    scene.set_display_option("compact_cards", True)
    assert plain.card_scene_rect().height() == h and "No description" in texts(plain)


def test_compact_card_details_open_under_the_title_bar(scene):
    plain = scene.add_card(CardData(title="Plain", status="Draft"))
    scene.set_display_option("show_description", False)
    scene.set_display_option("compact_cards", True)
    plain.set_details_visible(True)
    assert plain._details_top is None  # no dividing line inside the title bar
    assert "Draft" in texts(plain)
    assert plain.card_scene_rect().height() > HEADER_HEIGHT
    plain.set_details_visible(False)
    assert plain.card_scene_rect().height() == HEADER_HEIGHT


def test_groups_and_strand_cards_are_unaffected(scene):
    group = scene.add_card(CardData(title="G", kind="group", tags=["Act 1"]))
    strand = scene.add_card(CardData(title="Mara", kind="strand", strand_kind="characters",
                                     strand="Mara", x=400))
    before = (group.card_scene_rect().height(), strand.card_scene_rect().height())
    scene.set_display_option("show_description", False)
    scene.set_display_option("compact_cards", True)
    assert (group.card_scene_rect().height(), strand.card_scene_rect().height()) == before


def test_loaded_board_is_laid_out_with_it_off(scene):
    """Cards are laid out before joining the board; the new options must be in the
    layout key, or a loaded board would still show descriptions."""
    board = BoardData(cards=[CardData(id="a", title="A", description="Text")],
                      display=dict(DISPLAY_DEFAULTS, show_description=False, compact_cards=True))
    scene.load_board_data(board)
    assert "Text" not in texts(scene.cards["a"])
    assert scene.cards["a"].card_scene_rect().height() == HEADER_HEIGHT


def test_menu_items_undo_and_save(window):
    s = window.scene
    s.add_card(CardData(title="A", description="Text"))
    assert window.act_show_description.isChecked()
    assert window.act_show_no_description.isEnabled() and not window.act_compact_cards.isEnabled()
    window.act_show_description.setChecked(False)
    assert s.display["show_description"] is False
    assert not window.act_show_no_description.isEnabled() and window.act_compact_cards.isEnabled()
    window.act_compact_cards.setChecked(True)
    raw = json.loads(json.dumps(s.to_board_data().to_dict()))
    loaded = BoardData.from_dict(raw).display
    assert loaded["show_description"] is False and loaded["compact_cards"] is True
    s.undo()
    s.undo()
    assert s.display["show_description"] is True and window.act_show_description.isChecked()
    assert window.act_show_no_description.isEnabled() and not window.act_compact_cards.isEnabled()


def test_older_boards_load_with_descriptions_shown():
    raw = {"version": 10, "cards": [], "connections": [], "display": {"show_tags": False}}
    display = BoardData.from_dict(raw).display
    assert display["show_description"] is True and display["compact_cards"] is False


def test_board_options_dialog_greys_out_what_does_not_apply(qapp):
    from warpingweft.board_options import BoardOptionsDialog
    dialog = BoardOptionsDialog(dict(DISPLAY_DEFAULTS))
    assert dialog.checks["show_no_description"].isEnabled()
    assert not dialog.checks["compact_cards"].isEnabled()
    dialog.checks["show_description"].setChecked(False)
    assert not dialog.checks["show_no_description"].isEnabled()
    assert dialog.checks["compact_cards"].isEnabled()
    dialog.checks["compact_cards"].setChecked(True)
    values = dialog.values()
    assert values["show_description"] is False and values["compact_cards"] is True
    dialog.deleteLater()
