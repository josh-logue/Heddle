"""Card filtering logic (no Qt): option collection and matching.

Values are compared case-insensitively. Within a category, checked values are
OR'd; across categories they are AND'd. Tags, characters, locations and
introductions are lists: a card matches if any of its entries is checked, or,
with that category set to "match all", only if it has every checked entry.
Colour, POV and status hold one value each, so "all" of two could never match:
they're always "any". An empty field is represented by
NONE_KEY so "cards with no status" etc. can be filtered too.

Some categories aren't stored on cards but worked out from the arrows (which
characters a card introduces). Their values are passed in as `extras`:
{category: {card id: [values]}}.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from .model import COLOR_NAMES, CardData, count_values

class FilterCounts(NamedTuple):
    """How many cards and groups a filter shows. Group frames match a filter on
    their own colour and tags, just as cards do, so they're counted apart."""
    cards_shown: int
    cards_total: int
    groups_shown: int = 0
    groups_total: int = 0


def _count(shown: int | None, total: int, noun: str) -> str:
    word = noun if total == 1 else noun + "s"
    return f"{total} {word}" if shown is None else f"{shown} of {total} {word}"


def describe_counts(counts: FilterCounts, filtered: bool = True) -> str:
    """'2 of 17 cards, 1 of 5 groups' (filtered) or '17 cards, 5 groups' (not).
    Groups are left out on a board without any."""
    parts = [_count(counts.cards_shown if filtered else None, counts.cards_total, "card")]
    if counts.groups_total:
        parts.append(_count(counts.groups_shown if filtered else None, counts.groups_total, "group"))
    return ", ".join(parts)


CATEGORIES = ("tags", "color", "characters", "pov", "introduces", "locations", "status")
LABELS = {"tags": "Tags", "color": "Color", "characters": "Characters", "pov": "POV",
          "introduces": "Introduces", "locations": "Locations", "status": "Status"}
# Categories whose cards hold several values, so "match all" means something.
MATCH_ALL_CATEGORIES = ("tags", "characters", "introduces", "locations")
COMPUTED = ("introduces",)  # worked out from the arrows, passed in as extras
Extras = dict[str, dict[str, list[str]]]
NONE_KEY = ""
NONE_LABEL = "(none)"

Option = tuple[str, str, int]  # (key, display text, number of cards)


def _raw_values(card: CardData, category: str, extras: Extras | None = None) -> list[str]:
    if category == "color":
        return [card.color.strip().lower()]
    if category in COMPUTED:
        return [v for v in (extras or {}).get(category, {}).get(card.id, ()) if v.strip()]
    value = getattr(card, category)
    if isinstance(value, list):  # tags, characters, locations
        return [v.strip() for v in value if v.strip()]
    value = value.strip()
    return [value] if value else []


def _key(category: str, raw: str) -> str:
    return raw if category == "color" else raw.casefold()


def card_keys(card: CardData, category: str, extras: Extras | None = None) -> set[str]:
    keys = {_key(category, v) for v in _raw_values(card, category, extras)}
    return keys or {NONE_KEY}


def display_for(category: str, raw: str) -> str:
    if category == "color":
        return COLOR_NAMES.get(raw, raw)
    return raw


def collect_options(cards: Iterable[CardData], extras: Extras | None = None) -> dict[str, tuple[Option, ...]]:
    """Distinct values per category, with card counts, sorted alphabetically,
    "(none)" last. Text fields use model.count_values (first spelling shown)."""
    cards = list(cards)
    result: dict[str, tuple[Option, ...]] = {}
    for cat in CATEGORIES:
        if cat == "color" or cat in COMPUTED:
            counted: dict[str, tuple[str, int]] = {}
            for card in cards:
                seen = set()
                for raw in _raw_values(card, cat, extras):
                    key = _key(cat, raw)
                    if key in seen:
                        continue
                    seen.add(key)
                    name, n = counted.get(key, (display_for(cat, raw), 0))
                    counted[key] = (name, n + 1)
        else:
            counted = count_values(cards, cat)
        options = sorted(((k, name, n) for k, (name, n) in counted.items()),
                         key=lambda o: o[1].casefold())
        empty = sum(1 for card in cards if not _raw_values(card, cat, extras))
        if empty:
            options.append((NONE_KEY, NONE_LABEL, empty))
        result[cat] = tuple(options)
    return result


SEARCH_FIELDS = (("title", "Title"), ("description", "Description"), ("notes", "Notes"))
# Strands are searched too, after the text: a card's own values, then the strand a
# strand card stands for, then the descriptions and field values of the strands a card has.
SEARCH_STRANDS = (("tags", "Tag"), ("characters", "Character"), ("locations", "Location"),
                  ("status", "Status"))
SNIPPET_CHARS = 30  # context shown either side of a search match


def _snippet(text: str, needle: str) -> str | None:
    text = " ".join(text.split())   # flatten line breaks for snippets
    at = text.casefold().find(needle)
    if at < 0:
        return None
    start, end = max(0, at - SNIPPET_CHARS), min(len(text), at + len(needle) + SNIPPET_CHARS)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def _card_strands(card: CardData) -> list[tuple[str, str]]:
    """(kind, name) of every strand the card has, or that a strand card stands for."""
    if card.kind == "strand":
        return [(card.strand_kind, card.strand)] if card.strand_kind and card.strand else []
    out = [(kind, v) for kind in ("tags", "characters", "locations") for v in getattr(card, kind)]
    if card.status:
        out.append(("status", card.status))
    return out


def search_cards(cards: Iterable[CardData], query: str,
                 strand_info: dict | None = None) -> list[tuple[str, str, str]]:
    """Cards whose text or strands contain `query` (ignoring case), in the order
    given: (card id, field label, snippet around the first match). Text comes first
    (title, description, notes), then the card's tags, characters, locations and
    status, then the descriptions of its strands (`strand_info`: {(kind, casefolded
    name): StrandInfo}), then their field values, so searching "Greta" finds every card
    she's on."""
    needle = " ".join(query.split()).casefold()
    if not needle:
        return []
    labels = dict(SEARCH_STRANDS)
    found = []
    for card in cards:
        hit = None
        for name, label in SEARCH_FIELDS:
            snippet = _snippet(getattr(card, name), needle)
            if snippet is not None:
                hit = (label, snippet)
                break
        strands = _card_strands(card)
        if hit is None:
            hit = next(((labels.get(kind, "Strand"), name) for kind, name in strands
                        if needle in name.casefold()), None)
        if hit is None and strand_info:
            infos = [(name, strand_info.get((kind, name.casefold()))) for kind, name in strands]
            infos = [(name, info) for name, info in infos if info is not None]
            for name, info in infos:
                snippet = _snippet(info.description, needle)
                if snippet is not None:
                    hit = (f"{name}’s description", snippet)
                    break
            # Then the strands' field values (never the field names: "Age" would find
            # every card with a character who has an age).
            hit = hit or next(((f"{name}’s {field}", snippet) for name, info in infos
                               for field, value in info.fields
                               if (snippet := _snippet(value, needle)) is not None), None)
        if hit is not None:
            found.append((card.id, *hit))  # one entry per card: the first field that matches
    return found


def matches(card: CardData, selection: dict[str, set[str]], match_all: Iterable[str] = (),
            extras: Extras | None = None) -> bool:
    """Whether `card` passes the filter. `match_all` names the categories where a card
    needs every ticked entry; only MATCH_ALL_CATEGORIES take part (a card has one
    colour, POV and status, so "all" of two of those would match nothing)."""
    if card.kind == "strand":
        return _strand_card_matches(card, selection)
    match_all = set(match_all).intersection(MATCH_ALL_CATEGORIES)
    for cat, selected in selection.items():
        if not selected:
            continue
        keys = card_keys(card, cat, extras)
        if cat in match_all:
            if not selected <= keys:
                return False
        elif not keys & selected:
            return False
    return True


def _strand_card_matches(card: CardData, selection: dict[str, set[str]]) -> bool:
    """A strand card stays lit when its own strand is ticked (a character also under
    POV or Introduces), or its colour is; other categories don't apply to it. "Match
    all" doesn't either: it stands for one strand, so it could never have two."""
    active = {c for c, s in selection.items() if s}
    if not active:
        return True
    key = card.strand.casefold()
    cats = {card.strand_kind} | ({"pov", "introduces"} if card.strand_kind == "characters" else set())
    if any(key in selection.get(c, ()) for c in cats):
        return True
    return "color" in active and card.color.lower() in selection["color"]
