"""A board with a damaged card or arrow entry still opens, without that entry, and says
what it repaired. Reused arrow ids are renewed so the story tools see every arrow."""
import json

import warpingweft.main_window as mw
from warpingweft.graph import StoryGraph
from warpingweft.model import BoardData


def raw_board(**extra):
    raw = {"app": "warpingweft", "version": 8,
           "cards": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}, {"id": "c", "title": "C"}],
           "connections": [{"id": "x", "source": "a", "target": "b"}]}
    raw.update(extra)
    return raw


def test_a_damaged_arrow_is_skipped_not_fatal():
    raw = raw_board(connections=[{"id": "x", "source": "a", "target": "b"},
                                 {"id": "y", "source": "b"},   # no target
                                 "not an arrow"])
    board = BoardData.from_dict(raw)
    assert [c.id for c in board.connections] == ["x"]
    assert board.load_notes == ["2 damaged arrows skipped"]


def test_a_damaged_card_is_skipped_not_fatal():
    raw = raw_board()
    raw["cards"].append(["not", "a", "card"])
    board = BoardData.from_dict(raw)
    assert [c.id for c in board.cards] == ["a", "b", "c"]
    assert board.load_notes == ["1 damaged card skipped"]


def test_reused_arrow_ids_are_renewed_so_every_arrow_counts():
    raw = raw_board(connections=[{"id": "x", "source": "a", "target": "b"},
                                 {"id": "x", "source": "b", "target": "c"}])
    board = BoardData.from_dict(raw)
    assert len({c.id for c in board.connections}) == 2
    graph = StoryGraph(board.cards, board.connections)
    assert len(graph.arrows) == 2
    assert "c" in graph.succ["b"]
    assert board.load_notes == ["1 arrow given a new id (the id was used twice)"]


def test_a_clean_board_has_no_notes():
    assert BoardData.from_dict(raw_board()).load_notes == []


def test_opening_a_damaged_board_says_what_was_repaired(window, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "information", staticmethod(lambda *a: shown.append(a[2])))
    monkeypatch.setattr(mw.QMessageBox, "critical", staticmethod(lambda *a: shown.append("failed")))
    path = tmp_path / "damaged.json"
    path.write_text(json.dumps(raw_board(connections=[{"id": "y", "source": "a"}])), encoding="utf-8")
    window.open_path(path)
    assert window.current_path == path
    assert set(window.scene.cards) == {"a", "b", "c"}
    assert shown and "1 damaged arrow skipped" in shown[0]
