"""The fast "who introduces whom" (each loop counted as a single step) must give
exactly the answers of the original, simple-but-slow method, and stay fast on
boards with a big loop. Also: undo works introductions out once, not twice."""
import random
import time

from warpingweft.graph import StoryGraph
from warpingweft.model import CardData, ConnectionData


def reference_introductions(g: StoryGraph) -> dict[str, list[str]]:
    """The original method, kept as the definition to test against: for each card
    featuring a character, walk the graph from every other card featuring them.
    Correct, but slow on loops (the cost grows with the cube of the loop size)."""
    linked = [i for i in g.nodes() if g.succ[i] or g.pred[i]]
    by_key: dict[str, list[str]] = {}
    spelling: dict[tuple[str, str], str] = {}
    for i in linked:
        for name in g.cards[i].characters:
            key = name.casefold()
            if i not in by_key.setdefault(key, []):
                by_key[key].append(i)
            spelling[(i, key)] = name
    loop_of = {i: n for n, comp in enumerate(g.strongly_connected()) if len(comp) > 1 for i in comp}
    rank = {i: n for n, i in enumerate(g.arrow_order())}
    out: dict[str, list[str]] = {}
    for key, cards in by_key.items():
        reached = g._walk(cards, g.succ)
        for c in cards:
            if c in reached:
                if c not in loop_of:
                    continue
                leads_here = [o for o in cards if o != c and c in g._walk([o], g.succ)]
                if any(loop_of.get(o) != loop_of[c] or rank[o] < rank[c] for o in leads_here):
                    continue
            out.setdefault(c, []).append(spelling[(c, key)])
    for c, names in out.items():
        order = {n.casefold(): k for k, n in enumerate(g.cards[c].characters)}
        names.sort(key=lambda n: order.get(n.casefold(), len(order)))
    return out


def random_graph(rnd: random.Random) -> StoryGraph:
    n = rnd.randint(2, 30)
    cast = ["Ailsa", "bran", "Ciar", "DÁITHÍ", "Eimear"]
    cards = [CardData(id=f"c{i}", x=rnd.random() * 2000, y=rnd.random() * 2000,
                      characters=rnd.sample(cast, rnd.randint(0, 3)),
                      pov=rnd.choice(["", "", "Fionn", "ailsa"])) for i in range(n)]
    conns, pairs = [], set()
    for k in range(rnd.randint(0, n * 2)):
        s, t = rnd.randrange(n), rnd.randrange(n)
        if s != t and (s, t) not in pairs:
            pairs.add((s, t))
            conns.append(ConnectionData(f"c{s}", f"c{t}", id=f"e{k}"))
    return StoryGraph(cards, conns)


def test_same_answers_as_the_reference_on_random_boards():
    rnd = random.Random(20261113)
    for _ in range(500):
        g = random_graph(rnd)
        assert g.introductions() == reference_introductions(g)


def looped_board(n: int, cast=("Hero",)) -> StoryGraph:
    """A chain of n cards with a 'back to the hub' arrow from the last to card 15:
    one loop holding most of the board, every card featuring the same character."""
    rnd = random.Random(1)
    extra = [f"C{k}" for k in range(60)]
    cards = [CardData(id=f"c{i}", x=i * 300, y=(i % 7) * 120,
                      characters=list(cast) + rnd.sample(extra, 3)) for i in range(n)]
    conns = [ConnectionData(f"c{i}", f"c{i + 1}", id=f"e{i}") for i in range(n - 1)]
    conns.append(ConnectionData(f"c{n - 1}", "c15", id="back"))
    return StoryGraph(cards, conns)


def test_a_big_loop_stays_fast():
    g = looped_board(500)
    start = time.perf_counter()
    intro = g.introductions()
    elapsed = time.perf_counter() - start
    assert elapsed < 0.25, f"{elapsed * 1000:.0f} ms"   # was ~11 s with the reference method
    assert intro["c0"][0] == "Hero"                     # introduced at the very start
    assert not any("Hero" in names for cid, names in intro.items() if cid != "c0")


def test_undo_works_introductions_out_once(scene, monkeypatch):
    a = scene.add_card(CardData(title="A", characters=["X"]))
    b = scene.add_card(CardData(title="B", x=400, characters=["X"]))
    scene.add_connection(a, b)
    scene.reset_history()
    b.card.characters.append("Y")
    b.apply_data(b.card)
    scene.mark_modified()
    scene.flush_history()
    calls = []
    real = StoryGraph.introductions
    monkeypatch.setattr(StoryGraph, "introductions", lambda self: calls.append(1) or real(self))
    assert scene.undo()
    assert len(calls) == 1
    assert scene.introductions == {a.card.id: ["X"]}   # and still up to date afterwards
