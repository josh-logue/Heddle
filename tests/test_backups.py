from datetime import datetime, timedelta

from warpingweft.backups import backup_dir_for, file_digest, list_backups, make_backup
from warpingweft.model import BoardData, CardData, load_board, save_board

T0 = datetime(2026, 11, 13, 9, 0, 0)


def board(tmp_path, title="v1", name="story [draft].json"):
    p = tmp_path / name
    save_board(BoardData(cards=[CardData(title=title)]), p)
    return p


def test_nothing_to_back_up_for_a_new_file(tmp_path):
    assert make_backup(tmp_path / "missing.json", tmp_path / "root") is None


def test_throttled_unless_forced(tmp_path):
    p, root = board(tmp_path), tmp_path / "root"
    assert make_backup(p, root, now=T0)
    assert make_backup(p, root, now=T0 + timedelta(minutes=2)) is None
    assert make_backup(p, root, now=T0 + timedelta(minutes=2), force=True)
    # the forced one (at 2 min) is now the newest, so the next is due at 7 min
    assert make_backup(p, root, now=T0 + timedelta(minutes=6)) is None
    assert make_backup(p, root, now=T0 + timedelta(minutes=8))
    assert len(list_backups(p, root)) == 3


def test_same_second_backups_are_listed_newest_first(tmp_path):
    p, root = board(tmp_path, "first"), tmp_path / "root"
    make_backup(p, root, now=T0)
    for title in ("second", "third"):
        save_board(BoardData(cards=[CardData(title=title)]), p)
        make_backup(p, root, now=T0, force=True)
    titles = [load_board(f).cards[0].title for f, _ in list_backups(p, root)]
    assert titles == ["third", "second", "first"]


def test_old_backups_are_pruned(tmp_path):
    p, root = board(tmp_path), tmp_path / "root"
    for i in range(8):
        make_backup(p, root, now=T0 + timedelta(minutes=10 * i), keep=5)
    found = list_backups(p, root)
    assert len(found) == 5 and found[0][1] == T0 + timedelta(minutes=70)


def test_same_name_in_different_folders_get_separate_backups(tmp_path):
    (tmp_path / "sub").mkdir()
    a, b = board(tmp_path), board(tmp_path / "sub")
    assert backup_dir_for(a, tmp_path / "r") != backup_dir_for(b, tmp_path / "r")


def test_file_digest_tracks_contents_not_timestamps(tmp_path):
    p = board(tmp_path)
    d = file_digest(p)
    p.write_bytes(p.read_bytes())                    # rewritten, identical
    assert file_digest(p) == d
    save_board(BoardData(cards=[CardData(title="changed")]), p)
    assert file_digest(p) != d and file_digest(tmp_path / "nope.json") is None
