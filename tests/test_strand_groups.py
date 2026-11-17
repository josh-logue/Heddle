"""Strand groups: named sets of strands of one kind (a "Family" of characters), saved
with the board, kept in step with renames and removals, and undoable. A strand can be
in several groups; cards never refer to a group."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialogButtonBox

import heddle.strands_panel as sp
from heddle.model import (
    FORMAT_VERSION, BoardData, CardData, StrandGroup, StrandInfo, clean_strand_groups,
)


# ----- the model ---------------------------------------------------------------------------------
def test_groups_are_cleaned():
    g = StrandGroup("characters", " The\nFamily ", [" Rowan ", "Mabel", "rowan", "", 7], None)
    assert (g.name, g.members, g.description) == ("The Family", ("Rowan", "Mabel"), "")
    assert StrandGroup("places", "X").kind == ""
    assert StrandGroup("tags", "X", members="not a list").members == ()
    assert isinstance(g.members, tuple)
    hash(g.members)  # usable inside an undo snapshot
    assert g.has("ROWAN") and not g.has("Greta")


def test_cleaning_a_list_keeps_one_group_per_name_and_empty_groups():
    raw = [{"kind": "characters", "name": "Family", "members": ["Rowan"]},
           {"kind": "characters", "name": "FAMILY", "members": ["Greta"]},   # same name: dropped
           {"kind": "tags", "name": "Family"},                                # other kind: fine
           {"kind": "nonsense", "name": "X"}, {"kind": "tags", "name": "  "},  # dropped
           "junk", {"kind": "locations", "name": "Wards", "extra": 1}]
    groups = clean_strand_groups(raw)
    assert [(g.kind, g.name, g.members) for g in groups] == [
        ("characters", "Family", ("Rowan",)), ("tags", "Family", ()), ("locations", "Wards", ())]
    assert clean_strand_groups("nope") == []


def test_round_trip_and_version():
    board = BoardData(strand_groups=[StrandGroup("characters", "Family", ("Rowan", "Mabel"), "Kin")])
    raw = board.to_dict()
    assert raw["version"] == FORMAT_VERSION == 13
    assert raw["strand_groups"] == [{"kind": "characters", "name": "Family",
                                     "members": ["Rowan", "Mabel"], "description": "Kin"}]
    assert BoardData.from_dict(raw).strand_groups == board.strand_groups


def test_older_boards_load_without_groups():
    assert BoardData.from_dict({"version": 12, "cards": []}).strand_groups == []


def test_members_count_as_strands_on_the_board():
    board = BoardData(cards=[CardData(characters=["Rowan"])],
                      strand_groups=[StrandGroup("characters", "Family", ("rowan", "Mabel"))])
    assert board.all_values("characters") == ["Mabel", "Rowan"]


# ----- on the board ------------------------------------------------------------------------------
def test_create_uses_the_boards_spelling_and_refuses_clashes(scene, settle):
    scene.add_card(CardData(title="A", characters=["Rowan"]))
    g = scene.create_strand_group("characters", "Family", ["ROWAN", "Mabel", "rowan"])
    assert g.members == ("Rowan", "Mabel")
    assert scene.create_strand_group("characters", "family") is None      # taken
    assert scene.create_strand_group("characters", "  ") is None           # blank
    assert scene.create_strand_group("tags", "Family") is not None         # other kind: fine
    settle()
    assert "Mabel" in scene.all_values("characters")                       # kept by the group
    assert [x.name for x in scene.groups_with("characters", "rowan")] == ["Family"]


def test_edits_are_undoable_and_saved(scene, settle):
    scene.create_strand_group("characters", "Family", ["Rowan"])
    settle()
    assert scene.update_strand_group("characters", "family", new_name="Kin", description="Blood")
    settle()
    assert scene.add_to_strand_group("characters", "Kin", ["Mabel", "rowan"]) == 1
    settle()
    assert scene.strand_group("characters", "kin").members == ("Rowan", "Mabel")
    assert scene.to_board_data().strand_groups == [StrandGroup("characters", "Kin", ("Rowan", "Mabel"), "Blood")]
    scene.undo()
    assert scene.strand_group("characters", "Kin").members == ("Rowan",)
    scene.undo()
    assert scene.strand_group("characters", "Kin") is None
    assert scene.strand_group("characters", "Family").description == ""
    scene.redo()
    scene.redo()
    assert scene.strand_group("characters", "Kin").members == ("Rowan", "Mabel")


def test_rename_keeps_its_place_in_the_order(scene, settle):
    for name in ("A", "B", "C"):
        scene.create_strand_group("tags", name)
    settle()
    scene.update_strand_group("tags", "B", new_name="Bee")
    assert [g.name for g in scene.strand_groups.values()] == ["A", "Bee", "C"]
    assert not scene.update_strand_group("tags", "Bee", new_name="a")   # taken
    assert not scene.update_strand_group("tags", "Bee", new_name="")    # blank
    assert not scene.update_strand_group("tags", "Bee", new_name="Bee")  # no change
    assert [g.name for g in scene.groups_of("tags")] == ["A", "Bee", "C"]


def test_leaving_or_deleting_a_group_keeps_the_strands(scene, settle):
    scene.create_strand_group("characters", "Family", ["Rowan", "Mabel"])
    settle()
    assert scene.remove_from_strand_group("characters", "Family", ["MABEL", "Greta"]) == 1
    settle()
    assert "Mabel" in scene.all_values("characters")        # kept as a saved strand
    assert scene.delete_strand_group("characters", "family")
    settle()
    assert scene.strand_group("characters", "Family") is None
    assert {"Rowan", "Mabel"} <= set(scene.all_values("characters"))
    scene.undo()
    assert scene.strand_group("characters", "Family").members == ("Rowan",)


def test_renaming_a_strand_renames_it_in_every_group(scene, settle):
    scene.add_card(CardData(title="A", characters=["Rowan", "Ro"]))
    scene.create_strand_group("characters", "Family", ["Rowan", "Ro"])
    scene.create_strand_group("characters", "Council", ["Ro", "Greta"])
    settle()
    scene.rename_value("characters", "ro", "Rowan")          # a merge
    settle()
    assert scene.strand_group("characters", "Family").members == ("Rowan",)
    assert scene.strand_group("characters", "Council").members == ("Rowan", "Greta")
    assert "Ro" not in scene.all_values("characters")
    scene.undo()
    assert scene.strand_group("characters", "Council").members == ("Ro", "Greta")


def test_renaming_a_strand_only_in_a_group(scene, settle):
    """A member no card uses can still be renamed (the group is what keeps it)."""
    scene.create_strand_group("locations", "Wards", ["East Ward"])
    settle()
    scene.rename_value("locations", "East Ward", "Eastward")
    settle()
    assert scene.strand_group("locations", "Wards").members == ("Eastward",)
    assert "East Ward" not in scene.all_values("locations")


def test_grouped_unused_strands_are_only_removed_on_request(scene, settle):
    scene.saved_values = {"tags": ["spare"]}
    scene.create_strand_group("tags", "Moods", ["grim"])
    scene.add_card(CardData(title="A", tags=["used"]))
    settle()
    plain, detailed = scene.unused_strands()
    assert plain == {"tags": ["spare"]} and detailed == {"tags": ["grim"]}
    assert scene.unused_saved_values() == {"tags": ["spare"]}
    assert scene.remove_saved_values({"tags": ["grim"]}) == 1
    settle()
    assert scene.strand_group("tags", "Moods").members == ()      # the group stays, empty
    assert "grim" not in scene.all_values("tags")


def test_rename_dialog_offers_grouped_strands(scene):
    scene.create_strand_group("locations", "Wards", ["East Ward"])
    assert scene._kept_strands()["locations"] == ["East Ward"]


def test_groups_go_with_a_new_board(scene, settle):
    scene.create_strand_group("tags", "Moods", ["grim"])
    settle()
    scene.clear_board()
    assert scene.strand_groups == {}


@pytest.mark.parametrize("kind", ["tags", "characters", "locations", "status"])
def test_every_strand_kind_can_have_groups(scene, kind):
    assert scene.create_strand_group(kind, "G", ["x"]) is not None
    assert "x" in scene.all_values(kind)


def test_details_and_groups_are_independent(scene, settle):
    scene.set_strand_info(StrandInfo("characters", "Rowan", "Keeper"))
    scene.create_strand_group("characters", "Family", ["Rowan"])
    settle()
    scene.delete_strand_group("characters", "Family")
    settle()
    assert scene.strand("characters", "Rowan").description == "Keeper"


# ----- the Strands panel -------------------------------------------------------------------------
@pytest.fixture
def panel(window, qapp):
    window.show()
    window.strands_dock.show()
    qapp.processEvents()
    return window.strands_panel


def _heading(panel, kind):
    return next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                if panel.tree.topLevelItem(i).data(0, sp.ROLE_KIND) == kind)


def outline(panel, kind):
    """The rows under a kind's heading as text: groups as "[name   (count)]", their rows indented."""
    heading = _heading(panel, kind)
    out = []
    for j in range(heading.childCount()):
        row = heading.child(j)
        if row.data(0, sp.ROLE_GROUP) is not None and row.data(0, sp.ROLE_NAME) is None:
            out.append(f"[{row.text(0)}]")
            out += ["  " + row.child(k).text(0) for k in range(row.childCount())]
        else:
            out.append(row.text(0))
    return out


def visible(panel, kind):
    heading = _heading(panel, kind)
    out = []
    for j in range(heading.childCount()):
        row = heading.child(j)
        if not row.isHidden():
            out.append(row.text(0))
            out += ["  " + row.child(k).text(0) for k in range(row.childCount())
                    if not row.child(k).isHidden()]
    return out


def make_board(scene, settle):
    scene.add_card(CardData(title="A", characters=["Rowan", "Mabel", "Greta"]))
    scene.add_card(CardData(title="B", characters=["Rowan"], x=300))
    scene.create_strand_group("characters", "Family", ["Rowan", "Mabel"])
    scene.create_strand_group("characters", "Council", ["Rowan"])
    scene.create_strand_group("characters", "Empty")
    settle()


def member_item(panel, name):
    return next(panel.members.item(i) for i in range(panel.members.count())
                if panel.members.item(i).text() == name)


def test_groups_come_first_with_their_strands_under_them(window, panel, settle):
    make_board(window.scene, settle)
    panel.refresh()
    assert outline(panel, "characters") == [
        "[Council   (1)]", "  Rowan",
        "[Empty   (0)]", "  Empty: tick strands in its member list below",
        "[Family   (2)]", "  Rowan", "  Mabel",
        "Greta"]
    assert panel.select("characters", "Mabel")          # strands under groups are still picked
    assert panel.groups_label.text() == "In strand group Family" and not panel.groups_label.isHidden()
    assert panel.select("characters", "Rowan")
    assert panel.groups_label.text() == "In strand groups Council, Family"
    assert panel.select("characters", "Greta")
    assert panel.groups_label.isHidden()


def test_picking_a_group_shows_it_and_ticks_edit_its_members(window, panel, settle, qapp):
    make_board(window.scene, settle)
    panel.refresh()
    assert panel.select_group("characters", "family")
    assert panel.details.currentWidget() is panel.group_details
    assert panel.group_title.text() == "Family"
    assert panel.group_usage.text() == "Character strand group · 2 characters · 2 cards"
    ticks = {panel.members.item(i).text(): panel.members.item(i).checkState() == Qt.CheckState.Checked
             for i in range(panel.members.count())}
    assert ticks == {"Greta": False, "Mabel": True, "Rowan": True}
    member_item(panel, "Greta").setCheckState(Qt.CheckState.Checked)
    qapp.processEvents()
    assert window.scene.strand_group("characters", "Family").members == ("Rowan", "Mabel", "Greta")
    member_item(panel, "Rowan").setCheckState(Qt.CheckState.Unchecked)
    qapp.processEvents()
    assert window.scene.strand_group("characters", "Family").members == ("Mabel", "Greta")
    window.scene.undo()
    panel.refresh()
    assert panel.members_heading.text() == "Members (3)"
    assert member_item(panel, "Rowan").checkState() == Qt.CheckState.Checked   # undo shows through
    assert panel.select("characters", "Greta")          # back to a strand: its page shows
    assert panel.details.currentWidget() is panel.strand_details


def test_group_description_saves_and_undoes(window, panel, settle, qapp):
    make_board(window.scene, settle)
    panel.refresh()
    panel.select_group("characters", "Family")
    panel.group_description.setPlainText("Blood kin")
    assert panel._commit_timer.isActive()
    assert panel.commit_description()
    qapp.processEvents()
    assert window.scene.strand_group("characters", "Family").description == "Blood kin"
    window.scene.undo()
    panel.refresh()
    assert panel.group_description.toPlainText() == ""


def test_new_group_starts_with_the_picked_strands(window, panel, settle, monkeypatch):
    make_board(window.scene, settle)
    panel.refresh()
    panel.select("characters", "Greta")
    panel.tree.clearSelection()
    for item in panel._strand_items():
        if item.data(0, sp.ROLE_NAME) in ("Greta", "Mabel"):
            item.setSelected(True)
    seen = {}

    def run(dialog):
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        seen["kind"] = dialog.kind()
        seen["note"] = dialog.members_note.text()
        seen["ok_when_blank"] = ok.isEnabled()
        dialog.name_edit.setText("family")                 # taken: refused
        seen["ok_when_taken"] = ok.isEnabled()
        seen["problem"] = dialog.problem.text()
        dialog.name_edit.setText("  Elders ")
        return True
    monkeypatch.setattr(sp.StrandGroupDialog, "exec", run)
    group = panel.new_group()
    assert seen == {"kind": "characters", "note": "It starts with the 2 characters you picked.",
                    "ok_when_blank": False, "ok_when_taken": False,
                    "problem": "There's already a character strand group called “family”."}
    assert (group.name, set(group.members)) == ("Elders", {"Greta", "Mabel"})
    assert panel.selected_group().name == "Elders"


def test_rename_and_delete_a_group(window, panel, settle, monkeypatch):
    make_board(window.scene, settle)
    panel.refresh()
    panel.select_group("characters", "Council")

    def rename(dialog):
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert not dialog.kind_combo.isEnabled()
        dialog.name_edit.setText("council")               # its own name, respelt: allowed
        assert ok.isEnabled()
        dialog.name_edit.setText("Wardens")
        return True
    monkeypatch.setattr(sp.StrandGroupDialog, "exec", rename)
    panel._rename_group()
    assert panel.selected_group().name == "Wardens"
    panel._delete_group()
    assert window.scene.strand_group("characters", "Wardens") is None
    assert panel.selected_group() is None
    assert "Rowan" in window.scene.all_values("characters")


def test_search_shows_matching_groups_and_strands(window, panel, settle):
    make_board(window.scene, settle)
    panel.refresh()
    panel.search.setText("fam")
    assert visible(panel, "characters") == ["Family   (2)", "  Rowan", "  Mabel"]
    panel.search.setText("mab")
    assert visible(panel, "characters") == ["Family   (2)", "  Mabel"]
    panel.search.setText("")
    assert len(visible(panel, "characters")) == 8


def test_right_click_menus(window, panel, settle):
    make_board(window.scene, settle)
    panel.refresh()
    s = window.scene
    greta = next(i for i in panel._strand_items() if i.data(0, sp.ROLE_NAME) == "Greta")
    menu = panel._menu_for(greta)
    assert menu.actions()[0].text() == "Add Greta to Strand Group"
    add = menu.actions()[0].menu()
    assert [a.text() for a in add.actions() if a.text()] == ["Council", "Empty", "Family", "New Strand Group…"]
    next(a for a in add.actions() if a.text() == "Council").trigger()
    assert s.strand_group("characters", "Council").members == ("Rowan", "Greta")
    panel.refresh()
    mabel = next(i for i in panel._strand_items()
                 if i.data(0, sp.ROLE_NAME) == "Mabel" and i.data(0, sp.ROLE_GROUP) == "Family")
    menu = panel._menu_for(mabel)
    next(a for a in menu.actions() if a.text() == "Remove from “Family”").trigger()
    assert s.strand_group("characters", "Family").members == ("Rowan",)
    panel.refresh()
    group = next(i for i in panel._group_items() if i.data(0, sp.ROLE_GROUP) == "Family")
    assert [a.text() for a in panel._menu_for(group).actions()] == ["Rename Strand Group…", "Delete Strand Group"]
    assert [a.text() for a in panel._menu_for(_heading(panel, "characters")).actions()] == [
        "New Character Strand Group…"]


def test_folding_a_group_is_remembered(window, panel, settle):
    make_board(window.scene, settle)
    panel.refresh()
    next(i for i in panel._group_items() if i.data(0, sp.ROLE_GROUP) == "Family").setExpanded(False)
    window.scene.create_strand_group("characters", "Later")
    settle()
    panel.refresh()
    family = next(i for i in panel._group_items() if i.data(0, sp.ROLE_GROUP) == "Family")
    council = next(i for i in panel._group_items() if i.data(0, sp.ROLE_GROUP) == "Council")
    assert not family.isExpanded() and council.isExpanded()
    assert family.parent().isExpanded()                # folding a group isn't folding its kind


def test_list_allows_picking_several(panel):
    assert panel.tree.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
