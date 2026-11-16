"""Easy follow-ups: filter counts split into cards and groups, oversized PDF pages
scaled to fit, and a lower minimum zoom."""
import re

from heddle.filters import FilterCounts, describe_counts
from heddle.model import KIND_GROUP, CardData


# ----- filter counts ----------------------------------------------------------------------------
def test_describe_counts():
    assert describe_counts(FilterCounts(2, 17, 1, 5)) == "2 of 17 cards, 1 of 5 groups"
    assert describe_counts(FilterCounts(1, 1, 0, 1)) == "1 of 1 card, 0 of 1 group"
    assert describe_counts(FilterCounts(2, 3)) == "2 of 3 cards"           # no groups: not mentioned
    assert describe_counts(FilterCounts(2, 17, 1, 5), filtered=False) == "17 cards, 5 groups"


def test_filter_shows_cards_and_groups_apart(window, qapp, tick_filter):
    s = window.scene
    red, blue = "#b8475b", "#4a7fc1"
    g1 = s.add_card(CardData(title="Forge", kind=KIND_GROUP, color=red))
    g2 = s.add_card(CardData(title="Ledger", kind=KIND_GROUP, color=blue, x=600))
    s.add_card(CardData(title="Smiths", color=blue, parent=g1.card.id))
    s.add_card(CardData(title="Administration", color=red, x=600, parent=g2.card.id))
    s.add_card(CardData(title="Menagerie", color=red, x=1200))
    s.mark_modified()
    window.show()
    qapp.processEvents()
    tick_filter(window, "color", red)
    counts, active = window._filter_state
    assert active and counts == FilterCounts(2, 3, 1, 2)
    assert window.filter_label.text() == "Filter active: 2 of 3 cards, 1 of 2 groups shown"
    assert "showing 2 of 3 cards, 1 of 2 groups" in window.filter_banner.label.text()
    assert window.filter_panel.summary.text() == "Showing 2 of 3 cards, 1 of 2 groups"


def test_unfiltered_summary_counts_both(window, qapp):
    s = window.scene
    g = s.add_card(CardData(title="G", kind=KIND_GROUP))
    s.add_card(CardData(title="A", parent=g.card.id))
    s.mark_modified()
    window.filter_panel.apply()
    assert window.filter_panel.summary.text() == "1 card, 1 group · no filter"


# ----- PDF page size ------------------------------------------------------------------------------
def test_pdf_page_is_actual_size_until_too_big():
    from heddle.export_image import MAX_PDF_POINTS, pdf_page_size
    small = pdf_page_size(960, 480)                  # 10 × 5 inches
    assert (small.width(), small.height()) == (720, 360)
    huge = pdf_page_size(40000, 10000)
    assert huge.width() == MAX_PDF_POINTS == 14400
    assert abs(huge.height() - 3600) < 1e-6           # same shape


def test_huge_board_exports_a_pdf_readers_can_open(scene, tmp_path):
    from heddle.export_image import export_image
    scene.add_card(CardData(title="West", x=0))
    scene.add_card(CardData(title="East", x=30000))
    path = tmp_path / "wide.pdf"
    export_image(scene, path)
    box = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", path.read_bytes())
    assert box is not None
    w, h = float(box.group(3)), float(box.group(4))
    assert w <= 14400.5 and h <= 14400.5 and w > 10000  # wide, but within the 200-inch limit


# ----- zoom -----------------------------------------------------------------------------------------
def test_zoom_goes_down_to_five_percent(window):
    v = window.view
    for _ in range(60):
        v.zoom_by(0.8)
    assert abs(v.current_scale() - 0.05) < 1e-9


# ----- search flash --------------------------------------------------------------------------------
def test_search_flash_survives_the_card_going_away(window, qapp, monkeypatch):
    """The flash on a search match ends 0.7 s later; if the card was deleted (or the
    board replaced) meanwhile, that used to raise an error."""
    import sys

    from conftest import wait_until
    from heddle import main_window as mw
    from heddle.model import BoardData
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    monkeypatch.setattr(mw, "SEARCH_FLASH_MS", 50)
    s = window.scene
    gone = s.add_card(CardData(title="Gone"))
    window._jump_to_match([(gone, "Title", "Gone")], 0)
    s.load_board_data(BoardData())              # the matched card no longer exists
    kept = s.add_card(CardData(title="Kept"))
    window._jump_to_match([(kept, "Title", "Kept")], 0)
    assert kept._drop_highlight
    wait_until(lambda: not kept._drop_highlight, 2000)  # the surviving card's flash ends
    assert errors == []
