"""Auto-arrange with unconnected nested groups and plain cards together: the groups
keep the column (row) to themselves, and the plain cards fill the space beside the
run of smaller groups at its end, wrapping where the groups' column (row) ends."""
from warpingweft.layout import V_GAP, Node, arrange
from warpingweft.model import KIND_GROUP, CardData


def G(i, w, h, y=0.0, x=0.0):
    return Node(i, w, h, x, y, group=True)


def C(i, w=200, h=80, y=0.0, x=0.0):
    return Node(i, w, h, x, y)


SECTIONS = [G("forge", 1140, 140, y=0), G("ledger", 690, 140, y=200),
          G("medical", 690, 140, y=400), G("thaum", 690, 140, y=600), G("humanities", 680, 140, y=800)]


def test_top_to_bottom_cards_go_beside_the_narrower_groups():
    p = arrange([*SECTIONS, C("general", y=700)], [], vertical=True)
    assert {p[n.id][0] for n in SECTIONS} == {0}                        # groups: one column, in order
    assert [p[n.id][1] for n in SECTIONS] == sorted(p[n.id][1] for n in SECTIONS)
    assert p["general"] == (690 + V_GAP, p["ledger"][1])        # beside Ledger, level with it
    assert p["general"][0] + 200 <= 1140                              # inside the column's width


def test_cards_wrap_into_a_new_column_at_the_bottom():
    cards = [C(f"c{n}", h=200, y=900 + n) for n in range(5)]
    p = arrange([*SECTIONS, *cards], [], vertical=True)
    bottom = p["humanities"][1] + 140
    col1 = [c.id for c in cards if p[c.id][0] == p["c0"][0]]
    assert col1 and all(p[i][1] + 200 <= bottom for i in col1)        # stops at the column's end
    second = [c.id for c in cards if c.id not in col1]
    assert second and p[second[0]][0] > p["c0"][0]                   # next column, to the right
    assert p[second[0]][1] == p["c0"][1]                             # ...starting at the same height


def test_groups_of_one_size_put_the_cards_beside_the_whole_column():
    groups = [G(f"g{n}", 600, 140, y=n * 200) for n in range(3)]
    p = arrange([*groups, C("card", y=999)], [], vertical=True)
    assert p["card"] == (600 + V_GAP, 0)


def test_groups_a_few_pixels_apart_count_as_one_size():
    # A sorting board's year groups: cards with a character line are 2 px taller, so
    # the groups came out 547/543/541 px tall and the card went under the shortest
    # (rightmost) one to save 6 px, instead of lining up on the left.
    groups = [G("y1", 300, 547, x=0), G("y2", 300, 543, x=330), G("y3", 300, 541, x=660)]
    p = arrange([*groups, C("supreme", h=71, y=600)], [])
    assert p["supreme"] == (0, 547 + V_GAP)


def test_left_to_right_is_the_mirror_image():
    groups = [G("tall", 140, 1000, x=0), G("short1", 140, 500, x=200), G("short2", 140, 500, x=400)]
    p = arrange([*groups, C("card", w=80, h=200, x=999)], [])
    assert [p[g.id][1] for g in groups] == [0, 0, 0]                  # groups in a row
    assert p["card"] == (p["short1"][0], 500 + V_GAP)                # below the shorter ones


def test_only_groups_or_only_cards_are_laid_out_as_before():
    p = arrange([G("a", 300, 100, y=0), G("b", 500, 100, y=200)], [], vertical=True)
    assert p == {"a": (0, 0), "b": (0, 100 + V_GAP)}
    p = arrange([C("a", y=0), C("b", y=100)], [], vertical=True)
    assert p == {"a": (0, 0), "b": (0, 80 + V_GAP)}


def test_grid_wraps_the_cards_after_a_square_number():
    cards = [C(f"c{n}", w=100, h=60, y=900 + n) for n in range(4)]
    p = arrange([*SECTIONS, *cards], [], vertical=True, grid=True)
    columns = sorted({p[c.id][0] for c in cards})
    assert len(columns) == 2                                         # 2 per column for 4 cards


def test_a_card_too_big_for_any_gap_goes_after_the_groups():
    groups = [G("a", 300, 100, y=0), G("b", 300, 100, y=200)]
    p = arrange([*groups, C("huge", w=200, h=900, y=999)], [], vertical=True)
    assert p["huge"][0] >= 300 and set(p) == {"a", "b", "huge"}


def test_auto_arrange_on_the_board(scene):
    sections = scene.add_card(CardData(title="Sections", kind=KIND_GROUP, arrange_vertical=True))
    wide = scene.add_card(CardData(title="Wide", kind=KIND_GROUP, parent=sections.card.id, y=0))
    for n in range(4):
        scene.add_card(CardData(title=f"W{n}", parent=wide.card.id, x=n * 260, y=60))
    narrow = scene.add_card(CardData(title="Narrow", kind=KIND_GROUP, parent=sections.card.id, y=400))
    scene.add_card(CardData(title="N0", parent=narrow.card.id, y=460))
    general = scene.add_card(CardData(title="General", parent=sections.card.id, y=300))
    scene._update_z()
    scene._refit_ids({wide.card.id, narrow.card.id, sections.card.id})
    scene.auto_arrange_group(sections)
    n, g = narrow.card_scene_rect(), general.card_scene_rect()
    assert abs(g.top() - n.top()) < 1e-6 and g.left() > n.right()    # beside the narrow group
    assert g.right() <= wide.card_scene_rect().right()                 # within the wide one's width
    assert general.card.parent == sections.card.id
