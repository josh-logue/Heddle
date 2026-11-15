"""F4: the POV field, and the per-board card-face options (POV line, character pills)."""
from PySide6.QtCore import QPointF

import warpingweft.dialogs as dlg
from warpingweft.card_item import HEADER_HEIGHT
from warpingweft.filters import collect_options, matches
from warpingweft.model import DISPLAY_DEFAULTS, KIND_GROUP, CardData, rename_value, save_board


def run_editor(monkeypatch, scene, item, edit):
    """Open the real editor on `item`, let `edit(dialog)` change it, press OK."""
    seen = {}

    def fake_exec(self):
        seen["dialog"] = self
        edit(self)
        self.accept()
        return self.result()
    monkeypatch.setattr(dlg.CardDialog, "exec", fake_exec)
    scene.edit_card(item)
    return seen["dialog"]


def height(item):
    return item.card_rect().height()


# ----- editing ------------------------------------------------------------------------
def test_pov_is_saved_and_joins_the_characters(scene, monkeypatch):
    scene.add_card(CardData(title="Other", characters=["Mabel", "Gus"], x=600))
    a = scene.add_card(CardData(title="A", characters=["Ailsa"]))
    d = run_editor(monkeypatch, scene, a, lambda d: d.pov_combo.setCurrentText("rowan"))
    # The card's own characters are offered first, then the rest of the board's.
    choices = [d.pov_combo.itemText(i) for i in range(d.pov_combo.count())]
    assert choices[:2] == ["", "Ailsa"] and set(choices[2:]) >= {"Gus", "Mabel"}
    assert a.card.pov == "rowan" and a.card.characters == ["Ailsa", "rowan"]


def test_choosing_an_existing_character_as_pov_uses_its_spelling(scene, monkeypatch):
    a = scene.add_card(CardData(title="A", characters=["Rowan"]))
    run_editor(monkeypatch, scene, a, lambda d: d.pov_combo.setCurrentText("ROWAN"))
    assert a.card.pov == "Rowan" and a.card.characters == ["Rowan"]


def test_removing_the_pov_characters_chip_clears_the_pov(scene, monkeypatch):
    a = scene.add_card(CardData(title="A", pov="Rowan", characters=["Rowan", "Mabel"]))
    d = run_editor(monkeypatch, scene, a, lambda d: d.characters_input.remove_value("Rowan"))
    assert d.pov_combo.currentText() == ""
    assert a.card.pov == "" and a.card.characters == ["Mabel"]


# ----- rename & filter -------------------------------------------------------------------
def test_renaming_a_character_renames_the_pov():
    cards = [CardData(pov="Rowan"), CardData(characters=["rowan"]), CardData(pov="Mabel")]
    changed = rename_value(cards, "characters", "Rowan", "Roan")
    assert [c.pov for c in cards] == ["Roan", "", "Mabel"]
    assert [c.characters for c in cards][:2] == [["Roan"], ["Roan"]]
    assert changed == cards[:2]


def test_rename_in_the_scene_updates_the_pov_and_face(scene):
    a = scene.add_card(CardData(title="A", pov="Rowan"))
    assert scene.rename_value("characters", "Rowan", "Roan") == 1
    assert a.card.pov == "Roan"
    assert any(text == "Roan" for _, text, _, _ in a._blocks)


def test_filter_by_pov():
    cards = [CardData(id="a", pov="Rowan"), CardData(id="b", characters=["Rowan"]), CardData(id="c")]
    options = collect_options(cards)["pov"]
    assert [(name, n) for _, name, n in options] == [("Rowan", 1), ("(none)", 2)]
    shown = [c.id for c in cards if matches(c, {"pov": {"rowan"}})]
    assert shown == ["a"]


def test_filter_selection_follows_a_character_rename(window, tick_filter):
    s = window.scene
    s.add_card(CardData(title="A", pov="Rowan"))
    s.add_card(CardData(title="B", x=400))
    window.show()
    tick_filter(window, "pov", "rowan")
    assert window.filter_panel.is_active()
    s.rename_value("characters", "Rowan", "Roan")
    assert window.filter_panel._selection["pov"] == {"roan"}
    assert window._filter_state[0].cards_shown == 1  # still showing just that card


# ----- card face ---------------------------------------------------------------------------
def test_pov_line_shows_by_default_and_can_be_hidden(scene):
    plain = scene.add_card(CardData(title="Plain"))
    pov = scene.add_card(CardData(title="POV", pov="Rowan", x=400))
    assert height(pov) > height(plain)
    assert ("POV" in [t for _, t, _, _ in pov._blocks]) and pov.face_options() == (True, False, True)
    assert scene.set_display_option("show_pov", False)
    assert height(pov) == height(plain)
    assert not scene.set_display_option("show_pov", False)  # no change, nothing to do


def test_character_pills_skip_the_pov_shown_above_them(scene):
    a = scene.add_card(CardData(title="A", pov="Rowan", characters=["Mabel", "Rowan"]))
    before = height(a)
    scene.set_display_option("show_characters", True)
    assert [t for _, t in a._char_pills] == ["Mabel"] and height(a) > before
    scene.set_display_option("show_pov", False)
    assert [t for _, t in a._char_pills] == ["Mabel", "Rowan"]


def test_face_options_refit_groups_and_undo(window):
    s = window.scene
    g = s.add_card(CardData(title="G", kind=KIND_GROUP))
    a = s.add_card(CardData(title="A", characters=["Mabel", "Gus"], x=0, y=60, parent=g.card.id))
    s._refit_ids({g.card.id})
    s.reset_history()
    group_h, card_h = height(g), height(a)
    assert not window.act_show_characters.isChecked()

    window.act_show_characters.trigger()
    s.flush_history()
    assert s.display["show_characters"] and height(a) > card_h and height(g) > group_h
    assert window.act_show_characters.isChecked() and window.isWindowModified()

    assert s.undo()
    a2, g2 = s.cards[a.card.id], s.cards[g.card.id]
    assert not s.display["show_characters"] and height(a2) == card_h and height(g2) == group_h
    assert not window.act_show_characters.isChecked()
    assert s.redo() and window.act_show_characters.isChecked()
    assert height(s.cards[a.card.id]) > card_h


def test_group_with_a_pov_gets_a_header_panel(scene):
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP, pov="Rowan"))
    assert g.header_area_height() > HEADER_HEIGHT


def test_face_options_are_saved_per_board(window, tmp_path):
    s = window.scene
    s.add_card(CardData(title="A", pov="Rowan", characters=["Mabel"]))
    s.set_display_option("show_characters", True)
    s.set_display_option("show_pov", False)
    path = tmp_path / "face.json"
    save_board(s.to_board_data(), path)

    window.setWindowModified(False)
    window.new_board()
    assert s.display == DISPLAY_DEFAULTS
    assert window.act_show_pov.isChecked() and not window.act_show_characters.isChecked()

    window.open_path(path)
    a = next(iter(window.scene.cards.values()))
    assert window.act_show_characters.isChecked() and not window.act_show_pov.isChecked()
    assert [t for _, t in a._char_pills] == ["Mabel", "Rowan"]   # laid out with the board's options
    assert "POV" not in [t for _, t, _, _ in a._blocks]


def test_pasted_cards_use_the_boards_face_options(window):
    s = window.scene
    a = s.add_card(CardData(title="A", characters=["Mabel"]))
    s.set_display_option("show_characters", True)
    a.setSelected(True)
    frag = s.selection_fragment()
    pasted = s.paste_fragment(frag, QPointF(0, 400))
    assert [t for _, t in pasted[0]._char_pills] == ["Mabel"]
    assert height(pasted[0]) == height(a)
