"""A strand stays on the board when the last card using it lets go of it (removed from
the card, or the card deleted), even with no description: only Edit → Remove Unused
Strands… (or a rename) takes it off the list. Undo still takes back a strand you just
added."""
from dataclasses import replace

from PySide6.QtCore import QPointF

from heddle.model import CardData


def edit(scene, item, qapp, **changes):
    """Change a card the way the card editor does, then let the edit be recorded."""
    item.apply_data(replace(item.card, **changes))
    scene.mark_modified()
    qapp.processEvents()


def test_removing_a_strand_from_its_only_card_keeps_it(scene, settle, qapp):
    item = scene.add_card(CardData(title="Gate", tags=["Dark"], characters=["Mara"],
                                   locations=["Keep"], status="Draft"))
    settle()
    edit(scene, item, qapp, tags=[], characters=[], locations=[], status="")
    for kind, name in (("tags", "Dark"), ("characters", "Mara"), ("locations", "Keep"),
                       ("status", "Draft")):
        assert name in scene.all_values(kind), kind
    assert scene.to_board_data().saved_values["tags"] == ["Dark"]  # saved with the board
    scene.undo()
    assert scene.cards[item.card.id].card.tags == ["Dark"]
    assert "Dark" not in scene.saved_values.get("tags", [])        # back in use, not saved twice
    assert scene.all_values("tags") == ["Dark"]


def test_deleting_its_only_card_keeps_it(scene, settle, qapp):
    item = scene.add_card(CardData(title="Gate", characters=["Mara"]))
    settle()
    scene.remove_cards([item])
    settle()
    assert "Mara" in scene.all_values("characters")


def test_deleting_its_strand_card_keeps_it(scene, settle, qapp):
    card = scene.create_strand_card("locations", "Keep", QPointF(0, 0))
    settle()
    scene.remove_cards([card])
    settle()
    assert "Keep" in scene.all_values("locations")


def test_undo_still_takes_back_a_strand_just_added(scene, settle, qapp):
    item = scene.add_card(CardData(title="Gate"))
    settle()
    edit(scene, item, qapp, tags=["Typo"])
    scene.undo()
    assert "Typo" not in scene.all_values("tags")


def test_a_rename_doesnt_keep_the_old_name(scene, settle, qapp):
    scene.add_card(CardData(title="Gate", characters=["Mara"]))
    settle()
    scene.rename_value("characters", "Mara", "Maura")
    settle()
    assert scene.all_values("characters") == ["Maura"]


def test_remove_unused_strands_still_removes_it(scene, settle, qapp):
    item = scene.add_card(CardData(title="Gate", tags=["Dark"]))
    settle()
    edit(scene, item, qapp, tags=[])
    assert scene.unused_saved_values() == {"tags": ["Dark"]}
    scene.remove_saved_values({"tags": ["Dark"]})
    qapp.processEvents()
    assert "Dark" not in scene.all_values("tags")


# ----- built-in statuses (Idea, Outline, Draft, Revised, Final) ----------------------------
def test_built_in_statuses_are_always_on_the_board_and_never_unused(scene, settle, qapp):
    from heddle.model import BUILTIN_STATUSES
    assert set(BUILTIN_STATUSES) <= set(scene.all_values("status"))     # on an empty board too
    item = scene.add_card(CardData(title="Gate", status="Draft"))
    settle()
    edit(scene, item, qapp, status="")
    assert "Draft" in scene.all_values("status")
    assert "status" not in scene.saved_values                          # nothing to keep: it's built in
    scene.saved_values = {"status": ["Final", "Shelved"]}              # e.g. kept by an older version
    assert scene.unused_strands()[0] == {"status": ["Shelved"]}        # only the custom one is offered


def test_the_panel_lists_built_in_statuses_and_they_drag(window, qapp):
    import heddle.strands_panel as sp
    window.strands_dock.show()
    panel = window.strands_panel
    panel.refresh()
    qapp.processEvents()
    final = next(i for i in panel._strand_items() if i.data(0, sp.ROLE_NAME) == "Final")
    assert final.text(1) == "built-in"
    assert panel.select("status", "Final")
    assert "built-in" in panel.usage.text() and "kept" not in panel.usage.text()
    assert not panel.rename_btn.isEnabled()          # unused and built in: nothing to rename
    window.scene.add_card(CardData(title="Gate", status="Final"))
    panel.refresh()
    assert panel.select("status", "Final") and panel.rename_btn.isEnabled()
    from heddle.view import strand_from_mime
    assert strand_from_mime(panel.tree.drag_payload()) == ("status", "Final")
