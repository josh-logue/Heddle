"""F7: exporting the story as Markdown, and the board as PNG / SVG / PDF."""
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

import warpingweft.export_dialogs as ed
from warpingweft import theme
from warpingweft.export import OUTLINE, TextOptions, export_route, export_text
from warpingweft.export_image import (
    MARGIN, ExportTooLarge, ImageOptions, export_image, export_items, export_rect,
)
from warpingweft.graph import StoryGraph
from warpingweft.model import KIND_GROUP, BoardData, CardData, ConnectionData


def story_board():
    """Opening → [Act One: Meeting → Choice] → Exile ("if she refuses") / Crown, plus a note."""
    cards = [CardData(id="open", title="Opening", description="It begins.", x=-600, y=0,
                      characters=["Mabel"], status="Draft", notes="Keep it short.\nReally."),
             CardData(id="act", title="Act One", kind=KIND_GROUP, x=-300, y=-60),
             CardData(id="meet", title="Meeting", description="They meet.", x=-280, y=0, parent="act",
                      pov="Mabel", characters=["Gus"]),
             CardData(id="choice", title="Choice", x=50, y=0, parent="act"),
             CardData(id="exile", title="Exile", x=500, y=-150),
             CardData(id="crown", title="Crown", x=500, y=150),
             CardData(id="note", title="Loose note", x=-600, y=600)]
    conns = [ConnectionData(s, t, label, id=f"{s}>{t}") for s, t, label in
             (("open", "act", ""), ("meet", "choice", ""), ("choice", "exile", "if she refuses"),
              ("choice", "crown", ""))]
    board = BoardData(cards=cards, connections=conns)
    return board, StoryGraph(board.cards, board.connections)


# ----- text --------------------------------------------------------------------------
def test_document_in_story_order_with_branches():
    board, g = story_board()
    md = export_text(board, g, "My Story")
    headings = [line for line in md.splitlines() if line.startswith("#")]
    assert headings == ["# My Story", "## Opening", "## Act One", "### Meeting", "### Choice",
                        "## Exile", "## Crown", "## Loose note"]
    assert "*Next: Exile (if she refuses) · Crown*" in md
    assert "Next: Meeting" not in md                   # simply the next card listed
    assert "**POV:** Mabel · **Characters:** Gus" in md
    assert "**Characters:** Mabel · **Status:** Draft" in md
    assert "It begins." in md and "> Keep it short." not in md   # notes are off by default


def test_include_options():
    board, g = story_board()
    md = export_text(board, g, "S", TextOptions(descriptions=False, details=False, notes=True,
                                                 next_steps=False))
    assert "It begins." not in md and "**POV:**" not in md and "Next:" not in md
    assert "> Keep it short.\n> Really." in md


def test_outline_nests_groups():
    board, g = story_board()
    md = export_text(board, g, "S", TextOptions(layout=OUTLINE, details=False))
    lines = md.splitlines()
    assert "- **Act One**" in lines
    assert "  - **Meeting**: They meet." in lines
    assert "    - Next: Exile (if she refuses) · Crown" in lines


def test_selection_keeps_the_groups_around_it():
    board, g = story_board()
    md = export_text(board, g, "S", include={"choice", "crown"})
    headings = [line for line in md.splitlines() if line.startswith("#")]
    assert headings == ["# S", "## Act One", "### Choice", "## Crown"]


def test_board_without_arrows_uses_reading_order():
    board = BoardData(cards=[CardData(id="b", title="B", x=300), CardData(id="a", title="A"),
                             CardData(id="c", title="C", y=300)])
    md = export_text(board, StoryGraph(board.cards, []), "S")
    assert [line for line in md.splitlines() if line.startswith("## ")] == ["## A", "## B", "## C"]


def test_route_export():
    board, _ = story_board()
    md = export_route(board, ["open", "meet", "choice", "exile"], ["", "", "", "if she refuses"], "Route")
    assert "## 4. Exile" in md and "*via “if she refuses”*" in md
    outline = export_route(board, ["open", "exile"], ["", "if she refuses"], "R",
                           TextOptions(layout=OUTLINE))
    assert "2. **Exile** *(via “if she refuses”)*" in outline


# ----- images ------------------------------------------------------------------------------
def scene_with_cards(scene):
    a = scene.add_card(CardData(title="A"))
    b = scene.add_card(CardData(title="B", x=500, y=100))
    scene.add_connection(a, b)
    return a, b


def test_png_size_background_and_state_restored(scene, tmp_path):
    a, b = scene_with_cards(scene)
    b.setSelected(True)
    scene.set_highlight({a.card.id}, label="kept", owner="paths")
    rect = export_rect(*export_items(scene, False))
    size = export_image(scene, tmp_path / "x.png", ImageOptions(scale=2.0))
    assert (size.width(), size.height()) == (round(rect.width() * 2), round(rect.height() * 2))
    img = QImage(str(tmp_path / "x.png"))
    assert img.size() == size
    assert img.pixelColor(2, 2) == theme.current().canvas_bg   # plain, no grid in the margin
    assert img.pixelColor(int(MARGIN), int(MARGIN) // 2) == theme.current().canvas_bg
    # Everything is back as it was.
    assert b.isSelected() and scene.highlight_label() == "kept" and scene.export_background is None
    assert a.isVisible() and b.isVisible()


def test_transparent_png_and_selection_only(scene, tmp_path):
    a, b = scene_with_cards(scene)
    a.setSelected(True)
    size = export_image(scene, tmp_path / "sel.png",
                        ImageOptions(selection_only=True, scale=1.0, transparent=True))
    r = a.card_scene_rect()
    assert (size.width(), size.height()) == (round(r.width() + 2 * MARGIN), round(r.height() + 2 * MARGIN))
    img = QImage(str(tmp_path / "sel.png"))
    assert img.pixelColor(1, 1).alpha() == 0
    assert b.isVisible()                                    # hidden only while exporting


def test_light_theme_export_from_dark(scene, tmp_path):
    scene_with_cards(scene)
    previous = theme.current()
    theme._current = theme.DARK
    try:
        export_image(scene, tmp_path / "light.png", ImageOptions(scale=1.0, light=True))
        assert theme.current() is theme.DARK
    finally:
        theme._current = previous
    assert QImage(str(tmp_path / "light.png")).pixelColor(1, 1) == QColor(theme.LIGHT.canvas_bg)


def test_svg_and_pdf(scene, tmp_path):
    scene_with_cards(scene)
    export_image(scene, tmp_path / "b.svg")
    export_image(scene, tmp_path / "b.pdf")
    assert (tmp_path / "b.svg").read_text(encoding="utf-8").lstrip().startswith("<?xml")
    assert (tmp_path / "b.pdf").read_bytes().startswith(b"%PDF")


def test_export_errors(scene, tmp_path):
    with pytest.raises(ValueError):
        export_image(scene, tmp_path / "empty.png")          # no cards
    scene_with_cards(scene)
    with pytest.raises(ValueError):
        export_image(scene, tmp_path / "x.gif")
    with pytest.raises(ValueError):
        export_image(scene, tmp_path / "x.png", ImageOptions(selection_only=True))
    scene.add_card(CardData(title="Far", x=9000))
    with pytest.raises(ExportTooLarge):
        export_image(scene, tmp_path / "big.png", ImageOptions(scale=3.0))


# ----- the menu commands -----------------------------------------------------------------------
def accept_with(monkeypatch, cls, setup=lambda d: None):
    def fake_exec(self):
        setup(self)
        self.accept()
        return self.result()
    monkeypatch.setattr(cls, "exec", fake_exec)


def save_as(monkeypatch, path, chosen_filter):
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), chosen_filter)))


def test_export_story_command(window, monkeypatch, tmp_path):
    s = window.scene
    a, b = scene_with_cards(s)
    accept_with(monkeypatch, ed.ExportTextDialog)
    save_as(monkeypatch, tmp_path / "story", "Plain text (*.txt)")
    out = window.export_story()
    assert out == tmp_path / "story.txt"                      # extension from the chosen type
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Untitled") and "## A" in text and "## B" in text


def test_export_route_command(window, monkeypatch, tmp_path):
    s = window.scene
    a, b = scene_with_cards(s)
    window.read_from(a)
    window.path_reader.next()
    accept_with(monkeypatch, ed.ExportTextDialog,
                lambda d: d.scope[ed.SCOPE_ROUTE].setChecked(True))
    save_as(monkeypatch, tmp_path / "route.md", "Markdown (*.md)")
    text = window.export_story().read_text(encoding="utf-8")
    assert "## 1. A" in text and "## 2. B" in text


def test_export_picture_command_and_too_large(window, monkeypatch, tmp_path):
    s = window.scene
    scene_with_cards(s)
    accept_with(monkeypatch, ed.ExportImageDialog)
    save_as(monkeypatch, tmp_path / "board", "PDF document (*.pdf)")
    assert window.export_picture() == tmp_path / "board.pdf"
    s.add_card(CardData(title="Far", x=9000))
    accept_with(monkeypatch, ed.ExportImageDialog, lambda d: d.scale.setCurrentIndex(2))
    save_as(monkeypatch, tmp_path / "big.png", "PNG image (*.png)")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[1])))
    assert window.export_picture() is None and warned == ["Image too large"]
