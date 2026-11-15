"""F5: story checks (dead ends, starts, endings, loops, loose cards, routes) and their panel."""

import warpingweft.checks_panel as cp
from conftest import wait_until
from warpingweft import settings
from warpingweft.checks import is_ending, run_checks, summary
from warpingweft.graph import StoryGraph
from warpingweft.model import KIND_GROUP, CardData, ConnectionData


def graph(cards, pairs):
    return StoryGraph(cards, [ConnectionData(s, t, id=f"{s}>{t}") for s, t in pairs])


def card(cid, x=0.0, y=0.0, parent="", group=False, tags=(), status=""):
    return CardData(id=cid, title=cid, x=x, y=y, parent=parent, tags=list(tags), status=status,
                    kind=KIND_GROUP if group else "card")


def kinds(report):
    return {k: [f.cards for f in report.of_kind(k)] for k in
            ("dead_end", "loose_starts", "cycle", "isolated", "start", "ending") if report.of_kind(k)}


# ----- the checks ------------------------------------------------------------------------
def test_chain_with_an_unmarked_end():
    r = run_checks(graph([card("A"), card("B", 300), card("C", 600)], [("A", "B"), ("B", "C")]))
    assert kinds(r) == {"dead_end": [("C",)], "start": [("A",)]}
    assert r.paths.count == 1 and r.warnings == 1
    assert summary(r) == "1 start · 1 end · 1 route · 1 to look at"


def test_marked_endings_are_not_dead_ends():
    cards = [card("A"), card("B", 300, tags=["ending"]), card("C", 300, 300, status="Ending"),
             card("D", 300, 600, tags=["Finale"])]
    pairs = [("A", "B"), ("A", "C"), ("A", "D")]
    r = run_checks(graph(cards, pairs))
    assert kinds(r)["ending"] == [("B",), ("C",)] and kinds(r)["dead_end"] == [("D",)]
    assert run_checks(graph(cards, pairs), ending_word="finale").of_kind("dead_end")[0].cards == ("B",)
    assert is_ending(card("x", tags=["Ending"])) and not is_ending(card("x"), "")


def test_two_openings_into_one_chain_are_flagged():
    cards = [card("A"), card("B", 0, 300), card("M", 300, tags=["Ending"])]
    r = run_checks(graph(cards, [("A", "M"), ("B", "M")]))
    assert kinds(r)["loose_starts"] == [("A", "B")] and r.paths.count == 2
    # Separate chains each with their own start are fine.
    cards = [card("A"), card("B", 300), card("C", 0, 300), card("D", 300, 300)]
    r = run_checks(graph(cards, [("A", "B"), ("C", "D")]))
    assert "loose_starts" not in kinds(r) and kinds(r)["start"] == [("A",), ("C",)]


def test_loops_are_reported():
    cards = [card("S"), card("A", 300), card("B", 600), card("E", 900, tags=["Ending"])]
    r = run_checks(graph(cards, [("S", "A"), ("A", "B"), ("B", "A"), ("B", "E")]))
    assert kinds(r)["cycle"] == [("A", "B")]
    assert r.of_kind("cycle")[0].message == "A → B → A"
    assert r.paths.has_cycles and "plus loops" in summary(r)


def test_cards_without_arrows_on_a_board_with_arrows():
    cards = [card("A"), card("B", 300, tags=["Ending"]), card("Note", 0, 400)]
    r = run_checks(graph(cards, [("A", "B")]))
    assert kinds(r)["isolated"] == [("Note",)] and "dead_end" not in kinds(r)


def test_a_board_without_arrows_has_nothing_to_check():
    r = run_checks(graph([card("A"), card("B", 300)], []))
    assert not r.has_arrows and r.findings == []
    assert summary(r) == "No arrows here, so there's nothing to check."


def test_checking_one_group():
    cards = [card("Out", -500), card("G", group=True), card("P", 0, 60, "G"), card("Q", 300, 60, "G"),
             card("Loose", 0, 300, "G"), card("After", 900), card("Elsewhere", 0, 900)]
    # Out -> P -> Q -> After: inside G, P is entered from outside and Q carries on outside.
    g = graph(cards, [("Out", "P"), ("P", "Q"), ("Q", "After"), ("Elsewhere", "After")])
    r = run_checks(g, scope="G")
    assert kinds(r) == {"isolated": [("Loose",)]}
    assert r.stops == 3


# ----- the panel ------------------------------------------------------------------------------
def board(scene):
    a = scene.add_card(CardData(title="A"))
    b = scene.add_card(CardData(title="B", x=400))
    c = scene.add_card(CardData(title="C", x=800))
    scene.add_connection(a, b)
    scene.add_connection(b, c)
    return a, b, c


def open_panel(window, qapp):
    window.show()
    window.checks_dock.show()
    qapp.processEvents()
    return window.checks_panel


def tops(panel):
    return [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]


def test_panel_lists_results_and_finds_cards(window, qapp):
    a, b, c = board(window.scene)
    panel = open_panel(window, qapp)
    assert tops(panel) == ["⚠  Dead ends (1)", "•  Starts (1)"]
    assert panel.summary.text() == "1 start · 1 end · 1 route · 1 to look at"
    dead = panel.tree.topLevelItem(0).child(0)
    panel._on_clicked(dead)
    s = window.scene
    assert s.highlight_owner() == cp.OWNER and c.highlight and not a.highlight
    assert c.isSelected() and not a.isSelected()
    window.checks_dock.close()
    qapp.processEvents()
    assert not s.has_highlight()


def test_panel_rechecks_after_edits(window, qapp):
    s = window.scene
    a, b, c = board(s)
    panel = open_panel(window, qapp)
    c.card.tags = ["Ending"]
    c.apply_data(c.card)
    s.mark_modified()
    assert panel._timer.isActive()  # the recheck waits for the board to settle...
    wait_until(lambda: not panel._timer.isActive())  # ...however long that takes here
    assert tops(panel) == ["•  Starts (1)", "•  Endings (1)"]
    assert panel.summary.text().endswith("nothing to fix")


def test_panel_scope_and_ending_word(window, qapp):
    s = window.scene
    g = s.add_card(CardData(title="Act One", kind=KIND_GROUP))
    p = s.add_card(CardData(title="P", x=0, y=60, parent=g.card.id))
    s._refit_ids({g.card.id})
    a, b, c = board(s)
    s.add_connection(c, p)                       # the chain ends inside the group
    panel = open_panel(window, qapp)
    scopes = [panel.scope.itemText(i) for i in range(panel.scope.count())]
    assert scopes == ["Whole board", "Group: Act One"]
    panel.scope.setCurrentIndex(1)
    assert [f.cards for f in panel.report.of_kind("dead_end")] == [(p.card.id,)]
    assert panel.report.of_kind("start") == []   # P is entered from outside the group
    panel.ending.setText("Finale")
    panel.ending.editingFinished.emit()
    assert settings.store().value(cp.ENDING_KEY) == "Finale"
    p.card.tags = ["finale"]
    p.apply_data(p.card)
    s.mark_modified()                            # as every edit does
    assert panel.recheck().of_kind("dead_end") == []


def test_board_without_arrows_says_so(window, qapp):
    window.scene.add_card(CardData(title="Lonely"))
    panel = open_panel(window, qapp)
    assert panel.summary.text().startswith("No arrows here") and tops(panel) == []
