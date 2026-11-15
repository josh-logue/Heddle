"""Strands: every strand with its usage, and a strand's own description and
picture (linked, not copied), shown only in the Strands panel."""
import json
import os

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

import warpingweft.main_window as mw
from warpingweft.export import export_text
from warpingweft.model import (
    FORMAT_VERSION, BoardData, CardData, RouteData, StrandInfo, clean_strands, load_board,
    picture_for_file, picture_from_file, save_board, strands_for_file,
)


def make_image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = QImage(40, 30, QImage.Format.Format_RGB32)
    img.fill(QColor("#7b5ea7"))
    assert img.save(str(path))
    return path


# ----- model ---------------------------------------------------------------------------------
def test_strand_info_is_cleaned():
    s = StrandInfo(kind="bogus", name="  Mara ", description=None, picture=" x.png ")
    assert (s.kind, s.name, s.description, s.picture) == ("", "Mara", "", "x.png")
    assert StrandInfo("tags", "A").is_blank() and not StrandInfo("tags", "A", "text").is_blank()
    raw = [{"kind": "characters", "name": "Mara", "description": "one"},
           {"kind": "characters", "name": "MARA", "description": "dup"},
           {"kind": "characters", "name": "Blank"}, {"kind": "nope", "name": "X", "description": "y"}, "junk"]
    assert [(s.name, s.description) for s in clean_strands(raw)] == [("Mara", "one")]


def test_round_trip_and_version():
    board = BoardData(strands=[StrandInfo("locations", "Keep", "Old stone", "/pics/keep.png"),
                               StrandInfo("tags", "Empty")])
    raw = board.to_dict()
    assert raw["version"] == FORMAT_VERSION == 11 and len(raw["strands"]) == 1
    back = BoardData.from_dict(raw)
    assert back.strands == [StrandInfo("locations", "Keep", "Old stone", "/pics/keep.png")]
    assert "Keep" in back.all_values("locations")     # a strand with details is kept on the board
    assert BoardData.from_dict({"version": 5, "cards": []}).strands == []


def test_picture_paths_relative_only_inside_the_boards_folder(tmp_path):
    board_dir = tmp_path / "Board"
    inside = str(board_dir / "images" / "mara.png")
    outside = str(tmp_path / "Pictures" / "keep.png")
    assert picture_for_file(inside, board_dir) == "images/mara.png"
    assert picture_for_file(outside, board_dir) == outside       # elsewhere: stays absolute
    assert picture_for_file(inside, None) == inside               # untitled board: absolute
    assert picture_from_file("images/mara.png", board_dir) == os.path.normpath(inside)
    assert picture_from_file(outside, board_dir) == outside
    board = BoardData(strands=[StrandInfo("characters", "Mara", picture=inside)])
    written = strands_for_file(board, board_dir)
    assert written.strands[0].picture == "images/mara.png" and board.strands[0].picture == inside


# ----- saving and opening (window) -----------------------------------------------------------------
def test_board_and_its_pictures_can_move_together(window, tmp_path):
    folder = tmp_path / "Story"
    pic = make_image(folder / "images" / "mara.png")
    far = make_image(tmp_path / "Pictures" / "keep.png")
    s = window.scene
    s.add_card(CardData(title="A", characters=["Mara"], locations=["Keep"]))
    s.set_strand_info(StrandInfo("characters", "Mara", "Hero", str(pic)))
    s.set_strand_info(StrandInfo("locations", "Keep", "", str(far)))
    path = folder / "story.json"
    assert window._write(path)
    saved = {d["name"]: d["picture"] for d in json.loads(path.read_text(encoding="utf-8"))["strands"]}
    assert saved == {"Mara": "images/mara.png", "Keep": str(far)}
    # Move the whole folder: the relative picture still resolves, the absolute one too.
    moved = tmp_path / "Moved"
    folder.rename(moved)
    window.setWindowModified(False)
    window.open_path(moved / "story.json")
    assert s.strand("characters", "mara").picture == os.path.normpath(moved / "images" / "mara.png")
    assert s.strand("locations", "Keep").picture == str(far)


def test_save_as_elsewhere_keeps_pictures_pointing_at_the_same_files(window, tmp_path):
    pic = make_image(tmp_path / "A" / "img" / "x.png")
    s = window.scene
    s.set_strand_info(StrandInfo("tags", "T", picture=str(pic)))
    assert window._write(tmp_path / "A" / "board.json")
    (tmp_path / "B").mkdir()
    assert window._write(tmp_path / "B" / "copy.json")
    back = mw.strands_from_file(load_board(tmp_path / "B" / "copy.json"), tmp_path / "B")
    assert back.strands[0].picture == str(pic)  # outside B's folder: written absolute


# ----- board logic -----------------------------------------------------------------------------------
def test_set_clear_and_undo(scene, qapp):
    assert scene.set_strand_info(StrandInfo("characters", "Mara", "Hero"))
    qapp.processEvents()
    assert "Mara" in scene.all_values("characters")              # kept without any card
    assert not scene.set_strand_info(StrandInfo("characters", "MARA", "Hero"))  # same: no change
    scene.undo()
    assert scene.strand("characters", "Mara") is None
    scene.redo()
    assert scene.strand("characters", "mara").description == "Hero"
    assert scene.set_strand_info(StrandInfo("characters", "Mara"))  # blank: forgotten
    assert scene.strand("characters", "Mara") is None


def test_usage_counts_cards_and_routes(scene):
    a = scene.add_card(CardData(title="A", tags=["Act 1"], pov="Mara"))
    b = scene.add_card(CardData(title="B", tags=["act 1"], x=300))
    scene.add_connection(a, b)
    scene.set_route_data(RouteData(key=[a.card.id, b.card.id], tags=["Act 1", "Main"]))
    assert scene.strand_usage("tags") == {"act 1": (2, 1), "main": (0, 1)}
    assert scene.strand_usage("characters") == {"mara": (1, 0)}


def test_rename_carries_details_and_merging_combines_them(scene, settle):
    scene.add_card(CardData(title="A", characters=["Mara", "Maura"]))
    scene.set_strand_info(StrandInfo("characters", "Mara", "First notes", "/p/mara.png"))
    scene.set_strand_info(StrandInfo("characters", "Maura", "Second notes"))
    settle()
    scene.rename_value("characters", "mara", "MARA")               # spelling only
    settle()
    assert scene.strand("characters", "mara").name == "MARA"
    scene.rename_value("characters", "MARA", "Maura")              # merge into Maura
    settle()
    merged = scene.strand("characters", "maura")
    assert scene.strand("characters", "mara") is None
    assert merged.description == "Second notes" + "\n\n———\n\n" + "First notes"
    assert merged.picture == "/p/mara.png"                          # Maura had none
    scene.undo()
    assert scene.strand("characters", "mara").description == "First notes"


def test_unused_strands_with_details_are_kept_unless_asked(scene):
    scene.add_card(CardData(title="A", tags=["used"]))
    scene.saved_values = {"tags": ["spare", "noted"]}
    scene.set_strand_info(StrandInfo("tags", "noted", "has notes"))
    scene.set_strand_info(StrandInfo("locations", "Keep", "only details"))
    plain, detailed = scene.unused_strands()
    assert plain == {"tags": ["spare"]} and detailed == {"locations": ["Keep"], "tags": ["noted"]}
    assert scene.unused_saved_values() == {"tags": ["spare"]}
    assert scene.unused_saved_values(with_details=True) == {"tags": ["spare", "noted"], "locations": ["Keep"]}
    assert scene.remove_saved_values({"tags": ["noted"], "locations": ["Keep"]}) == 2
    assert scene.strand("tags", "noted") is None and scene.strand("locations", "Keep") is None
    assert "noted" not in scene.all_values("tags")


def test_import_brings_details_along(window, tmp_path, monkeypatch):
    other = tmp_path / "Other"
    pic = make_image(other / "faces" / "ra.png")
    save_board(strands_for_file(BoardData(
        cards=[CardData(title="X", characters=["Ra"])],
        strands=[StrandInfo("characters", "Ra", "Sun", str(pic))]), other), other / "o.json")
    monkeypatch.setattr(mw.ValueChecklistDialog, "exec", lambda self: True)
    assert window.import_values_from(other / "o.json") == 1
    info = window.scene.strand("characters", "Ra")
    assert info.description == "Sun" and info.picture == os.path.normpath(pic)


def test_remove_unused_dialog_offers_detailed_strands_on_request(window, monkeypatch):
    s = window.scene
    s.saved_values = {"tags": ["spare"]}
    s.set_strand_info(StrandInfo("tags", "noted", "has notes"))
    seen = {}

    def run(dialog):
        seen["before"] = dialog.selected()
        assert dialog.extra_check.isVisible() or not dialog.isVisible()
        dialog.extra_check.setChecked(True)
        seen["after"] = dialog.selected()
        return True
    monkeypatch.setattr(mw.ValueChecklistDialog, "exec", run)
    assert window.remove_unused_values() == 2
    assert seen["before"] == {"tags": ["spare"]} and seen["after"] == {"tags": ["spare", "noted"]}
    assert s.strand("tags", "noted") is None


# ----- the panel --------------------------------------------------------------------------------------
@pytest.fixture
def panel(window, qapp):
    window.show()
    window.strands_dock.show()
    qapp.processEvents()
    return window.strands_panel


def rows(panel):
    out = {}
    for item in panel._strand_items():
        if item.data(0, mw.Qt.ItemDataRole.UserRole + 1) is not None:
            out[item.text(0)] = item.text(1)
    return out


def test_panel_lists_every_strand_with_its_usage(window, panel, qapp):
    s = window.scene
    s.add_card(CardData(title="A", tags=["Act 1"], characters=["Mara"], status="Draft"))
    s.saved_values = {"locations": ["Keep"]}
    s.set_strand_info(StrandInfo("characters", "Mara", "Hero"))
    panel.refresh()
    assert rows(panel) == {"Act 1": "1 card", "Mara ✎": "1 card", "Keep": "unused", "Draft": "1 card",
                           "Idea": "built-in", "Outline": "built-in", "Revised": "built-in", "Final": "built-in"}
    assert window.act_strands.shortcut().toString() == "Ctrl+Shift+B"


def test_description_saves_as_you_pause_and_survives_refreshes(window, panel, qapp):
    s = window.scene
    s.add_card(CardData(title="A", characters=["Mara"]))
    s.mark_modified()
    qapp.processEvents()                              # (the card is its own undo step)
    panel.refresh()
    assert panel.select("characters", "Mara")
    panel.description.setPlainText("A young")
    assert panel._commit_timer.isActive()
    s.mark_modified()
    panel.refresh()                                   # a refresh while typing
    assert panel.description.toPlainText() == "A young"
    assert panel.commit_description()                 # (what the pause or leaving the box does)
    qapp.processEvents()
    assert s.strand("characters", "Mara").description == "A young"
    s.undo()
    panel.refresh()
    assert panel.description.toPlainText() == ""      # undo shows through


def test_pictures_choose_missing_and_remove(window, panel, qapp, tmp_path, monkeypatch):
    s = window.scene
    s.add_card(CardData(title="A", locations=["Keep"]))
    pic = make_image(tmp_path / "keep.png")
    panel.refresh()
    panel.select("locations", "Keep")
    import warpingweft.strands_panel as sp
    monkeypatch.setattr(sp.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(pic), "")))
    panel._choose_picture()
    assert s.strand("locations", "Keep").picture == os.path.normpath(pic)
    assert not panel.picture.pixmap().isNull() and panel.choose_btn.text() == "Change picture…"
    pic.unlink()                                      # the file goes missing
    panel._previews.clear()
    panel.refresh()
    assert "not found" in panel.picture.text() and panel.choose_btn.text() == "Relink…"
    panel.remove_pic_btn.click()
    assert s.strand("locations", "Keep") is None      # nothing else set: forgotten


def test_select_cards_thread_and_clear(window, panel, qapp):
    s = window.scene
    a = s.add_card(CardData(title="A", characters=["Mara"]))
    s.add_card(CardData(title="B", x=300))
    s.set_strand_info(StrandInfo("characters", "Mara", "Hero"))
    panel.refresh()
    panel.select("characters", "Mara")
    got = []
    panel.show_cards.connect(got.append)
    panel.select_btn.click()
    assert got == [[a]]
    assert panel.thread_btn.isVisible()
    panel.clear_btn.click()
    assert s.strand("characters", "Mara") is None


def test_selection_follows_a_rename(window, panel, qapp):
    s = window.scene
    s.add_card(CardData(title="A", tags=["draft"]))
    panel.refresh()
    panel.select("tags", "draft")
    s.rename_value("tags", "draft", "Draft 2")
    panel.refresh()
    assert panel.selected() == ("tags", "Draft 2")


# ----- shown only in the panel ------------------------------------------------------------------------
def test_details_appear_nowhere_else(window, tmp_path):
    s = window.scene
    a = s.add_card(CardData(title="A", characters=["Mara"], tags=["T"]))
    height = a.card_scene_rect().height()
    before = export_text(s.to_board_data(), s.story_graph(), "Story")
    s.set_strand_info(StrandInfo("characters", "Mara", "SECRET DESCRIPTION", str(tmp_path / "m.png")))
    a.set_details_visible(True)
    a.set_details_visible(False)
    assert a.card_scene_rect().height() == height
    assert export_text(s.to_board_data(), s.story_graph(), "Story") == before
    assert "SECRET" not in (a.toolTip() or "")


def test_panel_remove_unused_button_runs_remove_unused_strands(window, panel, qapp, monkeypatch):
    """The panel's *Remove unused…* is Edit → Remove Unused Strands…: the same checklist,
    and only enabled while some strand is unused."""
    s = window.scene
    item = s.add_card(CardData(title="A", tags=["Dark"]))
    s.mark_modified()
    qapp.processEvents()
    panel.refresh()
    assert not panel.remove_unused_btn.isEnabled()              # everything is in use
    item.apply_data(CardData(id=item.card.id, title="A"))       # take the tag off its only card
    s.mark_modified()
    qapp.processEvents()
    panel.refresh()
    assert "Dark" in rows(panel) and panel.remove_unused_btn.isEnabled()
    offered = []

    def run(dialog):
        offered.append(dialog.selected())
        return True
    monkeypatch.setattr(mw.ValueChecklistDialog, "exec", run)
    QTest.mouseClick(panel.remove_unused_btn, mw.Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert offered == [{"tags": ["Dark"]}]
    assert "Dark" not in rows(panel) and not panel.remove_unused_btn.isEnabled()
    s.undo()
    panel.refresh()
    assert "Dark" in rows(panel)                                 # one undo step brings it back
