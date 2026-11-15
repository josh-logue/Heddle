"""Review finding C: with the Path Reader focused, Space moves to the next card even
when the pointer is over the canvas (Space-to-pan used to take it). Elsewhere,
Space still pans as before."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from warpingweft.model import CardData


def reading(window, qapp, monkeypatch):
    s = window.scene
    a = s.add_card(CardData(title="A"))
    b = s.add_card(CardData(title="B", x=400))
    s.add_connection(a, b)
    s.mark_modified()
    window.show()
    window.activateWindow()
    qapp.processEvents()
    window.read_from(a)
    qapp.processEvents()
    # e.g. right-click a card → Read from here leaves the pointer over the canvas
    monkeypatch.setattr(window.view, "_pointer_over_canvas", lambda: True)
    return a, b


def test_space_steps_the_reader_with_the_pointer_over_the_canvas(window, qapp, monkeypatch):
    a, b = reading(window, qapp, monkeypatch)
    reader = window.path_reader
    assert QApplication.focusWidget() is reader
    QTest.keyClick(reader, Qt.Key.Key_Space)
    assert reader.route == [a.card.id, b.card.id]
    assert not window.view._space_held          # it didn't start panning


def test_space_still_pans_from_the_canvas(window, qapp, monkeypatch):
    a, b = reading(window, qapp, monkeypatch)
    window.focus_canvas()
    qapp.processEvents()
    QTest.keyPress(window.view.viewport(), Qt.Key.Key_Space)
    assert window.view._space_held
    QTest.keyRelease(window.view.viewport(), Qt.Key.Key_Space)
    assert not window.view._space_held
    assert window.path_reader.route == [a.card.id]   # the reader didn't move
