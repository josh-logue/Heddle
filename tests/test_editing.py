"""Basic editing features: keyboard nudging/Enter, recent files & drag-and-drop,
copy/paste/duplicate, multi-card editing, and search."""
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import heddle.main_window as mw
import heddle.scene as sc
from heddle.model import BoardData, CardData, save_board


def key(window, k, mods=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(window.view.viewport(), k, mods)


# ----- 1. keyboard ------------------------------------------------------------------------
def test_arrow_keys_nudge_the_selection(window, qapp):
    a = window.scene.add_card(CardData(x=0, y=0))
    window.show()
    window.view.setFocus()
    a.setSelected(True)
    key(window, Qt.Key.Key_Right)
    key(window, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert a.pos() == QPointF(sc.NUDGE_STEP, sc.NUDGE_FINE)


def test_nudging_a_group_moves_its_cards_and_frames_refit(window, qapp):
    s = window.scene
    m = s.add_card(CardData(title="M"))
    g = s.add_card(CardData(kind="group", x=-50, y=-80))
    s.set_group_members(g, [m.card.id])
    still = s.add_card(CardData(title="Still", x=-400, y=0))
    outer = s.add_card(CardData(kind="group", x=-100, y=-150))
    s.set_group_members(outer, [g.card.id, still.card.id])
    start_m, start_frame = QPointF(m.pos()), outer.card_scene_rect()
    g.setSelected(True)
    assert s.nudge_selected(-300, 0)               # away from "Still", which sits to its right
    assert m.pos() == start_m + QPointF(-300, 0)
    assert outer.card_scene_rect().width() > start_frame.width()   # outer frame grew to fit
    assert m.card.parent == g.card.id                            # membership unchanged


def test_a_burst_of_nudges_is_one_undo_step(window, qapp):
    s = window.scene
    a = s.add_card(CardData(x=0, y=0))
    s.mark_modified()
    qapp.processEvents()
    a.setSelected(True)
    for _ in range(5):
        s.nudge_selected(10, 0)
    assert window.isWindowModified()
    s.undo()                                     # flushes the pending burst, then undoes it
    assert s.cards[a.card.id].pos() == QPointF(0, 0)
    s.redo()
    assert s.cards[a.card.id].pos() == QPointF(50, 0)


def test_arrow_keys_scroll_when_nothing_is_selected(window, qapp):
    window.scene.add_card(CardData())
    window.show()
    window.view.setFocus()
    hs = window.view.horizontalScrollBar()
    before = hs.value()
    key(window, Qt.Key.Key_Right)
    assert hs.value() != before


def test_enter_edits_the_selected_card_or_arrow(window, qapp, monkeypatch):
    s = window.scene
    a, b = s.add_card(CardData()), s.add_card(CardData(x=400))
    e = s.add_connection(a, b)
    opened = []
    monkeypatch.setattr(sc.BoardScene, "edit_card", lambda self, c: opened.append(("card", c)))
    monkeypatch.setattr(sc.BoardScene, "edit_connection_label", lambda self, c: opened.append(("edge", c)))
    window.show()
    window.view.setFocus()
    a.setSelected(True)
    key(window, Qt.Key.Key_Return)
    s.clearSelection()
    e.setSelected(True)
    key(window, Qt.Key.Key_Enter)
    assert opened == [("card", a), ("edge", e)]


# ----- 2. recent files & drag-and-drop ------------------------------------------------------
def make_board(tmp_path, name, title="x"):
    p = tmp_path / name
    save_board(BoardData(cards=[CardData(title=title)]), p)
    return p


def test_recent_files_order_dedupe_and_limit(window, tmp_path):
    paths = [make_board(tmp_path, f"b{i}.json") for i in range(mw.RECENT_MAX + 2)]
    for p in paths:
        window.open_path(p)
    window.open_path(paths[3])                         # reopening moves it to the top
    recent = window.recent_files()
    assert len(recent) == mw.RECENT_MAX and recent[0] == paths[3].resolve()
    assert len({str(p).lower() for p in recent}) == len(recent)
    window._rebuild_recent_menu()
    labels = [a.text() for a in window.recent_menu.actions() if a.text()]
    assert labels[0] == "&1 b3.json" and "Clear List" in labels


def test_saving_adds_to_recent_and_missing_files_are_dropped(window, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "information", staticmethod(lambda *a: shown.append(a[2])))
    saved = tmp_path / "saved.json"
    assert window._write(saved)
    gone = make_board(tmp_path, "gone.json")
    window.open_path(gone)
    gone.unlink()
    window.open_recent(gone.resolve())
    assert shown and "can no longer be found" in shown[0]
    assert window.recent_files() == [saved.resolve()]


def drop(widget, files):
    """Simulate a real drag-and-drop: drag-enter (which must be accepted), then drop."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f)) for f in files])
    enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, enter)
    if not enter.isAccepted():
        return False
    ev = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)
    return ev.isAccepted()


def test_dropping_a_board_file_on_the_canvas_opens_it(window, tmp_path, monkeypatch):
    board = make_board(tmp_path, "dropped.json", title="From drop")
    other = tmp_path / "notes.txt"
    other.write_text("hi")
    window.show()
    drop(window.view.viewport(), [other])                 # not a board: ignored
    assert window.current_path is None and not window.scene.cards
    assert drop(window.view.viewport(), [board])
    assert window.current_path == board and [c.card.title for c in window.scene.cards.values()] == ["From drop"]


def test_drop_on_a_board_in_use_opens_a_new_window(window, tmp_path, monkeypatch):
    board = make_board(tmp_path, "b.json")
    window.scene.add_card(CardData(title="unsaved"))
    window.setWindowModified(True)
    asked = []
    monkeypatch.setattr(mw.MainWindow, "maybe_save", lambda self: asked.append(self) or False)
    window.open_dropped([board])
    assert window.current_path is None and window.isWindowModified()   # left as it was
    assert not asked                                                    # nothing to ask
    assert mw.window_for(board) not in (None, window)


# ----- 3. copy / paste / duplicate ---------------------------------------------------------
def test_clone_fragment_remaps_ids_parents_and_arrows():
    from heddle.model import ConnectionData, clone_fragment
    frag = BoardData(cards=[CardData(id="g", kind="group"), CardData(id="a", parent="g", tags=["t"]),
                            CardData(id="b", parent="elsewhere"), CardData(id="c", parent="kept")],
                     connections=[ConnectionData("a", "b", "x"), ConnectionData("a", "zzz")])
    out = clone_fragment(frag, keep_parents={"kept"})
    ids = [c.id for c in out.cards]
    assert not set(ids) & {"g", "a", "b", "c"} and len(set(ids)) == 4
    g, a, b, c = out.cards
    assert a.parent == g.id and b.parent == "" and c.parent == "kept"
    assert [(e.source, e.target, e.label) for e in out.connections] == [(a.id, b.id, "x")]
    a.tags.append("only on the copy")                   # lists aren't shared with the original
    assert frag.cards[1].tags == ["t"]


def build(scene):
    a = scene.add_card(CardData(title="A", tags=["t"], x=0, y=0))
    b = scene.add_card(CardData(title="B", x=400, y=0))
    outside = scene.add_card(CardData(title="Out", x=900, y=0))
    scene.add_connection(a, b, "next")
    scene.add_connection(b, outside)
    g = scene.add_card(CardData(title="G", kind="group", x=-60, y=-90))
    scene.set_group_members(g, [a.card.id, b.card.id])
    return a, b, outside, g


def titles(scene):
    return sorted(i.card.title for i in scene.cards.values())


def test_copy_paste_a_group_brings_its_cards_and_inner_arrows(window, qapp):
    s = window.scene
    a, b, outside, g = build(s)
    g.setSelected(True)
    assert window.copy()
    pasted = window.paste(QPointF(3000, 3000))
    assert pasted == 3 and titles(s) == ["A", "A", "B", "B", "G", "G", "Out"]
    new_g = next(i for i in s.selectedItems())
    assert new_g.card.title == "G" and new_g is not g and len(s.members_of(new_g)) == 2
    labels = sorted(e.conn.label for e in s.edges)
    assert labels == ["", "next", "next"]                  # B->Out wasn't copied
    assert new_g.card_scene_rect().left() == 3000 and new_g.card_scene_rect().top() >= 2900


def test_paste_onto_a_group_joins_it(window, qapp):
    s = window.scene
    a, b, outside, g = build(s)
    outside.setSelected(True)
    window.copy()
    window.paste(g.card_scene_rect().center())
    copy = next(i for i in s.selectedItems())
    assert copy.card.title == "Out" and copy.card.parent == g.card.id


def test_duplicate_keeps_the_original_group_and_is_offset(window, qapp):
    s = window.scene
    a, b, outside, g = build(s)
    a.setSelected(True)
    window.act_duplicate.trigger()
    copy = next(i for i in s.selectedItems())
    assert copy is not a and copy.card.parent == g.card.id
    assert copy.pos() == a.pos() + QPointF(sc.PASTE_OFFSET, sc.PASTE_OFFSET)
    assert copy.card.tags == ["t"] and copy.card.tags is not a.card.tags


def test_cut_is_one_undo_step_and_pastes_back(window, qapp):
    s = window.scene
    a, b, outside, g = build(s)
    s.mark_modified()
    qapp.processEvents()
    g.setSelected(True)
    assert window.cut()
    qapp.processEvents()
    assert titles(s) == ["Out"]
    s.undo()
    assert titles(s) == ["A", "B", "G", "Out"] and len(s.edges) == 2
    s.redo()
    window.paste(QPointF(0, 2000))
    assert titles(s) == ["A", "B", "G", "Out"]


def test_paste_between_windows(window, qapp):
    a, *_ = build(window.scene)
    window.scene.add_card(CardData(title="Custom", color="#123456", x=2000))
    window.scene.custom_colors = ["#123456"]
    for item in window.scene.cards.values():
        item.setSelected(item.card.title in ("A", "Custom"))
    window.copy()
    other = mw.MainWindow()
    try:
        assert other.paste(QPointF(0, 0)) == 2
        assert sorted(i.card.title for i in other.scene.cards.values()) == ["A", "Custom"]
        assert other.scene.custom_colors == ["#123456"]
    finally:
        other.setWindowModified(False)
        other.close()


def test_paste_ignores_other_clipboard_content(window, qapp):
    QApplication.clipboard().setText("just some text")
    assert window.paste(QPointF(0, 0)) == 0 and not window.can_paste()


# ----- 4. editing several cards ----------------------------------------------------------
def test_apply_bulk_edit_rules():
    from heddle.model import apply_bulk_edit
    a = CardData(tags=["Act 1", "plot"], status="Draft", color="#4a7fc1")
    b = CardData(tags=["PLOT"], status="Final", color="#d9822b")
    c = CardData(tags=["x"])
    changed = apply_bulk_edit([a, b, c], add_tags=["plot", "New"], remove_tags=["act 1"])
    assert a.tags == ["plot", "New"] and b.tags == ["PLOT", "New"] and c.tags == ["x", "plot", "New"]
    assert (a.status, b.status, a.color, b.color) == ("Draft", "Final", "#4a7fc1", "#d9822b")
    assert len(changed) == 3
    assert apply_bulk_edit([a, b], status="Revised", color="#123456") == [a, b]
    assert a.status == b.status == "Revised" and a.color == b.color == "#123456"
    assert apply_bulk_edit([a, b], status="Revised") == []          # nothing actually changed
    apply_bulk_edit([a], status="")
    assert a.status == ""                                              # blank clears


def test_multi_edit_dialog_applies_to_all_selected(window, qapp, monkeypatch):
    import heddle.multi_edit as me
    s = window.scene
    a = s.add_card(CardData(title="A", tags=["old"], status="Draft"))
    b = s.add_card(CardData(title="B", tags=["keep"], status="Final", x=400))
    g = s.add_card(CardData(title="G", kind="group", x=-60, y=-90))
    s.set_group_members(g, [a.card.id])
    s.mark_modified()
    qapp.processEvents()

    def fill(self):
        assert self.windowTitle() == "Edit 2 cards"
        self.color_check.setChecked(True)
        self._swatches.buttons()[3].setChecked(True)
        self.add_tags.add_value("Act 2")
        self.remove_tags.add_value("OLD")
        self.status_combo.setCurrentText("Revised")
        self.accept()
        return self.result()
    monkeypatch.setattr(me.MultiEditDialog, "exec", fill)
    a.setSelected(True)
    b.setSelected(True)
    window.show()
    window.view.setFocus()
    key(window, Qt.Key.Key_Return)                     # Enter with several cards selected
    from heddle.model import CARD_COLORS
    assert a.card.tags == ["Act 2"] and b.card.tags == ["keep", "Act 2"]
    assert a.card.status == b.card.status == "Revised"
    assert a.card.color == b.card.color == CARD_COLORS[3]
    assert g.card_scene_rect().contains(a.card_scene_rect())   # frame refit to the taller card
    qapp.processEvents()
    s.undo()
    assert s.cards[a.card.id].card.tags == ["old"] and s.cards[b.card.id].card.status == "Final"


def test_multi_edit_colour_choice_is_explicit(qapp):
    from heddle.multi_edit import MultiEditDialog
    d = MultiEditDialog(2)
    assert d._swatches.checkedButton() is None and d.color() is None   # nothing pre-picked
    d._swatches.buttons()[2].click()
    assert d.color_check.isChecked() and d.color() == d._swatches.buttons()[2].color_name
    d.color_check.setChecked(False)
    assert d._swatches.checkedButton() is None and d.color() is None


def test_multi_edit_defaults_change_nothing(window, monkeypatch):
    import heddle.multi_edit as me
    s = window.scene
    a = s.add_card(CardData(tags=["t"], status="Draft", color="#123456"))
    b = s.add_card(CardData(x=400))
    monkeypatch.setattr(me.MultiEditDialog, "exec", lambda self: (self.accept(), self.result())[1])
    a.setSelected(True)
    b.setSelected(True)
    assert s.edit_selected_cards() == 0
    assert (a.card.tags, a.card.status, a.card.color) == (["t"], "Draft", "#123456")


# ----- 5. search -------------------------------------------------------------------------
def test_search_cards_fields_case_and_snippets():
    from heddle.filters import search_cards
    cards = [CardData(id="1", title="The Lighthouse"),
             CardData(id="2", title="x", description="She climbs the\nLIGHTHOUSE stairs at dawn"),
             CardData(id="3", title="y", notes="lighthouse keeper backstory"),
             CardData(id="4", title="z", tags=["lighthouse"])]          # strands come after text
    found = search_cards(cards, "  lighthouse ")
    assert [(cid, field) for cid, field, _ in found] == [("1", "Title"), ("2", "Description"),
                                                     ("3", "Notes"), ("4", "Tag")]
    assert "LIGHTHOUSE stairs" in found[1][2] and "\n" not in found[1][2]
    assert search_cards(cards, "") == [] and search_cards(cards, "nope") == []
    long = CardData(id="5", description="a" * 100 + " needle " + "b" * 100)
    snippet = search_cards([long], "needle")[0][2]
    assert snippet.startswith("…") and snippet.endswith("…") and len(snippet) < 80


def test_search_box_jumps_and_steps_in_reading_order(window, qapp):
    s = window.scene
    lower = s.add_card(CardData(title="Dawn at sea", x=0, y=600))
    upper_right = s.add_card(CardData(title="Dawn, the city", x=600, y=0))
    upper_left = s.add_card(CardData(title="Quiet dawn", x=0, y=0))
    s.add_card(CardData(title="Noon", x=300, y=300))
    window.show()
    window.activateWindow()
    qapp.processEvents()
    window.act_find.trigger()
    qapp.processEvents()
    assert window.search_bar.edit.hasFocus()
    QTest.keyClicks(window.search_bar.edit, "DAWN")
    assert s.selectedItems() == [upper_left] and window.search_bar.count.text() == "1 of 3"
    QTest.keyClick(window.search_bar.edit, Qt.Key.Key_Return)
    assert s.selectedItems() == [upper_right]
    window.act_find_next.trigger()
    assert s.selectedItems() == [lower] and window.search_bar.count.text() == "3 of 3"
    window.act_find_next.trigger()                     # wraps around
    assert s.selectedItems() == [upper_left]
    QTest.keyClick(window.search_bar.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert s.selectedItems() == [lower]
    vp_centre = window.view.mapToScene(window.view.viewport().rect().center())
    assert lower.card_scene_rect().adjusted(-200, -200, 200, 200).contains(vp_centre)
    QTest.keyClick(window.search_bar.edit, Qt.Key.Key_Escape)
    assert window.search_bar.text() == "" and window.search_bar.count.text() == ""


def test_search_reports_no_matches_and_filtered_cards(window, qapp, tick_filter):
    s = window.scene
    s.add_card(CardData(title="Storm", tags=["a"]))
    s.add_card(CardData(title="Calm", tags=["b"], x=400))
    s.mark_modified()
    window.show()
    tick_filter(window, "tags", "b")                   # "Storm" is now dimmed
    window.search_bar.edit.setText("zzz")
    assert window.search_bar.count.text() == "No matches" and not window.search_bar.next_btn.isEnabled()
    window.search_bar.edit.setText("storm")
    assert "hidden by the filter" in window.statusBar().currentMessage()


def test_ctrl_f_is_search_and_ctrl_l_is_filter(window):
    from PySide6.QtGui import QKeySequence
    assert window.act_find.shortcut() == QKeySequence(QKeySequence.StandardKey.Find)
    assert window.act_filter.shortcut() == QKeySequence("Ctrl+L")


def test_pending_nudge_does_not_leak_into_a_new_board(window, qapp):
    a = window.scene.add_card(CardData())
    a.setSelected(True)
    window.scene.nudge_selected(10, 0)
    window.setWindowModified(False)
    window.new_board()
    assert not window.scene._nudge_timer.isActive()   # the burst can't settle into the new board
    QApplication.processEvents()
    assert not window.isWindowModified()


def test_bulk_edit_adds_and_removes_characters_and_locations():
    from heddle.model import apply_bulk_edit
    a = CardData(characters=["Mara", "Nia"], pov="Mara", locations=["Keep"])
    b = CardData(characters=["nia"])
    changed = apply_bulk_edit([a, b], add={"characters": ["Rowan"], "locations": ["Gate"]},
                              remove={"characters": ["NIA", "mara"], "locations": ["keep"]})
    assert changed == [a, b]
    assert (a.characters, a.pov, a.locations) == (["Rowan"], "", ["Gate"])   # POV went with Mara
    assert (b.characters, b.locations) == (["Rowan"], ["Gate"])


def test_bulk_edit_gives_strand_cards_only_the_color():
    """(Bug fix: strand cards were given tags and a status, which they can't hold.)"""
    from heddle.model import KIND_STRAND, apply_bulk_edit
    s = CardData(kind=KIND_STRAND, strand_kind="characters", strand="Mara")
    assert apply_bulk_edit([s], add_tags=["x"], status="Draft",
                           add={"characters": ["Nia"]}) == []
    assert (s.tags, s.status, s.characters) == ([], "", [])
    assert apply_bulk_edit([s], color="#123456", add_tags=["x"]) == [s] and s.tags == []


def test_multi_edit_dialog_edits_characters_and_locations(window, qapp, monkeypatch):
    import heddle.multi_edit as me
    s = window.scene
    a = s.add_card(CardData(title="A", characters=["Mara"], locations=["Keep"]))
    b = s.add_card(CardData(title="B", x=400, characters=["Mara", "Nia"]))
    s.mark_modified()
    qapp.processEvents()

    def fill(self):
        assert self.removers["characters"]._suggestions[:2] == ["Mara", "Nia"]   # what the cards have
        self.adders["characters"].add_value("Rowan")
        self.removers["characters"].add_value("Mara")
        self.adders["locations"].add_value("Gate")
        self.accept()
        return self.result()
    monkeypatch.setattr(me.MultiEditDialog, "exec", fill)
    a.setSelected(True)
    b.setSelected(True)
    window.show()
    window.view.setFocus()
    key(window, Qt.Key.Key_Return)
    assert a.card.characters == ["Rowan"] and b.card.characters == ["Nia", "Rowan"]
    assert a.card.locations == ["Keep", "Gate"] and b.card.locations == ["Gate"]
    qapp.processEvents()
    s.undo()
    assert s.cards[a.card.id].card.characters == ["Mara"]          # one undo step
