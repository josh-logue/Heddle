"""The shared searchable checklist, as used by the group editor and the List… picker."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from warpingweft.dialogs import MemberList
from warpingweft.token_input import EntryPickerDialog


@pytest.fixture
def members(qapp):
    w = MemberList([("id1", "Intro", True), ("id2", "Election", False), ("id3", "Pack", False)])
    w.resize(400, 300)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def click_row(widget, row, x):
    rect = widget.list.visualItemRect(widget.list.item(row))
    QTest.mouseClick(widget.list.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(x, rect.center().y()))


@pytest.mark.parametrize("x", [8, 200])          # on the checkbox, and on the text
def test_any_click_on_a_row_toggles_it_exactly_once(members, x):
    click_row(members, 1, x)
    assert members.checked_ids() == ["id1", "id2"]
    click_row(members, 1, x)
    assert members.checked_ids() == ["id1"]


def test_search_and_bulk_checking_only_affect_visible_rows(members):
    members.search.setText("ion")                 # matches "Election" only
    members._set_visible_checked(True)
    members.search.setText("")
    assert members.checked_ids() == ["id1", "id2"]
    assert members.count_label.text() == "2 of 3 in group"


def test_entry_picker_returns_checked_labels(qapp):
    d = EntryPickerDialog("tags", ["alpha", "Beta", "gamma"], ["beta"])
    assert d.checked_values() == ["Beta"] and d.checklist.count_label.text() == "1 of 3 selected"
    empty = EntryPickerDialog("tags", [], [])
    assert empty.checked_values() == [] and empty.list.count() == 1
