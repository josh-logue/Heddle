"""The app was renamed StoryBoard -> WarpingWeft -> Heddle. Preferences, local data
(backups, logs, recovery) and boards from either former name carry over once."""
import json

import pytest
from PySide6.QtCore import QSettings

from heddle import error_log, recovery
from heddle import settings as app_settings
from heddle.main_window import MainWindow
from heddle.model import APP_ID, BoardData, load_board


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """INI stand-ins for the registry entries under each name (never the real registry)."""
    def make(name):
        return QSettings(str(tmp_path / f"{name}.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(app_settings, "_legacy_store", make)
    monkeypatch.setattr(app_settings, "_legacy_checked", False)
    return make


def test_legacy_names_are_newest_first():
    assert app_settings.APP_NAME == "Heddle"
    assert app_settings.LEGACY_APP_NAMES == ("WarpingWeft", "StoryBoard")


def test_warpingweft_preferences_carry_over(stores):
    old = stores("WarpingWeft")
    old.setValue("dark_mode", True)
    old.setValue("recent_files", ["C:/boards/story.json"])
    old.sync()
    current = stores("Heddle")
    app_settings._adopt_legacy(current)
    assert current.value("dark_mode", type=bool) is True
    assert current.value("recent_files") == ["C:/boards/story.json"]  # Open Recent kept
    assert stores("WarpingWeft").value("dark_mode", type=bool) is True  # old entry left alone


def test_storyboard_preferences_still_carry_over(stores):
    old = stores("StoryBoard")
    old.setValue("autosave", True)
    old.sync()
    current = stores("Heddle")
    app_settings._adopt_legacy(current)
    assert current.value("autosave", type=bool) is True


def test_newer_former_name_wins(stores):
    for name, theme in (("StoryBoard", "old"), ("WarpingWeft", "newer")):
        s = stores(name)
        s.setValue("theme", theme)
        s.setValue(f"only_{name}", 1)
        s.sync()
    current = stores("Heddle")
    app_settings._adopt_legacy(current)
    assert current.value("theme") == "newer"
    assert "only_StoryBoard" not in current.allKeys()  # never a mix of the two


def test_existing_preferences_are_not_overwritten(stores):
    old = stores("WarpingWeft")
    old.setValue("theme", "old")
    old.sync()
    current = stores("Heddle")
    current.setValue("theme", "mine")
    app_settings._adopt_legacy(current)
    assert current.value("theme") == "mine"


def test_migration_runs_once_per_session(stores):
    current = stores("Heddle")
    app_settings._adopt_legacy(current)  # nothing to copy yet
    old = stores("WarpingWeft")
    old.setValue("theme", "late")
    old.sync()
    app_settings._adopt_legacy(current)
    assert "theme" not in current.allKeys()


@pytest.fixture
def base(tmp_path, monkeypatch):
    root = tmp_path / "LocalAppData"
    root.mkdir()
    monkeypatch.setattr(app_settings, "_data_base", lambda: root)
    for var in ("HEDDLE_BACKUP_DIR", "HEDDLE_LOG_DIR", "HEDDLE_RECOVERY_DIR"):
        monkeypatch.delenv(var, raising=False)
    return root


@pytest.mark.parametrize("old_name", ["WarpingWeft", "StoryBoard"])
def test_local_data_moves_from_a_former_name(base, old_name):
    for sub in ("backups", "logs", "recovery"):
        (base / old_name / sub).mkdir(parents=True)
        (base / old_name / sub / "kept.txt").write_text(sub)
    assert MainWindow._backup_root() == base / "Heddle" / "backups"
    assert error_log.log_dir() == base / "Heddle" / "logs"
    assert recovery.recovery_dir() == base / "Heddle" / "recovery"
    for sub in ("backups", "logs", "recovery"):
        assert (base / "Heddle" / sub / "kept.txt").read_text() == sub
        assert not (base / old_name / sub).exists()


def test_newer_former_folder_is_moved_first(base):
    (base / "StoryBoard" / "backups").mkdir(parents=True)
    (base / "WarpingWeft" / "backups").mkdir(parents=True)
    (base / "WarpingWeft" / "backups" / "newer.txt").write_text("x")
    root = app_settings.data_dir("backups")
    assert (root / "newer.txt").exists()
    assert (base / "StoryBoard" / "backups").is_dir()  # left where it was


def test_existing_folder_is_left_alone(base):
    (base / "Heddle" / "backups").mkdir(parents=True)
    (base / "WarpingWeft" / "backups").mkdir(parents=True)
    assert app_settings.data_dir("backups") == base / "Heddle" / "backups"
    assert (base / "WarpingWeft" / "backups").is_dir()


def test_old_folder_is_used_if_it_cannot_be_moved(base, monkeypatch):
    old = base / "WarpingWeft" / "logs"
    old.mkdir(parents=True)

    def refuse(self, target):
        raise OSError("in use")
    monkeypatch.setattr(type(old), "rename", refuse)
    assert app_settings.data_dir("logs") == old


def test_nothing_to_move_gives_the_new_folder(base):
    assert app_settings.data_dir("recovery") == base / "Heddle" / "recovery"


@pytest.mark.parametrize("old_app", ["WarpingWeft", "StoryBoard"])
def test_boards_saved_under_a_former_name_still_open(tmp_path, old_app):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"app": old_app, "version": 12,
                                "cards": [{"id": "a", "title": "Rowan"}]}), encoding="utf-8")
    board = load_board(path)
    assert [c.title for c in board.cards] == ["Rowan"]
    assert BoardData().to_dict()["app"] == APP_ID == "Heddle"  # new saves use the new name
