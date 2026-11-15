"""Phase E (November 2026): the speed-ups stay correct, and a 1,000-card board with
nested and collapsed groups and the Card panel open stays quick. The time budgets are
several times what a normal machine takes, so they only catch real regressions."""
import time

import warpingweft.scene as sc
from warpingweft.graph import StoryGraph
from warpingweft.model import KIND_GROUP, BoardData, CardData, ConnectionData


def big_board() -> BoardData:
    """8 parts × 5 chapters × 25 scenes, chained by arrows; every 5th chapter collapsed."""
    cards, conns, prev = [], [], None
    for o in range(8):
        cards.append(CardData(id=f"O{o}", title=f"Part {o}", kind=KIND_GROUP))
        for g in range(5):
            gi = o * 5 + g
            cards.append(CardData(id=f"G{gi}", title=f"Chapter {gi}", kind=KIND_GROUP, parent=f"O{o}",
                                  collapsed=gi % 5 == 4))
            for k in range(25):
                cid = f"c{gi}_{k}"
                cards.append(CardData(id=cid, title=f"Scene {k}", parent=f"G{gi}", characters=[f"ch{(gi + k) % 30}"],
                                      x=o * 9000 + g * 1800 + (k % 5) * 300, y=(k // 5) * 220))
                if prev:
                    conns.append(ConnectionData(source=prev, target=cid))
                prev = cid
    return BoardData(cards=cards, connections=conns)


def timed(f, n=1) -> float:
    t = time.perf_counter()
    for _ in range(n):
        f()
    return (time.perf_counter() - t) / n * 1000


def test_a_thousand_cards_stay_quick(window, qapp):
    window.card_dock.show()
    s = window.scene
    s.load_board_data(big_board())
    s.reset_history()
    card = s.cards["c0_0"]
    card.setSelected(True)
    qapp.processEvents()
    nudge = timed(lambda: s.nudge_selected(10, 0), 10)
    s.flush_history()
    undo = timed(s.undo)
    assert nudge < 80, f"nudge took {nudge:.0f} ms"      # ~11 ms here
    assert undo < 600, f"undo took {undo:.0f} ms"        # ~120 ms here
    assert not s.cards["c4_0"].isVisible()               # chapter 4 is still folded after undo


def test_undo_puts_the_board_back_if_rebuilding_fails(scene, monkeypatch, settle):
    a = scene.add_card(CardData(title="A"))
    b = scene.add_card(CardData(title="B", x=400))
    scene.add_connection(a, b)
    settle()
    scene.cards[a.card.id].card.title = "A2"
    scene.mark_modified()
    scene.flush_history()
    real = sc.BoardScene.add_connection
    calls = []

    def fail_once(self, *args, **kwargs):
        if not calls:
            calls.append(1)
            raise RuntimeError("simulated")
        return real(self, *args, **kwargs)
    monkeypatch.setattr(sc.BoardScene, "add_connection", fail_once)
    try:
        scene.undo()
    except RuntimeError:
        pass
    assert sorted(i.card.title for i in scene.cards.values()) == ["A2", "B"]   # as before the undo
    assert len(scene.edges) == 1


def test_story_order_is_cached_but_handed_out_as_copies():
    cards = [CardData(id=i, title=i, x=n * 300) for n, i in enumerate("abc")]
    g = StoryGraph(cards, [ConnectionData(source="a", target="b")])
    first = g.arrow_order()
    first.append("junk")
    assert g.arrow_order() == ["a", "b", "c"]
    assert g.arrow_order(["c", "a"]) == ["a", "c"]


def test_the_story_graph_sees_current_positions(scene):
    a = scene.add_card(CardData(title="A", x=0))
    b = scene.add_card(CardData(title="B", x=400))
    assert scene.story_graph().arrow_order() == [a.card.id, b.card.id]
    a.setPos(800, 0)
    scene.mark_modified()
    assert scene.story_graph().arrow_order() == [b.card.id, a.card.id]
