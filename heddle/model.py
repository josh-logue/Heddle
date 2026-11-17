"""Plain data model for a board, plus JSON load/save.

Kept free of Qt so it can be tested or reused on its own.
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

APP_ID = "Heddle"
# v2: tags/characters/locations are lists (v1: tag/characters/location strings).
# v3: card `pov`, arrow `style`/`color`, board `display` options. v2 files load with defaults.
# v4: `routes`, the fields given to routes in the Routes panel. v3 files load with none.
# v5: more `display` options (see DISPLAY_DEFAULTS) and a card's `outside_story`.
# v6: `strands`, a description and picture for strands (Strands panel).
# v7: strand cards: a card `kind` "strand" with `strand_kind` and `strand`.
# v8: `display.show_no_description`.
# v9: a group card's `collapsed` (folded to its title bar).
# v10: a strand's custom `fields` ({"name", "value"} objects, in order).
# v11: `display.show_description` and `display.compact_cards`.
# v12: a group card's `arrange_wrap` (auto-arrange's row limit).
# v13: `strand_groups`, named sets of strands of one kind ({"kind", "name", "members",
#      "description"}), for filtering and adding several strands at once.
FORMAT_VERSION = 13
# The largest row limit a group can have (steps per row when auto-arranging).
ARRANGE_WRAP_MAX = 99

# Arrow line styles, and how arrows are drawn between cards (a per-board choice).
ARROW_STYLES = ("solid", "dashed", "dotted")
ARROW_ROUTINGS = ("straight", "curved", "avoid")
# Per-board display options and their defaults.
DISPLAY_DEFAULTS: dict[str, Any] = {
    # Card face
    "show_pov": True,            # a POV line on the card face
    "show_characters": False,    # every character as a pill on the card face
    "show_tags": True,           # tag pills on the card face (tags still work when hidden)
    "show_introductions": True,  # the ★ on cards that introduce a character
    "show_group_count": True,    # "N cards" in a group's title bar
    "show_shadows": True,        # drop shadows under cards
    # "No description" on cards without one. Off: a card with nothing else on its face
    # keeps the space blank; one with tags, POV or characters showing closes it up.
    "show_no_description": True,
    # Descriptions on card faces. Hidden, pointing at a card shows its description.
    "show_description": True,
    # While descriptions are hidden: a card with nothing else on its face is just its
    # title bar (off: it keeps a blank line).
    "compact_cards": False,
    # Canvas and arrows
    "show_handles": True,        # each card's ● connection handle
    "show_arrow_labels": True,   # arrow labels drawn on the canvas (else shown on hover)
    "show_grid": True,           # the background grid (snapping works either way)
    "arrow_routing": "straight",
    # Story tools: off hides ★ markers, the Introduces filter and the story panels
    # (Story Checks, Routes, Path Reader, Character Thread), e.g. for a board used
    # just to sort things into groups.
    "story_tools": True,
    "follow_paths": False,       # selecting a card lights up its paths
}
# The on/off options (everything but arrow_routing).
DISPLAY_TOGGLES = tuple(k for k, v in DISPLAY_DEFAULTS.items() if isinstance(v, bool))

KIND_CARD = "card"
KIND_GROUP = "group"  # holds other cards (those whose `parent` is this card's id)
# Stands for a strand (a character, location, tag or status) on the canvas: shows its
# name, and its description in the details. Always outside the story tools.
KIND_STRAND = "strand"

# Card fields holding multiple entries.
LIST_FIELDS = ("tags", "characters", "locations")

# Header colors offered for cards; new cards cycle through these.
CARD_COLORS = [
    "#4a7fc1",  # blue
    "#d9822b",  # orange
    "#3f9e6e",  # green
    "#b8475b",  # red
    "#7b5ea7",  # purple
    "#2a9aa6",  # teal
    "#c9a227",  # mustard
    "#6b6b6b",  # gray
]
COLOR_NAMES = dict(zip(CARD_COLORS, ["Blue", "Orange", "Green", "Red", "Purple", "Teal",
                                     "Mustard", "Gray"]))


def new_id() -> str:
    return uuid.uuid4().hex[:12]


_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def _as_text(value: Any) -> str:
    """Strings pass through; numbers become text; anything else (null, lists…) is blank."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _as_number(value: Any) -> float:
    """A finite number, or 0.0 for anything else (null, strings, NaN, infinity, booleans)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return 0.0


def _as_wrap(value: Any) -> int:
    """A row limit from the file: a whole number from 0 (no limit) to ARRANGE_WRAP_MAX."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0
    return max(0, min(ARRANGE_WRAP_MAX, int(value)))


def _is_hex_color(value: Any) -> bool:
    return isinstance(value, str) and _HEX_COLOR.fullmatch(value.strip()) is not None


def _as_color(value: Any) -> str:
    if _is_hex_color(value):
        return value.strip().lower()
    return CARD_COLORS[0]


def clean_display(raw: Any) -> dict[str, Any]:
    """Board display options: the defaults, overridden by any valid saved values."""
    out = dict(DISPLAY_DEFAULTS)
    if isinstance(raw, dict):
        for key in DISPLAY_TOGGLES:
            if isinstance(raw.get(key), bool):
                out[key] = raw[key]
        if raw.get("arrow_routing") in ARROW_ROUTINGS:
            out["arrow_routing"] = raw["arrow_routing"]
    return out


def clean_list(values: Any) -> list[str]:
    """Normalize a list field: accepts a list or a comma-separated string (v1 files),
    strips blanks, and drops case-insensitive duplicates keeping the first spelling."""
    if isinstance(values, str):
        values = values.split(",")
    elif not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            continue
        v = v.strip()
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


@dataclass
class CardData:
    id: str = field(default_factory=new_id)
    title: str = "New card"
    description: str = ""
    color: str = CARD_COLORS[0]
    tags: list[str] = field(default_factory=list)
    # Details: hidden on the card until toggled.
    characters: list[str] = field(default_factory=list)
    pov: str = ""  # point-of-view character (also kept in `characters`)
    locations: list[str] = field(default_factory=list)
    status: str = ""
    notes: str = ""
    # Position on the canvas (top-left corner).
    x: float = 0.0
    y: float = 0.0
    kind: str = KIND_CARD  # "card", "group" (groups ignore `description`) or "strand"
    parent: str = ""       # id of the group this card sits in, or "" for none
    # Groups only: manually resized frame size; 0 means "fit exactly around the cards".
    width: float = 0.0
    height: float = 0.0
    # Groups only: auto-arrange puts each card color on its own row within a chain.
    arrange_by_color: bool = False
    # Groups only: auto-arrange runs top-to-bottom instead of left-to-right.
    arrange_vertical: bool = False
    # Groups only: auto-arrange wraps unconnected cards into a grid (else one row/column).
    arrange_grid: bool = False
    # Groups only: auto-arrange starts a new row (column, top to bottom) after this
    # many steps, and wraps unconnected cards after this many. 0 means no limit.
    arrange_wrap: int = 0
    # Left out of the story tools (checks, routes, introductions, threads), with
    # everything inside it if it's a group: e.g. notes or reference cards.
    outside_story: bool = False
    # Groups only: folded to its title bar, its cards hidden (they keep their places).
    collapsed: bool = False
    # Strand cards only: which strand it stands for (its kind, as in RENAMABLE_FIELDS,
    # and its name). The title is kept equal to the name.
    strand_kind: str = ""
    strand: str = ""

    def __post_init__(self) -> None:
        # Values may come straight from a hand-edited or damaged JSON file, so every
        # field is coerced to its proper type here rather than failing later on screen.
        if not isinstance(self.id, str) or not self.id.strip():
            self.id = new_id()
        for name in ("title", "description", "status", "notes", "parent"):
            setattr(self, name, _as_text(getattr(self, name)))
        self.pov = _as_text(self.pov).strip()
        self.color = _as_color(self.color)
        self.arrange_by_color = self.arrange_by_color is True
        self.arrange_vertical = self.arrange_vertical is True
        self.arrange_grid = self.arrange_grid is True
        self.arrange_wrap = _as_wrap(self.arrange_wrap)
        self.outside_story = self.outside_story is True
        for name in LIST_FIELDS:
            setattr(self, name, clean_list(getattr(self, name)))
        if self.pov:  # the POV character is one of the card's characters
            match = next((c for c in self.characters if c.casefold() == self.pov.casefold()), None)
            if match is None:
                self.characters.append(self.pov)
            else:
                self.pov = match  # one spelling per card
        if self.kind not in (KIND_CARD, KIND_GROUP, KIND_STRAND):
            self.kind = KIND_CARD
        self.strand_kind, self.strand = _as_text(self.strand_kind), _as_text(self.strand).strip()
        if self.kind == KIND_STRAND:
            if self.strand_kind not in ("tags", "characters", "locations", "status"):
                self.strand_kind = "characters"
            self.strand = self.strand or self.title.strip() or "Untitled"
            self.title = self.strand
            # A strand card only names its strand: it has no text or values of its own.
            self.description = self.notes = self.status = self.pov = ""
            self.tags, self.characters, self.locations = [], [], []
            self.outside_story = False  # (it's always outside the story anyway)
        else:
            self.strand_kind = self.strand = ""
        self.collapsed = self.collapsed is True and self.kind == KIND_GROUP
        self.x, self.y = _as_number(self.x), _as_number(self.y)
        for name in ("width", "height"):
            value = _as_number(getattr(self, name))
            setattr(self, name, value if value > 0 else 0.0)


def count_values(cards, field_name: str, extra=()) -> dict[str, tuple[str, int]]:
    """The distinct values of a text field, compared case-insensitively:
    {casefolded key: (display spelling, number of cards using it)}.

    This is the one place the rules live: the first spelling found on a card is
    shown; each card counts once per value; `extra` values (e.g. the board's saved
    values) are included with a count of 0 unless a card already uses them."""
    found: dict[str, tuple[str, int]] = {}
    for card in cards:
        raw = getattr(card, field_name)
        seen: set[str] = set()
        for v in (raw if isinstance(raw, list) else [raw]):
            v = v.strip()
            key = v.casefold()
            if not v or key in seen:
                continue
            seen.add(key)
            spelling, n = found.get(key, (v, 0))
            found[key] = (spelling, n + 1)
    for v in extra:
        v = v.strip()
        if v:
            found.setdefault(v.casefold(), (v, 0))
    return found


def board_values(cards: list[CardData], field_name: str, extra=()) -> list[str]:
    """All distinct values of a field across cards plus `extra`, sorted."""
    return sorted((s for s, _ in count_values(cards, field_name, extra).values()), key=str.casefold)


# Strands: the entries in a board's tags, characters, locations and status (a card's
# POV is one of its characters). They're offered as suggestions, can be renamed or
# merged everywhere, and a board can keep ones no card uses (`saved_values`). In code
# they're still called "values"; the file format keeps its keys.
RENAMABLE_FIELDS = ("tags", "characters", "locations", "status")
# Statuses every board has, used or not (offered in the card editor, listed in the
# Strands panel, never "unused").
BUILTIN_STATUSES = ("Idea", "Outline", "Draft", "Revised", "Final")
BULK_LIST_FIELDS = ("tags", "characters", "locations")  # what Edit Selected Cards adds / removes


def rename_value(cards: list[CardData], field_name: str, old: str, new: str) -> list[CardData]:
    """Replace every occurrence of `old` (case-insensitive) with `new` in one field,
    in place. If `new` already exists, the two merge into one entry spelled as
    `new` everywhere. Returns the cards that changed."""
    if field_name not in RENAMABLE_FIELDS:
        raise ValueError(f"Field {field_name!r} cannot be renamed.")
    old_key, new = old.strip().casefold(), new.strip()
    if not old_key or not new:
        return []
    targets = {old_key, new.casefold()}
    changed: list[CardData] = []
    for card in cards:
        touched = False
        value = getattr(card, field_name)
        if isinstance(value, list):
            # Put the new name where the old one was, then drop duplicates.
            updated = clean_list([new if v.casefold() in targets else v for v in value])
            if updated != value:
                setattr(card, field_name, updated)
                touched = True
        elif value.strip().casefold() in targets and value != new:
            setattr(card, field_name, new)
            touched = True
        # The POV is one of the card's characters, so it's renamed along with them.
        if field_name == "characters" and card.pov.casefold() in targets and card.pov != new:
            card.pov = new
            touched = True
        if touched:
            changed.append(card)
    return changed


@dataclass
class ConnectionData:
    source: str
    target: str
    label: str = ""
    id: str = field(default_factory=new_id)
    style: str = "solid"  # one of ARROW_STYLES
    color: str = ""       # "#rrggbb", or "" for the theme's arrow color

    def __post_init__(self) -> None:
        self.source, self.target = _as_text(self.source), _as_text(self.target)
        self.label = _as_text(self.label)
        if not isinstance(self.id, str) or not self.id.strip():
            self.id = new_id()
        if self.style not in ARROW_STYLES:
            self.style = "solid"
        self.color = _as_color(self.color) if _is_hex_color(self.color) else ""


@dataclass
class RouteData:
    """Fields given to one route through the story (Routes panel). `key` names the
    route: its stops' card ids in order, a loop's ids sorted and joined by "+" (see
    graph.Route.key). With `inherit` on, the route also shows its cards' values."""
    key: list[str] = field(default_factory=list)
    name: str = ""
    tags: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    pov: str = ""
    locations: list[str] = field(default_factory=list)
    status: str = ""
    notes: str = ""
    inherit: bool = False

    def __post_init__(self) -> None:
        key = self.key if isinstance(self.key, (list, tuple)) else []
        self.key = [k.strip() for k in key if isinstance(k, str) and k.strip()]
        for name in ("name", "status", "notes"):
            setattr(self, name, _as_text(getattr(self, name)))
        self.pov = _as_text(self.pov).strip()
        self.inherit = self.inherit is True
        for name in LIST_FIELDS:
            setattr(self, name, clean_list(getattr(self, name)))
        if self.pov:  # as on cards: the POV character is one of the characters
            match = next((c for c in self.characters if c.casefold() == self.pov.casefold()), None)
            if match is None:
                self.characters.append(self.pov)
            else:
                self.pov = match

    def is_blank(self) -> bool:
        """Nothing set: such a route isn't saved."""
        return not (self.name.strip() or self.tags or self.characters or self.pov
                    or self.locations or self.status.strip() or self.notes.strip() or self.inherit)


def _one_line(value: Any) -> str:
    """Text for a strand field's name or value: one line, trimmed."""
    return " ".join(_as_text(value).splitlines()).strip()


def clean_fields(raw: Any) -> tuple[tuple[str, str], ...]:
    """A strand's custom fields as ordered (name, value) pairs. Accepts the saved form
    ({"name", "value"} objects) or pairs. Nameless entries are dropped and a name used
    twice (ignoring case) keeps its first entry. A tuple of tuples, so the shallow
    copies taken for undo snapshots and saving never share anything mutable."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, (list, tuple)) else ():
        if isinstance(entry, dict):
            name, value = entry.get("name"), entry.get("value")
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            name, value = entry
        else:
            continue
        name = _one_line(name)
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append((name, _one_line(value)))
    return tuple(out)


def merge_fields(target, moving) -> tuple[tuple[str, str], ...]:
    """The fields of a strand renamed onto `target`'s strand: the target's fields in
    its order with its values kept (an empty one takes the other's), then the fields
    only the renamed strand had."""
    theirs = {name.casefold(): value for name, value in moving}
    merged = [(name, value or theirs.get(name.casefold(), "")) for name, value in target]
    have = {name.casefold() for name, _ in target}
    merged += [(name, value) for name, value in moving if name.casefold() not in have]
    return tuple(merged)


def apply_fields(source, target, names=None, with_values: bool = False) -> tuple[tuple[str, str], ...]:
    """`target`'s fields after "applying" `source`'s to it: the source fields it lacks
    (ignoring case) are added at the end in the source's order, empty unless
    `with_values`. Existing fields keep their place, and their values, except that
    `with_values` fills an empty one. `names` limits which source fields are applied."""
    wanted = None if names is None else {n.strip().casefold() for n in names}
    picked = [(n, v) for n, v in source if wanted is None or n.casefold() in wanted]
    given = {n.casefold(): v for n, v in picked}
    out = [(n, v or given.get(n.casefold(), "")) if with_values else (n, v) for n, v in target]
    have = {n.casefold() for n, _ in target}
    out += [(n, v if with_values else "") for n, v in picked if n.casefold() not in have]
    return tuple(out)


@dataclass
class StrandInfo:
    """A strand's own details (Strands panel): a description, a picture and custom
    fields. `kind` is the field it belongs to (tags, characters, locations or status);
    names match ignoring case. `picture` is a path to an image file. On the board (in
    the app) it's absolute; in a saved file it's relative to the board's folder when
    the image is inside that folder (so the two can move together), else absolute.
    `fields` are the user's own (name, value) pairs, in order (see clean_fields)."""
    kind: str = "tags"
    name: str = ""
    description: str = ""
    picture: str = ""
    fields: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        self.kind = self.kind if self.kind in RENAMABLE_FIELDS else ""
        self.name = _as_text(self.name).strip()
        self.description = _as_text(self.description)
        self.picture = _as_text(self.picture).strip()
        self.fields = clean_fields(self.fields)

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.name.casefold()

    def is_blank(self) -> bool:
        # Field names alone count: applying fields to a strand must survive a save.
        return not (self.description.strip() or self.picture or self.fields)

    def to_dict(self) -> dict[str, Any]:
        """As saved: fields become {"name", "value"} objects."""
        return {"kind": self.kind, "name": self.name, "description": self.description,
                "picture": self.picture,
                "fields": [{"name": n, "value": v} for n, v in self.fields]}


def clean_strands(raw: Any) -> list[StrandInfo]:
    """Saved strand details: well-formed, not blank, one per strand (the first wins)."""
    out: list[StrandInfo] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        info = _build(StrandInfo, entry)
        if info.kind and info.name and not info.is_blank() and info.key not in seen:
            seen.add(info.key)
            out.append(info)
    return out


@dataclass
class StrandGroup:
    """A named set of strands of one kind (Strands panel), e.g. a "Family" of
    characters. A strand can be in several groups. A group is a shortcut: adding one to a
    card adds its members, and cards never refer to the group, so the story tools and
    filters only ever see strands. Names match ignoring case, within a kind. `members` keep
    the board's spellings, in the order they were added; they count as strands on the
    board (see BoardData.all_values), so a member no card uses stays listed."""
    kind: str = "tags"
    name: str = ""
    members: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        self.kind = self.kind if self.kind in RENAMABLE_FIELDS else ""
        self.name = _one_line(self.name)
        # A tuple, so undo snapshots and copies never share a list later edits could change.
        self.members = tuple(clean_list(self.members if isinstance(self.members, (list, tuple)) else []))
        self.description = _as_text(self.description)

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.name.casefold()

    def has(self, strand: str) -> bool:
        key = strand.strip().casefold()
        return any(m.casefold() == key for m in self.members)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "members": list(self.members),
                "description": self.description}


def clean_strand_groups(raw: Any) -> list[StrandGroup]:
    """Saved strand groups: well-formed, named, one per name within a kind (the first
    wins). Empty groups are kept: a group can be made before anything is put in it."""
    out: list[StrandGroup] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        group = _build(StrandGroup, entry)
        if group.kind and group.name and group.key not in seen:
            seen.add(group.key)
            out.append(group)
    return out


def picture_for_file(picture: str, board_dir: Path | None) -> str:
    """How a picture path is written into a board file in `board_dir`: relative if the
    image is inside that folder (or below it), otherwise absolute."""
    if not picture or board_dir is None or not os.path.isabs(picture):
        return picture
    try:
        rel = os.path.relpath(picture, board_dir)
    except ValueError:  # another drive
        return picture
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return picture
    return Path(rel).as_posix()


def picture_from_file(picture: str, board_dir: Path | None) -> str:
    """A picture path read from a board file in `board_dir`, made absolute."""
    if not picture or os.path.isabs(picture) or board_dir is None:
        return picture
    return os.path.normpath(os.path.join(board_dir, picture))


def strands_for_file(board: BoardData, board_dir: Path | None) -> BoardData:
    """The board ready to write into `board_dir` (its strand pictures made relative
    where they can be). Returns a copy; `board` is unchanged."""
    return replace(board, strands=[replace(s, picture=picture_for_file(s.picture, board_dir))
                                   for s in board.strands])


def strands_from_file(board: BoardData, board_dir: Path | None) -> BoardData:
    """A board just read from a file in `board_dir`, with absolute picture paths (in place)."""
    for s in board.strands:
        s.picture = picture_from_file(s.picture, board_dir)
    return board


def copy_route(route: RouteData) -> RouteData:
    """An independent copy (its lists aren't shared)."""
    return replace(route, key=list(route.key), tags=list(route.tags),
                   characters=list(route.characters), locations=list(route.locations))


def clean_routes(raw: Any) -> list[RouteData]:
    """Saved route fields: well-formed, not blank, one per route (the first wins)."""
    out: list[RouteData] = []
    seen: set[tuple[str, ...]] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        route = _build(RouteData, entry)
        key = tuple(route.key)
        if key and key not in seen and not route.is_blank():
            seen.add(key)
            out.append(route)
    return out


@dataclass
class BoardData:
    cards: list[CardData] = field(default_factory=list)
    connections: list[ConnectionData] = field(default_factory=list)
    # Board-specific colors added via "Custom color…", in the order they were added.
    custom_colors: list[str] = field(default_factory=list)
    # Tags/characters/locations/statuses kept on the board even when no card uses
    # them (e.g. imported from another board); offered as suggestions.
    saved_values: dict[str, list[str]] = field(default_factory=dict)
    # How this board is shown (see DISPLAY_DEFAULTS); saved with the board.
    display: dict[str, Any] = field(default_factory=lambda: dict(DISPLAY_DEFAULTS))
    # Fields given to routes (only routes with something set).
    routes: list[RouteData] = field(default_factory=list)
    # Strands' own descriptions and pictures (only those with something set).
    strands: list[StrandInfo] = field(default_factory=list)
    # Named sets of strands (see StrandGroup), in the order they were made.
    strand_groups: list[StrandGroup] = field(default_factory=list)
    # The format version the board was read from (not saved: saving writes the
    # current version). Higher than FORMAT_VERSION means a newer app wrote it.
    source_version: int = field(default=FORMAT_VERSION, compare=False, repr=False)
    # What loading had to repair, in words ("1 damaged arrow skipped"): shown once on
    # opening, never saved.
    load_notes: list[str] = field(default_factory=list, compare=False, repr=False)

    def all_values(self, field_name: str) -> list[str]:
        """Every value of a field on this board: used on cards or saved."""
        extra = list(self.saved_values.get(field_name, ()))
        extra += [spelling for spelling, _ in count_values(self.routes, field_name).values()]
        extra += [s.name for s in self.strands if s.kind == field_name]
        extra += [m for g in self.strand_groups if g.kind == field_name for m in g.members]
        return board_values(self.cards, field_name, extra)

    @property
    def from_newer_version(self) -> bool:
        return self.source_version > FORMAT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": APP_ID,
            "version": FORMAT_VERSION,
            "custom_colors": list(self.custom_colors),
            "saved_values": {k: list(v) for k, v in self.saved_values.items() if v},
            "display": clean_display(self.display),
            "cards": [asdict(c) for c in self.cards],
            "connections": [asdict(c) for c in self.connections],
            "routes": [asdict(r) for r in self.routes if r.key and not r.is_blank()],
            "strands": [s.to_dict() for s in self.strands if s.kind and s.name and not s.is_blank()],
            "strand_groups": [g.to_dict() for g in self.strand_groups if g.kind and g.name],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> BoardData:
        if not isinstance(raw, dict) or not isinstance(raw.get("cards"), list):
            raise ValueError("This file is not a Heddle board.")
        # One damaged entry mustn't make the whole board unopenable: skip it and say so.
        notes: list[str] = []
        cards = _build_all(CardData, raw["cards"])
        renewed = _renew_duplicate_ids(cards)  # duplicates would leave orphaned cards
        _note(notes, len(raw["cards"]) - len(cards), "damaged card", "skipped")
        _note(notes, renewed, "card", "given a new id (the id was used twice)")
        raw_conns = raw.get("connections")
        raw_conns = raw_conns if isinstance(raw_conns, list) else []
        conns = _build_all(ConnectionData, raw_conns)
        # Arrows are keyed by id in the story tools: a reused id hid one of them.
        renewed = _renew_duplicate_ids(conns)
        _note(notes, len(raw_conns) - len(conns), "damaged arrow", "skipped")
        _note(notes, renewed, "arrow", "given a new id (the id was used twice)")
        if isinstance(raw.get("custom_colors"), list):
            customs = [c for c in raw["custom_colors"]
                       if isinstance(c, str) and _HEX_COLOR.fullmatch(c.strip())]
        else:  # older file: recover any non-preset colors cards already use
            customs = [c.color for c in cards]
        version = raw.get("version")
        version = version if isinstance(version, int) and not isinstance(version, bool) else 1
        return cls(cards=cards, connections=conns, custom_colors=_dedupe_colors(customs),
                   saved_values=clean_saved_values(raw.get("saved_values")),
                   display=clean_display(raw.get("display")), routes=clean_routes(raw.get("routes")),
                   strands=clean_strands(raw.get("strands")),
                   strand_groups=clean_strand_groups(raw.get("strand_groups")),
                   source_version=version, load_notes=notes)


REPLACE_FIELDS = (("title", "Titles"), ("description", "Descriptions"), ("notes", "Notes"))


def _replace_pattern(find: str, match_case: bool) -> re.Pattern | None:
    if not find:
        return None
    return re.compile(re.escape(find), 0 if match_case else re.IGNORECASE)


def replaceable(card: CardData, field_name: str) -> bool:
    """Strand cards are named by their strand (Rename Strand changes those), and
    groups have no description of their own."""
    if card.kind == KIND_STRAND:
        return False
    return not (card.kind == KIND_GROUP and field_name == "description")


def count_replacements(cards, find: str, fields, match_case: bool = False) -> tuple[int, int]:
    """(matches, cards with a match) that replace_text would change."""
    pattern = _replace_pattern(find, match_case)
    if pattern is None:
        return 0, 0
    total = touched = 0
    for card in cards:
        n = sum(len(pattern.findall(getattr(card, f))) for f in fields if replaceable(card, f))
        total += n
        touched += bool(n)
    return total, touched


def replace_text(cards, find: str, replacement: str, fields, match_case: bool = False) -> list[CardData]:
    """Replace `find` with `replacement` in the given text fields of each card, in
    place (ignoring case unless `match_case`). Returns the cards that changed."""
    pattern = _replace_pattern(find, match_case)
    if pattern is None:
        return []
    changed = []
    for card in cards:
        before = tuple(getattr(card, f) for f in fields)
        for f in fields:
            if replaceable(card, f):
                setattr(card, f, pattern.sub(lambda _m: replacement, getattr(card, f)))
        if tuple(getattr(card, f) for f in fields) != before:
            changed.append(card)
    return changed


def title_labels(cards) -> dict[str, str]:
    """Each card's title as lists show it: "Warden · East Ward" when another card
    has the same title (ignoring case), so the two can be told apart, else the bare
    title. A shared title outside any group stays bare: there's nothing to add."""
    cards = list(cards)
    by_id = {c.id: c for c in cards}
    counts: dict[str, int] = {}
    for c in cards:
        key = c.title.strip().casefold()
        counts[key] = counts.get(key, 0) + 1
    out = {}
    for c in cards:
        title = c.title.strip() or "Untitled"
        parent = by_id.get(c.parent)
        if counts[c.title.strip().casefold()] > 1 and parent is not None:
            title += f" · {parent.title.strip() or 'Untitled'}"
        out[c.id] = title
    return out


def apply_bulk_edit(cards: list[CardData], color: str | None = None, add_tags=(), remove_tags=(),
                    status: str | None = None, add: dict | None = None,
                    remove: dict | None = None) -> list[CardData]:
    """Edit several cards at once, in place. None / empty means "leave as is" for
    each card: color and status replace; tags, characters and locations (`add` /
    `remove`: {field: values}; add_tags / remove_tags for tags) are removed then
    added, matched case-insensitively (an existing spelling is kept). Removing a
    card's POV character clears its POV, as in the card editor. Strand cards only
    take the color: they have no values of their own. Returns the cards that changed."""
    add = {f: list(v) for f, v in (add or {}).items()}
    remove = {f: list(v) for f, v in (remove or {}).items()}
    add["tags"] = add.get("tags", []) + list(add_tags)
    remove["tags"] = remove.get("tags", []) + list(remove_tags)
    adding = {f: clean_list(add.get(f, [])) for f in BULK_LIST_FIELDS}
    removing = {f: {v.strip().casefold() for v in remove.get(f, []) if v.strip()}
                for f in BULK_LIST_FIELDS}
    changed = []
    for card in cards:
        before = (card.color, *(list(getattr(card, f)) for f in BULK_LIST_FIELDS),
                  card.status, card.pov)
        if color is not None:
            card.color = color
        if card.kind != KIND_STRAND:
            for f in BULK_LIST_FIELDS:
                if removing[f] or adding[f]:
                    kept = [v for v in getattr(card, f) if v.casefold() not in removing[f]]
                    setattr(card, f, clean_list(kept + adding[f]))
            if card.pov and card.pov.casefold() in removing["characters"]:
                card.pov = ""
            if status is not None:
                card.status = status.strip()
        after = (card.color, *(list(getattr(card, f)) for f in BULK_LIST_FIELDS),
                 card.status, card.pov)
        if after != before:
            changed.append(card)
    return changed


CLIPBOARD_MIME ="application/x-heddle-fragment"  # copied cards on the system clipboard


def clone_fragment(fragment: BoardData, keep_parents: set[str] = frozenset()) -> BoardData:
    """Copy of a board fragment with fresh ids, ready to paste: groups keep their own
    cards, arrows keep their (re-mapped) ends, and arrows to cards outside the
    fragment are dropped. A card whose group isn't in the fragment stays in that
    group only if its id is in `keep_parents`; otherwise it becomes top-level."""
    id_map = {c.id: new_id() for c in fragment.cards}
    cards = []
    for c in fragment.cards:
        if c.parent in id_map:
            parent = id_map[c.parent]
        else:
            parent = c.parent if c.parent in keep_parents else ""
        cards.append(replace(c, id=id_map[c.id], parent=parent, tags=list(c.tags),
                             characters=list(c.characters), locations=list(c.locations)))
    # replace() keeps every other arrow field (style, color, …) as it was.
    conns = [replace(e, source=id_map[e.source], target=id_map[e.target], id=new_id())
             for e in fragment.connections if e.source in id_map and e.target in id_map]
    return BoardData(cards=cards, connections=conns, custom_colors=list(fragment.custom_colors))


def clean_saved_values(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    out = {f: clean_list(raw.get(f)) for f in RENAMABLE_FIELDS}
    return {f: v for f, v in out.items() if v}


def rename_in_list(values: list[str], old: str, new: str) -> list[str]:
    """Rename (case-insensitive) within a plain value list, merging duplicates."""
    targets = {old.strip().casefold(), new.strip().casefold()}
    return clean_list([new.strip() if v.casefold() in targets else v for v in values])


def _dedupe_colors(colors: list[str]) -> list[str]:
    presets = {c.lower() for c in CARD_COLORS}
    out: list[str] = []
    for c in colors:
        c = c.strip().lower()
        if c and c not in presets and c not in out:
            out.append(c)
    return out


def _build(cls: type, raw: Any):
    """Construct a dataclass from a dict, ignoring unknown keys (forward compat)."""
    if not isinstance(raw, dict):
        raise ValueError(f"Malformed {cls.__name__} entry in board file.")
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in names})


def _build_all(cls: type, entries: list) -> list:
    """Build each entry, leaving out the ones too damaged to build (not a dict, or
    missing a required field such as an arrow's ends)."""
    out = []
    for entry in entries:
        try:
            out.append(_build(cls, entry))
        except (ValueError, TypeError, AttributeError):
            continue
    return out


def _renew_duplicate_ids(items: list) -> int:
    """Give every repeat of an id a fresh one; returns how many were renewed."""
    seen: set[str] = set()
    renewed = 0
    for item in items:
        if item.id in seen:
            item.id = new_id()
            renewed += 1
        seen.add(item.id)
    return renewed


def _note(notes: list[str], count: int, thing: str, what: str) -> None:
    if count:
        notes.append(f"{count} {thing}{'s' if count != 1 else ''} {what}")


def save_board(board: BoardData, path: Path) -> None:
    """Write atomically so a crash mid-save never corrupts the existing file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:  # e.g. target locked by a sync client; don't leave the temp file behind
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_board(path: Path) -> BoardData:
    return BoardData.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
