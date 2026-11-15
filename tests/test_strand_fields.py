"""Custom fields on strands (Age, Ancestry, Biome…): ordered name/value pairs kept in
StrandInfo, saved with the board, merged on rename and copied by "apply"."""
import pytest
from conftest import wait_until
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit

from warpingweft.model import (
    FORMAT_VERSION, BoardData, CardData, StrandInfo, apply_fields, clean_strands, merge_fields,
)


def test_fields_are_cleaned_into_ordered_pairs():
    s = StrandInfo("characters", "Rowan", fields=[
        {"name": " Age ", "value": " 34 "},
        ["Ancestry", "half-elf"],
        {"name": "", "value": "no name: dropped"},
        {"name": "AGE", "value": "duplicate name: dropped"},
        {"name": "Home", "value": None},
        {"name": "Line\nbreaks", "value": "one\nline"},
        "junk", 42, {"value": "no name key"}, ["too", "many", "items"],
    ])
    assert s.fields == (("Age", "34"), ("Ancestry", "half-elf"), ("Home", ""),
                        ("Line breaks", "one line"))
    assert StrandInfo("tags", "A", fields="not a list").fields == ()
    assert StrandInfo("tags", "A", fields=None).fields == ()


def test_field_names_alone_are_details():
    """Field names with empty values still count (an Apply onto unused strands must
    survive saving)."""
    assert StrandInfo("tags", "A").is_blank()
    assert not StrandInfo("locations", "Marsh", fields=[("Biome", "")]).is_blank()
    raw = [{"kind": "locations", "name": "Marsh", "fields": [{"name": "Biome", "value": ""}]}]
    assert [s.fields for s in clean_strands(raw)] == [(("Biome", ""),)]


def test_round_trip_keeps_field_order():
    board = BoardData(strands=[StrandInfo("characters", "Mabel", "Baker",
                                          fields=[("Ancestry", "human"), ("Age", "61")])])
    raw = board.to_dict()
    assert raw["version"] == FORMAT_VERSION == 10
    assert raw["strands"][0]["fields"] == [{"name": "Ancestry", "value": "human"},
                                           {"name": "Age", "value": "61"}]
    back = BoardData.from_dict(raw)
    assert back.strands == board.strands
    assert back.strands[0].fields == (("Ancestry", "human"), ("Age", "61"))


def test_older_boards_load_without_fields():
    raw = {"version": 9, "cards": [],
           "strands": [{"kind": "characters", "name": "Greta", "description": "Warden"}]}
    assert BoardData.from_dict(raw).strands == [StrandInfo("characters", "Greta", "Warden")]
    assert BoardData.from_dict(raw).strands[0].fields == ()


def test_fields_are_immutable_so_copies_never_share_them():
    """Undo snapshots and saved copies take strands with a shallow copy: the fields
    must be a tuple of tuples, never a list that later edits could change."""
    s = StrandInfo("tags", "A", fields=[["Mood", "grim"]])
    assert isinstance(s.fields, tuple) and all(isinstance(f, tuple) for f in s.fields)
    hash(s.fields)  # usable inside an undo snapshot


def test_merge_keeps_the_targets_values():
    target = (("Age", "34"), ("Ancestry", ""), ("Home", "East Ward"))
    moving = (("ancestry", "elf"), ("Age", "35"), ("Trade", "smith"))
    # The target's order and values first; an empty target value takes the other's;
    # fields only the renamed strand had come after, in its order.
    assert merge_fields(target, moving) == (("Age", "34"), ("Ancestry", "elf"),
                                            ("Home", "East Ward"), ("Trade", "smith"))
    assert merge_fields((), moving) == moving
    assert merge_fields(target, ()) == target


def test_apply_copies_missing_names_with_empty_values():
    source = (("Age", "34"), ("Ancestry", "half-elf"), ("Home", "East Ward"))
    target = (("home", "Hollybank"), ("Mood", "calm"))
    # Existing fields (ignoring case) stay exactly as they are; missing ones are added
    # at the end in the source's order, empty.
    assert apply_fields(source, target) == (("home", "Hollybank"), ("Mood", "calm"),
                                            ("Age", ""), ("Ancestry", ""))
    assert apply_fields(source, ()) == (("Age", ""), ("Ancestry", ""), ("Home", ""))


def test_apply_a_chosen_subset_of_names():
    source = (("Age", "34"), ("Ancestry", "half-elf"), ("Home", "East Ward"))
    assert apply_fields(source, (), names=["home", "Age"]) == (("Age", ""), ("Home", ""))
    assert apply_fields(source, (("Mood", "calm"),), names=[]) == (("Mood", "calm"),)


def test_apply_with_values_fills_only_empty_values():
    source = (("Age", "34"), ("Biome", "marsh"), ("Home", "East Ward"))
    target = (("Biome", ""), ("Home", "Hollybank"))
    assert apply_fields(source, target, with_values=True) == (
        ("Biome", "marsh"), ("Home", "Hollybank"), ("Age", "34"))


# ----- on the board (scene) ------------------------------------------------------------------
AGE = (("Age", "34"), ("Ancestry", "half-elf"))


def test_changing_only_the_fields_is_an_edit_and_undoes(scene, settle):
    scene.set_strand_info(StrandInfo("characters", "Rowan", "Ferry keeper"))
    settle()
    assert scene.set_strand_info(StrandInfo("characters", "Rowan", "Ferry keeper", fields=AGE))
    settle()
    assert scene.strand("characters", "rowan").fields == AGE
    assert not scene.set_strand_info(StrandInfo("characters", "ROWAN", "Ferry keeper", fields=AGE))
    scene.undo()
    assert scene.strand("characters", "Rowan").fields == ()
    scene.redo()
    assert scene.strand("characters", "Rowan").fields == AGE


def test_a_strand_with_only_fields_is_kept_and_saved(scene, settle):
    assert scene.set_strand_info(StrandInfo("locations", "Marsh", fields=[("Biome", "")]))
    settle()
    assert "Marsh" in scene.all_values("locations")
    saved = BoardData.from_dict(scene.to_board_data().to_dict())
    assert saved.strands == [StrandInfo("locations", "Marsh", fields=[("Biome", "")])]


def test_rename_carries_fields_and_a_merge_keeps_the_targets_values(scene, settle):
    scene.set_strand_info(StrandInfo("characters", "Rowan", fields=[("Age", "34"), ("Trade", "ferry")]))
    scene.set_strand_info(StrandInfo("characters", "Mabel", fields=[("Age", "61"), ("Home", "")]))
    settle()
    scene.rename_value("characters", "Rowan", "Ro")
    settle()
    assert scene.strand("characters", "Ro").fields == (("Age", "34"), ("Trade", "ferry"))
    scene.rename_value("characters", "Ro", "Mabel")                 # merge into Mabel
    settle()
    assert scene.strand("characters", "Mabel").fields == (("Age", "61"), ("Home", ""),
                                                          ("Trade", "ferry"))
    scene.undo()
    assert scene.strand("characters", "Ro").fields == (("Age", "34"), ("Trade", "ferry"))


def test_apply_fields_to_chosen_strands_is_one_undo_step(scene, settle):
    scene.saved_values = {"characters": ["Mabel", "Greta", "Warden"]}
    scene.set_strand_info(StrandInfo("characters", "Rowan", fields=AGE))
    scene.set_strand_info(StrandInfo("characters", "Greta", "Gardener", fields=[("age", "70")]))
    settle()
    assert scene.apply_strand_fields("characters", "Rowan", ["mabel", "Greta", "Rowan", "Nobody"]) \
        == (2, 3)                                    # 2 strands changed, 3 fields added
    settle()
    # Mabel had no details: she gets the names, empty. Greta keeps her age; Rowan (the
    # source) and a name the board doesn't have are skipped. Warden wasn't picked.
    assert scene.strand("characters", "Mabel") == StrandInfo(
        "characters", "Mabel", fields=[("Age", ""), ("Ancestry", "")])
    assert scene.strand("characters", "Greta").fields == (("age", "70"), ("Ancestry", ""))
    assert scene.strand("characters", "Rowan").fields == AGE
    assert scene.strand("characters", "Warden") is None
    assert scene.strand("characters", "Nobody") is None
    scene.undo()                                     # the whole apply at once
    assert scene.strand("characters", "Mabel") is None
    assert scene.strand("characters", "Greta").fields == (("age", "70"),)


def test_apply_some_fields_with_their_values(scene, settle):
    scene.add_card(CardData(title="A", locations=["Marsh", "East Ward"]))
    scene.set_strand_info(StrandInfo("locations", "Fen", fields=[("Biome", "marsh"), ("Size", "big")]))
    scene.set_strand_info(StrandInfo("locations", "East Ward", fields=[("Biome", "")]))
    settle()
    assert scene.apply_strand_fields("locations", "Fen", ["Marsh", "East Ward"], names=["biome"],
                                     with_values=True) == (2, 1)
    assert scene.strand("locations", "Marsh").fields == (("Biome", "marsh"),)
    assert scene.strand("locations", "East Ward").fields == (("Biome", "marsh"),)  # empty filled
    assert scene.apply_strand_fields("locations", "Fen", ["Marsh"], names=["biome"]) == (0, 0)


def test_apply_from_a_strand_without_fields_does_nothing(scene):
    scene.saved_values = {"tags": ["a", "b"]}
    assert scene.apply_strand_fields("tags", "a", ["b"]) == (0, 0)
    assert scene.strand("tags", "b") is None


def test_unused_strands_with_only_fields_count_as_detailed(scene):
    scene.saved_values = {"tags": ["spare"]}
    scene.set_strand_info(StrandInfo("tags", "mood", fields=[("Tone", "")]))
    plain, detailed = scene.unused_strands()
    assert plain == {"tags": ["spare"]} and detailed == {"tags": ["mood"]}


def test_import_brings_fields_along(window, tmp_path, monkeypatch):
    import warpingweft.main_window as mw
    from warpingweft.model import save_board
    save_board(BoardData(strands=[StrandInfo("characters", "Warden", fields=AGE)]),
               tmp_path / "other.json")
    monkeypatch.setattr(mw.ValueChecklistDialog, "exec", lambda self: True)
    assert window.import_values_from(tmp_path / "other.json") == 1
    assert window.scene.strand("characters", "Warden").fields == AGE


# ----- the fields editor in the Strands panel ------------------------------------------------
@pytest.fixture
def panel(window, qapp):
    window.show()
    window.strands_dock.show()
    qapp.processEvents()
    return window.strands_panel


def table_fields(panel):
    t = panel.fields_table
    return tuple((t.item(r, 0).text(), t.item(r, 1).text()) for r in range(t.rowCount()))


def open_strand(window, panel, qapp, kind="characters", name="Rowan", **details):
    window.scene.add_card(CardData(title="A", **{kind: [name]}))
    if details:
        window.scene.set_strand_info(StrandInfo(kind, name, **details))
    window.scene.mark_modified()
    qapp.processEvents()                              # (the setup is its own undo step)
    panel.refresh()
    assert panel.select(kind, name)


def type_into_cell(panel, qapp, row, col, text):
    """Edit a cell the way a user does: open its editor, type, press Enter."""
    t = panel.fields_table
    t.setCurrentCell(row, col)
    t.editItem(t.item(row, col))
    qapp.processEvents()
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.selectAll()
    QTest.keyClicks(editor, text)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    qapp.processEvents()


def test_table_shows_fields_and_each_edit_is_saved(window, panel, qapp):
    open_strand(window, panel, qapp, fields=AGE)
    s = window.scene
    assert table_fields(panel) == AGE
    assert panel.fields_toggle.text() == "▾ Fields (2)"
    type_into_cell(panel, qapp, 0, 1, "35")
    assert s.strand("characters", "Rowan").fields == (("Age", "35"), ("Ancestry", "half-elf"))
    s.undo()
    panel.refresh()
    assert table_fields(panel) == AGE                 # undo shows through
    panel.clear_btn.click()                           # Clear details clears fields too
    assert s.strand("characters", "Rowan") is None and table_fields(panel) == ()
    assert panel.fields_empty.isVisible() and not panel.fields_table.isVisible()


def test_add_rename_move_and_remove_fields(window, panel, qapp):
    open_strand(window, panel, qapp)
    s = window.scene
    panel.add_field_btn.click()
    qapp.processEvents()
    assert s.strand("characters", "Rowan").fields == (("Field", ""),)
    assert panel.fields_table.state() == QAbstractItemView.State.EditingState  # name ready to type
    editor = QApplication.focusWidget()
    editor.selectAll()
    QTest.keyClicks(editor, "Home")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    qapp.processEvents()
    panel.add_field_btn.click()                       # a second one: "Field" is free again
    qapp.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    assert s.strand("characters", "Rowan").fields == (("Home", ""), ("Field", ""))
    panel.fields_table.setCurrentCell(1, 0)
    panel.field_up_btn.click()
    assert s.strand("characters", "Rowan").fields == (("Field", ""), ("Home", ""))
    assert panel.fields_table.currentRow() == 0       # the moved row stays picked
    panel.field_down_btn.click()
    assert table_fields(panel) == (("Home", ""), ("Field", ""))
    panel.fields_table.setCurrentCell(0, 1)
    panel.remove_field_btn.click()
    assert s.strand("characters", "Rowan").fields == (("Field", ""),)


def test_duplicate_or_empty_names_are_refused(window, panel, qapp):
    open_strand(window, panel, qapp, fields=AGE)
    s = window.scene
    type_into_cell(panel, qapp, 1, 0, "AGE")
    assert s.strand("characters", "Rowan").fields == AGE
    assert table_fields(panel) == AGE and "already" in panel.fields_note.text()
    type_into_cell(panel, qapp, 1, 0, "   ")
    assert table_fields(panel) == AGE and "name" in panel.fields_note.text()
    type_into_cell(panel, qapp, 1, 0, "Kin")          # a good edit clears the note
    assert s.strand("characters", "Rowan").fields == (("Age", "34"), ("Kin", "half-elf"))
    assert panel.fields_note.text() == ""


def test_a_refresh_while_editing_a_cell_keeps_the_typing(window, panel, qapp):
    open_strand(window, panel, qapp, fields=AGE)
    t = panel.fields_table
    t.setCurrentCell(0, 1)
    t.editItem(t.item(0, 1))
    qapp.processEvents()
    editor = QApplication.focusWidget()
    editor.selectAll()
    QTest.keyClicks(editor, "40")
    window.scene.set_strand_info(StrandInfo("characters", "Rowan", "Ferry keeper", fields=AGE))
    panel.refresh()                                   # the board changed meanwhile
    assert t.state() == QAbstractItemView.State.EditingState and editor.text() == "40"
    QTest.keyClick(editor, Qt.Key.Key_Return)
    qapp.processEvents()
    assert window.scene.strand("characters", "Rowan").fields[0] == ("Age", "40")


def test_picking_another_strand_saves_the_cell_being_edited(window, panel, qapp):
    open_strand(window, panel, qapp, fields=AGE)
    window.scene.saved_values = {"characters": ["Mabel"]}
    panel.refresh()
    t = panel.fields_table
    t.setCurrentCell(0, 1)
    t.editItem(t.item(0, 1))
    qapp.processEvents()
    editor = QApplication.focusWidget()
    editor.selectAll()
    QTest.keyClicks(editor, "41")
    assert panel.select("characters", "Mabel")
    qapp.processEvents()
    assert window.scene.strand("characters", "Rowan").fields[0] == ("Age", "41")
    assert window.scene.strand("characters", "Mabel") is None
    assert table_fields(panel) == ()


def test_fields_and_picture_sections_collapse(window, panel, qapp):
    open_strand(window, panel, qapp, fields=AGE)
    window.scene.saved_values = {"characters": ["Mabel"]}
    panel.refresh()
    assert panel.fields_box.isVisible() and panel.picture_box.isVisible()   # open to start with
    panel.fields_toggle.click()
    panel.picture_toggle.click()
    assert not panel.fields_box.isVisible() and not panel.picture_box.isVisible()
    assert panel.fields_toggle.text() == "▸ Fields (2)" and panel.picture_toggle.text() == "▸ Picture"
    panel.select("characters", "Mabel")               # stays folded for every strand
    qapp.processEvents()
    assert not panel.fields_box.isVisible() and panel.fields_toggle.text() == "▸ Fields (0)"
    panel.fields_toggle.click()
    assert panel.fields_box.isVisible()


def test_the_table_stops_growing_and_scrolls(window, panel, qapp):
    import warpingweft.strands_panel as sp
    many = [(f"F{i}", "") for i in range(sp.FIELDS_VISIBLE_ROWS + 4)]
    open_strand(window, panel, qapp, fields=many[:2])
    two = panel.fields_table.height()
    window.scene.set_strand_info(StrandInfo("characters", "Rowan", fields=many[:sp.FIELDS_VISIBLE_ROWS]))
    panel.refresh()
    full = panel.fields_table.height()
    window.scene.set_strand_info(StrandInfo("characters", "Rowan", fields=many))
    panel.refresh()
    qapp.processEvents()
    assert two < full == panel.fields_table.height()
    assert panel.fields_table.verticalScrollBar().maximum() > 0


def test_a_growing_field_list_relays_out_the_pane(window, panel, qapp, tmp_path):
    """When the field list grows on a real board, the panel relays out: the table
    doesn't run under its buttons or into the Picture section."""
    import shutil
    from pathlib import Path

    import warpingweft.strands_panel as sp
    board = tmp_path / "lantern-tide.json"
    shutil.copy(Path(__file__).resolve().parents[1] / "examples" / "lantern-tide.json", board)
    window.open_path(board)
    window.resize(1400, 900)
    qapp.processEvents()
    panel.refresh()
    name = window.scene.all_values("characters")[0]
    window.scene.set_strand_info(StrandInfo("characters", name, fields=AGE))
    panel.refresh()
    assert panel.select("characters", name)
    qapp.processEvents()
    window.scene.set_strand_info(StrandInfo("characters", name, fields=[
        (f"F{i}", "") for i in range(sp.FIELDS_VISIBLE_ROWS + 4)]))
    panel.refresh()

    def top(w):
        return w.mapTo(panel.details, w.rect().topLeft()).y()

    def bottom(w):
        return w.mapTo(panel.details, w.rect().bottomLeft()).y()

    def laid_out():
        return (bottom(panel.fields_table) < top(panel.add_field_btn)
                and bottom(panel.fields_box) < top(panel.picture_toggle))
    # The pane relays out over a few event-loop passes, as in the running app (a grab
    # taken after just one pass shows the sections still squeezed together).
    wait_until(laid_out, timeout_ms=2000)
    assert panel.fields_table.height() == panel.fields_table.minimumHeight()


# ----- applying one strand's fields to others ------------------------------------------------
def make_apply_dialog(others=("Mabel", "Greta", "Warden")):
    from warpingweft.apply_fields_dialog import ApplyFieldsDialog
    return ApplyFieldsDialog("characters", "Rowan", AGE, list(others))


def test_apply_dialog_starts_with_every_field_and_no_strand_ticked(qapp):
    d = make_apply_dialog()
    assert d.selected_names() == ["Age", "Ancestry"]
    assert d.selected_targets() == [] and not d.with_values()
    assert not d.apply_button.isEnabled()             # nothing to apply to yet
    assert d.all_check.text() == "All characters (3)"
    assert "Rowan" in d.windowTitle()


def test_apply_dialog_all_box_search_and_picks(qapp):
    d = make_apply_dialog()
    d.all_check.setChecked(True)
    assert d.selected_targets() == ["Mabel", "Greta", "Warden"] and d.apply_button.isEnabled()
    d.target_item("Greta").setCheckState(Qt.CheckState.Unchecked)
    assert d.all_check.checkState() == Qt.CheckState.PartiallyChecked
    assert d.selected_targets() == ["Mabel", "Warden"]
    d.search.setText("war")                           # narrows the list; ticks stay
    assert [d.target_item(n).isHidden() for n in ("Mabel", "Greta", "Warden")] == [True, True, False]
    assert d.selected_targets() == ["Mabel", "Warden"]
    d.all_check.setChecked(False)
    assert d.selected_targets() == [] and d.all_check.checkState() == Qt.CheckState.Unchecked
    d.target_item("Greta").setCheckState(Qt.CheckState.Checked)
    d.field_checks[0].setChecked(False)               # only Ancestry
    d.values_check.setChecked(True)
    assert d.selected_names() == ["Ancestry"] and d.selected_targets() == ["Greta"] and d.with_values()
    d.field_checks[1].setChecked(False)               # no fields: nothing to apply
    assert not d.apply_button.isEnabled()


def test_apply_dialog_with_no_other_strands(qapp):
    d = make_apply_dialog(others=())
    assert d.all_check.text() == "All characters (0)" and not d.all_check.isEnabled()
    assert not d.apply_button.isEnabled()


def test_apply_button_in_the_panel(window, panel, qapp, monkeypatch):
    import warpingweft.strands_panel as sp
    open_strand(window, panel, qapp, fields=AGE)
    s = window.scene
    s.saved_values = {"characters": ["Mabel", "Greta"], "locations": ["Marsh"]}
    s.set_strand_info(StrandInfo("characters", "Greta", fields=[("Age", "70")]))
    s.mark_modified()
    qapp.processEvents()
    panel.refresh()
    seen = {}

    def run(dialog):
        seen["offered"] = [dialog.target_item(i).text() for i in ("Mabel", "Greta")]
        seen["marsh"] = dialog.target_item("Marsh")
        dialog.all_check.setChecked(True)
        return True
    monkeypatch.setattr(sp.ApplyFieldsDialog, "exec", run)
    notices = []
    s.notice.connect(notices.append)
    assert panel.apply_fields_btn.isEnabled()
    panel.apply_fields_btn.click()
    qapp.processEvents()
    assert seen == {"offered": ["Mabel", "Greta"], "marsh": None}   # same kind, not Rowan
    assert s.strand("characters", "Mabel").fields == (("Age", ""), ("Ancestry", ""))
    assert s.strand("characters", "Greta").fields == (("Age", "70"), ("Ancestry", ""))
    assert notices == ["Added 3 fields to 2 characters"]
    s.undo()                                          # one undo step
    assert s.strand("characters", "Mabel") is None
    monkeypatch.setattr(sp.ApplyFieldsDialog, "exec", lambda d: d.all_check.setChecked(True) or True)
    s.redo()
    panel.apply_fields_btn.click()                    # again: nothing left to add
    assert notices[-1] == "Those characters already have these fields"


def test_apply_button_needs_fields(window, panel, qapp):
    open_strand(window, panel, qapp)
    assert not panel.apply_fields_btn.isEnabled()
    panel.add_field_btn.click()
    qapp.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    assert panel.apply_fields_btn.isEnabled()


def test_clicking_a_part_ticked_all_box_ticks_everything(qapp):
    d = make_apply_dialog()
    d.target_item("Greta").setCheckState(Qt.CheckState.Checked)
    assert d.all_check.checkState() == Qt.CheckState.PartiallyChecked
    d.all_check.click()
    assert d.selected_targets() == ["Mabel", "Greta", "Warden"]
    d.all_check.click()
    assert d.selected_targets() == [] and d.all_check.checkState() == Qt.CheckState.Unchecked


# ----- fields shown elsewhere: strand card details and search --------------------------------
def detail_texts(item):
    return [block[1] for block in item._blocks]


def test_strand_card_details_list_fields_with_a_value(scene, qapp):
    from PySide6.QtCore import QPointF
    card = scene.create_strand_card("characters", "Rowan", QPointF(0, 0))
    card.set_details_visible(True)
    assert detail_texts(card) == ["No description yet. Add one in Strands."]
    closed = card.card_rect().height()
    scene.set_strand_info(StrandInfo("characters", "Rowan", fields=[("Age", "34"), ("Home", "")]))
    assert detail_texts(card) == ["Age: 34"]          # empty values are left out
    scene.set_strand_info(StrandInfo("characters", "Rowan", "Ferry keeper",
                                     fields=[("Age", "34"), ("Ancestry", "half-elf")]))
    assert detail_texts(card) == ["Ferry keeper", "Age: 34", "Ancestry: half-elf"]
    assert card.card_rect().height() > closed         # the card grew to fit them
    scene.set_strand_info(StrandInfo("characters", "Rowan", fields=[("Home", "")]))
    assert detail_texts(card) == ["No description yet. Add one in Strands."]


def test_applying_fields_refits_the_targets_strand_cards(scene):
    from PySide6.QtCore import QPointF
    scene.saved_values = {"characters": ["Mabel"]}
    scene.set_strand_info(StrandInfo("characters", "Rowan", fields=[("Age", "34")]))
    card = scene.create_strand_card("characters", "Mabel", QPointF(0, 0))
    card.set_details_visible(True)
    scene.apply_strand_fields("characters", "Rowan", ["Mabel"], with_values=True)
    assert detail_texts(card) == ["Age: 34"]


def test_search_finds_field_values_but_not_field_names():
    from warpingweft.filters import search_cards
    cards = [CardData(id="a", title="Crossing", characters=["Rowan"]),
             CardData(id="b", title="Market", locations=["East Ward"]),
             CardData(id="c", title="Age of lanterns")]
    info = {("characters", "rowan"): StrandInfo("characters", "Rowan", fields=[("Ancestry", "half-elf")]),
            ("locations", "east ward"): StrandInfo("locations", "East Ward", "Old docks",
                                                   fields=[("Biome", "salt marsh"), ("Age", "")])}
    assert search_cards(cards, "half-elf", info) == [("a", "Rowan’s Ancestry", "half-elf")]
    assert search_cards(cards, "marsh", info) == [("b", "East Ward’s Biome", "salt marsh")]
    assert search_cards(cards, "ancestry", info) == []        # names alone find nothing
    assert search_cards(cards, "biome", info) == []
    # "Age" is a field name on East Ward, but it's in card c's title: that's what's found.
    assert search_cards(cards, "age", info) == [("c", "Title", "Age of lanterns")]
    # A description match still comes before a field value.
    assert search_cards(cards, "old", info)[0][1] == "East Ward’s description"
