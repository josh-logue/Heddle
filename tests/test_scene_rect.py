"""Review finding D: cards beyond ±20,000 px used to be out of reach. The board
area now grows to hold every card (plus a margin) and shrinks back, never below
the original ±20,000."""
from PySide6.QtCore import QPointF

import warpingweft.scene as sc
from warpingweft.model import BoardData, CardData, save_board


def visible(window, item) -> bool:
    view = window.view
    shown = view.mapToScene(view.viewport().rect()).boundingRect()
    return shown.intersects(item.card_scene_rect())


def test_far_cards_can_be_reached(window, qapp):
    s = window.scene
    s.add_card(CardData(title="Home"))
    far = s.add_card(CardData(title="Far", x=30000, y=-28000))
    s.mark_modified()
    rect = s.sceneRect()
    assert rect.contains(far.card_scene_rect().adjusted(-sc.SCENE_MARGIN, -sc.SCENE_MARGIN,
                                                         sc.SCENE_MARGIN, sc.SCENE_MARGIN))
    window.resize(1100, 700)
    window.show()
    qapp.processEvents()
    window.view.centerOn(far)                # e.g. jumping to it from search
    qapp.processEvents()
    assert visible(window, far)


def test_fit_all_shows_cards_past_the_old_edge(window, qapp):
    """A board that fits on screen at the minimum zoom, lying past x = 20,000:
    before the fix the view couldn't scroll there at all."""
    s = window.scene
    home = s.add_card(CardData(title="Home", x=19000))
    far = s.add_card(CardData(title="Far", x=24000))
    s.mark_modified()
    window.resize(1100, 700)
    window.show()
    qapp.processEvents()
    window.view.fit_all()
    qapp.processEvents()
    assert visible(window, home) and visible(window, far)


def test_area_grows_with_moves_and_shrinks_back(scene):
    a = scene.add_card(CardData(title="A"))
    scene.mark_modified()
    assert scene.sceneRect() == sc.BASE_SCENE_RECT
    a.setSelected(True)
    a.setPos(25000, 0)
    scene.handle_drop(a)                     # a drag far out
    assert scene.sceneRect().right() >= 25000 + a.card_rect().width() + sc.SCENE_MARGIN
    scene.flush_history()
    assert scene.undo()                      # back where it was
    assert scene.sceneRect() == sc.BASE_SCENE_RECT
    b = scene.add_card(CardData(title="B", x=-40000))
    scene.mark_modified()
    assert scene.sceneRect().left() <= -40000 - sc.SCENE_MARGIN
    scene.remove_card(b)
    scene.mark_modified()
    assert scene.sceneRect() == sc.BASE_SCENE_RECT   # never smaller than the original


def test_nudging_and_pasting_far_out_grow_it(window):
    s = window.scene
    a = s.add_card(CardData(title="A", x=19900))
    a.setSelected(True)
    for _ in range(5):
        s.nudge_selected(100, 0)
    assert s.sceneRect().right() >= a.card_scene_rect().right() + sc.SCENE_MARGIN
    frag = s.selection_fragment()
    pasted = s.paste_fragment(frag, QPointF(60000, 60000))
    assert s.sceneRect().contains(pasted[0].card_scene_rect())


def test_opening_a_board_with_far_cards(window, tmp_path, qapp):
    path = tmp_path / "wide.json"
    save_board(BoardData(cards=[CardData(title="Near"), CardData(title="Far", x=45000, y=0)]), path)
    window.open_path(path)
    far = next(i for i in window.scene.cards.values() if i.card.title == "Far")
    assert window.scene.sceneRect().contains(far.card_scene_rect())
    window.new_board()
    assert window.scene.sceneRect() == sc.BASE_SCENE_RECT


def test_area_grows_while_a_card_is_dragged_or_added(scene):
    a = scene.add_card(CardData(title="A"))
    a.setPos(26000, 0)                       # mid-drag: no edit signalled yet
    assert scene.sceneRect().contains(a.card_scene_rect())
    b = scene.add_card(CardData(title="B", y=-33000))   # added by a script / paste
    assert scene.sceneRect().contains(b.card_scene_rect())
