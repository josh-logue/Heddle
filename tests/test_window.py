"""Main window behaviour (headless Qt): saving, autosave, backups, filter, navigation."""
import json

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

import heddle.backup_dialog as bd
import heddle.dialogs as dlg
import heddle.main_window as mw
from heddle import settings, theme
from heddle.backups import list_backups
from heddle.model import BoardData, CardData, save_board


def file_titles(path):
    return sorted(c["title"] for c in json.loads(path.read_text(encoding="utf-8"))["cards"])


@pytest.fixture
def no_dialogs(monkeypatch):
    """Record message boxes instead of showing them."""
    shown = []
    for kind in ("information", "critical", "warning"):
        monkeypatch.setattr(mw.QMessageBox, kind, staticmethod(lambda *a, k=kind: shown.append((k, a[2]))))
    return shown


# ----- opening damaged files -------------------------------------------------------------
def test_bad_values_open_fine_and_unreadable_files_keep_the_board(window, tmp_path, no_dialogs):
    good = tmp_path / "good.json"
    save_board(BoardData(cards=[CardData(title=f"G{i}") for i in range(3)]), good)
    window.open_path(good)
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"cards": [{"title": "ok"}, {"title": "x", "description": None, "x": None}]}))
    window.open_path(odd)
    assert sorted(i.card.title for i in window.scene.cards.values()) == ["ok", "x"] and not no_dialogs
    window.open_path(good)
    (tmp_path / "junk.json").write_text("{not json")
    window.open_path(tmp_path / "junk.json")
    assert window.current_path == good and len(window.scene.cards) == 3 and no_dialogs


# ----- autosave ------------------------------------------------------------------------
def test_failed_autosave_retries_with_backoff(window, tmp_path, monkeypatch, qapp):
    import heddle.model as model
    target = tmp_path / "b.json"
    window.act_autosave.setChecked(True)
    assert window._write(target)
    real, locked = model.os.replace, {"n": 3}

    def flaky(src, dst):
        if locked["n"]:
            locked["n"] -= 1
            raise PermissionError(13, "in use")
        return real(src, dst)
    monkeypatch.setattr(model.os, "replace", flaky)
    window.scene.add_card(CardData(title="Unsaved"))
    window.scene.mark_modified()
    qapp.processEvents()
    delays = []
    for _ in range(3):
        window._autosave()
        delays.append(window._autosave_timer.interval())
    assert delays == list(mw.AUTOSAVE_RETRY_MS)
    window._autosave()
    assert not window.isWindowModified() and file_titles(target) == ["Unsaved"]
    window.scene.add_card(CardData(title="Next"))
    window.scene.mark_modified()
    assert window._autosave_timer.interval() == mw.AUTOSAVE_MS


# ----- backups & changes on disk ----------------------------------------------------------
@pytest.fixture
def opened(window, tmp_path):
    p = tmp_path / "story.json"
    save_board(BoardData(cards=[CardData(id="g", title="Act 1", kind="group"),
                                CardData(title="Scene", parent="g", x=30, y=60)]), p)
    window.open_path(p)
    return p


def test_first_save_backs_up_the_file_as_opened(window, opened, qapp):
    window.scene.add_card(CardData(title="Extra", x=900))
    window.scene.mark_modified()
    assert window.save_board()
    window.scene.add_card(CardData(title="Extra2", x=1200))
    window.scene.mark_modified()
    assert window.save_board()
    backups = list_backups(opened, window._backup_root())
    assert len(backups) == 1 and file_titles(backups[0][0]) == ["Act 1", "Scene"]


def test_restore_backup_is_an_undoable_change(window, opened, qapp, monkeypatch):
    window.scene.remove_card(window.scene.cards["g"], with_contents=True)
    window.scene.mark_modified()
    qapp.processEvents()
    assert window.save_board()

    def pick(self):
        self.list.setCurrentRow(0)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(bd.BackupDialog, "exec", pick)
    before = file_titles(opened)
    window.restore_backup()
    assert "Act 1" in [i.card.title for i in window.scene.cards.values()]
    assert file_titles(opened) == before                      # nothing written yet
    qapp.processEvents()
    window.scene.undo()
    assert not window.scene.cards


def test_changes_on_disk_are_never_silently_overwritten(window, opened, qapp, monkeypatch):
    answers = []
    monkeypatch.setattr(mw.MainWindow, "_ask_about_conflict", lambda self, p: answers.pop(0))
    save_board(BoardData(cards=[CardData(title="From laptop")]), opened)
    window.scene.add_card(CardData(title="Mine"))
    window.scene.mark_modified()
    answers[:] = ["cancel"]
    assert not window.save_board() and file_titles(opened) == ["From laptop"]
    answers[:] = ["overwrite"]
    assert window.save_board() and "Mine" in file_titles(opened)
    assert file_titles(list_backups(opened, window._backup_root())[0][0]) == ["From laptop"]
    # autosave asks instead of overwriting, and pauses if cancelled
    save_board(BoardData(cards=[CardData(title="Other window")]), opened)
    window.scene.add_card(CardData(title="Auto"))
    window.scene.mark_modified()
    answers[:] = ["cancel"]
    window._autosave()
    qapp.processEvents()
    assert file_titles(opened) == ["Other window"] and window._autosave_blocked


def test_identical_rewrite_is_not_a_conflict(window, opened, monkeypatch):
    monkeypatch.setattr(mw.MainWindow, "_ask_about_conflict", lambda self, p: pytest.fail("asked"))
    opened.write_bytes(opened.read_bytes())
    window.scene.add_card(CardData(title="x"))
    window.scene.mark_modified()
    assert window.save_board()


# ----- import values ------------------------------------------------------------------------
def test_import_offers_only_new_values_and_custom_statuses(window, tmp_path, monkeypatch):
    src = tmp_path / "src.json"
    save_board(BoardData(cards=[CardData(tags=["school", "plot"], status="Draft"),
                                CardData(status="Needs research")],
                         custom_colors=["#123456"]), src)
    window.scene.add_card(CardData(tags=["School"]))
    offered = {}

    def accept_all(self):
        offered.update(self.selected())
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(mw.ValueChecklistDialog, "exec", accept_all)
    assert window.import_values_from(src) == 3
    assert offered == {"tags": ["plot"], "status": ["Needs research"], "custom_colors": ["#123456"]}


# ----- settings -------------------------------------------------------------------------
def test_typed_entries_are_kept_on_ok_when_enabled(window, monkeypatch):
    card = window.scene.add_card(CardData(tags=["existing"]))

    def type_and_ok(self):
        self.tags_input.edit.setText(" Act 2 ")
        self.characters_input.edit.setText("Mara")
        self.accept()
        return self.result()
    monkeypatch.setattr(dlg.CardDialog, "exec", type_and_ok)
    window.scene.edit_card(card)
    assert card.card.tags == ["existing", "Act 2"] and card.card.characters == ["Mara"]
    settings.set("commit_pending_entries", False)
    card.card.characters = []
    window.scene.edit_card(card)
    assert card.card.characters == []


# ----- filter indicators -------------------------------------------------------------------
def test_filter_banner_and_toolbar_show_an_active_filter(window, qapp, tick_filter):
    s = window.scene
    for k, tag in enumerate(["act1", "act1", "act2"]):
        s.add_card(CardData(title=f"C{k}", tags=[tag], x=k * 260))
    s.mark_modified()
    window.show()
    qapp.processEvents()
    button = window._toolbar.widgetForAction(window.act_filter)
    assert not window.filter_banner.isVisible() and window.act_filter.text() == "&Filter"
    tick_filter(window, "tags", "act1")
    assert window.filter_banner.isVisible() and "showing 2 of 3" in window.filter_banner.label.text()
    assert window.filter_banner.show_btn.isVisible()             # panel is hidden
    assert window.act_filter.text() == "&Filter (1)" and theme.ACCENT in button.styleSheet()
    QTest.mouseClick(window.filter_banner.clear_btn, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert not window.filter_banner.isVisible() and button.styleSheet() == ""


# ----- window layout is remembered ------------------------------------------------------
def test_window_size_and_filter_panel_are_restored(qapp):
    w = mw.MainWindow()
    w.show()
    w.resize(720, 560)   # the offscreen test screen is 800x800; Qt keeps restored windows on screen
    w.filter_dock.show()
    w.removeDockWidget(w.filter_dock)
    w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, w.filter_dock)
    w.filter_dock.show()
    w.filter_panel._selection["tags"].add("x")      # a filter selection: not remembered
    qapp.processEvents()
    w.close()
    qapp.processEvents()
    w2 = mw.MainWindow()
    w2.show()
    qapp.processEvents()
    try:
        assert (w2.width(), w2.height()) == (720, 560)
        assert w2.filter_dock.isVisible()
        assert w2.dockWidgetArea(w2.filter_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
        assert not w2.filter_panel.is_active() and not w2.filter_banner.isVisible()
    finally:
        w2.close()


def test_closing_with_cancel_does_not_save_layout(qapp, monkeypatch):
    w = mw.MainWindow()
    w.show()
    w.resize(700, 500)
    w.setWindowModified(True)
    monkeypatch.setattr(mw.MainWindow, "maybe_save", lambda self: False)
    w.close()
    assert w.settings.value("window/geometry") is None
    monkeypatch.undo()
    w.setWindowModified(False)
    w.close()


# ----- navigation -------------------------------------------------------------------------
def wheel(view, angle=(0, 0), pixel=(0, 0), mods=Qt.KeyboardModifier.NoModifier):
    vp = view.viewport()
    c = QPointF(vp.width() / 2, vp.height() / 2)
    QApplication.sendEvent(vp, QWheelEvent(c, vp.mapToGlobal(c), QPoint(*pixel), QPoint(*angle),
                                           Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False))


def test_scroll_pans_and_ctrl_scroll_zooms(window, qapp):
    v = window.view
    window.show()
    qapp.processEvents()

    def scroll():
        return v.horizontalScrollBar().value(), v.verticalScrollBar().value()
    z0, (h0, v0) = v.current_scale(), scroll()
    wheel(v, angle=(0, -120))
    assert v.current_scale() == z0 and scroll() == (h0, v0 + 120)
    h0, v0 = scroll()
    wheel(v, angle=(0, -120), mods=Qt.KeyboardModifier.ShiftModifier)
    assert scroll() == (h0 + 120, v0)
    wheel(v, angle=(0, 120), mods=Qt.KeyboardModifier.ControlModifier)
    assert abs(v.current_scale() - z0 * 1.15) < 1e-6
    v.wheel_zooms = True
    z1 = v.current_scale()
    wheel(v, angle=(0, -120))
    assert abs(v.current_scale() - z1 / 1.15) < 1e-6


def test_space_pans_without_canvas_focus(window, qapp, monkeypatch):
    window.scene.add_card(CardData(tags=["t"]))
    window.scene.mark_modified()
    window.filter_dock.show()
    window.show()
    window.activateWindow()
    qapp.processEvents()
    tree = window.filter_panel.tree
    tree.setFocus()
    item = tree.topLevelItem(0).child(0)
    tree.setCurrentItem(item)
    before = item.checkState(0)
    monkeypatch.setattr(window.view, "_pointer_over_canvas", lambda: True)
    QTest.keyPress(tree, Qt.Key.Key_Space)
    assert window.view._space_held and item.checkState(0) == before
    QTest.keyRelease(tree, Qt.Key.Key_Space)
    assert not window.view._space_held
