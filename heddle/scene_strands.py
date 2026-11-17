"""Strands on the board: strand cards, dragging a strand from the Strands panel, renaming,
saved (unused) strands and their details. Mixed into BoardScene (scene.py)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF

from .card_item import CARD_WIDTH, CardItem
from .model import (
    BUILTIN_STATUSES, BULK_LIST_FIELDS, CARD_COLORS, KIND_STRAND, CardData, apply_bulk_edit,
    board_values,
    count_values, RENAMABLE_FIELDS, clean_list,
    rename_in_list, rename_value, StrandGroup, StrandInfo, apply_fields, merge_fields,
)
from .rename_dialog import RenameDialog
from .values_dialog import COLORS_KEY

from .scene_consts import (
    MERGED_DESCRIPTIONS,
)
from .token_input import STRAND_GROUPS_KEY


class StrandsMixin:
    """Part of BoardScene: it uses the scene's own attributes and methods."""

    def _strand_card_data(self, kind: str, name: str, pos: QPointF) -> CardData:
        data = CardData(kind=KIND_STRAND, strand_kind=kind, strand=name,
                        x=pos.x() - CARD_WIDTH / 2, y=pos.y() - 20,
                        color=CARD_COLORS[len(self.cards) % len(CARD_COLORS)])
        if self.snap_to_grid:
            data.x, data.y = self.snapped(data.x), self.snapped(data.y)
        return data

    def create_strand_card(self, kind: str, name: str, pos: QPointF | None = None,
                           group: CardItem | None = None) -> CardItem:
        """Add a card standing for a strand, centred on pos (default: the middle of the
        view), inside group if given, as one undo step."""
        if pos is None:
            views = self.views()
            pos = (views[0].mapToScene(views[0].viewport().rect().center()) if views
                   else QPointF(0, 0))
        data = self._strand_card_data(kind, name, pos)
        if group is not None and group.scene() is self:
            data.parent = group.card.id
        item = self.add_card(data)
        if group is not None and group.scene() is self:
            group.refit()
        self.clearSelection()
        item.setSelected(True)
        self.mark_modified()
        return item

    # ----- drag a strand from the Strands panel onto the board -------------------
    def strand_drop_target(self, pos: QPointF) -> tuple[str, CardItem | None] | None:
        """What dropping a strand at pos would do: ("card", card) adds it to a standard
        card, ("group", group) puts a strand card inside a group, ("new", None) puts one
        on the blank board. None: refused (over a strand card, whose strand is fixed)."""
        card = next((i for i in self.items(pos) if isinstance(i, CardItem) and not i.is_group
                     and i.card_scene_rect().contains(pos)), None)
        if card is not None:
            return None if card.is_strand else ("card", card)
        group = self.group_at(pos, set())
        return ("group", group) if group is not None else ("new", None)

    def strand_drag_over(self, kind: str, name: str, pos: QPointF) -> bool:
        """A strand is dragged over pos: outline the card or group it would land on, or
        preview the strand card it would make. Returns whether a drop is accepted here."""
        target = self.strand_drop_target(pos)
        self._set_strand_hover(target[1] if target is not None else None)
        if target is not None and target[0] != "card":
            data = self._strand_card_data(kind, name, pos)
            size = CardItem(data).card_rect().size()  # laid out alone: close enough for a preview
            self._show_ghost(QRectF(QPointF(data.x, data.y), size), data.color)
        else:
            self._show_ghost(None)
        return target is not None

    def _set_strand_hover(self, hover: CardItem | None) -> None:
        """Outline the card or group a dragged strand (or strand group) would land on."""
        if hover is not self._strand_hover:
            if self._strand_hover is not None and self._strand_hover.scene() is self:
                self._strand_hover.set_drop_highlight(False)
            if hover is not None:
                hover.set_drop_highlight(True)
            self._strand_hover = hover

    def strand_drag_done(self) -> None:
        """The strand drag left the board or was dropped: no outline, no preview."""
        if self._strand_hover is not None and self._strand_hover.scene() is self:
            self._strand_hover.set_drop_highlight(False)
        self._strand_hover = None
        self._show_ghost(None)

    def drop_strand(self, kind: str, name: str, pos: QPointF) -> bool:
        """Drop a strand at pos, as one undo step: on a standard card it joins the card's
        tags, characters or locations (a status replaces the card's status); on a group
        or the blank board it becomes a strand card there. Returns whether anything
        changed; a notice says what happened when it isn't plain to see."""
        self.strand_drag_done()
        name = name.strip()
        if kind not in RENAMABLE_FIELDS or not name:
            return False
        target = self.strand_drop_target(pos)
        if target is None:
            return False
        what, item = target
        if what != "card":
            self.create_strand_card(kind, name, pos, group=item)
            return True
        card = item.card
        title = card.title or "Untitled"
        if kind == "status":
            old = card.status
            if old.casefold() == name.casefold():
                self.notice.emit(f"“{title}” already has the status {old}")
                return False
            new = replace(card, status=name)
            if old:
                self.notice.emit(f"“{title}”: status {old} → {name}")
        else:
            values = getattr(card, kind)
            if any(v.casefold() == name.casefold() for v in values):
                self.notice.emit(f"“{title}” already has {name}")
                return False
            new = replace(card, **{kind: [*values, name]})
        item.apply_data(new)  # re-lays the card out, and its group around it
        self.mark_modified()
        return True

    def strand_cards(self, kind: str, name: str) -> list[CardItem]:
        """The strand cards standing for this strand."""
        key = name.strip().casefold()
        return [i for i in self.cards.values()
                if i.is_strand and i.card.strand_kind == kind and i.card.strand.casefold() == key]

    def _refresh_strand_cards(self, kind: str, name: str) -> None:
        """A strand's description changed: its cards show it in their details."""
        for item in self.strand_cards(kind, name):
            item.refit()

    def rename_value(self, field_name: str, old: str, new: str) -> int:
        """Rename a tag/character/location/status on every card; returns cards changed."""
        self._let_go.add((field_name, old.strip().casefold()))  # the old name isn't kept
        changed = rename_value([item.card for item in self.cards.values()], field_name, old, new)
        routes_changed = rename_value(list(self.routes.values()), field_name, old, new)
        ids = {c.id for c in changed}
        for cid in ids:
            self.cards[cid].apply_data(self.cards[cid].card)
        # Tag pills can change card heights: refit the groups holding them.
        self._refit_ids({self.cards[c].card.parent for c in ids} - {""})
        saved = self.saved_values.get(field_name, [])
        renamed_saved = rename_in_list(saved, old, new)
        if renamed_saved != saved:
            self.saved_values[field_name] = renamed_saved
        details_changed = self._rename_strand_info(field_name, old, new)
        groups_changed = self._rename_in_groups(field_name, old, new)
        strand_cards = self.strand_cards(field_name, old)
        for item in strand_cards:
            if item.card.strand != new.strip():
                item.card.strand = item.card.title = new.strip()
                item.refit()  # its title, and its (possibly merged) description
        for item in self.strand_cards(field_name, new):
            item.refit()
        if (changed or routes_changed or renamed_saved != saved or details_changed or groups_changed
                or strand_cards):
            self.value_renamed.emit(field_name, old, new)
            self.mark_modified()
        return len(changed)

    def _rename_strand_info(self, kind: str, old: str, new: str) -> bool:
        """Carry a strand's details over to its new name. Renaming onto a strand that has
        details of its own merges them: both descriptions (the target's first), the
        target's picture (or the renamed one's, if the target has none) and the fields
        (the target's values kept; see model.merge_fields)."""
        old_key, new_key = (kind, old.strip().casefold()), (kind, new.strip().casefold())
        moving = self.strand_info.get(old_key)
        if moving is None or not new.strip():
            return False
        del self.strand_info[old_key]
        target = self.strand_info.get(new_key) if new_key != old_key else None
        if target is None:
            self.strand_info[new_key] = replace(moving, name=new.strip())
        else:
            texts = [t for t in (target.description.strip(), moving.description.strip()) if t]
            self.strand_info[new_key] = replace(
                target, name=new.strip(), description=MERGED_DESCRIPTIONS.join(texts),
                picture=target.picture or moving.picture,
                fields=merge_fields(target.fields, moving.fields))
        return True

    def apply_strand_fields(self, kind: str, source: str, targets, names=None,
                            with_values: bool = False) -> tuple[int, int]:
        """Copy `source`'s field names (only `names`, if given) to the `targets` strands
        of the same kind, as one undo step: fields a target lacks are added, empty
        unless `with_values`; existing ones are kept (`with_values` fills empty ones).
        The source itself and names the board doesn't have are skipped. Returns
        (strands changed, fields added)."""
        info = self.strand(kind, source)
        if info is None or not info.fields:
            return 0, 0
        spelling = {v.casefold(): v for v in self.all_values(kind)}
        changed = added = 0
        for target in dict.fromkeys(t.strip().casefold() for t in targets):
            if target == info.name.casefold() or target not in spelling:
                continue
            old = self.strand_info.get((kind, target)) or StrandInfo(kind=kind, name=spelling[target])
            fields = apply_fields(info.fields, old.fields, names, with_values)
            if fields == old.fields:
                continue
            self.strand_info[(kind, target)] = replace(old, fields=fields)
            changed += 1
            added += len(fields) - len(old.fields)
            self._refresh_strand_cards(kind, spelling[target])
        if changed:
            self.mark_modified()
        return changed, added

    # ----- strands: saved ones and their details ---------------------------------
    def all_values(self, field_name: str) -> list[str]:
        """Every strand of a field on this board: on cards, on routes, saved, or with details."""
        extra = list(self.saved_values.get(field_name, ()))
        if field_name == "status":
            extra += BUILTIN_STATUSES  # always on the board, used or not
        extra += [s for s, _ in count_values(self.routes.values(), field_name).values()]
        extra += [s.name for s in self.strand_info.values() if s.kind == field_name]
        extra += [m for g in self.strand_groups.values() if g.kind == field_name for m in g.members]
        extra += [i.card.strand for i in self.cards.values()
                  if i.is_strand and i.card.strand_kind == field_name]
        return board_values([i.card for i in self.cards.values()], field_name, extra)

    def strand_card_counts(self, kind: str) -> dict[str, int]:
        """{casefolded strand: number of strand cards standing for it} for one field."""
        out: dict[str, int] = {}
        for i in self.cards.values():
            if i.is_strand and i.card.strand_kind == kind:
                key = i.card.strand.casefold()
                out[key] = out.get(key, 0) + 1
        return out

    def strand(self, kind: str, name: str) -> StrandInfo | None:
        """A strand's details, if it has any."""
        return self.strand_info.get((kind, name.strip().casefold()))

    def set_strand_info(self, info: StrandInfo) -> bool:
        """Store a strand's description, picture and fields (one undo step); blank
        details forget them. Returns False if nothing changed."""
        if not info.kind or not info.name:
            return False
        key = info.key
        before = self.strand_info.get(key)
        if info.is_blank():
            if before is None:
                return False
            del self.strand_info[key]
        else:
            if before is not None and (before.description, before.picture, before.fields) == \
                    (info.description, info.picture, info.fields):
                return False  # the same details (however the name is spelled)
            self.strand_info[key] = replace(info, name=before.name if before else info.name)
        self._refresh_strand_cards(info.kind, info.name)
        self.mark_modified()
        return True

    def strand_usage(self, kind: str) -> dict[str, tuple[int, int]]:
        """{casefolded strand: (cards using it, routes using it)} for one field."""
        cards = count_values([i.card for i in self.cards.values()], kind)
        routes = count_values(self.routes.values(), kind)
        return {k: (cards.get(k, ("", 0))[1], routes.get(k, ("", 0))[1])
                for k in set(cards) | set(routes)}

    def unused_strands(self) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Strands nothing uses (no card or route), per field: (those without details
        — saved ones only —, those with a description, picture or fields, or in a
        strand group: someone set those up, so they're only offered on request)."""
        plain: dict[str, list[str]] = {}
        detailed: dict[str, list[str]] = {}
        for f in RENAMABLE_FIELDS:
            used = set(self.strand_usage(f)) | set(self.strand_card_counts(f))
            if f == "status":
                used |= {s.casefold() for s in BUILTIN_STATUSES}  # built in: never unused
            grouped = {m.casefold() for g in self.strand_groups.values() if g.kind == f for m in g.members}
            for name in self.all_values(f):
                key = name.casefold()
                if key in used:
                    continue
                if (f, key) in self.strand_info or key in grouped:
                    detailed.setdefault(f, []).append(name)
                elif any(v.casefold() == key for v in self.saved_values.get(f, ())):
                    plain.setdefault(f, []).append(name)
        return plain, detailed

    def color_usage(self, exclude: CardItem | None = None) -> dict[str, int]:
        """How many cards and arrows use each colour ("#rrggbb", lower case),
        not counting `exclude` (the card being edited)."""
        counts: dict[str, int] = {}
        for item in self.cards.values():
            if item is not exclude:
                key = item.card.color.lower()
                counts[key] = counts.get(key, 0) + 1
        for edge in self.edges:
            if edge.conn.color:
                key = edge.conn.color.lower()
                counts[key] = counts.get(key, 0) + 1
        return counts

    def unused_saved_values(self, with_details: bool = False) -> dict[str, list[str]]:
        """Saved strands nothing uses, per field, plus custom palette colours (under
        COLORS_KEY) that no card or arrow uses. Strands with a description, picture or fields,
        or in a strand group,
        are kept back unless `with_details`."""
        plain, detailed = self.unused_strands()
        out = {f: list(v) for f, v in plain.items()}
        if with_details:
            for f, names in detailed.items():
                out[f] = out.get(f, []) + names
        in_use = self.color_usage()
        spare = [c for c in self.custom_colors if c.lower() not in in_use]
        if spare:
            out[COLORS_KEY] = spare
        return out

    def import_values(self, values: dict[str, list[str]], colors: list[str] = (),
                      details=()) -> int:
        """Add strands (and custom colors) to the board without creating cards, with
        their descriptions and pictures from `details` (StrandInfo, absolute picture
        paths). Strands the board already has are skipped. Returns how many were added."""
        added = 0
        info = {d.key: d for d in details}
        for f, new in values.items():
            if f not in RENAMABLE_FIELDS:
                continue
            have = {v.casefold() for v in self.all_values(f)}
            fresh = [v for v in clean_list(new) if v.casefold() not in have]
            if fresh:
                self.saved_values[f] = self.saved_values.get(f, []) + fresh
                added += len(fresh)
                for v in fresh:
                    d = info.get((f, v.casefold()))
                    if d is not None and not d.is_blank():
                        self.strand_info[d.key] = replace(d, name=v)
        presets = {c.lower() for c in CARD_COLORS}
        for c in colors:
            c = c.strip().lower()
            if c and c not in presets and c not in self.custom_colors:
                self.custom_colors.append(c)
                added += 1
        if added:
            self.mark_modified()
        return added

    def remove_saved_values(self, values: dict[str, list[str]]) -> int:
        """Remove saved values (and, under COLORS_KEY, custom palette colours)."""
        removed = 0
        values = dict(values)
        colors = {c.lower() for c in values.pop(COLORS_KEY, [])}
        if colors:
            before = len(self.custom_colors)
            self.custom_colors = [c for c in self.custom_colors if c.lower() not in colors]
            removed += before - len(self.custom_colors)
        for f, gone in values.items():
            keys = {v.casefold() for v in gone}
            before = self.saved_values.get(f, [])
            after = [v for v in before if v.casefold() not in keys]
            gone_keys = {v.casefold() for v in before} - {v.casefold() for v in after}
            for key in keys:  # their details go too (a strand may have had only details)
                if self.strand_info.pop((f, key), None) is not None:
                    gone_keys.add(key)
            gone_keys |= self._drop_from_groups(f, keys)  # and their place in groups
            removed += len(gone_keys)
            self._let_go.update((f, key) for key in gone_keys)
            if after:
                self.saved_values[f] = after
            else:
                self.saved_values.pop(f, None)
        if removed:
            self.mark_modified()
        return removed

    def _kept_strands(self) -> dict[str, list[str]]:
        """Strands kept without a card using them: saved ones and ones with details."""
        out = {f: list(v) for f, v in self.saved_values.items()}
        for s in self.strand_info.values():
            out.setdefault(s.kind, []).append(s.name)
        for g in self.strand_groups.values():
            out.setdefault(g.kind, []).extend(g.members)
        return out

    # ----- strand groups -------------------------------------------------------------
    def strand_group(self, kind: str, name: str) -> StrandGroup | None:
        return self.strand_groups.get((kind, name.strip().casefold()))

    def groups_of(self, kind: str) -> list[StrandGroup]:
        """A field's strand groups, alphabetically (as the panels list them)."""
        return sorted((g for g in self.strand_groups.values() if g.kind == kind),
                      key=lambda g: g.name.casefold())

    def groups_with(self, kind: str, strand: str) -> list[StrandGroup]:
        """The groups `strand` is in, alphabetically."""
        return [g for g in self.groups_of(kind) if g.has(strand)]

    def _spelled(self, kind: str, names) -> list[str]:
        """`names` in the board's spelling where it has them (a group lists strands as
        the board writes them), duplicates dropped."""
        spelling = {v.casefold(): v for v in self.all_values(kind)}
        return clean_list([spelling.get(n.strip().casefold(), n) for n in names])

    def create_strand_group(self, kind: str, name: str, members=()) -> StrandGroup | None:
        """Make a group (one undo step). None if the name is blank or the kind already has
        a group by that name."""
        group = StrandGroup(kind, name, tuple(self._spelled(kind, members)))
        if not group.kind or not group.name or group.key in self.strand_groups:
            return None
        self.strand_groups[group.key] = group
        self.mark_modified()
        return group

    def update_strand_group(self, kind: str, name: str, *, new_name: str | None = None,
                            members=None, description: str | None = None) -> bool:
        """Rename a group, or replace its members or description (one undo step). Members
        it loses stay on the board as saved strands (see _keep_dropped_strands). False if
        nothing changed, the group is missing, or the new name is blank or taken."""
        group = self.strand_group(kind, name)
        if group is None:
            return False
        new = replace(group,
                      name=group.name if new_name is None else new_name,
                      members=group.members if members is None else tuple(self._spelled(kind, members)),
                      description=group.description if description is None else description)
        if not new.name or (new.key != group.key and new.key in self.strand_groups) or new == group:
            return False
        # Rebuilt, so a renamed group keeps its place in the order they were made.
        self.strand_groups = {(new.key if k == group.key else k): (new if k == group.key else g)
                              for k, g in self.strand_groups.items()}
        self.mark_modified()
        return True

    def add_to_strand_group(self, kind: str, name: str, strands) -> int:
        """Put strands in a group (one undo step); returns how many weren't in it already."""
        group = self.strand_group(kind, name)
        if group is None:
            return 0
        fresh = [s for s in self._spelled(kind, strands) if not group.has(s)]
        if fresh:
            self.update_strand_group(kind, name, members=[*group.members, *fresh])
        return len(fresh)

    def remove_from_strand_group(self, kind: str, name: str, strands) -> int:
        """Take strands out of a group (one undo step); returns how many were in it."""
        group = self.strand_group(kind, name)
        if group is None:
            return 0
        keys = {s.strip().casefold() for s in strands}
        kept = [m for m in group.members if m.casefold() not in keys]
        if len(kept) != len(group.members):
            self.update_strand_group(kind, name, members=kept)
        return len(group.members) - len(kept)

    def delete_strand_group(self, kind: str, name: str) -> bool:
        """Forget a group (one undo step). Its strands stay on the board."""
        group = self.strand_group(kind, name)
        if group is None:
            return False
        del self.strand_groups[group.key]
        self.mark_modified()
        return True

    def strand_group_choices(self) -> dict[str, dict[str, list[str]]]:
        """{field: {group name: members}} for the strand groups that can be added to
        cards: tags, characters and locations (a card has one status, so a group of
        statuses is only for filtering)."""
        return {f: {g.name: list(g.members) for g in self.groups_of(f)}
                for f in BULK_LIST_FIELDS if self.groups_of(f)}

    def strand_suggestions(self) -> dict:
        """What the editors offer: every strand per field, and the strand groups (under
        STRAND_GROUPS_KEY) whose strands a box can add in one go."""
        out: dict = {f: self.all_values(f) for f in RENAMABLE_FIELDS}
        out[STRAND_GROUPS_KEY] = self.strand_group_choices()
        return out

    def add_strands_to_cards(self, items, kind: str, names, what: str = "") -> int:
        """Add strands to cards' tags, characters or locations, as one undo step (strand
        cards have none of their own and are skipped). The status bar says what happened,
        naming the strands as `what`. Returns how many cards changed."""
        names = self._spelled(kind, names) if kind in BULK_LIST_FIELDS else []
        targets = [i for i in items if not i.is_strand and i.card.id in self.cards]
        what = what or ", ".join(names)
        if not names or not targets:
            if targets and kind in BULK_LIST_FIELDS:
                self.notice.emit(f"{what[0].upper() + what[1:]} has no strands yet")
            return 0
        changed = apply_bulk_edit([i.card for i in targets], add={kind: names})
        ids = {c.id for c in changed}
        for i in targets:
            if i.card.id in ids:
                i.apply_data(i.card)  # tags can change a card's height
        self._refit_ids({i.card.parent for i in targets if i.card.id in ids} - {""})
        if changed:
            self.mark_modified()
            self.notice.emit(f"Added {what} to {len(changed)} card" + ("" if len(changed) == 1 else "s"))
        else:
            self.notice.emit(("That card" if len(targets) == 1 else "Those cards") + f" already had {what}")
        return len(changed)

    def add_strand_group_to_cards(self, items, kind: str, name: str) -> int:
        """Add every strand in a strand group to cards (one undo step)."""
        group = self.strand_group(kind, name)
        if group is None:
            return 0
        return self.add_strands_to_cards(items, kind, group.members, f"the strand group “{group.name}”")

    # ----- drag a strand group onto a card ---------------------------------------
    def strand_group_drag_over(self, kind: str, pos: QPointF) -> bool:
        """A strand group is dragged over pos: only a standard card takes it (it adds the
        group's strands); groups, strand cards and the blank board don't."""
        target = self.strand_drop_target(pos) if kind in BULK_LIST_FIELDS else None
        card = target[1] if target is not None and target[0] == "card" else None
        self._set_strand_hover(card)
        self._show_ghost(None)
        return card is not None

    def drop_strand_group(self, kind: str, name: str, members, pos: QPointF) -> bool:
        """Drop a strand group at pos: on a standard card its strands join the card's (one
        undo step). `members` come with the drag, so it works from another window's board."""
        self.strand_drag_done()
        target = self.strand_drop_target(pos) if kind in BULK_LIST_FIELDS else None
        if target is None or target[0] != "card":
            return False
        return self.add_strands_to_cards([target[1]], kind, members, f"the strand group “{name}”") > 0

    def _rename_in_groups(self, kind: str, old: str, new: str) -> bool:
        """A renamed strand keeps its place in its groups; renaming onto a strand
        already in the same group merges the two entries."""
        if not new.strip():
            return False
        changed = False
        for key, g in list(self.strand_groups.items()):
            if g.kind == kind and g.has(old):
                renamed = tuple(rename_in_list(list(g.members), old, new))
                if renamed != g.members:
                    self.strand_groups[key] = replace(g, members=renamed)
                    changed = True
        return changed

    def _drop_from_groups(self, kind: str, keys: set[str]) -> set[str]:
        """Take strands (casefolded) out of every group; returns the ones that were in one."""
        dropped: set[str] = set()
        for key, g in list(self.strand_groups.items()):
            if g.kind != kind:
                continue
            kept = tuple(m for m in g.members if m.casefold() not in keys)
            if kept != g.members:
                dropped |= {m.casefold() for m in g.members} - {m.casefold() for m in kept}
                self.strand_groups[key] = replace(g, members=kept)
        return dropped

    def open_rename_dialog(self, field_name: str = "tags", value: str = "") -> int:
        self.dialog_opening.emit()
        dialog = RenameDialog([item.card for item in self.cards.values()], field_name, value,
                              self._dialog_parent(), self._kept_strands())
        if not dialog.exec():
            return 0
        return self.rename_value(dialog.field_name(), dialog.old_value(), dialog.new_value())
