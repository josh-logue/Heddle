"""Several boards in several windows: opening a board never replaces the one shown;
it opens in a new window (or in this one, if it's still a blank Untitled board), and
a board that's already open brings its window to the front instead."""
import pytest

import warpingweft.main_window as mw
from warpingweft import settings, theme
from warpingweft.model import BoardData, CardData, save_board


def board_file(tmp_path, name, title):
    path = tmp_path / name
    save_board(BoardData(cards=[CardData(title=title)]), path)
    return path


def titles(win):
    return [c.card.title for c in win.scene.cards.values()]


@pytest.fixture
def no_recovery(monkeypatch):
    offered = []
    monkeypatch.setattr(mw.MainWindow, "offer_recovery", lambda self: offered.append(self) or False)
    return offered


def test_a_blank_window_is_used_for_the_first_board(window, tmp_path):
    a = board_file(tmp_path, "a.json", "A")
    assert window.is_blank()
    assert window.request_open(a) is window
    assert window.current_path == a and mw.open_windows() == [window]


def test_another_board_opens_in_a_new_window(window, qapp, tmp_path, no_recovery):
    a, b = board_file(tmp_path, "a.json", "A"), board_file(tmp_path, "b.json", "B")
    window.show()
    window.request_open(a)
    other = window.request_open(b)
    assert other is not None and other is not window
    assert titles(window) == ["A"] and titles(other) == ["B"]       # nothing replaced
    assert mw.open_windows() == [window, other]
    assert other.pos() - window.pos() == mw.QPoint(mw.CASCADE, mw.CASCADE)
    assert other.size() == window.size() and other.isVisible()
    qapp.processEvents()
    assert other not in no_recovery                                  # only the first window offers recovery


def test_opening_an_open_board_brings_its_window_forward(window, qapp, tmp_path, monkeypatch):
    a, b = board_file(tmp_path, "a.json", "A"), board_file(tmp_path, "b.json", "B")
    window.show()
    window.request_open(a)
    other = window.request_open(b)
    raised = []
    monkeypatch.setattr(mw.MainWindow, "bring_to_front", lambda self: raised.append(self))
    # However it's spelled: a different case, or a path with a detour in it.
    respelled = tmp_path / "sub" / ".." / "A.JSON"
    (tmp_path / "sub").mkdir()
    assert other.request_open(respelled) is window
    assert raised == [window] and len(mw.open_windows()) == 2
    assert window.request_open(b) is other and raised[-1] is other


def test_open_recent_and_drops_follow_the_same_rules(window, qapp, tmp_path):
    a, b, c = (board_file(tmp_path, f"{n}.json", n.upper()) for n in "abc")
    window.request_open(a)
    window.open_recent(a)                                            # already open: nothing new
    assert len(mw.open_windows()) == 1
    window.open_dropped([b, c])                                      # two boards: two windows
    paths = sorted(w.current_path.name for w in mw.open_windows())
    assert paths == ["a.json", "b.json", "c.json"] and titles(window) == ["A"]


def test_file_new(window, qapp, no_recovery):
    assert window.new_window() is window                             # still blank: stays here
    window.scene.add_card(CardData(title="Draft"))
    fresh = window.new_window()
    assert fresh is not window and fresh.is_blank() and titles(window) == ["Draft"]
    assert window.act_new.toolTip() or window.act_new.statusTip()


def test_a_board_that_wont_open_makes_no_window(window, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "critical", staticmethod(lambda *a: shown.append(a[1])))
    window.scene.add_card(CardData(title="Busy"))
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert window.request_open(bad) is None
    assert shown and mw.open_windows() == [window] and titles(window) == ["Busy"]


def test_theme_and_settings_reach_every_window(window, qapp, no_recovery):
    window.scene.add_card(CardData(title="A"))
    other = window.new_window()
    start = theme.current().dark
    window.set_dark_mode(not start)
    assert other.act_dark.isChecked() == (not start) == window.act_dark.isChecked()
    window.set_dark_mode(start)
    settings.set("wheel_zooms", True)
    for w in mw.open_windows():  # what show_settings does after the dialog
        w._apply_settings()
    assert window.view.wheel_zooms and other.view.wheel_zooms


def test_closing_and_exit(window, qapp, no_recovery, monkeypatch):
    window.scene.add_card(CardData(title="A"))
    second = window.new_window()
    second.scene.add_card(CardData(title="B"))
    third = window.new_window()
    third.close()
    assert mw.open_windows() == [window, second]                     # a closed window is forgotten
    # Exit asks each window in turn; cancelling one stops it there.
    monkeypatch.setattr(mw.MainWindow, "maybe_save", lambda self: self is not window)
    assert mw.close_all_windows() is False
    assert mw.open_windows() == [window]                             # second closed, first cancelled
    monkeypatch.setattr(mw.MainWindow, "maybe_save", lambda self: True)
    assert mw.close_all_windows() is True and mw.open_windows() == []


def test_same_file():
    from pathlib import Path
    here = Path(__file__)
    assert mw.same_file(here, here.parent / ".." / here.parent.name / here.name)
    assert not mw.same_file(here, here.with_name("nope.py"))


def test_save_as_onto_a_board_open_in_another_window_is_refused(window, tmp_path, monkeypatch, no_recovery):
    from warpingweft.model import load_board
    window.scene.add_card(CardData(title="Mine"))
    other = window.new_window()
    other.scene.add_card(CardData(title="Theirs"))
    theirs = tmp_path / "theirs.json"
    assert other._write(theirs)
    asked = []
    monkeypatch.setattr(mw.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(theirs), "")))
    monkeypatch.setattr(mw.QMessageBox, "exec", lambda self: asked.append(self.text()) or 0)
    before = theirs.read_bytes()
    assert window.save_board_as() is False
    assert asked and "open in another window" in asked[0]
    assert theirs.read_bytes() == before
    assert [c.title for c in load_board(theirs).cards] == ["Theirs"]
    assert window.current_path is None
    # Saving a window's own board under its own name is still fine.
    monkeypatch.setattr(mw.QMessageBox, "exec", lambda self: 0)
    assert other.save_board_as()


def test_a_big_board_without_arrows_hints_at_story_tools_once(window, tmp_path, monkeypatch):
    from warpingweft.model import BoardData, save_board
    monkeypatch.setattr(mw, "_hinted_no_arrows", set())
    path = tmp_path / "sorting.json"
    save_board(BoardData(cards=[CardData(title=f"Role {n}", x=n * 300) for n in range(12)]), path)
    window.open_path(path)
    assert "No arrows on this board" in window.statusBar().currentMessage()
    assert window._hint_story_tools() is False          # once per board per session
    window.scene.set_display_option("story_tools", False)
    mw._hinted_no_arrows.clear()
    assert window._hint_story_tools() is False          # story tools already off
