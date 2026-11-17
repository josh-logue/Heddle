"""Strand cards: cards standing for a strand (character, location, tag, status). They
show its name, and its description in their details (never its picture); they're
outside the story tools; and they stay linked through renames, merges and undo."""
from PySide6.QtCore import QPointF

from heddle.export import export_text
from heddle.filters import matches
from heddle.graph import StoryGraph
from heddle.model import (
    FORMAT_VERSION, KIND_GROUP, KIND_STRAND, BoardData, CardData, ConnectionData, StrandInfo,
)


# ----- model --------------------------------------------------------------------------------
def test_strand_card_data_is_cleaned():
    c = CardData(kind=KIND_STRAND, strand_kind="nope", strand=" Mara ", title="ignored",
                 tags=["x"], characters=["y"], description="d", status="Draft")
    assert (c.strand_kind, c.strand, c.title) == ("characters", "Mara", "Mara")
    assert (c.tags, c.characters, c.description, c.status) == ([], [], "", "")
    plain = CardData(title="P", strand_kind="locations", strand="Keep")
    assert (plain.strand_kind, plain.strand) == ("", "")
    assert CardData(kind=KIND_STRAND, title="From title").strand == "From title"


def test_round_trip_and_version():
    board = BoardData(cards=[CardData(id="s", kind=KIND_STRAND, strand_kind="locations", strand="Keep")])
    raw = board.to_dict()
    assert raw["version"] == FORMAT_VERSION == 13
    back = BoardData.from_dict(raw).cards[0]
    assert (back.kind, back.strand_kind, back.strand) == (KIND_STRAND, "locations", "Keep")


# ----- story tools ----------------------------------------------------------------------------
def test_strand_cards_and_their_arrows_are_outside_the_story():
    cards = [CardData(id="a", x=0), CardData(id="b", x=300),
             CardData(id="m", kind=KIND_STRAND, strand="Mara", x=0, y=400),
             CardData(id="n", kind=KIND_STRAND, strand="Nia", x=300, y=400)]
    conns = [ConnectionData("a", "b"), ConnectionData("m", "n", label="sisters"), ConnectionData("b", "m")]
    g = StoryGraph(cards, conns)
    assert g.outside == {"m", "n"}
    assert g.succ["b"] == [] and [r.key for r in g.routes()] == [("a", "b")]


def test_outside_cards_are_never_a_groups_first_or_last_cards():
    """(Bug fix: also for cards marked 'not part of the story'.)"""
    cards = [CardData(id="a", x=0),
             CardData(id="g", kind=KIND_GROUP),
             CardData(id="note", parent="g", x=300, outside_story=True),
             CardData(id="inside", parent="g", x=300, y=300),
             CardData(id="map", kind=KIND_GROUP),
             CardData(id="loc", kind=KIND_STRAND, strand_kind="locations", strand="Keep", parent="map")]
    conns = [ConnectionData("a", "g"), ConnectionData("a", "map")]
    g = StoryGraph(cards, conns)
    assert g.succ["a"] == ["inside"]               # not the note, and not into the map
    assert {"note", "loc", "map"} <= g.outside


# ----- on the board --------------------------------------------------------------------------------
def test_create_one_undo_step(scene, settle, qapp):
    settle()
    card = scene.create_strand_card("characters", "Mara", QPointF(100, 100))
    qapp.processEvents()
    assert card.is_strand and card.card.title == "Mara" and card.isSelected()
    assert "Mara" in scene.all_values("characters")     # the card keeps the strand on the board
    scene.undo()
    assert not scene.cards


def test_face_shows_the_name_and_details_the_description(scene):
    card = scene.create_strand_card("characters", "Mara", QPointF(0, 0))
    collapsed = card.card_scene_rect().height()
    assert card._blocks == [] and not card._tag_pills
    card.set_details_visible(True)
    assert "No description yet" in card._blocks[0][1]
    scene.set_strand_info(StrandInfo("characters", "mara", "Eldest sister.", "/pics/mara.png"))
    assert card._blocks[0][1] == "Eldest sister."          # follows the Strands panel
    assert card.card_scene_rect().height() > collapsed
    assert all("mara.png" not in b[1] for b in card._blocks)  # the picture never shows


def test_rename_and_merge_keep_cards_linked(scene, settle):
    a = scene.create_strand_card("characters", "Mara", QPointF(0, 0))
    scene.create_strand_card("characters", "Maura", QPointF(300, 0))
    scene.set_strand_info(StrandInfo("characters", "Mara", "One"))
    scene.set_strand_info(StrandInfo("characters", "Maura", "Two"))
    settle()
    scene.rename_value("characters", "Mara", "Mira")
    settle()
    assert (a.card.strand, a.card.title) == ("Mira", "Mira")
    scene.rename_value("characters", "Mira", "Maura")       # merge
    settle()
    assert {c.card.strand for c in scene.strand_cards("characters", "maura")} == {"Maura"}
    assert len(scene.strand_cards("characters", "Maura")) == 2
    assert scene.strand("characters", "Maura").description.startswith("Two")
    scene.undo()
    assert {i.card.strand for i in scene.cards.values()} == {"Mira", "Maura"}


def test_a_strand_card_counts_as_a_use(scene):
    scene.saved_values = {"locations": ["Keep", "Spare"]}
    scene.create_strand_card("locations", "Keep", QPointF(0, 0))
    plain, _ = scene.unused_strands()
    assert plain == {"locations": ["Spare"]}
    assert scene.strand_card_counts("locations") == {"keep": 1}


def test_filter_keeps_a_strand_card_lit_by_its_own_strand():
    card = CardData(kind=KIND_STRAND, strand_kind="characters", strand="Mara", color="#3f9e6e")
    assert matches(card, {})
    assert matches(card, {"characters": {"mara"}}) and matches(card, {"pov": {"mara"}})
    assert not matches(card, {"characters": {"nia"}})
    assert not matches(card, {"tags": {"act 1"}})            # categories that don't apply
    assert matches(card, {"color": {"#3f9e6e"}})


def test_a_character_thread_lights_their_strand_card(scene, settle):
    a = scene.add_card(CardData(title="A", characters=["Mara"]))
    b = scene.add_card(CardData(title="B", characters=["Mara"], x=300))
    scene.add_connection(a, b)
    card = scene.create_strand_card("characters", "Mara", QPointF(0, 400))
    settle()
    assert scene.show_thread("Mara").startswith("Thread: Mara · 2 cards")  # it isn't a step
    assert card.highlight is True and card.badge == ""


def test_text_export_leaves_strand_cards_out(scene):
    scene.add_card(CardData(title="Scene one"))
    scene.create_strand_card("locations", "The Keep", QPointF(0, 300))
    text = export_text(scene.to_board_data(), scene.story_graph(), "Story")
    assert "Scene one" in text and "The Keep" not in text


def test_pasted_strand_card_brings_its_strand(scene):
    board = BoardData(cards=[CardData(kind=KIND_STRAND, strand_kind="tags", strand="Omen")])
    scene.load_board_data(board)
    assert "Omen" in scene.all_values("tags")


# ----- editor and panel ------------------------------------------------------------------------------------
def test_card_editor_strand_type(qapp):
    from heddle.dialogs import CardDialog
    d = CardDialog(CardData(title="Old", tags=["t"]), suggestions={"locations": ["Keep", "Hall"]})
    d.strand_radio.setChecked(True)
    assert not d._form.isRowVisible(d.title_edit) and d._form.isRowVisible(d.strand_row)
    assert not d.details_box.isVisible()
    d.strand_kind_combo.setCurrentIndex(d.strand_kind_combo.findData("locations"))
    assert [d.strand_name_combo.itemText(i) for i in range(d.strand_name_combo.count())] == ["Hall", "Keep"]
    d.strand_name_combo.setCurrentText("Keep")
    out = d.result_data()
    assert (out.kind, out.strand_kind, out.strand, out.title, out.tags) == (KIND_STRAND, "locations", "Keep",
                                                                           "Keep", [])
    back = CardDialog(out)
    assert back.strand_radio.isChecked() and back.strand_name_combo.currentText() == "Keep"


def test_panel_adds_cards_and_double_click_opens_it(window, qapp):
    s = window.scene
    s.add_card(CardData(title="A", characters=["Mara"]))
    window.show()
    window.strands_dock.show()
    qapp.processEvents()
    p = window.strands_panel
    p.refresh()
    p.select("characters", "Mara")
    p.add_card_btn.click()
    card = s.strand_cards("characters", "Mara")[0]
    p.refresh()
    assert "1 strand card" in p.usage.text()
    p.select("characters", "Mara")
    window.strands_dock.hide()
    s.strand_card_opened.emit("characters", "Mara")           # what double-clicking the card does
    qapp.processEvents()
    assert window.strands_dock.isVisible() and p.selected() == ("characters", "Mara")
    assert card.is_strand
