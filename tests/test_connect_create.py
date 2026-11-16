"""Dragging a card's handle onto empty canvas creates a new, connected card (F1),
and cancelling the editor for any brand-new card removes it again."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import heddle.dialogs as dlg
import heddle.main_window as mw
import heddle.scene as sc
from heddle.model import KIND_GROUP, CardData

NO_MODS = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier


def editor_returns(monkeypatch, accept: bool, title: str = "Next scene"):
    """Make the card editor answer immediately; returns the list of cards it saw."""
    seen = []

    def fake_exec(self):
        seen.append(self._card.id)
        if accept:
            self.title_edit.setText(title)
            self.accept()
        else:
            self.reject()
        return self.result()
    monkeypatch.setattr(dlg.CardDialog, "exec", fake_exec)
    return seen


def drag_drop(scene, source, pos, mods=NO_MODS):
    scene.begin_connection(source, source.port_scene_pos())
    scene.update_connection(pos)
    scene.finish_connection(pos, mods)


def setup(scene, *cards):
    items = [scene.add_card(c) for c in cards]
    scene.reset_history()  # the starting board is the "saved" state
    return items


def test_drop_on_empty_canvas_creates_a_connected_card_in_one_undo_step(scene, qapp, monkeypatch):
    seen = editor_returns(monkeypatch, accept=True)
    (a,) = setup(scene, CardData(title="A", color="#3f9e6e"))
    drop = a.port_scene_pos() + QPointF(200, 40)
    drag_drop(scene, a, drop)
    qapp.processEvents()  # the editor opens once the mouse is released

    assert len(scene.cards) == 2 and len(scene.edges) == 1
    new = next(c for c in scene.cards.values() if c is not a)
    assert seen == [new.card.id]
    assert new.card.title == "Next scene" and new.card.color == "#3f9e6e"
    e = scene.edges[0]
    assert e.source is a and e.target is new
    # Its left edge sits at the pointer, vertically centred on it.
    r = new.card_scene_rect()
    assert abs(r.left() - drop.x()) < 0.5 and abs(r.center().y() - drop.y()) < 0.5
    assert new.isSelected() and not a.isSelected()

    scene.flush_history()
    assert scene.undo()
    assert list(scene.cards) == [a.card.id] and not scene.edges
    assert not scene.history.can_undo()


def test_cancelling_the_editor_removes_the_card_and_arrow(window, qapp, monkeypatch):
    scene = window.scene
    editor_returns(monkeypatch, accept=False)
    (a,) = setup(scene, CardData(title="A"))
    drag_drop(scene, a, a.port_scene_pos() + QPointF(200, 0))
    qapp.processEvents()
    scene.flush_history()
    assert list(scene.cards) == [a.card.id] and not scene.edges
    assert not scene.history.can_undo()
    assert not window.isWindowModified()


def test_ctrl_drop_skips_the_editor(scene, qapp, monkeypatch):
    seen = editor_returns(monkeypatch, accept=True)
    (a,) = setup(scene, CardData(title="A"))
    drag_drop(scene, a, a.port_scene_pos() + QPointF(200, 0), CTRL)
    qapp.processEvents()
    assert seen == []
    assert len(scene.cards) == 2 and len(scene.edges) == 1
    scene.flush_history()
    assert scene.undo() and len(scene.cards) == 1 and not scene.edges


def test_dropping_left_of_the_card_places_the_new_card_to_the_left(scene, qapp, monkeypatch):
    editor_returns(monkeypatch, accept=True)
    (a,) = setup(scene, CardData(title="A", x=0, y=0))
    drop = QPointF(-150, 30)
    drag_drop(scene, a, drop, CTRL)
    new = next(c for c in scene.cards.values() if c is not a)
    assert abs(new.card_scene_rect().right() - drop.x()) < 0.5


def test_drop_inside_the_source_group_adds_the_card_to_that_group(scene, qapp, monkeypatch):
    editor_returns(monkeypatch, accept=True)
    group, a = setup(scene, CardData(title="G", kind=KIND_GROUP),
                     CardData(title="A", x=40, y=80))
    scene.set_parent(a, group.card.id)
    scene._refit_ids({group.card.id})
    group.resize_to(900, 500)  # plenty of empty room inside the frame
    scene.reset_history()
    drop = a.port_scene_pos() + QPointF(150, 0)
    assert group.card_scene_rect().contains(drop)
    drag_drop(scene, a, drop, CTRL)
    new = next(c for c in scene.cards.values() if c not in (a, group))
    assert new.card.parent == group.card.id
    assert scene.edges[0].source is a and scene.edges[0].target is new


def test_dropping_on_another_group_still_connects_to_it(scene, qapp, monkeypatch):
    editor_returns(monkeypatch, accept=True)
    a, group = setup(scene, CardData(title="A"), CardData(title="G", kind=KIND_GROUP, x=600, y=0))
    drag_drop(scene, a, group.card_scene_rect().center())
    assert len(scene.cards) == 2
    assert [(e.source, e.target) for e in scene.edges] == [(a, group)]


def test_short_drag_and_drops_on_cards_create_nothing(scene, qapp, monkeypatch):
    seen = editor_returns(monkeypatch, accept=True)
    a, b = setup(scene, CardData(title="A"), CardData(title="B", x=500))
    drag_drop(scene, a, a.port_scene_pos() + QPointF(sc.NEW_CARD_MIN_DRAG - 5, 0))
    drag_drop(scene, a, a.card_scene_rect().center())   # back onto itself
    assert len(scene.cards) == 2 and not scene.edges
    drag_drop(scene, a, b.card_scene_rect().center())   # onto a card: connects as before
    drag_drop(scene, a, b.card_scene_rect().center())   # already connected: nothing new
    qapp.processEvents()
    assert len(scene.cards) == 2 and len(scene.edges) == 1 and seen == []


def test_click_to_connect_never_creates_cards(scene, qapp, monkeypatch):
    editor_returns(monkeypatch, accept=True)
    (a,) = setup(scene, CardData(title="A"))
    scene.start_click_connection(a)
    pos = a.port_scene_pos() + QPointF(300, 0)
    scene.update_connection(pos)
    assert scene._ghost is None or not scene._ghost.isVisible()
    scene.finish_connection(pos, NO_MODS)
    assert len(scene.cards) == 1 and not scene.is_click_connecting()


def test_ghost_previews_the_new_card_only_over_empty_canvas(scene, qapp):
    a, b = setup(scene, CardData(title="A"), CardData(title="B", x=500))
    scene.begin_connection(a, a.port_scene_pos())
    empty = a.port_scene_pos() + QPointF(150, 200)
    scene.update_connection(empty)
    assert scene._ghost is not None and scene._ghost.isVisible()
    assert scene._ghost.sceneBoundingRect().contains(scene.new_card_rect(a, empty).center())
    scene.update_connection(b.card_scene_rect().center())
    assert not scene._ghost.isVisible()
    scene.cancel_connection()
    assert scene._ghost is None and len(scene.cards) == 2


def test_cancelling_any_new_card_removes_it(scene, qapp, monkeypatch):
    """Double-click / Add card: a cancelled editor no longer leaves "New card" behind."""
    editor_returns(monkeypatch, accept=False)
    setup(scene)
    scene.create_card_at(QPointF(0, 0))
    qapp.processEvents()
    scene.flush_history()
    assert not scene.cards and not scene.history.can_undo()


def test_editing_an_existing_card_and_cancelling_keeps_it(scene, qapp, monkeypatch):
    editor_returns(monkeypatch, accept=False)
    (a,) = setup(scene, CardData(title="A"))
    scene.edit_card(a)
    assert list(scene.cards) == [a.card.id]


def test_accepted_new_card_is_one_undo_step(scene, qapp, monkeypatch):
    editor_returns(monkeypatch, accept=True, title="Fresh")
    setup(scene)
    scene.create_card_at(QPointF(0, 0))
    qapp.processEvents()
    scene.flush_history()
    assert [c.card.title for c in scene.cards.values()] == ["Fresh"]
    assert scene.undo() and not scene.cards and not scene.history.can_undo()


def test_autosave_waits_while_a_dialog_is_open(window, monkeypatch, tmp_path):
    written = []
    monkeypatch.setattr(mw.MainWindow, "_write", lambda self, *a, **k: written.append(a) or True)
    window.current_path = tmp_path / "named.json"   # a named board: autosave writes the file
    window.setWindowModified(True)
    monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: window))
    window._autosave()
    assert written == [] and window._autosave_timer.isActive()
    monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: None))
    window._autosave()
    assert len(written) == 1


def test_real_mouse_drag_from_the_handle(window, qapp, monkeypatch):
    """End to end through the view: press on the handle, drag, release on empty canvas."""
    editor_returns(monkeypatch, accept=True)
    scene = window.scene
    (a,) = setup(scene, CardData(title="A", x=0, y=0))
    window.show()
    window.view.reset_zoom()
    window.view.centerOn(a.card_scene_rect().center() + QPointF(150, 0))
    qapp.processEvents()
    vp = window.view.viewport()
    start = window.view.mapFromScene(a.port_scene_pos())
    end = window.view.mapFromScene(a.port_scene_pos() + QPointF(220, 0))

    def send(kind, at, buttons):
        p = QPointF(at)
        ev = QMouseEvent(kind, p, vp.mapToGlobal(p), Qt.MouseButton.LeftButton
                         if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
                         buttons, NO_MODS)
        QApplication.sendEvent(vp, ev)

    left = Qt.MouseButton.LeftButton
    send(QEvent.Type.MouseButtonPress, start, left)
    send(QEvent.Type.MouseMove, (start + end) / 2, left)
    send(QEvent.Type.MouseMove, end, left)
    send(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
    qapp.processEvents()
    assert len(scene.cards) == 2 and len(scene.edges) == 1
    assert scene.edges[0].source is a
