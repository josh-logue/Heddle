"""Shared fixtures. Qt runs headless, and every test gets its own throwaway
settings file, backup folder, recovery folder, log folder and Documents folder, so running the suite never
touches your real preferences, backups or boards."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


_SCENES = None  # every BoardScene made during the current test (weakly held)


@pytest.fixture(autouse=True)
def children_index_stays_right():
    """After every test, each board's group-membership index (members_of) must match a
    full scan: a parent change that skipped set_parent would show up here."""
    import weakref

    from heddle.scene import BoardScene
    global _SCENES
    _SCENES = weakref.WeakSet()
    original = BoardScene.__init__

    def tracking_init(self, *a, **k):
        original(self, *a, **k)
        _SCENES.add(self)
    BoardScene.__init__ = tracking_init
    try:
        yield
        for s in list(_SCENES):
            assert s.check_children_index(), "the children index drifted from card.parent"
    finally:
        BoardScene.__init__ = original


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HEDDLE_SETTINGS_FILE", str(tmp_path / "settings.ini"))
    monkeypatch.setenv("HEDDLE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("HEDDLE_RECOVERY_DIR", str(tmp_path / "recovery"))
    monkeypatch.setenv("HEDDLE_LOG_DIR", str(tmp_path / "logs"))
    docs = tmp_path / "Documents"
    docs.mkdir()
    import heddle.main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_documents_dir", staticmethod(lambda: docs))
    yield
    _free_leftover_widgets()


def _free_leftover_widgets() -> None:
    """Delete every window and dialog a test left behind. deleteLater() alone isn't
    enough outside a running event loop (the deletion never happens), so leftover
    windows used to pile up, all still running their timers and panels, and slow
    later tests down until fixed waits timed out."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    from heddle.main_window import MainWindow
    for w in app.topLevelWidgets():
        if isinstance(w, MainWindow):
            w.setWindowModified(False)  # close without asking to save
            w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def pytest_sessionfinish(session, exitstatus):
    """Empty the clipboard before Python shuts down. On the offscreen platform, Qt
    crashes during interpreter exit (an access violation) if the clipboard still holds
    copied cards, turning a passing run into a failed one in CI."""
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is not None:
        QApplication.clipboard().clear()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp):
    """A fresh main window; closed without prompting afterwards."""
    from heddle.main_window import MainWindow
    w = MainWindow()
    w.resize(1100, 700)
    yield w
    w.setWindowModified(False)
    w.close()
    w.deleteLater()
    qapp.processEvents()


@pytest.fixture
def scene(window):
    return window.scene


@pytest.fixture
def tick_filter(qapp):
    """Tick a filter value the way a user does: open the panel, check its box."""
    from PySide6.QtCore import Qt

    def _tick(window, category, key, keep_open=False):
        was_open = window.filter_dock.isVisible()
        window.filter_dock.show()
        qapp.processEvents()
        tree = window.filter_panel.tree
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) == category and \
                        child.data(0, Qt.ItemDataRole.UserRole + 1) == key:
                    child.setCheckState(0, Qt.CheckState.Checked)
        if not (keep_open or was_open):
            window.filter_dock.hide()
        qapp.processEvents()
    return _tick


@pytest.fixture
def settle(qapp, scene):
    """Record a finished edit, as the end of a user action would (one undo step)."""
    def _settle():
        scene.mark_modified()
        qapp.processEvents()
    return _settle


def wait_until(condition, timeout_ms: int = 5000) -> None:
    """Process events until condition() is true (fails after timeout_ms). Use this
    rather than a fixed wait for debounced updates, which a busy machine can delay."""
    import time

    from PySide6.QtCore import QCoreApplication, QEventLoop
    deadline = time.monotonic() + timeout_ms / 1000
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout_ms} ms waiting for {condition}")
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)
