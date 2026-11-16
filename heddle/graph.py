"""The story as a graph: what comes before or after what (pure Python, no Qt).

Arrows connect cards and groups. For reading a story, a group with cards in it
isn't a stop of its own; it stands for its contents:

* an arrow INTO a group leads to the group's *entry* cards;
* an arrow OUT OF a group leaves from its *exit* cards.

A group chooses those with arrows drawn inside its own frame: an arrow from the
group to a card inside it marks a first card, and one from a card inside it to the
group marks a last card. These marker arrows aren't steps of the story themselves.
Without markers, the entry cards are the members no other member leads to (so all
of them if the group has no arrows inside), and the exit cards are the members that
lead to no other member.

Nested groups expand the same way, all the way down to cards. Empty groups are
ordinary stops. The resulting card-to-card "flow" is what path highlighting,
character threads, story checks and export all walk.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cached_property

from .model import KIND_GROUP, KIND_STRAND, CardData, ConnectionData


def longest_path_layers(comp: list[str], succ: dict[str, list[str]],
                        order_key: Callable[[str], tuple]) -> dict[str, int]:
    """Step number for each node of a connected component: the length of the longest
    arrow path reaching it, after dropping back-edges (found by DFS, so cycles are
    tolerated). `order_key` makes the result stable: DFS starts from sources first,
    in that order. Used by auto-arrange and by arrow_order()."""
    members = set(comp)
    order = sorted(comp, key=order_key)
    indeg = {i: 0 for i in comp}
    for u in comp:
        for v in succ.get(u, ()):
            if v in members:
                indeg[v] += 1

    dag: dict[str, list[str]] = {i: [] for i in comp}
    state: dict[str, int] = {}  # 1 = on stack, 2 = done
    for root in [i for i in order if indeg[i] == 0] + order:  # sources first
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(succ.get(root, ())))]
        while stack:
            u, it = stack[-1]
            v = next(it, None)
            if v is None:
                state[u] = 2
                stack.pop()
                continue
            if v not in members or state.get(v) == 1:  # outside, or a back-edge (cycle)
                continue
            dag[u].append(v)
            if v not in state:
                state[v] = 1
                stack.append((v, iter(succ.get(v, ()))))

    remaining = {i: 0 for i in comp}
    for u in comp:
        for v in dag[u]:
            remaining[v] += 1
    layer = {i: 0 for i in comp}
    queue = deque(i for i in order if remaining[i] == 0)
    while queue:
        u = queue.popleft()
        for v in dag[u]:
            layer[v] = max(layer[v], layer[u] + 1)
            remaining[v] -= 1
            if remaining[v] == 0:
                queue.append(v)
    return layer


@dataclass(frozen=True)
class PathCount:
    count: int          # distinct start-to-end routes (each cycle walked at most once)
    has_cycles: bool    # if True, looping round a cycle allows more


LOOP_JOIN = "+"  # joins a loop's card ids (sorted) into one stop of a route key


@dataclass(frozen=True)
class Route:
    """One way through the story from a start to an end. Each stop is a single
    card, or a loop's cards in story order (a loop is one stop, as when counting)."""
    stops: tuple[tuple[str, ...], ...]

    @cached_property
    def key(self) -> tuple[str, ...]:
        """Identifies the route across edits: a stop's card id, or a loop's ids
        sorted and joined with LOOP_JOIN. Worked out once: the Routes panel reads
        it many times per refresh."""
        return tuple(s[0] if len(s) == 1 else LOOP_JOIN.join(sorted(s)) for s in self.stops)

    @property
    def cards(self) -> list[str]:
        return [i for stop in self.stops for i in stop]

    @property
    def has_loop(self) -> bool:
        return any(len(s) > 1 for s in self.stops)


class StoryGraph:
    """Built once from a board's cards and arrows; cheap to query afterwards."""

    def __init__(self, cards: Iterable[CardData], connections: Iterable[ConnectionData]):
        self.cards: dict[str, CardData] = {c.id: c for c in cards}
        self._order_cache: dict[frozenset | None, tuple[str, ...]] = {}  # arrow_order results
        self.members: dict[str, list[str]] = {}
        for c in self.cards.values():
            p = c.parent
            if p and p != c.id and p in self.cards and self.cards[p].kind == KIND_GROUP:
                self.members.setdefault(p, []).append(c.id)
        # Cards marked "not part of the story", and everything inside such a group:
        # their arrows are ignored, so they take no part in paths, checks, routes,
        # introductions or threads.
        # Strand cards are always outside, and so is a group holding nothing but
        # outside cards (e.g. a map made of location cards).
        self.outside: set[str] = set()
        for cid, c in self.cards.items():
            if c.outside_story or c.kind == KIND_STRAND:
                self.outside.add(cid)
                self.outside |= self.contents(cid)
        changed = True
        while changed:
            changed = False
            for gid, members in self.members.items():
                if gid not in self.outside and members and all(m in self.outside for m in members):
                    self.outside.add(gid)
                    changed = True
        # Arrows between cards that both exist (and are in the story), without
        # duplicates or self-loops.
        self.arrows: dict[str, tuple[str, str]] = {}
        seen_pairs: set[tuple[str, str]] = set()
        for conn in connections:
            pair = (conn.source, conn.target)
            if (conn.source in self.cards and conn.target in self.cards
                    and conn.source not in self.outside and conn.target not in self.outside
                    and conn.source != conn.target and pair not in seen_pairs):
                seen_pairs.add(pair)
                self.arrows[conn.id] = pair
        # Arrows between a group and a card inside it mark first / last cards.
        self.first_marks: dict[str, list[str]] = {}
        self.last_marks: dict[str, list[str]] = {}
        self.boundary_arrows: set[str] = set()
        for cid, (s, t) in self.arrows.items():
            if self.is_inside(t, s):
                self.first_marks.setdefault(s, []).append(t)
                self.boundary_arrows.add(cid)
            elif self.is_inside(s, t):
                self.last_marks.setdefault(t, []).append(s)
                self.boundary_arrows.add(cid)
        self._entries_cache: dict[str, list[str]] = {}
        self._route_cache = None  # see _route_parts()
        self._exits_cache: dict[str, list[str]] = {}

        # Each arrow's flow ends: cards it leaves from and cards it arrives at.
        self.arrow_ends: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        self._step_arrows: dict[tuple[str, str], list[str]] = {}  # (a, b) -> arrow ids
        self.succ: dict[str, list[str]] = {i: [] for i in self.nodes()}
        self.pred: dict[str, list[str]] = {i: [] for i in self.nodes()}
        for cid, (s, t) in self.arrows.items():
            if cid in self.boundary_arrows:
                # A marker, not a step: it lights up along with the card it marks.
                inner = tuple(self.entry_cards(t) if t != s and self.is_inside(t, s)
                              else self.exit_cards(s))
                self.arrow_ends[cid] = (inner, inner)
                continue
            froms, tos = tuple(self.exit_cards(s)), tuple(self.entry_cards(t))
            self.arrow_ends[cid] = (froms, tos)
            for a in froms:
                for b in tos:
                    if a == b:
                        continue
                    self._step_arrows.setdefault((a, b), []).append(cid)
                    if b not in self.succ[a]:
                        self.succ[a].append(b)
                        self.pred[b].append(a)

    # ----- structure ----------------------------------------------------------
    def is_container(self, card_id: str) -> bool:
        """A group with cards in it: it stands for its contents rather than being a stop."""
        return bool(self.members.get(card_id))

    def nodes(self) -> list[str]:
        """The stops a story passes through: cards, plus empty groups."""
        return [i for i in self.cards if not self.is_container(i)]

    def contents(self, group_id: str) -> set[str]:
        """Every card and group inside a group, at any depth."""
        out: set[str] = set()
        stack = [group_id]
        while stack:
            for m in self.members.get(stack.pop(), ()):
                if m not in out:
                    out.add(m)
                    stack.append(m)
        return out

    def containers_of(self, ids: Iterable[str]) -> set[str]:
        """Groups holding any of `ids`, at any depth."""
        out: set[str] = set()
        for i in ids:
            seen = {i}
            p = self.cards[i].parent if i in self.cards else ""
            while p and p in self.cards and p not in seen:
                seen.add(p)
                out.add(p)
                p = self.cards[p].parent
        return out

    def is_inside(self, card_id: str, group_id: str) -> bool:
        """Is card_id inside group_id, at any depth?"""
        cur, seen = self.cards[card_id].parent if card_id in self.cards else "", {card_id}
        while cur and cur in self.cards and cur not in seen:
            if cur == group_id:
                return True
            seen.add(cur)
            cur = self.cards[cur].parent
        return False

    def first_cards(self, group_id: str) -> list[str]:
        """The cards a group's first-card arrows point to (empty: none marked)."""
        return list(self.first_marks.get(group_id, ()))

    def last_cards(self, group_id: str) -> list[str]:
        """The cards with last-card arrows to the group (empty: none marked)."""
        return list(self.last_marks.get(group_id, ()))

    def _direct_member(self, card_id: str, group_id: str) -> str | None:
        """The member of `group_id` that is `card_id` or holds it; None if outside."""
        cur, seen = card_id, set()
        while cur and cur in self.cards and cur not in seen:
            seen.add(cur)
            if self.cards[cur].parent == group_id:
                return cur
            cur = self.cards[cur].parent
        return None

    def _boundary(self, group_id: str, entries: bool) -> list[str]:
        """The group's marked first (entries) / last (exits) cards if it has any;
        otherwise the members with no arrow from (entries) / to (exits) another
        member, the arrows of nested groups counting for the nested group."""
        marked = (self.first_marks if entries else self.last_marks).get(group_id)
        if marked:
            return list(marked)
        # Cards outside the story are never a group's first or last cards.
        members = [m for m in self.members.get(group_id, []) if m not in self.outside]
        linked: set[str] = set()
        for cid, (s, t) in self.arrows.items():
            if cid in self.boundary_arrows:
                continue
            ms, mt = self._direct_member(s, group_id), self._direct_member(t, group_id)
            if ms is not None and mt is not None and ms != mt:
                linked.add(mt if entries else ms)
        out = [m for m in members if m not in linked]
        if not out and members:
            # Every member is led to (from) by another: the group is one big loop.
            # Enter at its top-left card and leave from its bottom-right one.
            pick = min if entries else max
            out = [pick(members, key=self._position)]
        return out

    def _expand(self, card_id: str, entries: bool, cache: dict, guard: frozenset = frozenset()) -> list[str]:
        if not self.is_container(card_id) or card_id in guard:
            return [card_id] if not self.is_container(card_id) else []
        if card_id in cache:
            return cache[card_id]
        out: list[str] = []
        for m in self._boundary(card_id, entries):
            for c in self._expand(m, entries, cache, guard | {card_id}):
                if c not in out:
                    out.append(c)
        cache[card_id] = out
        return out

    def entry_cards(self, card_id: str) -> list[str]:
        """Where an arrow into this card or group arrives (itself, if it's a stop)."""
        return self._expand(card_id, True, self._entries_cache)

    def exit_cards(self, card_id: str) -> list[str]:
        """Where an arrow out of this card or group leaves from (itself, if a stop)."""
        return self._expand(card_id, False, self._exits_cache)

    # ----- reachability -------------------------------------------------------
    def _walk(self, seeds: Iterable[str], adj: dict[str, list[str]]) -> set[str]:
        out: set[str] = set()
        queue = deque(seeds)
        while queue:
            for v in adj.get(queue.popleft(), ()):
                if v not in out:
                    out.add(v)
                    queue.append(v)
        return out

    def downstream(self, card_id: str) -> set[str]:
        """Every stop that can come after this card (or after a group's contents).
        The card itself is included only if a cycle leads back to it."""
        return self._walk(self.exit_cards(card_id), self.succ)

    def upstream(self, card_id: str) -> set[str]:
        """Every stop that can come before this card (or before a group's contents)."""
        return self._walk(self.entry_cards(card_id), self.pred)

    def arrows_within(self, ids: Iterable[str]) -> set[str]:
        """Arrows (connection ids) that link two of `ids`: one of the cards an arrow
        leaves from and one it arrives at must both be in the set."""
        ids = set(ids)
        return {cid for cid, (froms, tos) in self.arrow_ends.items()
                if ids.intersection(froms) and ids.intersection(tos)}

    # ----- characters -------------------------------------------------------------
    def featuring(self, name: str) -> list[str]:
        """Stops whose characters include `name` (ignoring case), in story order."""
        key = name.strip().casefold()
        rank = {i: n for n, i in enumerate(self.arrow_order())}
        found = [i for i in self.nodes() if i not in self.outside
                 and key in {c.casefold() for c in self.cards[i].characters}]
        return sorted(found, key=rank.__getitem__)

    def introductions(self) -> dict[str, list[str]]:
        """{card id: characters that card introduces}. A card introduces a character
        when it features them and no card on any route leading to it does. Branches
        each get their own introduction; a card reached again round a loop doesn't
        count. Only cards on arrow chains take part: with no arrows there's no
        "before", so nothing is introduced."""
        # Each loop is treated as a single step (its cards all lead to one another),
        # so "featured somewhere before" can be passed forward along the arrows in
        # one pass, for every character at once as bits of an integer. The work grows
        # with the number of cards and arrows, however big the loops.
        linked = [i for i in self.nodes() if self.succ[i] or self.pred[i]]
        comps = self.strongly_connected()
        comp_of = {i: n for n, comp in enumerate(comps) for i in comp}
        bit: dict[str, int] = {}                 # character (casefolded) -> bit number
        featured = [0] * len(comps)              # characters on each loop / card
        for i in linked:
            for name in self.cards[i].characters:
                featured[comp_of[i]] |= 1 << bit.setdefault(name.casefold(), len(bit))

        # before[n]: characters featured on some step leading (eventually) to step n.
        next_steps: list[set[int]] = [set() for _ in comps]
        waiting = [0] * len(comps)               # steps leading here not yet passed on
        for u, vs in self.succ.items():
            for v in vs:
                a, b = comp_of[u], comp_of[v]
                if a != b and b not in next_steps[a]:
                    next_steps[a].add(b)
                    waiting[b] += 1
        before = [0] * len(comps)
        queue = deque(n for n in range(len(comps)) if waiting[n] == 0)
        while queue:
            a = queue.popleft()
            carry = before[a] | featured[a]
            for b in next_steps[a]:
                before[b] |= carry
                waiting[b] -= 1
                if waiting[b] == 0:
                    queue.append(b)

        # A card introduces a character if nothing before its step features them;
        # on a loop, only the loop's earliest card (in story order) featuring them does.
        rank = {i: n for n, i in enumerate(self.arrow_order())}
        claimed: set[tuple[int, int]] = set()   # (loop, character bit) already introduced
        out: dict[str, list[str]] = {}
        for i in sorted(linked, key=rank.__getitem__):
            n = comp_of[i]
            for name in self.cards[i].characters:
                b = bit[name.casefold()]
                if before[n] >> b & 1:
                    continue  # featured on a step leading here
                if len(comps[n]) > 1:
                    if (n, b) in claimed:
                        continue  # an earlier card on this loop has them
                    claimed.add((n, b))
                out.setdefault(i, []).append(name)
        # Each card lists its introductions in its own character order.
        for c, names in out.items():
            order = {n.casefold(): k for k, n in enumerate(self.cards[c].characters)}
            names.sort(key=lambda n: order.get(n.casefold(), len(order)))
        return out

    def step_arrows(self, a: str, b: str) -> list[str]:
        """The arrows (connection ids) that make the step from stop a to stop b."""
        return list(self._step_arrows.get((a, b), ()))

    def markers_for(self, ids) -> set[str]:
        """First/last-card arrows marking any of these cards."""
        ids = set(ids)
        return {cid for cid in self.boundary_arrows if ids.intersection(self.arrow_ends[cid][0])}

    # ----- order ----------------------------------------------------------------
    def _position(self, i: str) -> tuple[float, float]:
        c = self.cards[i]
        return (c.y, c.x)

    def components(self, ids: Iterable[str] | None = None) -> list[list[str]]:
        """Connected chains among `ids` (default: every stop), ignoring arrow
        direction, in reading order of their top-left card."""
        pool = set(self.nodes() if ids is None else ids) & set(self.succ)
        comps: list[list[str]] = []
        seen: set[str] = set()
        for start in sorted(pool, key=self._position):
            if start in seen:
                continue
            seen.add(start)
            comp, stack = [], [start]
            while stack:
                u = stack.pop()
                comp.append(u)
                for v in self.succ[u] + self.pred[u]:
                    if v in pool and v not in seen:
                        seen.add(v)
                        stack.append(v)
            comps.append(comp)
        return comps

    def arrow_order(self, ids: Iterable[str] | None = None) -> list[str]:
        """Stops in story order: chain by chain (in reading order), and within a
        chain by step along the arrows, then top-to-bottom, left-to-right for cards
        at the same step. Cards without arrows simply follow reading order. Cached:
        the graph never changes once built, and many story tools ask for this."""
        key = None if ids is None else frozenset(ids)
        cached = self._order_cache.get(key)
        if cached is not None:
            return list(cached)
        out: list[str] = []
        for comp in self.components(ids):
            members = set(comp)
            sub = {u: [v for v in self.succ[u] if v in members] for u in comp}
            layer = longest_path_layers(comp, sub, lambda i: (self.cards[i].x, self.cards[i].y))
            out.extend(sorted(comp, key=lambda i: (layer[i], *self._position(i))))
        self._order_cache[key] = tuple(out)
        return out

    def outline(self, by_story: bool = True) -> dict[str, list[str]]:
        """Every card, strand cards included, under the group it sits in ("" for the
        board itself), as the Outline export and the Card List show them. With
        `by_story`, siblings come in story order (arrow_order: chain by chain, a group
        where its first card comes, a card without arrows where it sits in reading
        order); otherwise in reading order of their top-left corners (for boards that
        just sort things into groups)."""
        children: dict[str, list[str]] = {}
        for cid, c in self.cards.items():
            parent = c.parent if c.parent in self.cards and c.parent != cid else ""
            children.setdefault(parent, []).append(cid)
        if by_story:
            rank = {i: n for n, i in enumerate(self.arrow_order())}
            unranked = len(rank)

            def key(cid: str) -> tuple:
                ranks = [rank[i] for i in (cid, *self.contents(cid)) if i in rank]
                return (min(ranks) if ranks else unranked, *self._position(cid))
        else:
            key = self._position
        for kids in children.values():
            kids.sort(key=key)
        return children

    # ----- cycles and paths --------------------------------------------------------
    def _restricted(self, ids: Iterable[str] | None) -> tuple[list[str], dict[str, list[str]]]:
        """Stops and arrows-between-them, limited to `ids` (default: everything)."""
        if ids is None:
            return self.nodes(), self.succ
        pool = set(ids) & set(self.succ)
        nodes = [i for i in self.nodes() if i in pool]
        return nodes, {u: [v for v in self.succ[u] if v in pool] for u in nodes}

    def strongly_connected(self, ids: Iterable[str] | None = None) -> list[list[str]]:
        """Tarjan's algorithm, iteratively. Every stop (of `ids`, default all) is in
        exactly one component; only arrows between those stops count."""
        nodes, succ = self._restricted(ids)
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        comps: list[list[str]] = []
        counter = 0
        for root in nodes:
            if root in index:
                continue
            work = [(root, iter(succ[root]))]
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            on_stack.add(root)
            while work:
                u, it = work[-1]
                v = next(it, None)
                if v is not None:
                    if v not in index:
                        index[v] = low[v] = counter
                        counter += 1
                        stack.append(v)
                        on_stack.add(v)
                        work.append((v, iter(succ[v])))
                    elif v in on_stack:
                        low[u] = min(low[u], index[v])
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[u])
                if low[u] == index[u]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp.append(w)
                        if w == u:
                            break
                    comps.append(comp)
        return comps

    def cycles(self, ids: Iterable[str] | None = None) -> list[list[str]]:
        """Groups of stops that loop back on each other, each in story order."""
        loops = [c for c in self.strongly_connected(ids) if len(c) > 1]
        order = {i: n for n, i in enumerate(self.arrow_order())}
        loops = [sorted(c, key=order.__getitem__) for c in loops]
        return sorted(loops, key=lambda c: order[c[0]])

    def _condensation(self, ids: Iterable[str] | None = None):
        """The stops with each loop squashed into one: (components, successors of
        each component, in-degree of each, components with any arrow)."""
        ids = None if ids is None else list(ids)
        comps = self.strongly_connected(ids)
        _, succ = self._restricted(ids)
        comp_of = {i: n for n, c in enumerate(comps) for i in c}
        csucc: dict[int, set[int]] = {n: set() for n in range(len(comps))}
        indeg = {n: 0 for n in range(len(comps))}
        for u, vs in succ.items():
            for v in vs:
                a, b = comp_of[u], comp_of[v]
                if a != b and b not in csucc[a]:
                    csucc[a].add(b)
                    indeg[b] += 1
        linked = {n for n in csucc if csucc[n]} | {b for n in csucc for b in csucc[n]}
        return comps, csucc, indeg, linked

    def count_paths(self, ids: Iterable[str] | None = None) -> PathCount:
        """How many distinct routes lead from a start to an end (within `ids`, if
        given). Each cycle counts as a single stop (so looping isn't counted);
        has_cycles says if any exist."""
        comps, csucc, indeg, linked = self._condensation(ids)
        ways = {n: (1 if indeg[n] == 0 and n in linked else 0) for n in csucc}
        queue = deque(n for n in csucc if indeg[n] == 0)
        total = 0
        while queue:
            a = queue.popleft()
            if not csucc[a] and a in linked:
                total += ways[a]  # an end
            for b in csucc[a]:
                ways[b] += ways[a]
                indeg[b] -= 1
                if indeg[b] == 0:
                    queue.append(b)
        return PathCount(total, any(len(c) > 1 for c in comps))

    # ----- listing routes ----------------------------------------------------------
    def _route_parts(self):
        """Cached: the condensation, plus each component as a route stop (its cards
        in story order) and its key."""
        if self._route_cache is None:
            comps, csucc, indeg, linked = self._condensation()
            order = {i: n for n, i in enumerate(self.arrow_order())}
            stops = [tuple(sorted(c, key=lambda i: order.get(i, 0))) for c in comps]
            keys = [s[0] if len(s) == 1 else LOOP_JOIN.join(sorted(s)) for s in stops]
            self._route_cache = (stops, keys, csucc, indeg, linked)
        return self._route_cache

    def routes(self, limit: int | None = None) -> list[Route]:
        """Every route from a start to an end, in reading order (the same routes
        count_paths counts), stopping after `limit` if given. Walked without
        recursion, so very long chains are fine."""
        stops, _, csucc, indeg, linked = self._route_parts()
        pos = lambda n: self._position(stops[n][0])  # noqa: E731
        nexts = {n: sorted(csucc[n], key=pos) for n in csucc}
        sources = sorted((n for n in csucc if indeg[n] == 0 and n in linked), key=pos)
        out: list[Route] = []
        for src in sources:
            # Each frame: (component, index of the next successor to try).
            path, stack = [src], [(src, 0)]
            while stack:
                node, i = stack[-1]
                if not nexts[node]:
                    out.append(Route(tuple(stops[n] for n in path)))
                    if limit is not None and len(out) >= limit:
                        return out
                if i < len(nexts[node]):
                    stack[-1] = (node, i + 1)
                    child = nexts[node][i]
                    path.append(child)
                    stack.append((child, 0))
                else:
                    stack.pop()
                    path.pop()
        return out

    def route_for_key(self, key) -> Route | None:
        """The route with this key, if it's still a complete start-to-end route."""
        stops, keys, csucc, indeg, linked = self._route_parts()
        index = {k: n for n, k in enumerate(keys)}
        comps = [index.get(k) for k in key]
        if not comps or None in comps:
            return None
        first, last = comps[0], comps[-1]
        if indeg[first] != 0 or csucc[last] or first not in linked or last not in linked:
            return None
        if any(b not in csucc[a] for a, b in zip(comps, comps[1:])):
            return None
        return Route(tuple(stops[n] for n in comps))

    def route_arrows(self, route: Route) -> set[str]:
        """The arrows a route walks: each step between stops, the arrows inside its
        loops, and the first/last-card markers of the groups it passes through."""
        out: set[str] = set()
        for a, b in zip(route.stops, route.stops[1:]):
            for u in a:
                for v in b:
                    out.update(self.step_arrows(u, v))
        for stop in route.stops:
            if len(stop) > 1:
                out |= self.arrows_within(stop)
        return out | self.markers_for(route.cards)
