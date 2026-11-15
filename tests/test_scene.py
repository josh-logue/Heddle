"""Canvas behaviour (headless Qt): groups, connections, undo, rename, deletion, text."""
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QMessageBox

import warpingweft.scene as sc
from warpingweft.card_item import MAX_DESC_LINES, WRAP, elide_lines
from warpingweft.edge_item import MAX_LABEL_WIDTH
from warpingweft.model import BoardData, CardData, ConnectionData


def titles(scene):
    return sorted(i.card.title for i in scene.cards.values())


def make_group(scene, members, **kw):
    g = scene.add_card(CardData(title=kw.pop("title", "G"), kind="group", **kw))
    scene.set_group_members(g, [m.card.id for m in members])
    return g


# ----- groups & connections -----------------------------------------------------------
def test_group_can_connect_to_its_own_members_at_any_depth(scene):
    """Group → card inside marks a first card; card inside → group marks a last card."""
    a, b = scene.add_card(CardData(title="A")), scene.add_card(CardData(title="B", x=300))
    inner = make_group(scene, [b], title="Inner", x=600)
    g = make_group(scene, [a, inner])
    outside = scene.add_card(CardData(title="Out", x=2000))
    assert scene.add_connection(g, a) is not None and scene.add_connection(a, g) is not None
    assert scene.add_connection(g, b) is not None and scene.add_connection(b, inner) is not None
    assert scene.add_connection(a, b) is not None
    assert scene.add_connection(g, outside) is not None
    assert scene.add_connection(a, a) is None  # still never to itself
    assert all(not e._line.isEmpty() for e in scene.edges)


def test_joining_a_group_keeps_arrows_to_it(scene):
    """The arrow becomes a last-card marker instead of being deleted."""
    a = scene.add_card(CardData(title="A"))
    g = make_group(scene, [a])
    c = scene.add_card(CardData(title="C", x=1500))
    scene.add_connection(c, g)
    scene.set_group_members(g, [a.card.id, c.card.id])
    assert len(scene.edges) == 1 and scene.edges[0].is_boundary()


def test_files_with_group_member_arrows_keep_them(scene):
    scene.load_board_data(BoardData(
        cards=[CardData(id="g", kind="group"), CardData(id="m", parent="g")],
        connections=[ConnectionData("g", "m"), ConnectionData("m", "g")]))
    assert len(scene.edges) == 2 and len(scene.cards) == 2
    assert all(e.is_boundary() for e in scene.edges)


def test_groups_have_no_connection_handle(scene):
    g = scene.add_card(CardData(kind="group"))
    card = scene.add_card(CardData(x=500))
    assert not g.has_port and card.has_port


def test_details_toggles_never_change_saved_group_data(scene, settle):
    b = scene.add_card(CardData(title="B", x=900, characters=["Z"]))
    man = make_group(scene, [b], title="Manual", characters=["Q"], x=860, y=-100)
    man.resize_to(420, 220)
    a = scene.add_card(CardData(title="A", characters=["X"]))
    auto = make_group(scene, [a], title="Auto", tags=["t"], characters=["Y"], x=-2000)
    settle()
    base = scene.to_board_data().to_dict()
    for item in (auto, a, man, b):
        item.set_details_visible(True)
        assert scene.to_board_data().to_dict() == base
        item.set_details_visible(False)
    assert scene.to_board_data().to_dict() == base and not scene._commit_pending


def test_old_manual_group_opens_with_the_same_frame(scene):
    scene.load_board_data(BoardData(cards=[
        CardData(id="g", kind="group", x=100, y=200, width=500, height=300),
        CardData(id="m", parent="g", x=130, y=260)]))
    assert scene.cards["g"].card_scene_rect() == QRectF(100, 200, 500, 300)


def test_dragging_a_group_moves_its_anchor_and_undo_restores(scene, settle):
    man = make_group(scene, [scene.add_card(CardData())], x=0, y=0)
    man.resize_to(500, 300)
    settle()
    start = (man.card.x, man.card.y)
    man.setPos(man.pos() + QPointF(100, 50))
    scene.handle_drop(man)
    settle()
    assert (man.card.x, man.card.y) == (start[0] + 100, start[1] + 50)
    scene.undo()
    g = scene.cards[man.card.id]
    assert (g.card.x, g.card.y) == start


# ----- undo --------------------------------------------------------------------------
def test_one_action_is_one_undo_step(scene, settle, qapp):
    a, b = scene.add_card(CardData(title="A")), scene.add_card(CardData(title="B", x=300))
    settle()
    g = scene.add_card(CardData(title="G", kind="group", x=-100, y=-100))
    scene.set_group_members(g, [a.card.id, b.card.id])
    scene.mark_modified()
    scene.auto_arrange_group(g)
    scene.mark_modified()
    qapp.processEvents()
    scene.undo()
    assert g.card.id not in scene.cards and scene.cards[a.card.id].card.parent == ""


def test_undo_restores_deleted_card_with_its_details_open(scene, settle):
    a, b = scene.add_card(CardData(title="A")), scene.add_card(CardData(title="B", x=300))
    scene.add_connection(a, b)
    settle()
    a.set_details_visible(True)
    scene.remove_card(a)
    settle()
    scene.undo()
    assert scene.cards[a.card.id].details_visible and len(scene.edges) == 1


def test_duplicate_ids_never_leave_a_ghost(scene):
    scene.add_card(CardData(id="same", title="1"))
    scene.add_card(CardData(id="same", title="2"))
    assert len(scene.to_board_data().cards) == 2


def test_failed_load_rolls_back_to_previous_board(scene, monkeypatch):
    scene.add_card(CardData(title="Keep me"))

    def boom(*a, **k):
        raise RuntimeError("simulated")
    monkeypatch.setattr(sc.BoardScene, "add_connection", boom)
    other = BoardData(cards=[CardData(id="p"), CardData(id="q")], connections=[ConnectionData("p", "q")])
    try:
        scene.load_board_data(other)
    except RuntimeError:
        pass
    assert titles(scene) == ["Keep me"]


# ----- rename & saved values ------------------------------------------------------------
def test_rename_updates_cards_and_saved_values(scene, settle):
    a = scene.add_card(CardData(characters=["Rowan"]))
    scene.saved_values = {"characters": ["Scribe"]}
    settle()
    scene.rename_value("characters", "rowan", "Rówan")
    scene.rename_value("characters", "Scribe", "The Scribe")
    assert a.card.characters == ["Rówan"] and scene.saved_values["characters"] == ["The Scribe"]


def test_import_values_skips_existing_and_unused_values_can_be_removed(scene):
    scene.add_card(CardData(tags=["School"], locations=["Harbour"]))
    added = scene.import_values({"tags": ["school", "plot"], "locations": ["Forest"],
                                 "status": ["Needs research"]}, ["#123456", "#4a7fc1"])
    assert added == 4                       # plot, Forest, Needs research, #123456
    assert scene.saved_values == {"tags": ["plot"], "locations": ["Forest"], "status": ["Needs research"]}
    assert scene.custom_colors == ["#123456"]
    # The imported colour isn't used by any card either, so it's offered for removal too.
    assert scene.unused_saved_values() == {**scene.saved_values, "custom_colors": ["#123456"]}
    assert scene.remove_saved_values({"tags": ["plot"]}) == 1 and "tags" not in scene.saved_values
    assert scene.remove_saved_values({"custom_colors": ["#123456"]}) == 1 and scene.custom_colors == []


# ----- confirming multi-item deletes ------------------------------------------------------
def test_deleting_several_items_asks_first(scene, monkeypatch):
    asked, answer = [], [QMessageBox.StandardButton.No]
    monkeypatch.setattr(sc.QMessageBox, "question",
                        staticmethod(lambda p, t, text, *a: (asked.append(text), answer[0])[1]))
    a, b, c = (scene.add_card(CardData(title=t, x=i * 300)) for i, t in enumerate("ABC"))
    e = scene.add_connection(a, b)
    c.setSelected(True)
    scene.delete_selected()                      # single item: no question
    assert not asked and "C" not in titles(scene)
    for item in (a, b, e):
        item.setSelected(True)
    scene.delete_selected()
    assert "Delete 3 items (2 cards, 1 connection)?" in asked[-1] and titles(scene) == ["A", "B"]
    answer[0] = QMessageBox.StandardButton.Yes
    scene.delete_selected()
    assert titles(scene) == []


def test_delete_group_with_contents_counts_nested_cards(scene, monkeypatch):
    asked = []
    monkeypatch.setattr(sc.QMessageBox, "question",
                        staticmethod(lambda p, t, text, *a: (asked.append(text), QMessageBox.StandardButton.Yes)[1]))
    inner = make_group(scene, [scene.add_card(CardData(title="M1"))], title="Inner", x=500)
    g = make_group(scene, [inner, scene.add_card(CardData(title="M2", x=900))])
    scene.delete_group_with_contents(g)
    assert "Delete 4 items (2 cards, 2 groups)?" in asked[-1] and not scene.cards


# ----- text fitting --------------------------------------------------------------------
def drawn(item):
    r, text, font, _ = item._blocks[0]
    fm = QFontMetricsF(font)
    return text, round(fm.boundingRect(QRectF(0, 0, r.width(), 1e6), WRAP, text).height() / fm.lineSpacing())


def test_long_descriptions_end_with_ellipsis_and_tooltip(scene):
    cases = {"prose": ("The quick brown fox jumps. " * 30, True),
             "lines": ("\n".join(f"Line {k}" for k in range(12)), True),
             "six": ("\n".join(f"Line {k}" for k in range(6)), False),
             "huge word": ("x" * 400, True),
             "short": ("Hello.", False)}
    for name, (desc, cut) in cases.items():
        item = scene.add_card(CardData(title=name, description=desc))
        text, n = drawn(item)
        assert n <= MAX_DESC_LINES and text.endswith("…") == cut and bool(item.toolTip()) == cut, name


def test_elide_lines_keeps_text_that_fits(qapp):
    from PySide6.QtGui import QFont
    assert elide_lines("a\nb", QFont(), 200, 6) == ("a\nb", False)


def test_long_arrow_labels_are_shortened(scene):
    a, b = scene.add_card(CardData()), scene.add_card(CardData(x=900))
    e = scene.add_connection(a, b)
    e.set_label("then, after a very long and winding journey through the mountains, they arrive")
    assert e._label_text.endswith("…") and e._label_rect.width() <= MAX_LABEL_WIDTH + 12.5
    assert e.toolTip().startswith("then")
    e.set_label("meets")
    assert e._label_text == "meets" and not e.toolTip()
