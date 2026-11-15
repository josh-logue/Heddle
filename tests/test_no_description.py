"""Board option: hide "No description". A card with nothing else on its face keeps
the space (as if the words were invisible); one showing tags, POV or characters
closes it up, so those rows are its body."""
from warpingweft.model import DISPLAY_DEFAULTS, BoardData, CardData


def texts(item):
    return [b[1] for b in item._blocks]


def test_shown_by_default(scene):
    a = scene.add_card(CardData(title="Empty"))
    assert DISPLAY_DEFAULTS["show_no_description"] is True
    assert "No description" in texts(a)


def test_hidden_keeps_the_space_on_an_otherwise_empty_card(scene):
    empty = scene.add_card(CardData(title="Empty"))
    height = empty.card_scene_rect().height()
    assert scene.set_display_option("show_no_description", False)
    assert "No description" not in texts(empty)
    assert empty.card_scene_rect().height() == height                # invisible, not removed


def test_hidden_closes_up_under_other_rows(scene):
    scene.set_display_option("show_characters", True)
    warden = scene.add_card(CardData(title="Warden", characters=["Rowan"]))
    tagged = scene.add_card(CardData(title="Tagged", tags=["Office"], x=300))
    pov = scene.add_card(CardData(title="POV", pov="Mara", x=600))
    before = {c: c.card_scene_rect().height() for c in (warden, tagged, pov)}
    scene.set_display_option("show_no_description", False)
    for c in (warden, tagged, pov):
        assert "No description" not in texts(c)
        assert c.card_scene_rect().height() < before[c]                # that row is the body now
    # ...but if the characters aren't on the face, the card has nothing else: keeps the space
    scene.set_display_option("show_characters", False)
    plain = scene.add_card(CardData(title="Plain"))
    assert warden.card_scene_rect().height() == plain.card_scene_rect().height()


def test_cards_with_a_description_are_unchanged(scene):
    a = scene.add_card(CardData(title="A", description="Something happens."))
    height = a.card_scene_rect().height()
    scene.set_display_option("show_no_description", False)
    assert "Something happens." in texts(a) and a.card_scene_rect().height() == height


def test_hidden_on_a_board_loaded_with_it_off(scene):
    # Cards are laid out before they join the board, and only the tag/POV/character
    # options used to trigger a re-layout, so a loaded board still said "No description"
    # until the option was toggled.
    display = dict(DISPLAY_DEFAULTS, show_no_description=False)
    board = BoardData(cards=[CardData(id="e", title="Empty"),
                             CardData(id="c", title="Warden", characters=["Rowan"], x=300)],
                      display=display)
    scene.load_board_data(board)
    for card_id in ("e", "c"):  # (characters are off by default: nothing else on the face)
        assert "No description" not in texts(scene.cards[card_id])


def test_saved_undoable_and_in_the_menu(window, qapp):
    s = window.scene
    window.act_show_no_description.setChecked(False)
    assert s.display["show_no_description"] is False
    assert BoardData.from_dict(s.to_board_data().to_dict()).display["show_no_description"] is False
    s.undo()
    qapp.processEvents()
    assert s.display["show_no_description"] is True and window.act_show_no_description.isChecked()
