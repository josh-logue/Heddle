"""Dragging a strand from the Strands panel onto the board: onto a standard card it joins
the card's matching field (a status replaces the old one); onto a group or a blank spot it
becomes a strand card there. Strand cards refuse it. Each drop is one undo step."""
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import heddle.strands_panel as sp
from heddle.model import KIND_GROUP, KIND_STRAND, CardData
from heddle.view import strand_from_mime, strand_mime

# QDragMoveEvent's only constructor is flagged deprecated by the bindings.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
L, NONE, COPY = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.DropAction.CopyAction


@pytest.fixture
def board(window, qapp):
    window.show()
    window.view.resetTransform()
    window.view.centerOn(QPointF(400, 300))
    qapp.processEvents()
    return window


def at(window, scene_pt: QPointF) -> QPoint:
    return window.view.mapFromScene(scene_pt)


def drag_over(window, mime, scene_pt: QPointF) -> bool:
    """Enter the canvas and move to scene_pt: is a drop accepted there?"""
    vp, p = window.view.viewport(), at(window, scene_pt)
    QApplication.sendEvent(vp, QDragEnterEvent(p, COPY, mime, L, NONE))
    move = QDragMoveEvent(p, COPY, mime, L, NONE)
    QApplication.sendEvent(vp, move)
    return move.isAccepted()


def drop(window, qapp, mime, scene_pt: QPointF) -> bool:
    """A full drag onto the canvas, ending in a drop at scene_pt."""
    drag_over(window, mime, scene_pt)
    ev = QDropEvent(QPointF(at(window, scene_pt)), COPY, mime, L, NONE)
    QApplication.sendEvent(window.view.viewport(), ev)
    qapp.processEvents()  # the undo step is recorded once the event loop is idle
    return ev.isAccepted() and ev.dropAction() == COPY


def centre(item) -> QPointF:
    return item.card_scene_rect().center()


def card(scene, title="Gate", x=300.0, y=200.0, **kw):
    return scene.add_card(CardData(title=title, x=x, y=y, **kw))


# ----- the payload ------------------------------------------------------------------------
def test_mime_round_trip_and_junk():
    assert strand_from_mime(strand_mime("characters", "Mara")) == ("characters", "Mara")
    junk = QMimeData()
    junk.setData("application/x-heddle-strand", b"{not json")
    assert strand_from_mime(junk) is None
    assert strand_from_mime(QMimeData()) is None


def test_a_real_drag_out_of_the_list_carries_the_strand_as_a_copy(board, qapp, monkeypatch):
    scene = board.scene
    card(scene, characters=["Mara"])
    board.strands_dock.show()
    panel = board.strands_panel
    panel.refresh()
    qapp.processEvents()
    started = []

    class FakeDrag:  # QDrag.exec runs the system's drag loop, which a test can't drive
        def __init__(self, _source):
            pass

        def setMimeData(self, mime):
            self.mime = mime

        def setPixmap(self, pixmap):
            assert not pixmap.isNull()

        def setHotSpot(self, _p):
            pass

        def exec(self, actions):
            started.append((strand_from_mime(self.mime), actions))
            return COPY

    monkeypatch.setattr(sp, "QDrag", FakeDrag)
    tree = panel.tree
    item = next(i for i in panel._strand_items() if i.data(0, sp.ROLE_NAME) == "Mara")
    tree.scrollToItem(item)
    p = tree.visualItemRect(item).center()
    vp = tree.viewport()
    QTest.mousePress(vp, L, NONE, p)
    for k in range(1, 6):
        QTest.mouseMove(vp, p + QPoint(12 * k, 4 * k))
    QTest.mouseRelease(vp, L, NONE, p + QPoint(60, 20))
    assert started == [(("characters", "Mara"), COPY)]
    assert any(i.data(0, sp.ROLE_NAME) == "Mara" for i in panel._strand_items())  # still listed


def test_headings_dont_drag(board):
    tree = board.strands_panel.tree
    tree.setCurrentItem(tree.topLevelItem(0))
    assert tree.drag_payload() is None


# ----- onto a standard card ----------------------------------------------------------------------
def test_dropping_on_a_card_adds_it_to_the_matching_field_in_one_undo_step(board, qapp, settle):
    scene = board.scene
    gate = card(scene, characters=["Ash"])
    gate_id = gate.card.id
    settle()
    assert drop(board, qapp, strand_mime("characters", "Mara"), centre(gate))
    assert scene.cards[gate_id].card.characters == ["Ash", "Mara"]
    for kind, name in (("tags", "Dark"), ("locations", "Keep")):
        assert drop(board, qapp, strand_mime(kind, name), centre(scene.cards[gate_id]))
    c = scene.cards[gate_id].card
    assert (c.tags, c.locations) == (["Dark"], ["Keep"])
    scene.undo()
    scene.undo()
    assert scene.cards[gate_id].card.tags == [] and scene.cards[gate_id].card.characters == ["Ash", "Mara"]
    scene.undo()
    assert scene.cards[gate_id].card.characters == ["Ash"]   # one step per drop
    scene.redo()
    assert scene.cards[gate_id].card.characters == ["Ash", "Mara"]


def test_a_status_replaces_the_old_one_and_says_so(board, qapp, settle):
    scene = board.scene
    gate = card(scene, status="Draft")
    gate_id = gate.card.id
    settle()
    notices = []
    scene.notice.connect(notices.append)
    assert drop(board, qapp, strand_mime("status", "Done"), centre(gate))
    assert scene.cards[gate_id].card.status == "Done"
    assert notices and "Draft" in notices[-1] and "Done" in notices[-1]
    assert board.statusBar().currentMessage() == notices[-1]
    scene.undo()
    assert scene.cards[gate_id].card.status == "Draft"


def test_a_card_that_already_has_it_stays_as_it_is(board, qapp, settle):
    scene = board.scene
    gate = card(scene, tags=["Dark"], status="Done")
    settle()
    notices = []
    scene.notice.connect(notices.append)
    can_undo = scene.history.can_undo()
    assert not drop(board, qapp, strand_mime("tags", "dark"), centre(gate))   # any case
    assert not drop(board, qapp, strand_mime("status", "Done"), centre(gate))
    assert gate.card.tags == ["Dark"] and len(notices) == 2
    assert scene.history.can_undo() == can_undo   # nothing recorded


def test_a_card_in_a_group_grows_its_group(board, qapp, settle):
    scene = board.scene
    g = scene.add_card(CardData(title="Act", kind=KIND_GROUP, x=100, y=100))
    inner = card(scene, title="Inner", x=140, y=180, parent=g.card.id)
    scene._refit_ids({g.card.id})
    settle()
    before = g.card_scene_rect().height()
    for n in range(6):
        drop(board, qapp, strand_mime("tags", f"tag number {n}"), centre(inner))
    assert len(inner.card.tags) == 6
    assert g.card_scene_rect().height() > before
    assert g.card_scene_rect().contains(inner.card_scene_rect())


# ----- onto a group or a blank spot ------------------------------------------------------------------
def test_dropping_on_the_blank_board_makes_a_strand_card_there(board, qapp, settle):
    scene = board.scene
    settle()
    spot = QPointF(420, 330)
    assert drop(board, qapp, strand_mime("locations", "Keep"), spot)
    (made,) = scene.cards.values()
    assert made.is_strand and (made.card.strand_kind, made.card.strand) == ("locations", "Keep")
    assert made.card_scene_rect().contains(spot) and not made.card.parent and made.isSelected()
    scene.undo()
    assert not scene.cards


def test_dropping_on_a_group_puts_the_strand_card_inside_it(board, qapp, settle):
    scene = board.scene
    g = scene.add_card(CardData(title="Family", kind=KIND_GROUP, x=100, y=100))
    card(scene, title="Inside", x=140, y=180, parent=g.card.id)
    scene._refit_ids({g.card.id})
    settle()
    rect = g.card_scene_rect()
    spot = QPointF(rect.right() - 20, rect.bottom() - 15)   # in the frame, off the card
    assert scene.strand_drop_target(spot) == ("group", g)
    assert drop(board, qapp, strand_mime("characters", "Mara"), spot)
    made = next(i for i in scene.cards.values() if i.is_strand)
    assert made.card.parent == g.card.id
    assert scene.cards[g.card.id].card_scene_rect().contains(made.card_scene_rect())  # refitted
    scene.undo()
    assert not any(i.is_strand for i in scene.cards.values())


# ----- refused, and the feedback while dragging ----------------------------------------------------------
def test_strand_cards_refuse_the_drop(board, qapp, settle):
    scene = board.scene
    mara = scene.create_strand_card("characters", "Mara", QPointF(400, 300))
    settle()
    mime = strand_mime("characters", "Nia")
    assert not drag_over(board, mime, centre(mara))
    assert not drop(board, qapp, mime, centre(mara))
    assert len(scene.cards) == 1 and mara.card.strand == "Mara"


def test_outline_and_ghost_follow_the_drag_and_go_when_it_leaves(board, qapp):
    scene = board.scene
    gate = card(scene)
    g = scene.add_card(CardData(title="Act", kind=KIND_GROUP, x=700, y=100))
    card(scene, title="In", x=740, y=180, parent=g.card.id)
    scene._refit_ids({g.card.id})
    mime = strand_mime("tags", "Dark")
    assert drag_over(board, mime, centre(gate))
    assert gate._drop_highlight and not (scene._ghost and scene._ghost.isVisible())
    group_spot = QPointF(g.card_scene_rect().right() - 20, g.card_scene_rect().bottom() - 15)
    assert drag_over(board, mime, group_spot)
    assert g._drop_highlight and not gate._drop_highlight and scene._ghost.isVisible()
    assert drag_over(board, mime, QPointF(300, 700))       # blank: a ghost, no outline
    assert not g._drop_highlight and scene._ghost.isVisible()
    assert scene._ghost.boundingRect().width() > 100
    QApplication.sendEvent(board.view.viewport(), QDragLeaveEvent())
    assert not scene._ghost.isVisible() and not any(i._drop_highlight for i in scene.cards.values())


def test_a_dimmed_card_takes_drops_too(board, qapp, settle):
    scene = board.scene
    gate = card(scene)
    scene.apply_filter(lambda c: False)
    settle()
    assert drop(board, qapp, strand_mime("characters", "Mara"), centre(gate))
    assert gate.card.characters == ["Mara"]


def test_another_windows_board_takes_the_strand_as_a_plain_name(board, qapp, settle):
    """The payload is just kind and name, so it lands on any board."""
    scene = board.scene
    settle()
    assert drop(board, qapp, strand_mime("characters", "Stranger"), QPointF(400, 300))
    assert "Stranger" in scene.all_values("characters") and scene.strand("characters", "Stranger") is None


# ----- the panel's name ---------------------------------------------------------------------------------------
def test_the_panel_is_called_strands(board):
    assert board.strands_dock.windowTitle() == "Strands"
    assert board.act_strands.text() == "&Strands"
    s = board.scene.create_strand_card("characters", "Mara", QPointF(0, 0))
    s.set_details_visible(True)
    assert s._blocks[0][1] == "No description yet. Add one in Strands."
    assert s.card.kind == KIND_STRAND
