"""Export a board as Markdown (pure Python, no Qt).

Two layouts:

* document: groups become headings (nested by depth) and each card is a heading
  with its text underneath;
* outline: nested bullets, one per group and card.

Cards are listed in story order (along the arrows; cards without arrows follow in
reading order), and a card's branches are spelled out ("Next: Exile (if she
refuses) · Coronation") so the branching survives in plain text. A route read in
the Path Reader can be exported on its own, step by step.

Titles, arrow labels and values are escaped so characters like * _ # [ don't turn
into formatting; descriptions and notes are left as written (you may have used
Markdown in them on purpose).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .graph import StoryGraph
from .model import BoardData, CardData

DOCUMENT = "document"
OUTLINE = "outline"


@dataclass
class TextOptions:
    layout: str = DOCUMENT
    descriptions: bool = True
    details: bool = True       # POV, characters, locations, status, tags
    notes: bool = False
    next_steps: bool = True    # where each card leads (branches and arrow labels)


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~])")


def _clean(text: str) -> str:
    return " ".join(text.split())


def md_escape(text: str) -> str:
    """Plain text made safe to drop into a Markdown line."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _title(card: CardData) -> str:
    return md_escape(_clean(card.title)) or "Untitled"


def _values(values) -> str:
    return ", ".join(md_escape(v) for v in values)


def _detail_parts(card: CardData) -> list[str]:
    parts = []
    if card.pov:
        parts.append(f"**POV:** {md_escape(card.pov)}")
    others = [c for c in card.characters if c.casefold() != card.pov.casefold()]
    if others:
        parts.append(f"**Characters:** {_values(others)}")
    if card.locations:
        parts.append(f"**Locations:** {_values(card.locations)}")
    if card.status:
        parts.append(f"**Status:** {md_escape(card.status)}")
    if card.tags:
        parts.append(f"**Tags:** {_values(card.tags)}")
    return parts


class _Exporter:
    def __init__(self, board: BoardData, graph: StoryGraph, options: TextOptions,
                 include: set[str] | None):
        self.board, self.graph, self.opt = board, graph, options
        self.cards = {c.id: c for c in board.cards}
        self.labels = {c.id: md_escape(_clean(c.label)) for c in board.connections}
        rank = {i: n for n, i in enumerate(graph.arrow_order())}
        self.children: dict[str, list[str]] = {}
        for c in board.cards:
            if c.kind == "strand":
                continue  # strand cards aren't part of a story document
            parent = c.parent if c.parent in self.cards else ""
            self.children.setdefault(parent, []).append(c.id)

        def first_rank(cid: str) -> tuple:
            """Where a card or group comes in the story (a group: its first card)."""
            ids = [cid] + sorted(graph.contents(cid))
            ranks = [rank[i] for i in ids if i in rank]
            card = self.cards[cid]
            return (min(ranks) if ranks else len(rank), card.y, card.x)

        for kids in self.children.values():
            kids.sort(key=first_rank)
        # Limit to the chosen cards, keeping the groups that hold them.
        self.include = None
        if include is not None:
            keep = set(include)
            for cid in include:
                keep |= graph.contents(cid)
            keep |= graph.containers_of(keep)
            self.include = keep

    def kept(self, cid: str) -> bool:
        return self.include is None or cid in self.include

    def next_steps(self, cid: str, following: str | None) -> str:
        """'Next: A (label) · B', or '' when the only way on is simply the next card listed."""
        steps = []
        for nxt in self.graph.succ.get(cid, []):
            labels = [self.labels.get(a, "") for a in self.graph.step_arrows(cid, nxt)]
            label = next((x for x in labels if x), "")
            steps.append((nxt, label))
        if not steps:
            return ""
        if len(steps) == 1 and not steps[0][1] and steps[0][0] == following:
            return ""
        shown = [f"{_title(self.cards[n])} ({label})" if label else _title(self.cards[n])
                 for n, label in steps]
        return "Next: " + " · ".join(shown)

    def walk(self, parent: str = "", depth: int = 0):
        """(card id, depth) for everything kept, groups before their contents."""
        for cid in self.children.get(parent, []):
            if not self.kept(cid):
                continue
            yield cid, depth
            if self.children.get(cid):
                yield from self.walk(cid, depth + 1)

    def render(self, heading: str) -> str:
        items = list(self.walk())
        cards_listed = [cid for cid, _ in items if not self.children.get(cid)]
        following = {a: b for a, b in zip(cards_listed, cards_listed[1:])}
        lines = [f"# {md_escape(heading)}", ""]
        for cid, depth in items:
            card = self.cards[cid]
            is_group = bool(self.children.get(cid)) or card.kind == "group"
            nxt = self.next_steps(cid, following.get(cid)) if self.opt.next_steps else ""
            if self.opt.layout == OUTLINE:
                lines += self._outline(card, depth, is_group, nxt)
            else:
                lines += self._document(card, depth, is_group, nxt)
        return "\n".join(lines).rstrip() + "\n"

    def _document(self, card: CardData, depth: int, is_group: bool, nxt: str) -> list[str]:
        level = min(depth + 2, 6)
        out = [f"{'#' * level} {_title(card)}", ""]
        if self.opt.details and _detail_parts(card):
            out += [" · ".join(_detail_parts(card)), ""]
        if self.opt.descriptions and not is_group and card.description.strip():
            out += [card.description.strip(), ""]
        if self.opt.notes and card.notes.strip():
            out += ["> " + line if line else ">" for line in card.notes.strip().splitlines()] + [""]
        if nxt:
            out += [f"*{nxt}*", ""]
        return out

    def _outline(self, card: CardData, depth: int, is_group: bool, nxt: str) -> list[str]:
        pad = "  " * depth
        head = f"{pad}- **{_title(card)}**"
        if self.opt.descriptions and not is_group and card.description.strip():
            head += f": {_clean(card.description)}"
        out = [head]
        sub = pad + "  - "
        if self.opt.details:
            out += [sub + part for part in _detail_parts(card)]
        if self.opt.notes and card.notes.strip():
            out.append(sub + "*Notes:* " + _clean(card.notes))
        if nxt:
            out.append(sub + nxt)
        return out


def export_text(board: BoardData, graph: StoryGraph, heading: str,
                options: TextOptions | None = None, include: set[str] | None = None) -> str:
    """The board (or just the cards in `include`, with the groups holding them) as
    Markdown, in story order."""
    return _Exporter(board, graph, options or TextOptions(), include).render(heading)


def export_route(board: BoardData, route: list[str], via: list[str], heading: str,
                 options: TextOptions | None = None) -> str:
    """A route read in the Path Reader, step by step, with the arrow label that led
    to each step."""
    opt = options or TextOptions()
    cards = {c.id: c for c in board.cards}
    lines = [f"# {md_escape(heading)}", ""]
    for n, (cid, label) in enumerate(zip(route, via), 1):
        label = md_escape(label)
        card = cards.get(cid)
        if card is None:
            continue
        if opt.layout == OUTLINE:
            head = f"{n}. **{_title(card)}**"
            if label and opt.next_steps:
                head += f" *(via “{label}”)*"
            if opt.descriptions and card.description.strip():
                head += f": {_clean(card.description)}"
            lines.append(head)
            if opt.details:
                lines += ["   - " + part for part in _detail_parts(card)]
            if opt.notes and card.notes.strip():
                lines.append("   - *Notes:* " + _clean(card.notes))
            continue
        lines += [f"## {n}. {_title(card)}", ""]
        if label and opt.next_steps:
            lines += [f"*via “{label}”*", ""]
        if opt.details and _detail_parts(card):
            lines += [" · ".join(_detail_parts(card)), ""]
        if opt.descriptions and card.description.strip():
            lines += [card.description.strip(), ""]
        if opt.notes and card.notes.strip():
            lines += ["> " + line if line else ">" for line in card.notes.strip().splitlines()] + [""]
    return "\n".join(lines).rstrip() + "\n"
