"""Efficiency review, stage A: with "Curved, avoiding cards" routing, the board re-routes
every arrow only when something could have changed a route (a card moved, resized,
appeared, went or folded away), and only once per change: an edit that moves nothing,
an undo, or a burst of nudges no longer routes the whole board again (or twice)."""
import pytest

from warpingweft.edge_item import AVOID_SAMPLES, EdgeItem
from warpingweft.model import CardData
from conftest import wait_until


def crosses(edge, item) -> bool:
    rect = item.card_scene_rect()
    return any(rect.contains(edge._line.pointAtPercent(k / AVOID_SAMPLES))
               for k in range(AVOID_SAMPLES + 1))


@pytest.fixture
def counted(monkeypatch):
    """Counts full re-routing passes and single-arrow adjustments."""
    import warpingweft.scene as sc
    calls = {"passes": 0, "adjust": 0}
    real_pass, real_adjust = sc.BoardScene.reroute_arrows, EdgeItem.adjust

    def counting_pass(self):
        calls["passes"] += 1
        return real_pass(self)

    def counting_adjust(self):
        calls["adjust"] += 1
        return real_adjust(self)
    monkeypatch.setattr(sc.BoardScene, "reroute_arrows", counting_pass)
    monkeypatch.setattr(EdgeItem, "adjust", counting_adjust)
    return calls


def row_board(scene, n=6):
    """A row of chained cards with a card in the way of the first arrow, avoiding cards."""
    scene._nudge_timer.setInterval(40)    # don't wait the full pauses in tests
    scene._reroute_timer.setInterval(20)
    cards =[scene.add_card(CardData(title=f"C{i}", x=i * 700, y=0)) for i in range(n)]
    edges = [scene.add_connection(a, b) for a, b in zip(cards, cards[1:])]
    blocker = scene.add_card(CardData(title="In the way", x=350, y=-10))
    scene.set_display_option("arrow_routing", "avoid")
    scene.flush_history()
    assert not crosses(edges[0], blocker)
    return cards, edges, blocker


def settled(scene) -> None:
    wait_until(lambda: not scene._reroute_timer.isActive() and not scene._nudge_timer.isActive()
               and not scene.is_moving())


def test_an_edit_that_moves_nothing_does_not_reroute(scene, qapp, counted):
    cards, edges, blocker = row_board(scene)
    settled(scene)
    counted["passes"] = 0
    item = cards[2]
    item.card.status = "Draft"
    item.apply_data(item.card)
    scene.mark_modified()
    settled(scene)
    qapp.processEvents()
    assert counted["passes"] == 0                      # was every arrow, 120 ms later


def test_undo_routes_each_arrow_once(scene, qapp, counted):
    cards, edges, blocker = row_board(scene)
    cards[3].card.title = "Renamed"
    cards[3].apply_data(cards[3].card)
    scene.mark_modified()
    scene.flush_history()
    settled(scene)
    counted["adjust"] = 0
    assert scene.undo()
    settled(scene)
    qapp.processEvents()
    assert counted["adjust"] <= len(scene.edges) + 2     # was twice the arrows
    assert not crosses(scene.edges[0], scene.cards[blocker.card.id])


def test_a_burst_of_nudges_routes_once_when_it_settles(scene, qapp, counted):
    cards, edges, blocker = row_board(scene)
    settled(scene)
    counted["passes"] = 0
    cards[1].setSelected(True)
    for _ in range(3):
        scene.nudge_selected(0, 10)
    settled(scene)
    qapp.processEvents()
    assert counted["passes"] == 1                      # was one mid-burst, wasted, and one after


def test_a_card_moved_away_and_back_is_still_routed_round(scene, qapp):
    cards, edges, blocker = row_board(scene)
    settled(scene)
    b = cards[1]
    scene.begin_move()
    b.moveBy(0, 400)
    b.moveBy(0, -400)                                  # same place: the board looks unchanged
    assert crosses(edges[0], blocker)                  # but its arrow was drawn plainly meanwhile
    scene.end_move()
    settled(scene)
    assert not crosses(edges[0], blocker)


def test_a_card_growing_into_an_arrow_reroutes_it(scene, qapp):
    cards, edges, blocker = row_board(scene)
    settled(scene)
    tall = scene.add_card(CardData(title="Above", x=1050, y=-160))
    scene.mark_modified()
    settled(scene)
    assert not crosses(edges[1], tall)
    tall.card.tags = [f"tag number {n}" for n in range(24)]
    tall.apply_data(tall.card)                         # it grows down across the arrow
    scene.mark_modified()
    settled(scene)
    assert tall.card_scene_rect().bottom() > 40
    assert not crosses(edges[1], tall)


def test_a_click_while_an_edit_waits_still_reroutes(scene, qapp):
    """An edit made during a move that turns out to be a click is routed afterwards."""
    cards, edges, blocker = row_board(scene)
    settled(scene)
    scene.begin_move()
    blocker.setPos(blocker.pos().x(), 600)             # moved by code meanwhile, out of the way
    blocker.setPos(blocker.pos().x(), -10)             # and back in, while "moving"
    scene.mark_modified()
    scene.end_move(moved=False)
    settled(scene)
    assert not crosses(edges[0], blocker)
