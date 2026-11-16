"""Five improvements: a scrollable Help window from one shared source, snap to grid,
lists that keep their place, custom colours protected while in use, and recovery
copies (instead of Documents\\NewBoard-N.json) for untitled boards."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QMessageBox

import heddle.dialogs as dlg
import heddle.main_window as mw
import heddle.scene as sc
from heddle import settings
from heddle.help_text import (
    CONTROLS_END, CONTROLS_START, README_FILE, help_markdown, parse, readme_section,
    readme_with_controls,
)
from heddle.model import KIND_GROUP, CardData, save_board
from heddle.recovery import orphans, recovery_dir


# ----- 1. Help -----------------------------------------------------------------------
def test_controls_file_parses_into_sections():
    sections = parse()
    assert [s for s, _ in sections][:2] == ["Cards", "Connections"]
    assert all(entries for _, entries in sections)
    assert any(action == "Snap to grid" for _, entries in sections for action, _ in entries)
    with pytest.raises(ValueError):
        parse("## Cards\n- not an entry\n")


def test_readme_controls_match_the_controls_file():
    """If this fails, run:  .venv\\Scripts\\python.exe -m heddle.help_text"""
    readme = README_FILE.read_text(encoding="utf-8")
    assert CONTROLS_START in readme and CONTROLS_END in readme
    assert readme_with_controls(readme) == readme
    assert "| Snap to grid |" in readme_section()


def test_help_window_scrolls_and_fits_the_screen(window, qapp):
    window.show()
    help1 = window.show_help()
    qapp.processEvents()
    text = help1.browser.toPlainText()
    assert "Snap to grid" in text and "Character thread" in text
    assert "<!--" not in help_markdown()
    screen = window.screen().availableGeometry()
    assert help1.height() <= screen.height() and help1.width() <= screen.width()
    assert help1.browser.verticalScrollBar().maximum() > 0 or help1.height() < 760
    assert window.show_help() is help1           # F1 again brings the same window forward
    help1.close()


# ----- 2. Snap to grid --------------------------------------------------------------------
def test_snap_is_off_by_default_and_follows_the_setting(window):
    assert not window.scene.snap_to_grid and not window.act_snap.isChecked()
    window.act_snap.trigger()
    assert window.scene.snap_to_grid and settings.get("snap_to_grid")
    window.act_snap.trigger()
    assert not window.scene.snap_to_grid


def test_dropped_and_new_cards_land_on_the_grid(scene):
    scene.snap_to_grid = True
    a = scene.add_card(CardData(title="A", x=7, y=3))            # not moved: stays put
    b = scene.add_card(CardData(title="B", x=400))
    b.setPos(437, 61)
    b.setSelected(True)
    scene.handle_drop(b)
    assert (b.pos().x(), b.pos().y()) == (425, 50)
    assert (a.pos().x(), a.pos().y()) == (7, 3)
    new = scene.create_card_at(QPointF(333, 333), edit=False)
    assert new.pos().x() % sc.GRID == 0 and new.pos().y() % sc.GRID == 0


def test_a_dropped_group_snaps_and_keeps_its_cards_in_place(scene):
    scene.snap_to_grid = True
    g = scene.add_card(CardData(title="G", kind=KIND_GROUP))
    m = scene.add_card(CardData(title="M", x=13, y=67, parent=g.card.id))
    scene._refit_ids({g.card.id})
    offset = m.pos() - g.pos()
    g.setPos(g.pos() + QPointF(41, 17))
    g.setSelected(True)
    scene.handle_drop(g)
    assert g.pos().x() % sc.GRID == 0 and g.pos().y() % sc.GRID == 0
    assert m.pos() - g.pos() == offset


def test_nudging_with_snap(window):
    s = window.scene
    window.act_snap.trigger()
    a = s.add_card(CardData(title="A", x=13, y=0))
    a.setSelected(True)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window.show()
    window.focus_canvas()
    QTest.keyClick(window.view.viewport(), Qt.Key.Key_Right)
    assert a.pos().x() == 25                       # the next grid line, not 13 + 25
    QTest.keyClick(window.view.viewport(), Qt.Key.Key_Right)
    assert a.pos().x() == 50
    QTest.keyClick(window.view.viewport(), Qt.Key.Key_Left)
    assert a.pos().x() == 25
    QTest.keyClick(window.view.viewport(), Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert a.pos().x() == 26                       # Shift: 1 px, no snapping
    assert a.pos().y() == 0                        # the other axis is left alone


# ----- 3. Lists keep their place -------------------------------------------------------------
def test_checks_list_is_left_alone_when_nothing_changed(window, qapp):
    s = window.scene
    cards = [s.add_card(CardData(title=f"C{i}", x=i * 300)) for i in range(40)]
    for a, b in zip(cards[::2], cards[1::2]):
        s.add_connection(a, b)                    # 20 chains: 20 dead ends, 20 starts
    s.mark_modified()
    window.show()
    window.checks_dock.show()
    qapp.processEvents()
    panel = window.checks_panel
    panel.recheck()
    first = panel.tree.topLevelItem(0)
    bar = panel.tree.verticalScrollBar()
    bar.setValue(bar.maximum())
    cards[0].moveBy(50, 0)                        # a move: same results
    s.mark_modified()
    panel.recheck()
    assert panel.tree.topLevelItem(0) is first and bar.value() == bar.maximum()
    s.remove_card(cards[1])                       # results change: rebuilt, scroll kept
    s.mark_modified()
    scroll = bar.value()
    panel.recheck()
    assert panel.tree.topLevelItem(0) is not first and bar.value() == min(scroll, bar.maximum())


def test_filter_list_keeps_its_scroll_position(window, qapp):
    s = window.scene
    for i in range(60):
        s.add_card(CardData(title=f"C{i}", tags=[f"tag {i:02d}"], x=i * 10))
    s.mark_modified()
    window.show()
    window.filter_dock.show()
    qapp.processEvents()
    bar = window.filter_panel.tree.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    where = bar.value()
    s.add_card(CardData(title="New", tags=["tag 99"]))
    s.mark_modified()                             # the tag counts change: list rebuilt
    qapp.processEvents()
    assert bar.value() == where


# ----- 4. Custom colours ----------------------------------------------------------------------
def test_a_colour_in_use_elsewhere_cant_leave_the_palette(qapp):
    card = CardData(color="#4a7fc1")
    d = dlg.CardDialog(card, ["#123456", "#abcdef"], color_usage={"#123456": 2})
    assert d.removal_state("#123456") == (False, "Can't remove: used by 2 other cards and arrows")
    assert d.removal_state("#abcdef")[0] is True


def test_editor_is_told_which_colours_other_cards_and_arrows_use(scene, monkeypatch):
    a = scene.add_card(CardData(title="A", color="#123456"))
    b = scene.add_card(CardData(title="B", color="#123456", x=400))
    edge = scene.add_connection(a, b)
    edge.conn.color = "#abcdef"
    seen = {}

    def fake_exec(self):
        seen.update(self._color_usage)
        return 0
    monkeypatch.setattr(dlg.CardDialog, "exec", fake_exec)
    scene.edit_card(a)
    assert seen == {"#123456": 1, "#abcdef": 1}   # B and the arrow; not A itself


def test_remove_unused_offers_colours_nothing_uses(scene):
    scene.add_card(CardData(title="A", color="#123456"))
    a = scene.add_card(CardData(title="B", x=400))
    b = scene.add_card(CardData(title="C", x=800))
    scene.add_connection(a, b).conn.color = "#abcdef"
    scene.custom_colors = ["#123456", "#abcdef", "#00ff00"]
    assert scene.unused_saved_values() == {"custom_colors": ["#00ff00"]}
    assert scene.remove_saved_values({"custom_colors": ["#00ff00"]}) == 1
    assert scene.custom_colors == ["#123456", "#abcdef"]


# ----- 5. Recovery copies of untitled boards ----------------------------------------------------
def autosave_untitled(window):
    window.act_autosave.setChecked(True)
    window.scene.add_card(CardData(title="Draft card"))
    window.scene.mark_modified()
    window._autosave()
    return window._recovery.path


def test_untitled_autosave_writes_a_recovery_copy(window):
    path = autosave_untitled(window)
    assert path.exists() and path.parent == recovery_dir()
    assert window.current_path is None and "Untitled" in window.windowTitle()
    assert window.isWindowModified()
    assert not list(window._documents_dir().glob("*"))
    assert orphans() == []                       # its window is open: not offered


def test_saving_discarding_or_closing_removes_the_copy(window, tmp_path, monkeypatch):
    path = autosave_untitled(window)
    monkeypatch.setattr(mw.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "kept.json"), "")))
    assert window.save_board_as()
    assert not path.exists() and window._recovery is None

    window.new_board()
    path = autosave_untitled(window)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard))
    window.new_board()                           # chose Discard
    assert not path.exists()

    path = autosave_untitled(window)
    window.close()                               # Discard again
    assert not path.exists()


def leave_behind(board_cards=("Lost scene",)):
    """A recovery copy whose window has gone (as after a crash): no lock held."""
    from heddle.model import BoardData
    folder = recovery_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "Untitled-20261113-120000-abcdef.json"
    save_board(BoardData(cards=[CardData(title=t) for t in board_cards]), path)
    return path


def answer(monkeypatch, button_text):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton",
                        lambda self: next(b for b in self.buttons() if b.text() == button_text))


def test_next_launch_offers_to_recover(window, monkeypatch):
    path = leave_behind()
    answer(monkeypatch, "Recover")
    assert window.offer_recovery()
    assert [i.card.title for i in window.scene.cards.values()] == ["Lost scene"]
    assert window.current_path is None and window.isWindowModified()
    assert window._recovery.path == path          # keeps autosaving to the same copy
    assert orphans() == []                        # and holds its lock again


def test_delete_or_not_now(window, monkeypatch):
    path = leave_behind()
    answer(monkeypatch, "Not now")
    assert not window.offer_recovery() and path.exists() and not window.scene.cards
    assert [p for p, lock in orphans() if not lock.unlock()] == [path]   # offered again later
    answer(monkeypatch, "Delete")
    assert not window.offer_recovery() and not path.exists()


def test_only_offered_into_an_empty_untitled_window(window, monkeypatch):
    leave_behind()
    window.scene.add_card(CardData(title="Already working"))
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: asked.append(1) or 0)
    assert not window.offer_recovery() and asked == []
