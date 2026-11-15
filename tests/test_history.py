from warpingweft.history import History


def test_noop_commit_is_ignored():
    h = History()
    h.reset({"n": 0})
    assert not h.commit({"n": 0}) and not h.can_undo()


def test_undo_redo_and_new_edit_clears_redo():
    h = History()
    h.reset({"n": 0})
    h.commit({"n": 1})
    h.commit({"n": 2})
    assert h.undo() == {"n": 1} and h.undo() == {"n": 0} and h.undo() is None
    assert h.redo() == {"n": 1}
    h.commit({"n": 9})
    assert not h.can_redo() and h.undo() == {"n": 1}


def test_limit_drops_oldest_steps():
    h = History(limit=3)
    h.reset({"n": 0})
    for i in range(1, 6):
        h.commit({"n": i})
    assert [h.undo()["n"] for _ in range(3)] == [4, 3, 2] and h.undo() is None


def test_saved_state_tracking():
    h = History()
    h.reset({"n": 0})
    assert h.at_saved()
    h.commit({"n": 1})
    assert not h.at_saved()
    h.mark_saved()
    h.commit({"n": 2})
    h.undo()
    assert h.at_saved()
