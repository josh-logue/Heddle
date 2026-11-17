"""Adding a strand group to cards: its strands join the cards' tags, characters or
locations in one go. From a drag out of the Strands panel, the card editor's boxes, Edit
Selected Cards and the card's right-click menu. Groups of statuses are filter-only."""
import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

import heddle.scene as scene_module
from heddle.details_form import DetailFields
from heddle.model import KIND_GROUP, KIND_STRAND, CardData
from heddle.token_input import TokenInput, group_label
from heddle.view import STRAND_GROUP_MIME, strand_group_from_mime, strand_group_mime

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")  # QDragMoveEvent
L, NONE, COPY = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.DropAction.CopyAction


@pytest.fixture
def board(window, scene, settle, qapp):
    scene.add_card(CardData(id="a", title="A", x=300, y=200, characters=["Rowan"]))
    scene.add_card(CardData(id="b", title="B", x=700, y=200))
    scene.add_card(CardData(id="s", title="Greta", x=300, y=500, kind=KIND_STRAND,
                            strand_kind="characters", strand="Greta"))
    scene.create_strand_group("characters", "Family", ["Rowan", "Mabel"])
    scene.create_strand_group("tags", "Act one", ["Opening", "Inciting"])
    scene.create_strand_group("status", "Done", ["Final", "Revised"])
    scene.create_strand_group("locations", "Empty")
    settle()
    window.show()
    window.view.resetTransform()
    window.view.centerOn(QPointF(500, 300))
    qapp.processEvents()
    return window


def notices(scene):
    seen = []
    scene.notice.connect(seen.append)
    return seen


def chars(scene, cid):
    return scene.cards[cid].card.characters


# ----- the scene --------------------------------------------------------------------------------
def test_adding_a_group_keeps_spellings_and_is_one_undo_step(board, scene, qapp):
    said = notices(scene)
    items = [scene.cards["a"], scene.cards["b"], scene.cards["s"]]  # the strand card is skipped
    assert scene.add_strand_group_to_cards(items, "characters", "family") == 2
    qapp.processEvents()
    assert chars(scene, "a") == ["Rowan", "Mabel"]                # Rowan not doubled
    assert chars(scene, "b") == ["Rowan", "Mabel"]
    assert scene.cards["s"].card.characters == []
    assert said[-1] == "Added the strand group “Family” to 2 cards"
    scene.undo()
    assert chars(scene, "a") == ["Rowan"] and chars(scene, "b") == []
    assert scene.add_strand_group_to_cards([scene.cards["a"]], "characters", "Family") == 1
    qapp.processEvents()
    assert scene.add_strand_group_to_cards([scene.cards["a"]], "characters", "Family") == 0
    assert said[-1] == "That card already had the strand group “Family”"
    assert scene.add_strand_group_to_cards([scene.cards["a"]], "locations", "Empty") == 0
    assert said[-1] == "The strand group “Empty” has no strands yet"
    assert scene.add_strand_group_to_cards([scene.cards["a"]], "status", "Done") == 0  # filter-only
    assert scene.cards["a"].card.status == ""


def test_only_tag_character_and_location_groups_can_be_added(board, scene):
    assert scene.strand_group_choices() == {"tags": {"Act one": ["Opening", "Inciting"]},
                                            "characters": {"Family": ["Rowan", "Mabel"]},
                                            "locations": {"Empty": []}}
    assert scene.strand_suggestions()["strand_groups"] == scene.strand_group_choices()


# ----- dragging a group out of the Strands panel ------------------------------------------------
def drag_over(window, mime, scene_pt):
    vp, p = window.view.viewport(), window.view.mapFromScene(scene_pt)
    QApplication.sendEvent(vp, QDragEnterEvent(p, COPY, mime, L, NONE))
    move = QDragMoveEvent(p, COPY, mime, L, NONE)
    QApplication.sendEvent(vp, move)
    return move.isAccepted()


def drop(window, qapp, mime, scene_pt):
    drag_over(window, mime, scene_pt)
    ev = QDropEvent(QPointF(window.view.mapFromScene(scene_pt)), COPY, mime, L, NONE)
    QApplication.sendEvent(window.view.viewport(), ev)
    qapp.processEvents()
    return ev.isAccepted() and ev.dropAction() == COPY


def centre(item):
    return item.card_scene_rect().center()


def test_mime_round_trip_and_junk():
    assert strand_group_from_mime(strand_group_mime("tags", "Act one", ["A", "B"])) == ("tags", "Act one", ["A", "B"])
    junk = QMimeData()
    junk.setData(STRAND_GROUP_MIME, b'{"kind": "tags", "name": "x", "members": "nope"}')
    assert strand_group_from_mime(junk) is None
    junk.setData(STRAND_GROUP_MIME, b"not json")
    assert strand_group_from_mime(junk) is None
    assert strand_group_from_mime(QMimeData()) is None


def test_dropping_a_group_on_a_card_adds_its_strands(board, scene, qapp):
    mime = strand_group_mime("characters", "Family", ["Rowan", "Mabel"])
    b = scene.cards["b"]
    assert drag_over(board, mime, centre(b))
    assert drop(board, qapp, mime, centre(b))
    assert chars(scene, "b") == ["Rowan", "Mabel"]
    scene.undo()
    assert chars(scene, "b") == []


def test_a_group_is_refused_off_a_standard_card(board, scene, qapp):
    mime = strand_group_mime("characters", "Family", ["Rowan", "Mabel"])
    before = len(scene.cards)
    assert not drag_over(board, mime, QPointF(1500, 1500))            # the blank board
    assert not drag_over(board, mime, centre(scene.cards["s"]))       # a strand card
    assert not drop(board, qapp, mime, QPointF(1500, 1500))
    assert len(scene.cards) == before                                  # no strand cards made
    statuses = strand_group_mime("status", "Done", ["Final"])
    assert not drag_over(board, statuses, centre(scene.cards["b"]))   # a card has one status


def test_a_group_frame_refuses_a_group(board, scene, qapp):
    scene.add_card(CardData(id="g", title="Frame", kind=KIND_GROUP, x=1000, y=600, width=300, height=200))
    qapp.processEvents()
    mime = strand_group_mime("tags", "Act one", ["Opening"])
    assert not drag_over(board, mime, QPointF(1150, 750))


def test_drop_from_another_board_brings_the_strands(board, scene, qapp):
    """The drag carries the strands, so the group needn't exist on this board."""
    mime = strand_group_mime("locations", "Docks", ["Pier", "Harbour"])
    assert drop(board, qapp, mime, centre(scene.cards["b"]))
    assert scene.cards["b"].card.locations == ["Pier", "Harbour"]


def test_panel_drags_tag_character_and_location_groups(board, scene):
    panel = board.strands_panel
    board.strands_dock.show()
    panel.refresh()
    for kind, name, members in (("characters", "Family", ["Rowan", "Mabel"]),
                                ("status", "Done", None), ("locations", "Empty", None)):
        assert panel.select_group(kind, name)
        mime = panel.tree.drag_payload()
        if members is None:
            assert mime is None                     # statuses: filter-only; empty: nothing to add
        else:
            assert strand_group_from_mime(mime) == (kind, name, members)


# ----- the editor boxes -------------------------------------------------------------------------
def test_box_offers_groups_after_the_strands_and_adds_their_strands(qapp):
    box = TokenInput(["Rowan"], ["Greta", "Mabel", "Rowan"], "character",
                     groups={"Family": ["Rowan", "Mabel"], "Council": ["Rowan"], "Empty": []})
    label = group_label("Family", ["Rowan", "Mabel"])
    assert label == "Family · strand group (2)"
    # Council adds nothing new (Rowan is there), and an empty group is never offered.
    assert box._model.stringList() == ["Greta", "Mabel", label]
    changes = []
    box.changed.connect(lambda: changes.append(1))
    assert box.add_value(label)
    assert box.values() == ["Rowan", "Mabel"] and changes == [1]   # one change for the lot
    assert label not in box._model.stringList()                     # nothing left to add
    assert box.add_value("Family")                                   # the bare name: a strand
    assert box.values() == ["Rowan", "Mabel", "Family"]


def test_picking_a_group_from_the_completer(qapp):
    box = TokenInput([], ["Mabel", "Rowan"], "character", groups={"Family": ["rowan", "mabel"]})
    box._on_completion(group_label("Family", ["rowan", "mabel"]))
    assert box.values() == ["Rowan", "Mabel"]                        # the board's spelling


def test_card_editor_and_card_panel_boxes_offer_groups(board, scene):
    fields = DetailFields(CardData(), scene.strand_suggestions(), board)
    assert group_label("Family", ["Rowan", "Mabel"]) in fields.characters_input._model.stringList()
    assert group_label("Act one", ["Opening", "Inciting"]) in fields.tags_input._model.stringList()
    assert not any("strand group" in s for s in fields.locations_input._model.stringList())  # empty


def test_edit_selected_cards_adds_and_removes_groups(board, scene, monkeypatch, qapp):
    for cid in ("a", "b"):
        scene.cards[cid].setSelected(True)

    def add(dialog):
        dialog.adders["characters"].add_value(group_label("Family", ["Rowan", "Mabel"]))
        return True
    monkeypatch.setattr(scene_module.MultiEditDialog, "exec", add)
    assert scene.edit_selected_cards() == 2
    qapp.processEvents()
    assert chars(scene, "a") == ["Rowan", "Mabel"] and chars(scene, "b") == ["Rowan", "Mabel"]

    def remove(dialog):
        dialog.removers["characters"].add_value(group_label("Family", ["Rowan", "Mabel"]))
        return True
    monkeypatch.setattr(scene_module.MultiEditDialog, "exec", remove)
    assert scene.edit_selected_cards() == 2
    assert chars(scene, "a") == [] and chars(scene, "b") == []


# ----- the right-click menu ---------------------------------------------------------------------
def submenu(menu, text):
    return next(a.menu() for a in menu.actions() if a.text() == text)


def test_right_click_adds_a_group_to_the_selected_cards(board, scene, qapp):
    scene.cards["b"].setSelected(True)
    scene.cards["a"].setSelected(True)
    menu = scene.build_context_menu(scene.cards["a"], centre(scene.cards["a"]))
    add = submenu(menu, "Add Strand Group")
    assert [a.text() for a in add.actions()] == ["Tags", "Characters", "Locations"]  # no statuses
    family = submenu(add, "Characters").actions()[0]
    assert family.text() == "Family   (2)" and family.isEnabled()
    assert not submenu(add, "Locations").actions()[0].isEnabled()      # empty
    family.trigger()
    qapp.processEvents()
    assert chars(scene, "a") == ["Rowan", "Mabel"] and chars(scene, "b") == ["Rowan", "Mabel"]
    menu = scene.build_context_menu(scene.cards["a"], centre(scene.cards["a"]))
    assert not submenu(submenu(menu, "Add Strand Group"), "Characters").actions()[0].isEnabled()


def test_one_kind_of_group_is_a_flat_list(window, scene, settle):
    scene.add_card(CardData(id="a", title="A"))
    scene.create_strand_group("tags", "Moods", ["grim"])
    settle()
    menu = scene.build_context_menu(scene.cards["a"], centre(scene.cards["a"]))
    assert [a.text() for a in submenu(menu, "Add Strand Group").actions()] == ["Moods   (1)"]


def test_no_menu_without_groups_or_on_a_strand_card(window, scene, board):
    menu = scene.build_context_menu(scene.cards["s"], centre(scene.cards["s"]))
    assert "Add Strand Group" not in [a.text() for a in menu.actions()]
    for key in list(scene.strand_groups):
        scene.delete_strand_group(*scene.strand_groups[key].key[:1], scene.strand_groups[key].name)
    menu = scene.build_context_menu(scene.cards["a"], centre(scene.cards["a"]))
    assert "Add Strand Group" not in [a.text() for a in menu.actions()]
