"""Builds the two demo boards in this folder:

* lantern-tide.json: story planning (branches that meet again, nested acts and
  chapters, strands with descriptions, strand cards, a loop, routes, endings,
  notes kept outside the story, and a few Story Checks findings left on purpose).
* hollybank-garden.json: sorting things into groups with no arrows (nested groups,
  each auto-arrange option, colors and strands as categories, a pile to sort and
  an unused strand to drag on).

The content is written here once so the boards can be rebuilt with the same card
ids after the app changes:  .venv\\Scripts\\python.exe examples\\build_demos.py
Groups are auto-arranged in an offscreen scene, as the app would do it, then the
top-level groups are placed side by side.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from warpingweft.model import (  # noqa: E402
    DISPLAY_DEFAULTS, KIND_GROUP, KIND_STRAND, BoardData, CardData, ConnectionData, RouteData,
    StrandInfo, save_board,
)

BLUE, ORANGE, GREEN, RED, PURPLE, TEAL, MUSTARD, GRAY = (
    "#4a7fc1", "#d9822b", "#3f9e6e", "#b8475b", "#7b5ea7", "#2a9aa6", "#c9a227", "#6b6b6b")
GAP = 90  # space between top-level groups


class Builder:
    """Collects cards, arrows and strands with readable ids."""

    def __init__(self) -> None:
        self.cards: list[CardData] = []
        self.arrows: list[ConnectionData] = []
        self.strands: list[StrandInfo] = []

    def card(self, cid: str, title: str, parent: str = "", **fields) -> str:
        self.cards.append(CardData(id=cid, title=title, parent=parent, **fields))
        return cid

    def group(self, cid: str, title: str, parent: str = "", color: str = GRAY, **fields) -> str:
        return self.card(cid, title, parent, kind=KIND_GROUP, color=color, **fields)

    def strand_card(self, cid: str, kind: str, name: str, parent: str = "", color: str = GRAY) -> str:
        return self.card(cid, name, parent, kind=KIND_STRAND, strand_kind=kind, strand=name,
                         color=color)

    def arrow(self, source: str, target: str, label: str = "", **fields) -> None:
        self.arrows.append(ConnectionData(source=source, target=target, label=label,
                                          id=f"{source}>{target}", **fields))

    def describe(self, kind: str, entries: dict[str, str]) -> None:
        self.strands += [StrandInfo(kind=kind, name=n, description=d) for n, d in entries.items()]


# ---------------------------------------------------------------------------
# Lantern Tide: the story-planning demo
# ---------------------------------------------------------------------------
MIRA, TOBIAS, ILSE, HESK, TIDE = ("Mira Fenn", "Tobias Quill", "Captain Ilse Varn", "Old Hesk",
                                  "The Tidewright")
DOCKS, WORKSHOP, HALL, MARKET, ENGINE = ("Merrow Docks", "Hesk's Workshop", "Warden Hall",
                                         "The Drowned Market", "The Lantern Engine")
LOOP = "+".join(sorted(["market", "lost", "bells"]))  # how a route key names the loop

# Card faces show six lines of description, so the tour is a few short cards.
STORY_TIPS = (
    ("tip_checks", "Try: Story Checks",
     "Ctrl+Shift+K. A dead end, two starts, a loop and a card with no arrows are left in on "
     "purpose. Click a finding to find its cards."),
    ("tip_read", "Try: Read a Path",
     "Right-click “The Eleventh Lantern Fails” → Read from here. At each branch, pick a road "
     "by its arrow label."),
    ("tip_routes", "Try: Routes",
     "Ctrl+Shift+O lists every way from a start to an ending. Three routes have names and "
     "notes: expand them with ▸."),
    ("tip_light", "Try: Highlights and Threads",
     "Select a card and press H for what comes before and after it. Ctrl+T follows one "
     "character through the story."),
    ("tip_strands", "Try: Strands",
     "Ctrl+Shift+B lists every character, place and tag, with a description. Click ▸ on a "
     "strand card below to read its description there."),
)


def lantern_tide() -> tuple[BoardData, list[str]]:
    b = Builder()
    # Act I
    b.group("act1", "Act I: The Dimming", color=BLUE)
    b.group("ch1", "Chapter 1: Last Light", "act1", color=BLUE)
    b.card("lantern", "The Eleventh Lantern Fails", "ch1", color=BLUE, pov=MIRA,
           characters=[MIRA, HESK], locations=[DOCKS], tags=["Clue"], status="Final",
           description="Mira is on the docks when the eleventh tide lantern gutters out. "
                       "By dawn the water has risen a hand's width.")
    b.card("warning", "Hesk's Warning", "ch1", color=BLUE, pov=MIRA, characters=[MIRA, HESK],
           locations=[WORKSHOP], status="Revised",
           description="Old Hesk admits the lanterns were never meant to burn forever. Someone "
                       "has been paying for their oil, and has stopped.")
    b.group("ch2", "Chapter 2: The Ledger", "act1", color=BLUE)
    b.card("ledger", "The Stolen Ledger", "ch2", color=BLUE, pov=MIRA, characters=[MIRA],
           locations=[WORKSHOP], tags=["Clue"], status="Draft",
           description="The lamplighters' ledger is gone, and its last page was torn out by "
                       "someone who knew where to look.")
    b.card("coldopen", "Cold Open: The Tideway Run", "ch2", color=TEAL, pov=TOBIAS,
           characters=[TOBIAS], locations=[DOCKS], tags=["Flashback"], status="Draft",
           description="Years earlier, a boy smuggles lantern glass past the Wardens and hears "
                       "a voice in the dark water that knows his name.",
           notes="A second start into the same chain: Story Checks points it out, which is "
                 "fine for a cold open.")
    b.card("offer", "A Smuggler's Offer", "ch2", color=BLUE, pov=MIRA, characters=[MIRA, TOBIAS],
           locations=[DOCKS], status="Draft",
           description="Tobias Quill has the missing ledger page, and wants Mira's lantern key "
                       "in exchange.")
    # Act II: two roads
    b.group("act2", "Act II: Two Roads", color=PURPLE, arrange_vertical=True)  # roads stacked
    b.group("warden", "The Warden's Road", "act2", color=MUSTARD)
    b.card("hall", "The Warden Hall", "warden", color=MUSTARD, pov=MIRA, characters=[MIRA, ILSE],
           locations=[HALL], status="Draft",
           description="Mira takes the ledger to the Tide Wardens. Captain Ilse Varn listens far "
                       "too calmly.",
           notes="Ilse is introduced here only on this road: the ★ is worked out per branch.")
    b.card("test", "Captain Ilse's Test", "warden", color=MUSTARD, pov=MIRA,
           characters=[MIRA, ILSE], locations=[HALL], tags=["Action"], status="Outline",
           description="Ilse will help if Mira can relight a dead lantern alone, at high tide.")
    b.card("archive", "The Locked Archive", "warden", color=MUSTARD, pov=MIRA, characters=[MIRA],
           locations=[HALL], tags=["Clue", "Twist"], status="Outline",
           description="Behind the archive door: oil receipts signed by Ilse, paid to no one "
                       "Mira has heard of.")
    b.card("quarters", "Search Ilse's Quarters", "warden", color=MUSTARD, characters=[MIRA],
           locations=[HALL], status="Idea",
           description="Mira slips into the captain's rooms and finds a map of the Drowned Market.",
           notes="Not placed yet: Story Checks lists it as a dead end until it leads somewhere.")
    b.group("smuggler", "The Smuggler's Road", "act2", color=TEAL)
    b.card("crossing", "Night Crossing", "smuggler", color=TEAL, pov=TOBIAS,
           characters=[TOBIAS, MIRA], tags=["Action"], status="Draft",
           description="Tobias poles Mira through the flooded lanes, past lanterns that have "
                       "already gone dark.")
    b.card("market", "The Drowned Market", "smuggler", color=TEAL, pov=TOBIAS,
           characters=[TOBIAS, MIRA], locations=[MARKET], status="Draft",
           description="Stalls under a foot of seawater, lit by stolen lantern light. Everyone "
                       "here owes someone.")
    b.card("lost", "Lost in the Flooded Lanes", "smuggler", color=TEAL, pov=TOBIAS,
           characters=[TOBIAS, MIRA], tags=["Action"], status="Outline",
           description="A wrong turn. Once the water covers the street names, every lane looks "
                       "the same.")
    b.card("bells", "Follow the Bell-Buoys", "smuggler", color=TEAL, pov=MIRA,
           characters=[MIRA, TOBIAS], status="Idea",
           description="Hesk always said the bell-buoys ring towards the market. He was right, "
                       "which is the problem.",
           notes="This closes a loop back to the market. A loop is one stop on a route.")
    b.card("bargain", "Bargain with the Tidewright", "smuggler", color=TEAL, pov=TOBIAS,
           characters=[TOBIAS, MIRA, TIDE], locations=[MARKET], tags=["Twist"], status="Outline",
           description="Under the market, the Tidewright offers to hold back the sea for one "
                       "more year, for a price.")
    # Act III
    b.group("act3", "Act III: High Water", color=RED)
    b.card("engine", "The Lantern Engine", "act3", color=PURPLE, pov=MIRA,
           characters=[MIRA, TOBIAS, ILSE], locations=[ENGINE], status="Outline",
           description="Both roads end at the machine under the city that feeds the lanterns. "
                       "Its last valve is in Mira's hands.")
    b.card("relight", "Relight Every Lantern", "act3", color=RED, pov=MIRA, characters=[MIRA],
           locations=[ENGINE], status="Ending",
           description="Mira pours the stolen oil back into the engine. Merrow stays dry and "
                       "owes nobody.")
    b.card("flood", "Let the Sea In", "act3", color=RED, pov=MIRA, characters=[MIRA, TOBIAS],
           locations=[ENGINE], status="Ending",
           description="Mira opens the sluices. The city floods slowly enough for everyone to "
                       "leave, and the Tidewright goes hungry.")
    b.card("keep", "Keep the Bargain", "act3", color=RED, pov=TOBIAS, characters=[TOBIAS, TIDE],
           locations=[MARKET], tags=["Ending"], status="Idea",
           description="Tobias pays the Tidewright's price himself. The lanterns burn, and he "
                       "never comes back up.",
           notes="Marked with the tag Ending rather than the status, so it can still say Idea.")
    b.card("festival", "The Festival of Wicks", color=GRAY, locations=[DOCKS], status="Idea",
           description="Every lantern in Merrow lit at once. An opening for book two?",
           notes="No arrows yet, so Story Checks lists it.")
    # Outside the story
    b.group("start", "Start Here", color=GRAY, outside_story=True, arrange_grid=True)
    for cid, title, text in STORY_TIPS:
        b.card(cid, title, "start", color=GRAY, description=text)
    b.group("notes", "World Notes", color=GRAY, outside_story=True)
    b.card("howto", "How the Tide Lanterns Work", "notes", color=GRAY,
           description="Each lantern burns whale-oil pressed with salt. Its light pushes the tide "
                       "back about a street's width; twelve of them keep the old town dry.",
           notes="This group is ticked “Not part of the story”: the dashed outline means its "
                 "cards stay out of checks, routes and introductions.")
    b.card("timeline", "Merrow Timeline", "notes", color=GRAY,
           description="Year 0: the first lantern is lit.  Year 212: the Lantern Engine is "
                       "built.  Year 340: the story starts on the eleventh dark night.")
    b.group("cast", "Cast", color=ORANGE)
    for cid, name in (("s_mira", MIRA), ("s_tobias", TOBIAS), ("s_ilse", ILSE), ("s_hesk", HESK),
                      ("s_tide", TIDE)):
        b.strand_card(cid, "characters", name, "cast", color=ORANGE)
    b.group("map", "Map of Merrow", color=GREEN)
    for cid, name in (("m_docks", DOCKS), ("m_workshop", WORKSHOP), ("m_hall", HALL),
                      ("m_market", MARKET), ("m_engine", ENGINE)):
        b.strand_card(cid, "locations", name, "map", color=GREEN)

    teal = {"color": TEAL}
    for s, t, label, extra in (
        ("lantern", "warning", "", {}), ("warning", "ledger", "", {}), ("ledger", "offer", "", {}),
        ("coldopen", "offer", "years earlier", {"style": "dotted"}),
        ("offer", "hall", "trust the Wardens", {}), ("offer", "crossing", "take Tobias's offer", teal),
        ("hall", "test", "", {}), ("test", "archive", "", {}),
        ("test", "quarters", "optional", {"style": "dashed"}), ("archive", "engine", "", {}),
        ("crossing", "market", "", teal), ("market", "lost", "take the side canal", teal),
        ("lost", "bells", "", teal), ("bells", "market", "back to the market", teal),
        ("market", "bargain", "", teal), ("bargain", "engine", "", teal),
        ("bargain", "keep", "keep your word", teal),
        ("engine", "relight", "relight", {}), ("engine", "flood", "flood the city", {}),
        # Strand cards: a relationship map and a rough map (outside the story).
        ("s_hesk", "s_mira", "mentor", {}), ("s_tobias", "s_tide", "owes a debt", {"style": "dashed"}),
        ("s_ilse", "s_tobias", "hunting him", {}), ("s_mira", "s_tobias", "uneasy allies", {}),
        ("m_docks", "m_workshop", "Lamp Street", {}), ("m_docks", "m_hall", "Grand Canal", {}),
        ("m_docks", "m_market", "sluice tunnel", {"style": "dotted"}),
        ("m_hall", "m_engine", "stairs down", {}), ("m_market", "m_engine", "flooded tunnel", {}),
    ):
        b.arrow(s, t, label, **extra)

    b.describe("characters", {
        MIRA: "Apprentice lamplighter, seventeen. Reads tides the way other people read "
              "handwriting. POV for most of the book.",
        TOBIAS: "Smuggler who knows every flooded lane in Merrow. Owes the Tidewright more "
                "than he admits. POV on the Smuggler's Road.",
        ILSE: "Head of the Tide Wardens. Has kept the lanterns lit for twenty years by paying "
              "for oil nobody asked about.",
        HESK: "Retired lamplighter and Mira's mentor. Knows how the Lantern Engine works and "
              "hopes nobody asks him.",
        TIDE: "Something old that lives under the Drowned Market and trades in light. Never "
              "seen in full.",
    })
    b.describe("locations", {
        DOCKS: "Where the lanterns stand in a line along the sea wall.",
        WORKSHOP: "Hesk's cluttered workshop above the chandlery, smelling of oil and brass.",
        HALL: "The Tide Wardens' headquarters, on the highest ground in the city.",
        MARKET: "A market that kept trading after the sea came in. Reached by boat or tunnel.",
        ENGINE: "The machine under the city that feeds oil to every lantern.",
    })
    b.describe("tags", {
        "Clue": "Something the reader needs to solve the mystery.",
        "Flashback": "Happens before the main story.",
        "Action": "A chase, a fight or a race against the tide.",
        "Twist": "Changes what an earlier scene meant.",
        "Ending": "A deliberate ending: Story Checks doesn't count it as a dead end.",
    })
    b.describe("status", {
        "Ending": "A deliberate ending: Story Checks doesn't count it as a dead end.",
    })

    routes = [
        RouteData(key=["lantern", "warning", "ledger", "offer", "hall", "test", "archive",
                       "engine", "relight"],
                  name="The Warden's Road", status="Draft",
                  notes="Mira trusts the Wardens and finds out who has been paying for the oil."),
        RouteData(key=["lantern", "warning", "ledger", "offer", "crossing", LOOP, "bargain", "keep"],
                  name="The Smuggler's Road", inherit=True,
                  notes="Inherit card strands is on: the route shows every strand its cards have."),
        RouteData(key=["coldopen", "offer", "crossing", LOOP, "bargain", "engine", "flood"],
                  name="The Sea Wins", pov=TOBIAS,
                  notes="Tobias's version of the story, starting from the cold open."),
    ]
    display = dict(DISPLAY_DEFAULTS, show_characters=True, show_no_description=False,
                   arrow_routing="avoid")
    board = BoardData(cards=b.cards, connections=b.arrows, display=display, routes=routes,
                      strands=b.strands)
    arrange = ["ch1", "ch2", "act1", "warden", "smuggler", "act2", "act3", "start", "notes", "cast", "map"]
    return board, arrange


def place_lantern_tide(scene) -> None:
    start = scene.cards["start"].card_scene_rect()
    row = place_row(scene, ["act1", "act2", "act3"], 0, start.height() + GAP)
    move_to(scene, "start", 0, 0)
    move_to(scene, "festival", 0, row + GAP)
    festival = scene.cards["festival"].card_scene_rect()
    place_row(scene, ["notes", "cast", "map"], festival.right() + GAP, row + GAP)


# ---------------------------------------------------------------------------
# Hollybank Community Garden: the organizing demo
# ---------------------------------------------------------------------------
PRIYA, DEV, MARGUERITE, SAM = "Priya", "Dev", "Marguerite", "Sam"
NORTH, SOUTH, GLASS, ORCHARD = "North Plot", "South Plot", "Greenhouse", "Orchard Corner"

GARDEN_TIPS = (
    ("tip_colors", "Colors Are Plant Families",
     "Orange roots, purple brassicas, blue beans and peas, green leaves, red fruit, mustard "
     "herbs, teal water and buildings."),
    ("tip_filter", "Try: Filter",
     "Ctrl+L, then tick the tag Needs Netting or the volunteer Priya: everything else fades."),
    ("tip_drag", "Try: Drag a Strand",
     "Ctrl+Shift+B opens Strands. Drag the tag Frost Tender onto the Chilli, or Marguerite "
     "onto a blank spot for a strand card."),
    ("tip_arrange", "Try: Auto-arrange",
     "Right-click Seed Library → Auto-arrange cards: a grid, one row per color. Each group "
     "has its own options in its editor."),
    ("tip_sort", "Try: Sort the Pile",
     "Drag the plants below into a bed. Let go over a group to add a card to it."),
)


def plant(b: Builder, cid: str, title: str, parent: str, color: str, desc: str, *, tags=(),
          who=(), where=(), status="") -> str:
    return b.card(cid, title, parent, color=color, description=desc, tags=list(tags),
                  characters=list(who), locations=list(where), status=status)


def hollybank_garden() -> tuple[BoardData, list[str]]:
    b = Builder()
    b.group("start", "Start Here", color=GRAY, arrange_vertical=True)
    for cid, title, text in GARDEN_TIPS:
        b.card(cid, title, "start", color=GRAY, description=text)
    # The garden itself: groups and loose cards mixed in one group.
    b.group("garden", "Hollybank Garden 2027", color=GREEN)
    b.group("beds", "Raised Beds", "garden", color=GREEN, locations=[NORTH], arrange_grid=True)
    b.group("bed1", "Bed 1: Roots", "beds", color=ORANGE, arrange_grid=True)
    for cid, title, desc, tags, status in (
        ("carrot", "Carrot 'Nantes'", "Sweet, stump-ended. Thin to 5 cm.", ["Spring Sow"], "Growing"),
        ("beet", "Beetroot 'Boltardy'", "Doesn't bolt in a dry spell.", ["Spring Sow"], "Growing"),
        ("parsnip", "Parsnip", "Slow to come up: mark the row.", ["Spring Sow"], "Sown"),
        ("radish", "Radish 'French Breakfast'", "Ready in four weeks. Sow every fortnight.",
         ["Spring Sow", "Summer Sow"], "Harvesting"),
    ):
        plant(b, cid, title, "bed1", ORANGE, desc, tags=tags, who=[DEV], where=[NORTH], status=status)
    b.group("bed2", "Bed 2: Brassicas", "beds", color=PURPLE, arrange_grid=True)
    for cid, title, desc, tags, status in (
        ("kale", "Kale 'Nero di Toscana'", "Pick the lower leaves all winter.",
         ["Summer Sow", "Needs Netting"], "Growing"),
        ("psb", "Purple Sprouting Broccoli", "Crops in March, when little else does.",
         ["Summer Sow", "Needs Netting"], "Growing"),
        ("cabbage", "Red Cabbage", "Pigeons love it.", ["Spring Sow", "Needs Netting"], "Growing"),
        ("kohlrabi", "Kohlrabi", "Harvest at tennis-ball size.", ["Summer Sow"], "Sown"),
    ):
        plant(b, cid, title, "bed2", PURPLE, desc, tags=tags, who=[PRIYA], where=[NORTH],
              status=status)
    b.group("bed3", "Bed 3: Beans & Peas", "beds", color=BLUE, arrange_grid=True)
    for cid, title, desc, tags, status in (
        ("runner", "Runner Beans", "Up the bamboo wigwams. Pick often.",
         ["Summer Sow", "Pollinator Friendly"], "Growing"),
        ("peas", "Sugar Snap Peas", "Eat them in the garden.", ["Spring Sow"], "Harvesting"),
        ("broad", "Broad Beans 'Aquadulce'", "Sown in November, cropping in June.",
         ["Autumn Sow", "Pollinator Friendly"], "Resting"),
    ):
        plant(b, cid, title, "bed3", BLUE, desc, tags=tags, who=[SAM], where=[NORTH], status=status)
    b.group("bed4", "Bed 4: Salad", "beds", color=GREEN, arrange_grid=True)
    for cid, title, desc, tags, status in (
        ("lettuce", "Lettuce Mix", "Cut and come again.", ["Spring Sow", "Summer Sow"], "Harvesting"),
        ("rocket", "Rocket", "Bolts in the heat: sow in shade.", ["Summer Sow"], "Growing"),
        ("spinach", "Spinach", "Under fleece in winter.", ["Autumn Sow"], "Sown"),
        ("chard", "Rainbow Chard", "Stems in five colors.", ["Spring Sow"], "Growing"),
    ):
        plant(b, cid, title, "bed4", GREEN, desc, tags=tags, who=[PRIYA], where=[NORTH],
              status=status)
    # The greenhouse sorts itself into one row per color: fruit, leaves, herbs.
    b.group("glass", "Greenhouse", "garden", color=RED, locations=[GLASS], arrange_by_color=True)
    for cid, title, color, desc, tags in (
        ("tomato", "Tomato 'Sungold'", RED, "Orange cherry tomatoes. Pinch out side shoots.",
         ["Spring Sow"]),
        ("cucumber", "Cucumber 'Marketmore'", GREEN, "Keep the roots warm and the leaves damp.",
         ["Spring Sow"]),
        ("chilli", "Chilli 'Hungarian Wax'", RED, "Mild, then hot as they redden.", ["Spring Sow"]),
        ("basil", "Basil", MUSTARD, "Next to the tomatoes. Water in the morning.", ["Summer Sow"]),
        ("aubergine", "Aubergine", RED, "Needs every sunny day it can get.", ["Spring Sow"]),
    ):
        plant(b, cid, title, "glass", color, desc, tags=tags, who=[SAM], where=[GLASS],
              status="Growing")
    b.group("herbs", "Herb Spiral", "garden", color=MUSTARD, locations=[SOUTH],
            arrange_vertical=True)
    for cid, title, desc, tags in (
        ("thyme", "Thyme", "At the dry top of the spiral.", ["Perennial", "Pollinator Friendly"]),
        ("rosemary", "Rosemary", "Cut back after flowering.", ["Perennial", "Pollinator Friendly"]),
        ("sage", "Sage", "Replace every four years.", ["Perennial"]),
        ("chives", "Chives", "Purple flowers in May.", ["Perennial", "Pollinator Friendly"]),
        ("mint", "Mint", "In a sunken pot, or it takes over.", ["Perennial"]),
    ):
        plant(b, cid, title, "herbs", MUSTARD, desc, tags=tags, who=[MARGUERITE], where=[SOUTH])
    for cid, title, desc, who, where, tags in (
        ("compost", "Compost Bays", "Three bays: filling, rotting, ready.", [DEV], [SOUTH], []),
        ("barrels", "Rain Barrels", "Four butts off the shed roof.", [DEV], [SOUTH], []),
        ("shed", "Tool Shed", "Code on the noticeboard.", [], [SOUTH], []),
        ("beehotel", "Bee Hotel", "Hollow stems, south-facing.", [], [ORCHARD],
         ["Pollinator Friendly"]),
    ):
        plant(b, cid, title, "garden", TEAL, desc, tags=tags, who=who, where=where)
    # Left unarranged: auto-arrange sorts it into color rows.
    b.group("seeds", "Seed Library", color=GRAY, arrange_grid=True, arrange_by_color=True,
            characters=[MARGUERITE])
    seeds = (
        ("s_squash", "Seed: Squash 'Crown Prince'", RED, ["Spring Sow"]),
        ("s_kale", "Seed: Kale 'Red Russian'", PURPLE, ["Summer Sow"]),
        ("s_coriander", "Seed: Coriander", MUSTARD, ["Spring Sow", "Summer Sow"]),
        ("s_carrot", "Seed: Carrot 'Autumn King'", ORANGE, ["Spring Sow"]),
        ("s_bean", "Seed: French Bean 'Cobra'", BLUE, ["Summer Sow"]),
        ("s_lettuce", "Seed: Lettuce 'Little Gem'", GREEN, ["Spring Sow", "Summer Sow"]),
        ("s_pakchoi", "Seed: Pak Choi", PURPLE, ["Summer Sow"]),
        ("s_tomato", "Seed: Tomato 'Gardener's Delight'", RED, ["Spring Sow"]),
        ("s_pea", "Seed: Pea 'Kelvedon Wonder'", BLUE, ["Spring Sow"]),
        ("s_beet", "Seed: Beetroot 'Chioggia'", ORANGE, ["Spring Sow"]),
    )
    for cid, title, color, tags in seeds:
        b.card(cid, title, "seeds", color=color, tags=tags, status="Planned")
    b.group("jobs", "Jobs This Month", color=GRAY, arrange_vertical=True, arrange_grid=True)
    for cid, title, color, desc, who, tags in (
        ("j_net", "Net the brassicas", PURPLE, "Pigeons have found Bed 2.", [PRIYA], ["Urgent"]),
        ("j_compost", "Turn the compost", TEAL, "Move bay 1 into bay 2.", [DEV], ["When Dry"]),
        ("j_salad", "Sow the next salad row", GREEN, "Every three weeks until September.",
         [PRIYA], ["This Week"]),
        ("j_tap", "Fix the rain barrel tap", TEAL, "It drips. Washer in the shed.", [DEV, SAM],
         ["This Week"]),
        ("j_label", "Label the seed library", GRAY, "New envelopes in the shed.", [MARGUERITE],
         ["When Dry"]),
        ("j_pinch", "Pinch out the tomatoes", RED, "Side shoots, twice a week.", [SAM],
         ["This Week"]),
    ):
        plant(b, cid, title, "jobs", color, desc, tags=tags, who=who)
    b.group("people", "Who's Who", color=GRAY)
    for cid, name in (("p_priya", PRIYA), ("p_dev", DEV), ("p_marguerite", MARGUERITE),
                      ("p_sam", SAM)):
        b.strand_card(cid, "characters", name, "people", color=GRAY)
    # A pile still to sort, next to the Start Here card.
    for n, (cid, title, color, desc, tags) in enumerate((
        ("strawb", "Strawberries", RED, "Runners from Priya's plot.", ["Perennial"]),
        ("garlic", "Garlic 'Germidour'", ORANGE, "Plant before Christmas.", ["Autumn Sow"]),
        ("sunflower", "Sunflowers", MUSTARD, "For the bees, and the children.",
         ["Spring Sow", "Pollinator Friendly"]),
        ("pumpkin", "Pumpkin 'Jack Be Little'", RED, "Tiny pumpkins for the harvest fair.",
         ["Summer Sow"]),
    )):
        b.card(cid, title, color=color, description=desc, tags=tags, status="Planned",
               x=20 + (n % 2) * 150 + n * 8, y=(n // 2) * 70 + n * 12)

    b.describe("characters", {
        PRIYA: "Runs the Tuesday session. Looks after the brassicas and the salad bed.",
        DEV: "Compost, water and anything with a spanner. Mostly Saturdays.",
        MARGUERITE: "Keeps the seed library and the herb spiral. Knows every plant's Latin name.",
        SAM: "Greenhouse and beans. Brings the children's club on Thursdays.",
    })
    b.describe("locations", {
        NORTH: "The four raised beds by the gate: full sun, heavy soil.",
        SOUTH: "Herbs, compost and the shed, against the south wall.",
        GLASS: "The glasshouse donated by the allotment society. Unheated.",
        ORCHARD: "Six old apple trees and the bee hotel.",
    })
    b.describe("tags", {
        "Spring Sow": "Sow between March and May.",
        "Summer Sow": "Sow between June and August.",
        "Autumn Sow": "Sow or plant between September and November, to overwinter.",
        "Perennial": "Comes back every year: don't dig it up.",
        "Needs Netting": "Pigeons or butterflies will eat it: keep it under net.",
        "Pollinator Friendly": "Flowers bees and hoverflies visit.",
        "Frost Tender": "Bring it in, or fleece it, below 5 °C. Not on any card yet: drag it "
                        "from Strands onto the plants that need it.",
        "Urgent": "Do this before anything else.",
        "This Week": "Should be done by Sunday.",
        "When Dry": "Wait for a dry day.",
    })
    b.describe("status", {
        "Planned": "On the list, not sown yet.",
        "Sown": "In the ground, not up yet.",
        "Growing": "Up and growing.",
        "Harvesting": "Ready to pick.",
        "Resting": "Overwintering, or between crops.",
    })
    display = dict(DISPLAY_DEFAULTS, story_tools=False, show_handles=False, show_pov=False,
                   show_characters=True, show_no_description=False)
    board = BoardData(cards=b.cards, connections=b.arrows, display=display, strands=b.strands,
                      saved_values={"tags": ["Frost Tender"]})
    arrange = ["bed1", "bed2", "bed3", "bed4", "beds", "glass", "herbs", "garden", "jobs", "people", "start"]
    return board, arrange


def place_hollybank_garden(scene) -> None:
    start = scene.cards["start"].card_scene_rect()
    place_row(scene, ["garden", "seeds", "jobs"], start.right() + GAP, 0)
    jobs = scene.cards["jobs"].card_scene_rect()
    move_to(scene, "people", jobs.left(), jobs.bottom() + GAP)
    # The seed packets keep their shuffled spots; the pile sits under Start Here.
    pile = ["strawb", "garlic", "sunflower", "pumpkin"]
    top = start.bottom() + GAP
    for n, cid in enumerate(pile):
        move_to(scene, cid, 10 + (n % 2) * 40 + n * 6, top + n * 85)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------
def move_to(scene, cid: str, x: float, y: float) -> None:
    item = scene.cards[cid]
    rect = item.card_scene_rect()
    item.setPos(item.pos().x() + x - rect.x(), item.pos().y() + y - rect.y())


def place_row(scene, ids: list[str], x: float, y: float) -> float:
    """Top-level groups side by side from (x, y); returns the bottom of the row."""
    bottom = y
    for cid in ids:
        move_to(scene, cid, x, y)
        scene._refit_ids({cid})
        rect = scene.cards[cid].card_scene_rect()
        x = rect.right() + GAP
        bottom = max(bottom, rect.bottom())
    return bottom


def scatter_seeds(scene) -> None:
    """Seed packets in a deliberately untidy jumble, so auto-arrange visibly sorts them."""
    spots = [(0, 0), (250, 30), (510, -10), (40, 120), (300, 150), (560, 110), (10, 250),
             (270, 280), (530, 240), (150, 380)]
    group = scene.cards["seeds"]
    members = [m for m in scene.members_of(group)]
    ox = group.pos().x() + 22
    oy = group.pos().y() + group.header_area_height() + 22
    for m, (dx, dy) in zip(members, spots):
        m.setPos(ox + dx, oy + dy + 10)
    scene._refit_ids({"seeds"})


def build(board: BoardData, arrange: list[str], place, path: Path, extra=None) -> BoardData:
    from PySide6.QtWidgets import QApplication

    from warpingweft.scene import BoardScene

    QApplication.instance() or QApplication([])
    scene = BoardScene()
    scene.load_board_data(board)
    for gid in arrange:
        scene.auto_arrange_group(scene.cards[gid])
    if extra:
        extra(scene)
    place(scene)
    scene._refit_ids({cid for cid, item in scene.cards.items() if item.is_group})
    out = scene.to_board_data()
    save_board(out, path)
    return out


def main() -> None:
    board, arrange = lantern_tide()
    build(board, arrange, place_lantern_tide, HERE / "lantern-tide.json")
    board, arrange = hollybank_garden()
    build(board, arrange, place_hollybank_garden, HERE / "hollybank-garden.json",
          extra=scatter_seeds)
    print("Wrote", HERE / "lantern-tide.json", "and", HERE / "hollybank-garden.json")


if __name__ == "__main__":
    main()
