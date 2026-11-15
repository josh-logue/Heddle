"""The efficiency changes: batched deletes, shared undo snapshots, zoomed-out drawing,
card pixmap caching and the deferred filter recount, checked for correctness."""
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsItem

import warpingweft.filter_panel as fp_module
from warpingweft import theme
from warpingweft.card_item import LOD_TEXT, LOD_TITLE
from warpingweft.model import CardData


# ----- batched deletion -----------------------------------------------------------------
def test_deleting_nested_groups_together_releases_cards_to_the_surviving_group(scene):
    a = scene.add_card(CardData(title="A"))
    inner = scene.add_card(CardData(title="Inner", kind="group", x=500))
    scene.set_group_members(inner, [a.card.id])
    mid = scene.add_card(CardData(title="Mid", kind="group", x=400))
    scene.set_group_members(mid, [inner.card.id])
    outer = scene.add_card(CardData(title="Outer", kind="group", x=300))
    scene.set_group_members(outer, [mid.card.id])
    scene.remove_cards([inner, mid])                  # both groups, keeping their cards
    assert a.card.parent == outer.card.id and set(scene.cards) == {a.card.id, outer.card.id}
    assert outer.card_scene_rect().contains(a.card_scene_rect())


def test_batched_delete_removes_arrows_and_fixes_reverse_offsets(scene):
    a, b, c = (scene.add_card(CardData(title=t, x=i * 400)) for i, t in enumerate("ABC"))
    ab, ba = scene.add_connection(a, b), scene.add_connection(b, a)
    scene.add_connection(b, c)
    offset_line = ab._line.boundingRect()
    scene.remove_edges([ba])
    assert ab._line.boundingRect() != offset_line      # no longer offset for a reverse arrow
    scene.remove_cards([b])
    assert scene.edges == [] and not a.edges and not c.edges


def test_mass_delete_and_undo(scene, settle):
    cards = [scene.add_card(CardData(title=str(i), x=i * 260)) for i in range(60)]
    for x, y in zip(cards, cards[1:]):
        scene.add_connection(x, y)
    g = scene.add_card(CardData(kind="group", x=-500))
    scene.set_group_members(g, [c.card.id for c in cards[:30]])
    settle()
    before = scene.to_board_data().to_dict()
    scene.remove_cards([g], with_contents=True)
    settle()
    assert len(scene.cards) == 30 and all(e.source.card.id in scene.cards and e.target.card.id in scene.cards
                                          for e in scene.edges)
    scene.undo()
    assert scene.to_board_data().to_dict() == before


# ----- undo snapshots ----------------------------------------------------------------------
def test_unchanged_cards_share_their_snapshot_entry(scene):
    a = scene.add_card(CardData(title="A"))
    scene.add_card(CardData(title="B", x=300))
    s1 = scene._snapshot()
    a.card.title = "A2"
    s2 = scene._snapshot()
    assert s1[0][1] is s2[0][1]                          # B unchanged: the same tuple object
    assert s1[0][0] is not s2[0][0] and s1 != s2
    assert scene._snapshot() == s2


def test_snapshot_round_trips_every_field(scene):
    scene.add_card(CardData(title="T", description="D", tags=["x"], characters=["c"], locations=["l"],
                            status="Draft", notes="N", color="#123456", x=5, y=6))
    g = scene.add_card(CardData(title="G", kind="group", x=-400, arrange_grid=True, arrange_vertical=True))
    g.resize_to(500, 300)
    scene.custom_colors = ["#123456"]
    scene.saved_values = {"tags": ["saved"]}
    state = scene._snapshot()
    assert scene._board_from_snapshot(state).to_dict() == scene.to_board_data().to_dict()


# ----- zoomed-out drawing & caching ---------------------------------------------------------
@pytest.mark.parametrize("zoom", [1.0, (LOD_TEXT + LOD_TITLE) / 2, LOD_TITLE * 0.6])
def test_every_zoom_tier_renders(window, qapp, zoom):
    s = window.scene
    a = s.add_card(CardData(title="A", description="text " * 50, tags=["t"]))
    b = s.add_card(CardData(title="B", x=400))
    s.add_connection(a, b).set_label("a label")
    g = s.add_card(CardData(title="G", kind="group", x=-100, y=-100))
    s.set_group_members(g, [a.card.id])
    a.setSelected(True)
    window.show()
    window.view.reset_zoom()
    window.view.zoom_by(zoom)
    qapp.processEvents()
    assert not window.view.viewport().grab().isNull()


def test_plain_cards_are_cached_groups_are_not(scene):
    card = scene.add_card(CardData())
    assert card.cacheMode() == QGraphicsItem.CacheMode.DeviceCoordinateCache
    card.apply_data(CardData(id=card.card.id, kind="group"))
    assert card.cacheMode() == QGraphicsItem.CacheMode.NoCache


def test_theme_switch_repaints_cached_cards(window, qapp):
    card = window.scene.add_card(CardData(title="A", x=0, y=0))
    window.show()
    window.view.reset_zoom()
    window.view.centerOn(card)
    qapp.processEvents()

    def body_colour():
        p = window.view.mapFromScene(card.mapToScene(card.card_rect().center()))
        return QColor(window.view.viewport().grab().toImage().pixel(p.x(), p.y() + 15))
    first_dark = theme.current().dark
    before = body_colour()
    window.set_dark_mode(not first_dark)
    qapp.processEvents()
    after = body_colour()
    window.set_dark_mode(first_dark)
    assert after != before and after == (theme.DARK if not first_dark else theme.LIGHT).card_bg


# ----- filter recount deferred while hidden -----------------------------------------------
def test_filter_recount_waits_until_the_panel_is_shown(window, qapp, monkeypatch):
    calls = []
    real = fp_module.collect_options
    monkeypatch.setattr(fp_module, "collect_options",
                        lambda *args: calls.append(1) or real(*args))
    s, panel = window.scene, window.filter_panel
    window.show()
    s.add_card(CardData(tags=["late"]))
    s.mark_modified()
    assert calls == []                                    # hidden, no filter: skipped
    window.filter_dock.show()
    qapp.processEvents()
    assert calls and any(k == "late" for k, _, _ in panel._options["tags"])


def test_banner_clears_after_new_board_even_with_panel_hidden(window, qapp, tick_filter):
    s = window.scene
    s.add_card(CardData(tags=["x"]))
    s.add_card(CardData(tags=["y"], x=400))
    s.mark_modified()
    window.show()
    tick_filter(window, "tags", "x")                     # panel is hidden again afterwards
    assert window.filter_banner.isVisible() and not window.filter_dock.isVisible()
    window.setWindowModified(False)
    window.new_board()
    qapp.processEvents()
    assert not window.filter_banner.isVisible() and window.filter_label.text() == ""
