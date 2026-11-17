"""Shared fixtures: what the Python core answers for a set of boards, so the TypeScript
port (web/src/core) can be checked against it.

For each input board (the demo boards, small purpose-made ones, deliberately broken
files and seeded random ones) this records the cleaned board, graph flow, story order,
loops, routes, introductions, checks, filters, search, auto-arrange positions and the
Markdown export. web/tests/fixtures.test.ts runs the same inputs through the port and
must get the same results; tests/test_web_fixtures.py fails when these files are out of
date with the Python core.

Run from the repository root:  python web/fixtures/build_fixtures.py
"""
from __future__ import annotations

import copy
import json
import random
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heddle import checks, export, filters, layout, model, routes  # noqa: E402
from heddle.graph import StoryGraph  # noqa: E402

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"


class FixedIds:
    """Made-up ids ("new1", "new2", ...) in place of random ones while a case is built, so
    the results can be compared. The TypeScript tests use model.setIdMaker the same way.
    model.new_id is uuid.uuid4().hex[:12], looked up when it runs, so swapping the uuid
    module it sees reaches the dataclasses' default factories too."""

    def __init__(self):
        self.n = 0
        self.saved = model.uuid

    def __enter__(self):
        def uuid4():
            self.n += 1
            return SimpleNamespace(hex=f"new{self.n}")
        model.uuid = SimpleNamespace(uuid4=uuid4)
        return self

    def __exit__(self, *exc):
        model.uuid = self.saved


# ----- inputs -------------------------------------------------------------------------------

def demo_boards() -> dict[str, dict]:
    return {f"demo-{p.stem}": json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((ROOT / "examples").glob("*.json"))}


def card(cid, title=None, x=0.0, y=0.0, **kw):
    return {"id": cid, "title": cid if title is None else title, "x": x, "y": y, **kw}


def arrow(s, t, label="", cid=None):
    return {"id": cid or f"{s}>{t}", "source": s, "target": t, "label": label}


def small_boards() -> dict[str, dict]:
    """Shapes from the Python graph tests, plus text edge cases."""
    def board(cards, arrows=(), **kw):
        return {"app": "Heddle", "version": model.FORMAT_VERSION, "cards": list(cards),
                "connections": list(arrows), **kw}

    return {
        "chain": board([card("A"), card("B", x=300), card("C", x=600)], [arrow("A", "B"), arrow("B", "C")]),
        "branch-merge": board(
            [card("A"), card("B", x=300, y=200), card("C", x=300), card("D", x=600)],
            [arrow("A", "B", "if she refuses"), arrow("A", "C"), arrow("B", "D"), arrow("C", "D")]),
        "cycle": board([card("A"), card("B", x=300), card("C", x=600), card("D", x=900, status="Ending")],
                       [arrow("A", "B"), arrow("B", "C"), arrow("C", "A"), arrow("C", "D")]),
        "group-flow": board(
            [card("X"), card("G", x=200, kind="group"), card("P", x=220, y=50, parent="G"),
             card("Q", x=520, y=50, parent="G"), card("Y", x=900)],
            [arrow("X", "G"), arrow("P", "Q"), arrow("G", "Y")]),
        "group-markers": board(
            [card("X"), card("G", x=200, kind="group"), card("P", x=220, y=50, parent="G"),
             card("Q", x=520, y=50, parent="G"), card("R", x=520, y=250, parent="G"), card("Y", x=900)],
            [arrow("X", "G"), arrow("G", "Q"), arrow("Q", "P"), arrow("R", "G"), arrow("G", "Y")]),
        "nested-groups": board(
            [card("X"), card("G", x=200, kind="group"), card("H", x=220, kind="group", parent="G"),
             card("P", x=240, y=20, parent="H"), card("Q", x=600, parent="G"), card("Y", x=1000)],
            [arrow("X", "G"), arrow("P", "Q"), arrow("G", "Y")]),
        "group-loop": board(
            [card("X"), card("G", x=200, kind="group"), card("P", x=220, parent="G"),
             card("Q", x=220, y=300, parent="G")],
            [arrow("X", "G"), arrow("P", "Q"), arrow("Q", "P")]),
        "empty-group": board([card("A"), card("E", x=300, kind="group"), card("B", x=600)],
                             [arrow("A", "E"), arrow("E", "B")]),
        # Groups six deep: headings stop at ######, outline indents keep going.
        "deep-nesting": board(
            [card(f"G{k}", f"Level {k}", x=k * 20, y=k * 20, kind="group", parent=f"G{k - 1}" if k > 1 else "")
             for k in range(1, 7)]
            + [card(f"P{k}", f"Page {k}", x=k * 20 + 5, y=k * 20 + 300, parent=f"G{k}", description=f"Deep {k}")
               for k in range(1, 7)],
            [arrow(f"P{k}", f"P{k + 1}") for k in range(1, 6)] + [arrow("G6", "P6")]),
        "no-arrows": board([card("B", x=300), card("A"), card("C", y=200)]),
        "bad-arrows": board([card("A"), card("B", x=300)],
                            [arrow("A", "B", cid="1"), arrow("A", "B", cid="2"), arrow("A", "A", cid="3"),
                             arrow("A", "zzz", cid="4")]),
        "outside-story": board(
            [card("A"), card("B", x=300, outside_story=True), card("C", x=600),
             card("M", x=0, y=400, kind="group"),
             card("S", x=20, y=450, parent="M", kind="strand", strand_kind="locations", strand="Harbour")],
            [arrow("A", "B"), arrow("A", "C"), arrow("S", "C")]),
        "introductions": board(
            [card("A", characters=["Rowan"]), card("B", x=300, y=-100, characters=["Mabel", "rowan"]),
             card("C", x=300, y=100, characters=["Greta"], pov="Greta"),
             card("D", x=600, characters=["Mabel", "Greta", "Warden"])],
            [arrow("A", "B"), arrow("A", "C"), arrow("B", "D"), arrow("C", "D"), arrow("D", "B")]),
        "text-edge-cases": board(
            [card("t1", "Straße * _intro_ #1", description="Line one\nline   two three",
                  tags=["ß-tag", "SS-TAG", "Ärger", "7", "2024", "10"], characters=["ΣΊΣΥΦΟΣ", "σίσυφοσ", "Zoë"],
                  notes="> quoted\n\n- list\r\nend\x85after", status="Ending"),
             card("t2", "  [Warden]  ", x=300, description="emoji 🌊 tide 🌊 again", tags=["10", "7", "ﬁre"],
                   characters=["😀 Smiley", "Ångström"], locations=["East Ward", "east ward", "West <Ward>"]),
             card("t3", "", x=600, description="\t\v\f\x1c\x1d spaced 　 out \xa0 ", pov="Mabel",
                  characters=["mabel"], status="draft"),
             card("t4", "[Warden]", x=900, parent="", tags="a, b ,, A"),
             card("t5", "Ωmega", x=1200, characters=["İstanbul", "ǅemal"], tags=["Ꭰ", "ꭰ"])],
            [arrow("t1", "t2", "via the *tide* | maybe"), arrow("t2", "t3"), arrow("t2", "t4", "or [not]"),
             arrow("t4", "t5")],
            saved_values={"tags": ["Saved", "saved", "9"], "locations": ["Harbour"], "bogus": ["x"]},
            strands=[{"kind": "characters", "name": "Zoë", "description": "Keeper of the tide lamp",
                      "fields": [{"name": "Age", "value": "41"}, {"name": "age", "value": "x"},
                                 {"name": "Home", "value": "Line\nbreak"}]},
                     {"kind": "tags", "name": "7", "picture": "pics/seven.png"}],
            strand_groups=[{"kind": "characters", "name": "Kin", "members": ["zoë", "Mabel", "Keeper", "MABEL"],
                            "description": "Grouped"},
                           {"kind": "locations", "name": "Wards", "members": ["east ward", "North Ward"]},
                           {"kind": "tags", "name": "Empty"}],
            routes=[{"key": ["t1", "t2", "t3"], "name": "Short way", "tags": ["x"]},
                    {"key": ["t1", "gone"], "name": "Lost route"}]),
    }


def broken_boards() -> dict[str, dict]:
    """Damaged and hand-edited files: every value coerced, nothing crashes. Cards get
    different positions: the Python core orders cards at the very same spot by set order,
    which changes from run to run."""
    return {
        "broken-values": {
            "cards": [
                {"id": None, "title": 7, "description": None, "color": "red", "status": ["x"],
                 "notes": {"a": 1}, "parent": 3, "x": "12", "y": None, "width": -5, "height": True,
                 "tags": None, "kind": None, "arrange_by_color": "false", "arrange_vertical": 1,
                 "arrange_grid": "yes", "arrange_wrap": 250, "collapsed": True},
                {"id": "g", "x": 100, "kind": "group", "collapsed": True, "arrange_wrap": 3.7, "width": 400.5,
                 "color": " #ABCDEF "},
                {"id": "s", "x": 200, "kind": "strand", "strand_kind": "nonsense", "title": "  Harbour  ",
                 "description": "dropped", "tags": ["dropped"], "outside_story": True},
                {"id": "s2", "x": 300, "kind": "strand", "strand": " Rowan ", "strand_kind": "characters"},
                {"id": "p", "x": 400, "pov": "Rowan", "characters": "mabel, ROWAN", "kind": "mystery"},
                "not a card", 5, [1, 2],
            ],
            "connections": [{"source": "g", "target": "p", "style": "wavy", "color": "#ABCDEF",
                             "label": 12, "id": ""},
                            {"source": "p"}, "junk", {"source": None, "target": 5, "id": "n"}],
            "custom_colors": ["#123456", "red", 5, "#4A7FC1", " #123456"],
            "saved_values": {"tags": "x, y", "characters": [3, "A"], "status": None},
            "display": {"show_grid": False, "show_pov": "yes", "arrow_routing": "zigzag", "nope": True},
            "routes": [{"key": "p"}, {"key": ["p", " ", 4]}, {"key": ["p"], "inherit": True},
                       {"key": ["p"], "name": "dupe"}, "junk"],
            "strands": [{"kind": "places", "name": "x", "description": "y"},
                        {"kind": "tags", "name": "", "description": "y"},
                        {"kind": "tags", "name": "blank"},
                        {"name": "Default kind", "description": "tags is the default"},
                        {"kind": "tags", "name": "default KIND", "description": "duplicate"}],
            "strand_groups": [{"kind": "places", "name": "x"}, {"kind": "tags", "name": " "},
                              {"name": "Default\nkind", "members": "not a list", "description": 5},
                              {"kind": "tags", "name": "DEFAULT kind", "members": ["dupe"]},
                              {"kind": "characters", "name": "Odd", "members": [" Rowan ", 3, None, "", "rowan"]},
                              "junk", 4],
            "version": "12",
        },
        "broken-duplicate-ids": {
            "cards": [{"id": "d", "title": "First"}, {"id": "d", "title": "Second", "x": 10},
                      {"title": "No id", "x": 20}],
            "connections": [{"id": "a", "source": "d", "target": "d"}, {"id": "a", "source": "d", "target": "x"}],
        },
        "old-format": {
            "cards": [{"id": "c1", "title": "Old", "characters": "Mara, Rowan", "location": "x",
                       "color": "#123456", "tag": "y"}],
            "version": 1,
        },
        "newer-version": {"app": "Heddle", "version": 99, "cards": [{"id": "a", "title": "Rowan"}],
                          "from_the_future": {"x": 1}},
    }


NAMES = ["Rowan", "Mabel", "Greta", "Warden", "rowan", "ß", "SS", "Σ", "Zoë", "7", "2024", "Ärger", "🌊"]
TAGS = ["Plot", "plot", "Act I", "Ending", "10", "9", "lore_*", "ﬁ", "Straße", "east"]
PLACES = ["East Ward", "West Ward", "Harbour", "harbour", "Lighthouse"]
STATUSES = ["", "Idea", "Draft", "draft", "Final", "Ending"]
WORDS = ["tide", "lamp", "*bold*", "#hash", "[link]", "under_score", "ß", "Ω", "🌊", "pipe|bar", "~", "<tag>"]


def random_board(seed: int) -> dict:
    """A seeded board: groups (nested), arrows with loops, markers, strand cards and
    outside cards, awkward text. Card positions are all different, so nothing depends on
    how ties happen to be broken."""
    rng = random.Random(seed)
    n = rng.randint(3, 36)
    used: set[tuple[int, int]] = set()

    def spot() -> tuple[int, int]:
        while True:
            p = (rng.randint(0, 60) * 37 + rng.randint(0, 9), rng.randint(0, 40) * 41 + rng.randint(0, 9))
            if p not in used:
                used.add(p)
                return p

    def words(k: int) -> str:
        return " ".join(rng.choice(WORDS) for _ in range(k))

    cards = []
    groups: list[str] = []
    for i in range(n):
        cid = f"c{seed}_{i}" if rng.random() < 0.9 else str(rng.randint(1, 99999))
        if any(c["id"] == cid for c in cards):
            cid += "x"
        x, y = spot()
        kind = rng.choices(["card", "group", "strand"], [0.78, 0.17, 0.05])[0]
        c = {"id": cid, "title": rng.choice([words(rng.randint(1, 3)), rng.choice(NAMES), "Scene"]),
             "x": x + rng.choice([0, 0.5]), "y": y, "kind": kind,
             "color": rng.choice(model.CARD_COLORS + ["#123abc"])}
        if kind == "strand":
            c.update(strand_kind=rng.choice(["characters", "tags", "locations", "status"]),
                     strand=rng.choice(NAMES))
        else:
            c.update(description=rng.choice(["", words(rng.randint(1, 12)), words(3) + "\n\n" + words(4)]),
                     characters=rng.sample(NAMES, rng.randint(0, 3)),
                     tags=rng.sample(TAGS, rng.randint(0, 2)),
                     locations=rng.sample(PLACES, rng.randint(0, 2)),
                     status=rng.choice(STATUSES), notes=rng.choice(["", words(5), "a\nb"]),
                     outside_story=rng.random() < 0.06)
            if c["characters"] and rng.random() < 0.4:
                c["pov"] = rng.choice(c["characters"]).upper()
        if kind == "group":
            c.update(arrange_by_color=rng.random() < 0.3, arrange_vertical=rng.random() < 0.3,
                     arrange_grid=rng.random() < 0.3, arrange_wrap=rng.choice([0, 0, 2, 3]))
            groups.append(cid)
        cards.append(c)
    # Parents: any card may sit in an earlier group (so nesting never loops).
    for c in cards:
        options = [g for g in groups if g != c["id"] and cards.index(next(x for x in cards if x["id"] == g))
                   < cards.index(c)]
        if options and rng.random() < 0.55:
            c["parent"] = rng.choice(options)
    ids = [c["id"] for c in cards]
    arrows = []
    for k in range(rng.randint(0, int(n * 1.6))):
        s, t = rng.choice(ids), rng.choice(ids)
        label = rng.choice(["", "", "", words(1), words(2)])
        arrows.append({"id": f"a{seed}_{k}", "source": s, "target": t, "label": label,
                       "style": rng.choice(model.ARROW_STYLES), "color": rng.choice(["", "#ff0000"])})
    # Some group markers: a group to a card inside it, or a card inside to its group.
    for c in cards:
        if c.get("parent") and rng.random() < 0.25:
            pair = (c["parent"], c["id"]) if rng.random() < 0.5 else (c["id"], c["parent"])
            arrows.append({"id": f"m{seed}_{c['id']}", "source": pair[0], "target": pair[1]})
    return {"app": "Heddle", "version": model.FORMAT_VERSION, "cards": cards, "connections": arrows,
            "display": {"story_tools": True}}


RANDOM_SEEDS = range(1, 41)


def all_inputs() -> dict[str, dict]:
    out = {**demo_boards(), **small_boards(), **broken_boards()}
    for seed in RANDOM_SEEDS:
        out[f"random-{seed:02d}"] = random_board(seed)
    return out


# ----- expected results ---------------------------------------------------------------------

def pairs(d: dict) -> list:
    """A dict as [key, value] pairs: keeps its order through JSON (JavaScript objects
    reorder integer-like keys)."""
    return [[k, v] for k, v in d.items()]


def size_of(c: model.CardData) -> tuple[float, float]:
    """Made-up card sizes for auto-arrange (the real ones come from font measurements)."""
    w = 160 + (len(c.title) % 6) * 20 + (0.5 if len(c.id) % 2 else 0)
    h = 80 + (len(c.description) % 5) * 22 + (60 if c.kind == model.KIND_GROUP else 0)
    return w, h


def layout_cases(board: model.BoardData) -> list[dict]:
    """Auto-arrange each group's direct members (and the top level), with the group's
    options and a few others."""
    cards = {c.id: c for c in board.cards}
    parents = [""] + [c.id for c in board.cards if c.kind == model.KIND_GROUP]
    out = []
    for gid in parents:
        members = [c for c in board.cards if (c.parent if c.parent in cards else "") == gid and c.id != gid]
        if not members:
            continue
        nodes = [layout.Node(c.id, *size_of(c), c.x, c.y, c.color, c.kind == model.KIND_GROUP) for c in members]
        member_ids = {c.id for c in members}
        edges = [(e.source, e.target) for e in board.connections
                 if e.source in member_ids and e.target in member_ids]
        labels = {(e.source, e.target): (len(e.label) * 7.0, 18.0) for e in board.connections
                  if e.label and e.source in member_ids and e.target in member_ids}
        g = cards.get(gid)
        variants = [dict(by_color=g.arrange_by_color, vertical=g.arrange_vertical, grid=g.arrange_grid,
                         wrap=g.arrange_wrap)] if g else []
        variants += [dict(), dict(by_color=True), dict(vertical=True, grid=True), dict(wrap=2, by_color=True),
                     dict(vertical=True, wrap=3)]
        for opts in variants:
            placed = layout.arrange(nodes, edges, labels=labels, **opts)
            out.append({
                "group": gid, "options": opts,
                "nodes": [[n.id, n.w, n.h, n.x, n.y, n.color, n.group] for n in nodes],
                "edges": [list(e) for e in edges],
                "labels": [[s, t, w, h] for (s, t), (w, h) in labels.items()],
                "positions": [[i, x, y] for i, (x, y) in placed.items()],
            })
    return out


def graph_results(g: StoryGraph, board: model.BoardData) -> dict:
    cards = list(g.cards)
    names = sorted(dict.fromkeys(n for c in board.cards for n in c.characters), key=str.casefold)
    rs = g.routes(300)
    return {
        "nodes": g.nodes(),
        "outside": sorted(g.outside),
        "arrows": pairs({k: list(v) for k, v in g.arrows.items()}),
        "boundary_arrows": sorted(g.boundary_arrows),
        "succ": pairs(g.succ), "pred": pairs(g.pred),
        "arrow_ends": pairs({k: [list(a), list(b)] for k, (a, b) in g.arrow_ends.items()}),
        "entry_cards": [[i, g.entry_cards(i)] for i in cards],
        "exit_cards": [[i, g.exit_cards(i)] for i in cards],
        "contents": [[i, sorted(g.contents(i))] for i in cards if g.members.get(i)],
        "downstream": [[i, sorted(g.downstream(i))] for i in cards],
        "upstream": [[i, sorted(g.upstream(i))] for i in cards],
        "arrow_order": g.arrow_order(),
        "components": g.components(),
        "cycles": g.cycles(),
        "strongly_connected": g.strongly_connected(),
        "count_paths": [g.count_paths().count, g.count_paths().has_cycles],
        "introductions": pairs(g.introductions()),
        "featuring": [[n, g.featuring(n)] for n in names],
        "outline_story": pairs(g.outline(True)),
        "outline_reading": pairs(g.outline(False)),
        "routes": [{"stops": [list(s) for s in r.stops], "key": list(r.key),
                    "arrows": sorted(g.route_arrows(r))} for r in rs],
        "route_for_key": [[list(r.key), g.route_for_key(r.key) is not None] for r in rs[:20]]
                         + [[k, g.route_for_key(k) is not None] for k in (["nope"], [], cards[:2])],
    }


def check_results(g: StoryGraph) -> list:
    out = []
    for scope in [None] + [i for i in g.cards if g.members.get(i)]:
        r = checks.run_checks(g, scope)
        out.append({"scope": scope, "findings": [[f.kind, list(f.cards), f.message] for f in r.findings],
                    "paths": [r.paths.count, r.paths.has_cycles], "has_arrows": r.has_arrows,
                    "stops": r.stops, "warnings": r.warnings, "summary": checks.summary(r)})
    return out


def route_results(g: StoryGraph, board: model.BoardData) -> dict:
    cards = {c.id: c for c in board.cards}
    saved = {tuple(r.key): r for r in board.routes}
    listing = routes.list_routes(g, saved, limit=50)
    labels = model.title_labels(board.cards)
    rows = []
    for r in listing.routes:
        data = saved.get(r.key)
        rows.append({"key": list(r.key), "title": routes.route_title(r.key, cards, data, r.stops, labels),
                     "default": routes.default_title(r.key, cards),
                     "steps": routes.steps_text(r.key, cards, r.stops, labels),
                     "loops": routes.loop_details(r.key, cards, r.stops, labels),
                     "search": routes.search_text(r.key, cards, data, labels),
                     "inherited": pairs(routes.inherited_values(r.cards, cards))})
    return {"total": listing.total, "rows": rows, "missing": [r.name for r in listing.missing],
            "matches": [[q, [routes.matches(q, r.key, cards, saved.get(r.key)) for r in listing.routes]]
                        for q in ("tide", "ROWAN", "  ", "zz")]}


def filter_results(g: StoryGraph, board: model.BoardData) -> dict:
    extras = {"introduces": g.introductions()}
    options = filters.collect_options(board.cards, extras)
    info = {(s.kind, s.name.casefold()): s for s in board.strands}
    queries = ["tide", "ROWAN", "ss", "ß", "🌊", "  east   ward ", "41", "lamp", "*", "zzz"]
    selections = []
    for cat, opts in options.items():
        for key, _, _ in opts[:3]:
            selections.append(({cat: {key}}, ()))
        if len(opts) >= 2:
            both = {opts[0][0], opts[1][0]}
            selections.append(({cat: both}, ()))
            selections.append(({cat: both}, (cat,)))
    tags = [k for k, _, _ in options["tags"]][:2]
    if tags and options["characters"]:
        selections.append(({"tags": set(tags), "characters": {options["characters"][0][0]}}, ("tags",)))
    return {
        "options": [[cat, [list(o) for o in opts]] for cat, opts in options.items()],
        "search": [[q, [list(h) for h in filters.search_cards(board.cards, q, info)]] for q in queries],
        "matches": [{"selection": [[c, sorted(v)] for c, v in sel.items()], "match_all": list(ma),
                     "cards": [c.id for c in board.cards if filters.matches(c, sel, ma, extras)]}
                    for sel, ma in selections],
        "counts": [filters.describe_counts(filters.FilterCounts(2, 17, 1, 5)),
                   filters.describe_counts(filters.FilterCounts(1, 1, 0, 0), filtered=False)],
    }


def export_results(g: StoryGraph, board: model.BoardData) -> dict:
    o = export.TextOptions
    variants = {"document": o(), "outline": o(layout=export.OUTLINE),
                "everything": o(notes=True), "outline-everything": o(layout=export.OUTLINE, notes=True),
                "bare": o(descriptions=False, details=False, next_steps=False)}
    out = {name: export.export_text(board, g, "Board *title*", opt) for name, opt in variants.items()}
    group = next((c.id for c in board.cards if g.members.get(c.id)), None)
    if group:
        out["only-group"] = export.export_text(board, g, "Part", o(), include={group})
    labels = {e.id: e.label for e in board.connections}
    for n, r in enumerate(g.routes(3)):
        cards = r.cards
        via = [""] + [next((labels[a] for a in g.step_arrows(a, b) if labels[a]), "")
                      for a, b in zip(cards, cards[1:])]
        out[f"route-{n}"] = export.export_route(board, cards, via, "Route")
        out[f"route-{n}-outline"] = export.export_route(board, cards, via, "Route",
                                                        o(layout=export.OUTLINE, notes=True))
    return out


def model_results(board: model.BoardData) -> dict:
    out: dict = {
        "all_values": [[f, board.all_values(f)] for f in model.RENAMABLE_FIELDS],
        "count_values": [[f, pairs({k: list(v) for k, v in model.count_values(board.cards, f).items()})]
                         for f in model.RENAMABLE_FIELDS],
        "title_labels": pairs(model.title_labels(board.cards)),
        "from_newer_version": board.from_newer_version,
    }
    renames = []
    for f in model.RENAMABLE_FIELDS:
        values = board.all_values(f)
        first = (values[:1] or ["none"])[0]
        second = (values[1:2] or ["x"])[0]
        # A plain rename, then a merge of the second value into the first.
        for old, new in ((first, "Renamed ß"), (second, first.upper())):
            cards = copy.deepcopy(board.cards)
            changed = model.rename_value(cards, f, old, new)
            renames.append({"field": f, "old": old, "new": new, "changed": [c.id for c in changed],
                            "values": [[c.id, getattr(c, f), c.pov] for c in cards]})
    out["renames"] = renames
    replaces = []
    fields = [f for f, _ in model.REPLACE_FIELDS]
    for find, rep, case in (("tide", "TIDE$1\\1", False), ("Rowan", "", True), ("ß", "ss", False), ("*", "+", False)):
        cards = copy.deepcopy(board.cards)
        count = model.count_replacements(cards, find, fields, case)
        changed = model.replace_text(cards, find, rep, fields, case)
        replaces.append({"find": find, "replacement": rep, "match_case": case, "count": list(count),
                         "changed": [c.id for c in changed],
                         "text": [[c.id, c.title, c.description, c.notes] for c in changed]})
    out["replaces"] = replaces
    cards = copy.deepcopy(board.cards)
    chars = board.all_values("characters")[:1]
    changed = model.apply_bulk_edit(cards, color="#123abc", add_tags=["New", "plot"], remove_tags=["PLOT"],
                                    status=" Final ", add={"locations": ["Dock"]}, remove={"characters": chars})
    out["bulk_edit"] = {"remove_characters": chars, "changed": [c.id for c in changed],
                        "cards": [[c.id, c.color, c.tags, c.characters, c.pov, c.locations, c.status]
                                  for c in cards]}
    return out


def expected(raw: dict) -> dict:
    with FixedIds():
        try:
            board = model.BoardData.from_dict(copy.deepcopy(raw))
        except ValueError as e:
            return {"error": str(e)}
        return results(board)


def results(board: model.BoardData) -> dict:
    g = StoryGraph(board.cards, board.connections)
    return {
        "board": board.to_dict(),
        "source_version": board.source_version,
        "load_notes": board.load_notes,
        "model": model_results(board),
        "graph": graph_results(g, board),
        "checks": check_results(g),
        "routes": route_results(g, board),
        "filters": filter_results(g, board),
        "export": export_results(g, board),
        "layout": layout_cases(board),
    }


def strings_fixture() -> dict:
    """Python's string rules the port mimics (core/pystr.ts)."""
    folds = [[cp, chr(cp).casefold()] for cp in range(0x110000)
             if not 0xD800 <= cp <= 0xDFFF and chr(cp).casefold() != chr(cp)
             and unicodedata.category(chr(cp)) != "Cn"]
    samples = ["", " ", "a b", "  a\tb\n\nc  ", "\x1c\x1dx\x1e\x1f", "\x85y\xa0", "　z w ",
               "﻿bom﻿", "line\r\nline\rline\nline\v\f", "end\n", "\n", "\n\n", "a\x85b c",
               "ΣΑΣ", "Straße", "ﬁre", "İstanbul", "ǅemal", "Ꭰꭰ", "🌊 tide 🌊"]
    words = ["b", "a", "B", "ä", "z", "ﬁ", "🌊", "￿", "", "", "a\U0001f30a", "a￿", "10", "9"]
    return {
        "casefold": folds,
        "samples": [{"text": s, "casefold": s.casefold(), "strip": s.strip(), "rstrip": s.rstrip(),
                     "split": s.split(), "splitlines": s.splitlines(), "length": len(s)} for s in samples],
        "words": words,
        "sorted": sorted(words),
        "sorted_casefold": sorted(words, key=str.casefold),
    }


def build() -> dict[str, str]:
    """{file name: text} for every fixture file."""
    files = {}
    for name, raw in all_inputs().items():
        files[f"cases/{name}.json"] = dump({"name": name, "input": raw, "expected": expected(raw)})
    files["strings.json"] = dump(strings_fixture())
    files["manifest.json"] = dump({"format_version": model.FORMAT_VERSION,
                                   "cases": sorted(n[len("cases/"):] for n in files if n.startswith("cases/"))})
    return files


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> None:
    files = build()
    if CASES.exists():
        for old in CASES.glob("*.json"):
            if f"cases/{old.name}" not in files:
                old.unlink()
    CASES.mkdir(exist_ok=True)
    for name, text in files.items():
        (HERE / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(files)} fixture files written to {HERE}")


if __name__ == "__main__":
    main()
