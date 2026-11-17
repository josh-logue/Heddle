"""Strand groups in the Filter panel: listed first in their kind's categories with their
strands under them; ticking a group ticks every strand in it that cards use."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import heddle.filter_panel as fp
from heddle.model import CardData

CHECKED, PARTLY, OFF = Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked, Qt.CheckState.Unchecked


@pytest.fixture
def panel(window, scene, settle, qapp):
    scene.add_card(CardData(title="A", characters=["Rowan", "Mabel"], pov="Rowan"))
    scene.add_card(CardData(title="B", characters=["Greta"], x=300))
    scene.add_card(CardData(title="C", characters=["Warden"], x=600))
    scene.add_card(CardData(title="D", tags=["Act 1"], x=900))
    scene.create_strand_group("characters", "Family", ["Rowan", "Mabel", "Nobody"])
    scene.create_strand_group("characters", "Council", ["Rowan", "Greta"])
    scene.create_strand_group("characters", "Unused", ["Nobody"])   # no strand on a card: not listed
    settle()
    window.show()
    window.filter_dock.show()
    qapp.processEvents()
    window.filter_panel.refresh()
    return window.filter_panel


def heading(panel, cat):
    return next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                if panel.tree.topLevelItem(i).data(0, fp.ROLE_CAT) == cat)


def outline(panel, cat):
    top = heading(panel, cat)
    out = []
    for j in range(top.childCount()):
        row = top.child(j)
        out.append(row.text(0))
        out += ["  " + row.child(k).text(0) for k in range(row.childCount())]
    return out


def group_row(panel, cat, name):
    return next(r for r in panel._rows() if r.data(0, fp.ROLE_CAT) == cat and r.data(0, fp.ROLE_GROUP) == name)


def entries(panel, cat, key):
    return [r for r in panel._rows() if r.data(0, fp.ROLE_CAT) == cat and r.data(0, fp.ROLE_KEY) == key]


def lit(window):
    return sorted(i.card.title for i in window.scene.cards.values() if i.opacity() > 0.9)


def test_groups_come_first_with_the_strands_cards_use(panel):
    assert outline(panel, "characters") == [
        "Council   (2)", "  Rowan   (1)", "  Greta   (1)",
        "Family   (1)", "  Rowan   (1)", "  Mabel   (1)",
        "Warden   (1)", "(none)   (1)"]
    # POV and Introduces list character groups too, with only the strands they have.
    assert outline(panel, "pov") == ["Council   (1)", "  Rowan   (1)", "Family   (1)", "  Rowan   (1)",
                                     "(none)   (3)"]
    assert outline(panel, "tags") == ["Act 1   (1)", "(none)   (3)"]


def test_ticking_a_group_ticks_its_strands_everywhere(window, panel):
    group_row(panel, "characters", "Council").setCheckState(0, CHECKED)
    assert panel._selection["characters"] == {"rowan", "greta"}
    assert all(r.checkState(0) == CHECKED for r in entries(panel, "characters", "rowan"))
    assert group_row(panel, "characters", "Family").checkState(0) == PARTLY   # Rowan, not Mabel
    assert lit(window) == ["A", "B"]
    assert heading(panel, "characters").text(0) == "Characters   · 2 selected"
    group_row(panel, "characters", "Council").setCheckState(0, OFF)
    assert panel._selection["characters"] == set() and not panel.is_active()
    assert group_row(panel, "characters", "Family").checkState(0) == OFF


def test_one_strand_makes_its_groups_partly_ticked_and_a_click_ticks_the_rest(window, panel, qapp):
    entries(panel, "characters", "mabel")[0].setCheckState(0, CHECKED)
    family = group_row(panel, "characters", "Family")
    assert family.checkState(0) == PARTLY
    assert group_row(panel, "characters", "Council").checkState(0) == OFF
    # The keyboard toggles a box as a click does: partly ticked becomes ticked.
    panel.tree.setFocus()
    panel.tree.setCurrentItem(family)
    QTest.keyClick(panel.tree.viewport(), Qt.Key.Key_Space)
    qapp.processEvents()
    assert family.checkState(0) == CHECKED
    assert panel._selection["characters"] == {"rowan", "mabel"}
    assert group_row(panel, "characters", "Council").checkState(0) == PARTLY


def test_match_all_with_a_group_needs_every_strand(window, panel):
    assert "group" not in panel.hint.text()
    panel.set_match_all("characters", True)
    try:
        assert panel.hint.text().endswith("A ticked strand group there needs every strand in it.")
        group_row(panel, "characters", "Family").setCheckState(0, CHECKED)
        assert lit(window) == ["A"]
        group_row(panel, "characters", "Council").setCheckState(0, CHECKED)
        assert lit(window) == []                        # nobody has Rowan, Mabel and Greta
    finally:
        panel.set_match_all("characters", False)


def test_ticks_survive_group_edits_and_clear_unticks_groups(window, scene, panel, settle):
    group_row(panel, "characters", "Family").setCheckState(0, CHECKED)
    scene.add_to_strand_group("characters", "Family", ["Warden"])
    settle()
    panel.refresh()
    family = group_row(panel, "characters", "Family")
    assert family.checkState(0) == PARTLY            # Warden joined, unticked
    assert panel._selection["characters"] == {"rowan", "mabel"}
    scene.update_strand_group("characters", "Family", new_name="Kin")
    settle()
    panel.refresh()
    assert group_row(panel, "characters", "Kin").checkState(0) == PARTLY
    panel.clear_selection()
    assert group_row(panel, "characters", "Kin").checkState(0) == OFF
    assert all(r.checkState(0) == OFF for r in entries(panel, "characters", "rowan"))


def test_folding_a_group_is_remembered(window, scene, panel, settle):
    group_row(panel, "characters", "Family").setExpanded(False)
    scene.add_card(CardData(title="E", characters=["Greta"], x=1200))
    settle()
    panel.refresh()
    assert not group_row(panel, "characters", "Family").isExpanded()
    assert group_row(panel, "characters", "Council").isExpanded()
    assert heading(panel, "characters").isExpanded()


def test_a_group_row_has_no_rename_menu(window, panel):
    assert panel._menu_for(group_row(panel, "characters", "Family")) is None
    menu = panel._menu_for(entries(panel, "characters", "mabel")[0])
    assert [a.text() for a in menu.actions()][-1] == "Rename character “Mabel”…"
