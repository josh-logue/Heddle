"""Repeated titles name their group wherever cards are listed ("Warden · East
Ward"), so three Wardens in three groups can be told apart."""
from warpingweft.checks import run_checks
from warpingweft.graph import StoryGraph
from warpingweft.model import KIND_GROUP, CardData, title_labels
from warpingweft.routes import steps_text


def three_years():
    cards = []
    for year in ("East Ward", "North Ward", "West Ward"):
        g = CardData(title=year, kind=KIND_GROUP)
        cards += [g, CardData(title="Warden", parent=g.id), CardData(title=f"{year} only", parent=g.id)]
    cards.append(CardData(title="warden"))           # same title, different case, no group
    return cards


def test_repeated_titles_name_their_group_and_unique_ones_stay_bare():
    cards = three_years()
    labels = title_labels(cards)
    wardens = sorted(labels[c.id] for c in cards if c.title == "Warden")
    assert wardens == ["Warden · East Ward", "Warden · North Ward", "Warden · West Ward"]
    assert labels[next(c.id for c in cards if c.title == "East Ward only")] == "East Ward only"
    assert labels[cards[-1].id] == "warden"          # top level: nothing to add


def test_routes_steps_use_the_labels():
    cards = three_years()
    by_id = {c.id: c for c in cards}
    a = next(c for c in cards if c.title == "Warden")
    b = next(c for c in cards if c.title == "East Ward only")
    labels = title_labels(cards)
    assert steps_text((a.id, b.id), by_id, labels=labels) == ["Warden · East Ward", "East Ward only"]
    assert steps_text((a.id, b.id), by_id) == ["Warden", "East Ward only"]   # export: bare


def test_story_checks_name_the_group(qapp):
    from warpingweft.model import ConnectionData
    cards = three_years()
    first, second = (next(c for c in cards if c.title == "Warden" and c.parent == g.id)
                     for g in cards[0:6:3])
    report = run_checks(StoryGraph(cards, [ConnectionData(source=first.id, target=second.id)]))
    titles = " ".join(f.message for f in report.findings)
    assert "Warden · East Ward" in titles


def test_the_path_reader_and_search_name_the_group(window, qapp):
    s = window.scene
    groups = [s.add_card(CardData(title=y, kind=KIND_GROUP, x=n * 800)) for n, y in
              enumerate(("East Ward", "North Ward"))]
    a = s.add_card(CardData(title="Warden", x=40, y=80, parent=groups[0].card.id))
    b = s.add_card(CardData(title="Warden", x=840, y=80, parent=groups[1].card.id))
    s.add_connection(a, b)
    s.mark_modified()
    window.read_from(a)
    assert window.path_reader._choice_buttons[0].text() == "→ Warden · North Ward"
    window.search_bar.edit.setText("Warden")
    window._search_step(1)
    assert "in “East Ward”" in window.statusBar().currentMessage() or \
        "in “North Ward”" in window.statusBar().currentMessage()
