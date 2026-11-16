"""The demo boards in examples/ load and still show what they were built to show."""
from pathlib import Path

from heddle.checks import run_checks
from heddle.graph import StoryGraph
from heddle.model import FORMAT_VERSION, load_board

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_lantern_tide_findings():
    board = load_board(EXAMPLES / "lantern-tide.json")
    assert board.source_version == FORMAT_VERSION
    graph = StoryGraph(board.cards, board.connections)
    report = run_checks(graph)
    kinds = {k: [set(f.cards) for f in report.of_kind(k)] for k in
             ("dead_end", "loose_starts", "cycle", "isolated", "ending")}
    assert kinds["dead_end"] == [{"quarters"}]
    assert kinds["loose_starts"] == [{"lantern", "coldopen"}]
    assert kinds["cycle"] == [{"market", "lost", "bells"}]
    assert kinds["isolated"] == [{"festival"}]
    assert {c for s in kinds["ending"] for c in s} == {"relight", "flood", "keep"}
    intro = graph.introductions()
    assert {"lantern", "coldopen", "hall", "bargain"} <= set(intro)
    keys = {r.key for r in graph.routes()}
    assert all(tuple(r.key) in keys for r in board.routes)  # every named route still exists
    assert len(board.routes) == 3


def test_hollybank_garden_is_a_sorting_board():
    board = load_board(EXAMPLES / "hollybank-garden.json")
    assert not board.connections
    assert board.display["story_tools"] is False
    assert "Frost Tender" in board.all_values("tags")
    assert not any("Frost Tender" in c.tags for c in board.cards)  # left for the drag demo
