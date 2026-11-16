"""Small fixes from the November 2026 review (A5): the thread's dashed line follows
moved cards, Reverse says why it did nothing, and renaming a strand refits the groups
holding the renamed cards."""
from heddle.model import KIND_GROUP, CardData
from heddle.scene import BoardScene
from tests.conftest import wait_until


def test_the_thread_line_follows_a_moved_card(qapp):
    s = BoardScene()
    a = s.add_card(CardData(title="A", characters=["Greta"]))
    b = s.add_card(CardData(title="B", x=400, characters=["Greta"]))
    s.add_connection(a, b)
    s.show_thread("Greta")
    assert s._thread_line is not None
    b.moveBy(0, 300)
    wait_until(lambda: s._thread_line.path().elementAt(1).y == b.card_scene_rect().center().y())


def test_reversing_onto_an_existing_arrow_says_so(qapp):
    s = BoardScene()
    a = s.add_card(CardData(title="A"))
    b = s.add_card(CardData(title="B", x=400))
    forward = s.add_connection(a, b)
    s.add_connection(b, a)
    said = []
    s.notice.connect(said.append)
    s.reverse_edge(forward)
    assert len(s.edges) == 2
    assert said and "already has an arrow" in said[0]


def test_renaming_a_tag_refits_the_group_around_the_card(qapp):
    s = BoardScene()
    g = s.add_card(CardData(title="G", kind=KIND_GROUP))
    c = s.add_card(CardData(title="C", tags=["x"], x=40, y=80, parent=g.card.id))
    s._refit_ids({g.card.id})
    s.rename_value("tags", "x", "a very long tag name that wraps the pills onto more lines "
                                 "and so makes the card taller than it was")
    assert g.body_scene_rect().contains(c.card_scene_rect())
