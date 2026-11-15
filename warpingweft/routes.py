"""Routes through the story, as the Routes panel shows them (pure Python, no Qt).

A route is a walk from a start to an end (graph.Route); its fields (name, tags,
characters, …) are kept on the board as RouteData under the route's key. With
"inherit card strands" on, a route also shows every strand its cards have; those
stay live (nothing is copied) and are listed apart from the route's own."""
from __future__ import annotations

from dataclasses import dataclass, field

from .graph import LOOP_JOIN, Route, StoryGraph
from .model import CardData, RouteData, clean_list

# Fields a route can inherit from its cards, with the label the panel uses.
INHERITED_FIELDS = (("tags", "Tags"), ("characters", "Characters"), ("pov", "POV"),
                    ("locations", "Locations"), ("status", "Status"))
MAX_LISTED = 300  # routes listed at most (they can multiply fast); saved ones are always listed
COMPACT_LOOP_OVER = 4   # loops with more cards than this are summarised in a route's steps
LOOP_PREVIEW = 3        # ...naming this many of their cards


def card_title(card: CardData | None) -> str:
    if card is None:
        return "(deleted card)"
    return card.title.strip() or "Untitled"


def _title_of(cards: dict[str, CardData], i: str, labels: dict[str, str] | None) -> str:
    """A card's title, as `labels` (model.title_labels) gives it if passed."""
    if labels is not None and i in labels and i in cards:
        return labels[i]
    return card_title(cards.get(i))


def stop_ids(key_part: str) -> list[str]:
    """The card ids a route key part stands for (a loop's ids are joined)."""
    return key_part.split(LOOP_JOIN)


def key_cards(key) -> list[str]:
    return [i for part in key for i in stop_ids(part)]


def default_title(key, cards: dict[str, CardData], stops=None, labels=None) -> str:
    """'First card → Last card' (or a single card's title). A route that starts or
    ends in a loop uses the loop's first card in story order when `stops` is given."""
    lists = _stop_lists(key, stops)
    first = _title_of(cards, lists[0][0], labels) if lists else "Empty route"
    if len(lists) < 2:
        return first
    return f"{first} → {_title_of(cards, lists[-1][0], labels)}"


def route_title(key, cards: dict[str, CardData], data: RouteData | None, stops=None,
                labels=None) -> str:
    if data is not None and data.name.strip():
        return data.name.strip()
    return default_title(key, cards, stops, labels)


def _stop_lists(key, stops=None) -> list:
    """Each stop's card ids: from the route's own stops (loops in story order) if
    given, else from its key (where a loop's ids are sorted, not in story order)."""
    return [list(s) for s in stops] if stops is not None else [stop_ids(part) for part in key]


def steps_text(key, cards: dict[str, CardData], stops=None, labels=None) -> list[str]:
    """One line per stop: a card's title, or a loop's titles marked ↻. A loop of
    more than COMPACT_LOOP_OVER cards is summarised ("↻ Loop of 12 cards: A, B, C …"),
    which keeps long routes readable and cheap to show (see loop_details). Pass the
    route's `stops` (graph.Route.stops) to list loops in story order."""
    out = []
    for ids in _stop_lists(key, stops):
        if len(ids) == 1:
            out.append(_title_of(cards, ids[0], labels))
        elif len(ids) <= COMPACT_LOOP_OVER:
            out.append("↻ " + ", ".join(_title_of(cards, i, labels) for i in ids))
        else:
            names = ", ".join(_title_of(cards, i, labels) for i in ids[:LOOP_PREVIEW])
            out.append(f"↻ Loop of {len(ids)} cards: {names} …")
    return out


def loop_details(key, cards: dict[str, CardData], stops=None, labels=None) -> list[str]:
    """Every card of each loop that steps_text summarises, one line per loop."""
    return [f"Loop of {len(ids)} cards: " + ", ".join(_title_of(cards, i, labels) for i in ids)
            for ids in _stop_lists(key, stops) if len(ids) > COMPACT_LOOP_OVER]


def search_text(key, cards: dict[str, CardData], data: RouteData | None, labels=None) -> str:
    """Everything the filter box looks through, case-folded: the route's name,
    every card's title (loops in full), its notes and every value it shows."""
    hay = [route_title(key, cards, data, labels=labels),
           *(_title_of(cards, i, labels) for i in key_cards(key))]
    if data is not None:
        hay.append(data.notes)
    for view in merged_fields(data, key_cards(key), cards).values():
        hay.extend(view.own + view.inherited)
    return "\n".join(hay).casefold()


def inherited_values(card_ids, cards: dict[str, CardData]) -> dict[str, list[str]]:
    """Every value the route's cards have, per field, in route order, without
    case-insensitive repeats. POV and Status gather each card's single value."""
    out: dict[str, list[str]] = {}
    present = [cards[i] for i in card_ids if i in cards]
    for name, _label in INHERITED_FIELDS:
        values: list[str] = []
        for card in present:
            v = getattr(card, name)
            values.extend(v if isinstance(v, list) else [v])
        out[name] = clean_list(values)
    return out


@dataclass
class FieldView:
    """What the panel shows for one field: the route's own values, and (when it
    inherits) those of its cards that the route doesn't already have."""
    own: list[str] = field(default_factory=list)
    inherited: list[str] = field(default_factory=list)


def merged_fields(data: RouteData | None, card_ids, cards: dict[str, CardData]) -> dict[str, FieldView]:
    out: dict[str, FieldView] = {}
    inherit = data is not None and data.inherit
    from_cards = inherited_values(card_ids, cards) if inherit else {}
    for name, _label in INHERITED_FIELDS:
        own = [] if data is None else getattr(data, name)
        own = list(own) if isinstance(own, list) else ([own] if own.strip() else [])
        have = {v.casefold() for v in own}
        extra = [v for v in from_cards.get(name, []) if v.casefold() not in have]
        out[name] = FieldView(own, extra)
    return out


def matches(text: str, key, cards: dict[str, CardData], data: RouteData | None) -> bool:
    """Does a filter text appear in the route's name, card titles, notes or any
    value it shows (own or inherited)?"""
    needle = text.strip().casefold()
    return not needle or needle in search_text(key, cards, data)


@dataclass
class RouteListing:
    routes: list[Route]                       # current routes to list, in reading order
    total: int                                # how many routes the board has
    missing: list[RouteData]                  # saved fields whose route no longer exists

    @property
    def truncated(self) -> bool:
        return len(self.routes) < self.total


def list_routes(graph: StoryGraph, saved: dict, limit: int = MAX_LISTED) -> RouteListing:
    """The routes to list: the first `limit` in reading order, plus any route with
    saved fields that's still complete; and the saved fields whose route is gone."""
    routes = graph.routes(limit)
    total = graph.count_paths().count
    listed = {r.key for r in routes}
    missing = []
    for key, data in saved.items():
        if key in listed:
            continue
        route = graph.route_for_key(key)
        if route is None:
            missing.append(data)
        else:
            routes.append(route)
            listed.add(key)
    return RouteListing(routes, total, missing)
