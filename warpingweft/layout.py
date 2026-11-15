"""Auto-arrange for a group's cards (pure Python, no Qt).

Cards connected by arrows form a chain (a connected component). Each chain is
laid out left-to-right in arrow order on its own row; where a chain branches,
the cards at the same step stack in a column, centred in the row. Separate
chains are stacked vertically, keeping their current top-to-bottom order.
Cycles are tolerated: back-edges are ignored for ordering. Within each step,
cards start in their current order and are then reordered to reduce crossed
arrows (see _order_in_layers).

Unconnected cards don't form chains: they're gathered into one block after the
chains that runs the same way as the arrows (a row left-to-right; a column when
arranging top-to-bottom), or, with grid=True, wraps into a roughly square grid.
When that block holds both nested groups and plain cards, the groups keep the
row (column) to themselves and the plain cards fill the space beside the run of
smaller groups at its end, wrapping where the groups' row (column) ends: see
_place_mixed.

With by_color=True, each chain is further split into horizontal lanes, one per
card color: a card keeps its arrow-order column but sits in its color's lane.
Lanes are ordered by where each color first appears along the chain, so a story
that alternates between plotlines zig-zags between rows.

Arrow labels get room: the gap between two steps widens to fit the longest label on
the arrows between them (its width left-to-right, its height top-to-bottom).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .graph import longest_path_layers

H_GAP = 70.0    # between steps in a chain (leaves room for the arrow)
V_GAP = 30.0    # between branches stacked in the same column
ROW_GAP = 50.0  # between separate chains
SAME_SIZE = 30.0  # groups whose depth differs by less than this count as one size
# Around an arrow label: the source's handle (7), the arrowhead (13), and clear arrow
# either side of the label (about 14 each).
LABEL_MARGIN = 48.0


@dataclass
class Node:
    id: str
    w: float
    h: float
    x: float = 0.0  # current position, used only to keep a stable, familiar order
    y: float = 0.0
    color: str = ""  # lane key when arranging by color
    group: bool = False  # a nested group (kept apart from plain cards when unconnected)


def arrange(nodes: list[Node], edges: list[tuple[str, str]], by_color: bool = False,
            vertical: bool = False, grid: bool = False,
            labels: dict[tuple[str, str], tuple[float, float]] | None = None,
            ) -> dict[str, tuple[float, float]]:
    """Return {node id: (x, y)} top-left positions relative to (0, 0).

    vertical=True rotates the whole layout: chains run top-to-bottom, branches
    and colour lanes sit side by side, separate chains become columns, and
    unconnected cards form a column. grid=True wraps unconnected cards into a grid.
    labels gives the (width, height) of each arrow's label, keyed like `edges`:
    the gap between two steps widens to fit the labels on the arrows between them."""
    rank = reading_rank(nodes)  # on the board as it is, whichever way it's laid out
    labels = labels or {}
    if vertical:
        # Lay out the transposed problem horizontally, then swap the axes back.
        flipped = [Node(n.id, n.h, n.w, n.y, n.x, n.color, n.group) for n in nodes]
        room = {k: h for k, (_, h) in labels.items()}
        placed = _arrange(flipped, edges, by_color, grid, rank, room)
        return {i: (y, x) for i, (x, y) in placed.items()}
    return _arrange(nodes, edges, by_color, grid, rank, {k: w for k, (w, _) in labels.items()})


def reading_rank(nodes: list[Node]) -> dict[str, int]:
    """Each node's place in reading order, as you'd read the board by eye: in lines
    from top to bottom, each line left to right. Nodes are on the same line when they
    overlap vertically by at least half the smaller height (of the node, or of the
    line so far), so things side by side keep their left-to-right order even if
    they're a few pixels out of level, while a slightly ragged column stays a column."""
    lines: list[list] = []  # [top, bottom, nodes]
    for n in sorted(nodes, key=lambda n: (n.y, n.x)):
        top, bottom = n.y, n.y + n.h
        if lines:
            line = lines[-1]
            overlap = min(line[1], bottom) - max(line[0], top)
            if overlap >= 0.5 * min(n.h, line[1] - line[0]) and overlap > 0:
                line[0], line[1] = min(line[0], top), max(line[1], bottom)
                line[2].append(n)
                continue
        lines.append([top, bottom, [n]])
    order = [n.id for _, _, members in lines for n in sorted(members, key=lambda n: (n.x, n.y))]
    return {i: k for k, i in enumerate(order)}


def _arrange(nodes: list[Node], edges: list[tuple[str, str]], by_color: bool, grid: bool,
             rank: dict[str, int], room: dict[tuple[str, str], float]
             ) -> dict[str, tuple[float, float]]:
    """Lay out left-to-right. `rank` is reading order on the board (reading_rank):
    separate chains, and unconnected cards, keep that order. `room`: how much
    space each arrow's label needs along the chain."""
    by_id = {n.id: n for n in nodes}
    succ: dict[str, list[str]] = {n.id: [] for n in nodes}
    # Neighbours in the order the arrows were given (a dict keeps that order and
    # ignores repeats). A set of ids would be walked in an order that changes from
    # run to run with Python's string hashing, so tied cards could swap places.
    adj: dict[str, dict[str, None]] = {n.id: {} for n in nodes}
    for s, t in edges:
        if s in by_id and t in by_id and s != t and t not in succ[s]:
            succ[s].append(t)
            adj[s][t] = None
            adj[t][s] = None

    components: list[list[str]] = []
    seen: set[str] = set()
    for n in sorted(nodes, key=lambda n: (n.y, n.x)):
        if n.id in seen:
            continue
        seen.add(n.id)
        stack, comp = [n.id], []
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        components.append(comp)
    components.sort(key=lambda comp: min(rank[i] for i in comp))

    loose = sorted((c[0] for c in components if len(c) == 1), key=rank.__getitem__)
    chains = [c for c in components if len(c) > 1]

    positions: dict[str, tuple[float, float]] = {}
    row_top = 0.0
    for comp in chains:
        layer = _layers(comp, succ, by_id)
        rank = _order_in_layers(comp, layer, succ, by_id)
        gaps = _step_gaps(comp, layer, succ, room)
        if by_color:
            row_top += _place_color_lanes(comp, layer, rank, by_id, positions, row_top, gaps) + ROW_GAP
            continue
        columns: dict[int, list[str]] = {}
        for i in sorted(comp, key=lambda i: rank[i]):
            columns.setdefault(layer[i], []).append(i)
        col_w = {k: max(by_id[i].w for i in ids) for k, ids in columns.items()}
        col_h = {k: sum(by_id[i].h for i in ids) + V_GAP * (len(ids) - 1) for k, ids in columns.items()}
        row_h = max(col_h.values())
        x = 0.0
        for k in sorted(columns):
            y = row_top + (row_h - col_h[k]) / 2
            for i in columns[k]:
                positions[i] = (x, y)
                y += by_id[i].h + V_GAP
            x += col_w[k] + gaps.get(k, H_GAP)
        row_top += row_h + ROW_GAP
    if loose:
        _place_loose(loose, by_id, positions, row_top, grid, by_color)
    return positions


def _place_loose(ids: list[str], by_id: dict[str, Node], positions: dict[str, tuple[float, float]],
                 top: float, grid: bool, by_color: bool) -> None:
    """Unconnected cards: one row (or a grid with grid=True) below the chains. With
    by_color, each color gets its own row/grid, in order of first appearance."""
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(by_id[i].color if by_color else "", []).append(i)
    y = top
    for group in groups.values():
        mixed = any(by_id[i].group for i in group) and not all(by_id[i].group for i in group)
        place = _place_mixed if mixed else _place_block
        y += place(group, by_id, positions, y, grid) + V_GAP


def _place_mixed(ids: list[str], by_id: dict[str, Node], positions: dict[str, tuple[float, float]],
                 top: float, grid: bool) -> float:
    """Unconnected groups and plain cards together (described left-to-right; it's
    turned for top-to-bottom). The groups go in a row, in order. The plain cards
    go below the groups from some group k to the end of the row, starting just
    under the tallest of those and wrapping into a new row where the groups' row
    ends. k is the earliest (so the most room) giving the smallest overall block,
    give or take a SAME_SIZE-deep strip, which puts the cards beside the run of smaller groups at the
    end, or under the whole row if the groups are all much the same size. With
    grid=True the cards also wrap after a roughly square number per row. Returns
    the block's height."""
    groups = [i for i in ids if by_id[i].group]
    cards = [i for i in ids if not by_id[i].group]
    xs, x = [], 0.0
    for i in groups:
        xs.append(x)
        x += by_id[i].w + V_GAP
    row_end = x - V_GAP
    per_row = math.ceil(math.sqrt(len(cards))) if grid else len(cards)
    widest = max(by_id[i].w for i in cards)

    def cards_from(k: int):
        """Place the cards under groups[k:]: (positions, block width, block height)."""
        left = xs[k]
        if row_end - left < widest:  # too narrow for some card: not an option
            return None
        y = top + max(by_id[i].h for i in groups[k:]) + V_GAP
        placed, x, row_h, n_in_row = {}, left, 0.0, 0
        for i in cards:
            n = by_id[i]
            if n_in_row and (x + n.w > row_end or n_in_row >= per_row):
                x, y, row_h, n_in_row = left, y + row_h + V_GAP, 0.0, 0
            placed[i] = (x, y)
            x += n.w + V_GAP
            row_h = max(row_h, n.h)
            n_in_row += 1
        right = max(px + by_id[i].w for i, (px, _) in placed.items())
        bottom = max(py + by_id[i].h for i, (_, py) in placed.items())
        return placed, max(row_end, right), max(bottom, top + max(by_id[i].h for i in groups)) - top

    options = [(k, cards_from(k)) for k in range(len(groups))]
    options = [(k, o) for k, o in options if o is not None] or [(0, _cards_after(groups, cards, by_id, xs, top))]
    # Saving less than a SAME_SIZE-deep strip across the block isn't worth moving the
    # cards off the start: groups a few pixels apart (a card with a character line is
    # a little taller) should read as "all the same size".
    smallest = min(o[1] * o[2] for _, o in options)
    slack = SAME_SIZE * max(o[1] for _, o in options)
    k, (placed, width, height) = next((k, o) for k, o in options if o[1] * o[2] <= smallest + slack)
    for i, x in zip(groups, xs):
        positions[i] = (x, top)
    positions.update(placed)
    return height


def _cards_after(groups, cards, by_id, xs, top):
    """Fallback (a card wider than the whole groups' row): the cards in a row under it."""
    y = top + max(by_id[i].h for i in groups) + V_GAP
    placed, x = {}, 0.0
    for i in cards:
        placed[i] = (x, y)
        x += by_id[i].w + V_GAP
    width = max(xs[-1] + by_id[groups[-1]].w, x - V_GAP)
    return placed, width, y + max(by_id[i].h for i in cards) - top


def _place_block(ids: list[str], by_id: dict[str, Node], positions: dict[str, tuple[float, float]],
                 top: float, grid: bool) -> float:
    """Lay ids out in rows of `cols` (all in one row unless grid), aligned in columns;
    returns the block's height."""
    cols = math.ceil(math.sqrt(len(ids))) if grid else len(ids)
    rows = [ids[k:k + cols] for k in range(0, len(ids), cols)]
    col_w = [max(by_id[r[c]].w for r in rows if c < len(r)) for c in range(cols)]
    y = top
    for row in rows:
        x = 0.0
        for c, i in enumerate(row):
            positions[i] = (x, y)
            x += col_w[c] + V_GAP
        y += max(by_id[i].h for i in row) + V_GAP
    return y - V_GAP - top


def _order_in_layers(comp: list[str], layer: dict[str, int], succ: dict[str, list[str]],
                     by_id: dict[str, Node], sweeps: int = 4) -> dict[str, int]:
    """Order the cards within each step column to reduce crossed arrows.

    Starts from the cards' current top-to-bottom order, then sweeps forward and
    backward, sorting each column by the average position of each card's
    neighbours in the column(s) just placed (the barycentre heuristic). A new
    order is kept only if it strictly reduces crossings, so a layout that's
    already clean, or a manual order that crosses no more, is left alone.
    Returns each card's index within its column."""
    members = set(comp)
    nbrs: dict[str, set[str]] = {i: set() for i in comp}
    edges: list[tuple[str, str]] = []
    for u in comp:
        for v in succ[u]:
            if v in members and v != u and layer[u] != layer[v]:
                nbrs[u].add(v)
                nbrs[v].add(u)
                edges.append((u, v) if layer[u] < layer[v] else (v, u))

    columns: dict[int, list[str]] = {}
    for i in sorted(comp, key=lambda i: (by_id[i].y, by_id[i].x)):
        columns.setdefault(layer[i], []).append(i)
    keys = sorted(columns)
    pos = {i: k for col in columns.values() for k, i in enumerate(col)}

    def crossings() -> int:
        # Two arrows between the same pair of columns cross when their ends are
        # in opposite order on the two sides.
        by_pair: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for a, b in edges:
            by_pair.setdefault((layer[a], layer[b]), []).append((pos[a], pos[b]))
        total = 0
        for ends in by_pair.values():
            for k, (a1, b1) in enumerate(ends):
                for a2, b2 in ends[k + 1:]:
                    total += (a1 - a2) * (b1 - b2) < 0
        return total

    best, best_crossings = dict(pos), crossings()
    for sweep in range(sweeps if best_crossings else 0):  # already clean: nothing to do
        forward = sweep % 2 == 0
        for col_key in (keys[1:] if forward else list(reversed(keys[:-1]))):
            col = columns[col_key]

            def barycentre(i: str) -> float:
                # (used straight away, so the loop variables can't change under it)
                ref = [pos[n] for n in nbrs[i]
                       if (layer[n] < col_key if forward else layer[n] > col_key)]  # noqa: B023
                return sum(ref) / len(ref) if ref else pos[i]
            order = {i: (barycentre(i), pos[i]) for i in col}  # ties keep the current order
            col.sort(key=order.__getitem__)
            for k, i in enumerate(col):
                pos[i] = k
        c = crossings()
        if c < best_crossings:
            best, best_crossings = dict(pos), c
        if best_crossings == 0:
            break
    return best


def _step_gaps(comp: list[str], layer: dict[str, int], succ: dict[str, list[str]],
               room: dict[tuple[str, str], float]) -> dict[int, float]:
    """{step k: gap after it} where an arrow between steps k and k + 1 has a label
    that needs more than the usual H_GAP (with LABEL_MARGIN around it)."""
    gaps: dict[int, float] = {}
    for s in comp:
        for t in succ[s]:
            need = room.get((s, t), 0.0)
            a, b = sorted((layer[s], layer.get(t, layer[s])))
            if need > 0 and b - a == 1:
                gaps[a] = max(gaps.get(a, H_GAP), need + LABEL_MARGIN)
    return gaps


def _place_color_lanes(comp: list[str], layer: dict[str, int], rank: dict[str, int],
                       by_id: dict[str, Node], positions: dict[str, tuple[float, float]],
                       top: float, gaps: dict[int, float]) -> float:
    """Place one chain with a lane per color; returns the chain's total height."""
    first_seen: dict[str, tuple[int, float]] = {}
    for i in comp:
        key = (layer[i], by_id[i].y)
        c = by_id[i].color
        if c not in first_seen or key < first_seen[c]:
            first_seen[c] = key
    lanes = sorted(first_seen, key=lambda c: first_seen[c])
    lane_of = {c: n for n, c in enumerate(lanes)}

    cells: dict[tuple[int, int], list[str]] = {}
    for i in sorted(comp, key=lambda i: rank[i]):
        cells.setdefault((lane_of[by_id[i].color], layer[i]), []).append(i)

    def cell_h(ids: list[str]) -> float:
        return sum(by_id[i].h for i in ids) + V_GAP * (len(ids) - 1)

    col_w: dict[int, float] = {}
    lane_h: dict[int, float] = {}
    for (lane, col), ids in cells.items():
        col_w[col] = max(col_w.get(col, 0.0), max(by_id[i].w for i in ids))
        lane_h[lane] = max(lane_h.get(lane, 0.0), cell_h(ids))
    col_x: dict[int, float] = {}
    x = 0.0
    for col in sorted(col_w):
        col_x[col] = x
        x += col_w[col] + gaps.get(col, H_GAP)
    lane_y: dict[int, float] = {}
    y = top
    for lane in range(len(lanes)):
        lane_y[lane] = y
        y += lane_h[lane] + V_GAP

    for (lane, col), ids in cells.items():
        cy = lane_y[lane]  # top-aligned so a lane reads as a clean row
        for i in ids:
            positions[i] = (col_x[col], cy)
            cy += by_id[i].h + V_GAP
    return y - V_GAP - top


def _layers(comp: list[str], succ: dict[str, list[str]], by_id: dict[str, Node]) -> dict[str, int]:
    """Longest-path layering after dropping back-edges (shared with the story graph)."""
    return longest_path_layers(comp, succ, lambda i: (by_id[i].x, by_id[i].y))
