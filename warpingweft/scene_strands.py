"""Strands on the board: strand cards, dragging a strand from the Strands panel, renaming,
saved (unused) strands and their details. Mixed into BoardScene (scene.py)."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF

from .card_item import CARD_WIDTH, CardItem
from .model import (
    BUILTIN_STATUSES, CARD_COLORS, KIND_STRAND, CardData,
    board_values,
    count_values, RENAMABLE_FIELDS, clean_list,
    rename_in_list, rename_value, StrandInfo,
)
from .rename_dialog import RenameDialog
from .values_dialog import COLORS_KEY

from .scene_consts import (
    MERGED_DESCRIPTIONS,
)


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
        hover = target[1] if target is not None else None
        if hover is not self._strand_hover:
            if self._strand_hover is not None and self._strand_hover.scene() is self:
                self._strand_hover.set_drop_highlight(False)
            if hover is not None:
                hover.set_drop_highlight(True)
            self._strand_hover = hover
        if target is not None and target[0] != "card":
            data = self._strand_card_data(kind, name, pos)
            size = CardItem(data).card_rect().size()  # laid out alone: close enough for a preview
            self._show_ghost(QRectF(QPointF(data.x, data.y), size), data.color)
        else:
            self._show_ghost(None)
        return target is not None

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
        strand_cards = self.strand_cards(field_name, old)
        for item in strand_cards:
            if item.card.strand != new.strip():
                item.card.strand = item.card.title = new.strip()
                item.refit()  # its title, and its (possibly merged) description
        for item in self.strand_cards(field_name, new):
            item.refit()
        if changed or routes_changed or renamed_saved != saved or details_changed or strand_cards:
            self.value_renamed.emit(field_name, old, new)
            self.mark_modified()
        return len(changed)

    def _rename_strand_info(self, kind: str, old: str, new: str) -> bool:
        """Carry a strand's details over to its new name. Renaming onto a strand that has
        details of its own merges them: both descriptions (the target's first) and the
        target's picture (or the renamed one's, if the target has none)."""
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
                picture=target.picture or moving.picture)
        return True

    # ----- strands: saved ones and their details ---------------------------------
    def all_values(self, field_name: str) -> list[str]:
        """Every strand of a field on this board: on cards, on routes, saved, or with details."""
        extra = list(self.saved_values.get(field_name, ()))
        if field_name == "status":
            extra += BUILTIN_STATUSES  # always on the board, used or not
        extra += [s for s, _ in count_values(self.routes.values(), field_name).values()]
        extra += [s.name for s in self.strand_info.values() if s.kind == field_name]
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
        """Store a strand's description and picture (one undo step); blank details
        forget them. Returns False if nothing changed."""
        if not info.kind or not info.name:
            return False
        key = info.key
        before = self.strand_info.get(key)
        if info.is_blank():
            if before is None:
                return False
            del self.strand_info[key]
        else:
            if before is not None and (before.description, before.picture) == (info.description, info.picture):
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
        — saved ones only —, those with a description or picture)."""
        plain: dict[str, list[str]] = {}
        detailed: dict[str, list[str]] = {}
        for f in RENAMABLE_FIELDS:
            used = set(self.strand_usage(f)) | set(self.strand_card_counts(f))
            if f == "status":
                used |= {s.casefold() for s in BUILTIN_STATUSES}  # built in: never unused
            for name in self.all_values(f):
                key = name.casefold()
                if key in used:
                    continue
                if (f, key) in self.strand_info:
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
        COLORS_KEY) that no card or arrow uses. Strands with a description or picture
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
        return out

    def open_rename_dialog(self, field_name: str = "tags", value: str = "") -> int:
        self.dialog_opening.emit()
        dialog = RenameDialog([item.card for item in self.cards.values()], field_name, value,
                              self._dialog_parent(), self._kept_strands())
        if not dialog.exec():
            return 0
        return self.rename_value(dialog.field_name(), dialog.old_value(), dialog.new_value())
