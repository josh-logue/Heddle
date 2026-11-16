"""Filter panel: each multi-value category (tags, characters, introductions,
locations) has a "match any / match all" switch in its heading, remembered per machine."""
from heddle.filter_panel import MATCH_ALL_KEY, FilterPanel
from heddle.model import CardData
from heddle import settings


def _board(window):
    """Two cards, counted into the panel (it recounts when the board reports an edit)."""
    scene = window.scene
    both = scene.add_card(CardData(title="Both", tags=["Act 1", "Act 2"], characters=["Mara"],
                                   locations=["Dock", "Mill"]))
    one = scene.add_card(CardData(title="One", tags=["Act 1"], characters=["Rowan"],
                                  locations=["Dock"], x=300))
    window.show()
    window.filter_dock.show()
    window.filter_panel.refresh()
    return both, one


def test_heading_switch_for_multi_value_categories_only(window, scene, tick_filter):
    _board(window)
    buttons = window.filter_panel.mode_buttons
    assert set(buttons) == {"tags", "characters", "introduces", "locations"}  # not colour, POV, status
    assert all(b.text() == "match any" and not b.isChecked() for b in buttons.values())


def test_match_all_tags_dims_cards_missing_one(window, scene, tick_filter, qapp):
    both, one = _board(window)
    tick_filter(window, "tags", "act 1", keep_open=True)
    tick_filter(window, "tags", "act 2", keep_open=True)
    assert not both.dimmed and not one.dimmed                     # any: both shown
    window.filter_panel.mode_buttons["tags"].click()               # the user clicks the heading
    assert window.filter_panel.match_all() == {"tags"}
    assert window.filter_panel.mode_buttons["tags"].text() == "match all"
    assert not both.dimmed and one.dimmed
    assert "every ticked entry in tags" in window.filter_panel.hint.text()
    assert "all tags" in window.filter_banner.label.text()
    window.filter_panel.mode_buttons["tags"].click()
    assert not one.dimmed and "all tags" not in window.filter_banner.label.text()


def test_modes_mix_across_categories(window, scene, tick_filter):
    """All of these tags, but any of these characters."""
    both, one = _board(window)
    for key in ("act 1", "act 2"):
        tick_filter(window, "tags", key, keep_open=True)
    for key in ("mara", "rowan"):
        tick_filter(window, "characters", key, keep_open=True)
    window.filter_panel.set_match_all("tags", True)
    assert not both.dimmed and one.dimmed
    window.filter_panel.set_match_all("characters", True)
    assert both.dimmed and one.dimmed                              # nobody has Mara and Rowan


def test_banner_names_match_all_only_where_it_matters(window, scene, tick_filter):
    _board(window)
    window.filter_panel.set_match_all("tags", True)
    tick_filter(window, "tags", "act 1", keep_open=True)
    assert window.filter_panel.match_note() == ""                  # one tick: all = any
    tick_filter(window, "tags", "act 2", keep_open=True)
    assert window.filter_panel.match_note() == "all tags"


def test_mode_survives_recounting_and_a_new_board(window, scene, tick_filter, qapp):
    _board(window)
    window.filter_panel.set_match_all("locations", True)
    scene.add_card(CardData(title="New", tags=["Act 3"], x=900))   # new option: tree rebuilt
    scene.mark_modified()
    qapp.processEvents()
    window.filter_panel.refresh()
    assert window.filter_panel.mode_buttons["locations"].isChecked()
    window.filter_panel.reset()                                    # e.g. another board opened
    assert window.filter_panel.match_all() == {"locations"}


def test_remembered_per_machine(window, scene, qapp):
    window.filter_panel.set_match_all("tags", True)
    window.filter_panel.set_match_all("introduces", True)
    assert settings.store().value(MATCH_ALL_KEY) == "tags,introduces"
    other = FilterPanel(scene)
    assert other.match_all() == {"tags", "introduces"}
    other.deleteLater()
    settings.store().setValue(MATCH_ALL_KEY, "tags,status,bogus")  # only real multi-value ones
    third = FilterPanel(scene)
    assert third.match_all() == {"tags"}
    third.deleteLater()
