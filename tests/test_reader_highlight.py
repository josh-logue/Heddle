"""Review finding B: while the Path Reader is open, an edit mustn't replace someone
else's highlight (a character thread, a path highlight, a story check) or bring
back a highlight cleared with Esc. Taking a step in the reader re-highlights."""
import pytest

from warpingweft.model import CardData
from warpingweft.path_reader import OWNER


@pytest.fixture
def reading(window, qapp):
    """A → B → C, all featuring Mabel, with the reader at A."""
    s = window.scene
    a = s.add_card(CardData(title="A", characters=["Mabel"]))
    b = s.add_card(CardData(title="B", x=400, characters=["Mabel"]))
    c = s.add_card(CardData(title="C", x=800))
    s.add_connection(a, b)
    s.add_connection(b, c)
    s.mark_modified()
    s.reset_history()
    window.read_from(a)
    assert s.highlight_owner() == OWNER
    return window, s, a, b, c


def nudge(s, item):
    s.clearSelection()
    item.setSelected(True)
    s.nudge_selected(10, 0)   # an edit: the reader refreshes on every change


@pytest.mark.parametrize("other", ["thread", "paths", "checks"])
def test_edits_keep_another_highlight(reading, qapp, other):
    window, s, a, b, c = reading
    if other == "thread":
        s.show_thread("Mabel")
    elif other == "paths":
        s.highlight_paths(c)
    else:
        window.checks_dock.show()
        qapp.processEvents()
        panel = window.checks_panel
        panel.recheck()
        panel._on_clicked(panel.tree.topLevelItem(0).child(0))   # the dead end, C
    assert s.highlight_owner() == other
    label = s.highlight_label()
    nudge(s, c)
    assert s.highlight_owner() == other and s.highlight_label() == label
    assert window.path_reader.route == [a.card.id]   # still reading


def test_esc_stays_cleared_after_an_edit(reading):
    window, s, a, b, c = reading
    s.clear_highlight()               # what Esc does
    nudge(s, c)
    assert not s.has_highlight()


def test_a_step_brings_the_readers_highlight_back(reading):
    window, s, a, b, c = reading
    s.show_thread("Mabel")
    assert window.path_reader.next()
    assert s.highlight_owner() == OWNER
    assert {i.card.title for i in s.cards.values() if i.highlight} == {"A", "B"}


def test_the_readers_own_highlight_follows_edits_and_undo(reading):
    window, s, a, b, c = reading
    window.path_reader.next()
    nudge(s, c)
    assert s.highlight_owner() == OWNER
    s.flush_history()
    assert s.undo()
    assert s.highlight_owner() == OWNER
    assert {i.card.title for i in s.cards.values() if i.highlight} == {"A", "B"}
