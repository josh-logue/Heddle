"""The Path Reader's route ends where an arrow on it was deleted or reversed: it mustn't
go on showing (or exporting) steps that the board no longer joins."""
import pytest

from heddle.model import CardData


@pytest.fixture
def reading(window):
    """A → B → C → D with the reader walked to D."""
    s = window.scene
    items = [s.add_card(CardData(title=t, x=n * 400)) for n, t in enumerate("ABCD")]
    edges = [s.add_connection(items[n], items[n + 1]) for n in range(3)]
    s.mark_modified()
    s.reset_history()
    window.read_from(items[0])
    reader = window.path_reader
    while reader.next():
        pass
    assert reader.route == [i.card.id for i in items]
    return window, s, items, edges


def ids(items):
    return [i.card.id for i in items]


def test_deleting_an_arrow_mid_route_cuts_the_route_there(reading):
    window, s, items, edges = reading
    s.remove_edge(edges[1])                    # B → C
    s.mark_modified()                          # as Delete does after removing
    assert window.path_reader.route == ids(items[:2])
    assert len(window.path_reader.via) == 2
    assert window.path_reader.trail.text() == "A → B"


def test_reversing_an_arrow_mid_route_cuts_the_route_there(reading):
    window, s, items, edges = reading
    s.reverse_edge(edges[2])                   # C → D becomes D → C
    assert window.path_reader.route == ids(items[:3])


def test_an_unrelated_edit_keeps_the_route(reading):
    window, s, items, edges = reading
    s.add_card(CardData(title="Elsewhere", x=3000))
    s.mark_modified()
    assert window.path_reader.route == ids(items)
