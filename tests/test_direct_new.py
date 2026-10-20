from PySide6.QtCore import Qt

from helpers import Driver
from vectorflow.model import PathNode, Style


def _setup(win, pts=((100, 100), (300, 100)), closed=False):
    c = win.canvas
    d = c.doc
    n = PathNode.polyline(list(pts), closed, Style(fill=None, stroke=(0, 0, 0, 255), width=2.0))
    d.add_node(n)
    d.set_selection([n])
    c.set_tool("direct")
    return c, d, n


def test_shift_click_adds_a_point_and_drag_makes_it_smooth(win):
    c, d, n = _setup(win)
    D = Driver(c)
    D.press((200, 101), Qt.ShiftModifier)
    for q in ((210, 120), (230, 150), (240, 160)):
        D.move(q)
    D.release((240, 160))
    anchors = n.subpaths[0].anchors
    assert len(anchors) == 3
    a = anchors[1]
    assert a.smooth and abs(a.x - 200) < 3 and abs(a.y - 100) < 3
    assert abs((a.ox - a.x) + (a.ix - a.x)) < 1e-6 and abs((a.oy - a.y) + (a.iy - a.y)) < 1e-6
    assert a.has_out() and a.has_in()
    d.undo()
    from vectorflow.model import leaves
    paths = [x for x in leaves(d.root) if x.kind == "path"]
    assert len(paths) == 1 and len(paths[0].subpaths[0].anchors) == 2


def test_shift_click_without_drag_just_adds_a_corner_point(win):
    c, d, n = _setup(win)
    D = Driver(c)
    D.click((200, 100), Qt.ShiftModifier)
    a = n.subpaths[0].anchors
    assert len(a) == 3 and not a[1].has_out() and not a[1].has_in()


def test_wheel_click_flips_selected_points(win):
    c, d, n = _setup(win, ((100, 100), (200, 200), (300, 100)))
    D = Driver(c)
    D.click((200, 200))
    assert len(c.tool.sel) == 1
    D.press((0, 0), button=Qt.MiddleButton)
    D.release((0, 0), button=Qt.MiddleButton)
    a = n.subpaths[0].anchors[1]
    assert a.has_in() and a.has_out() and a.smooth
    D.press((0, 0), button=Qt.MiddleButton)
    D.release((0, 0), button=Qt.MiddleButton)
    assert not a.has_in() and not a.has_out()


def test_dragging_a_straight_line_bends_it_with_both_handles(win):
    c, d, n = _setup(win)
    D = Driver(c)
    D.drag((200, 100), (200, 140))
    a0, a1 = n.subpaths[0].anchors
    assert a0.has_out() and a1.has_in()
    assert a0.oy > 100 and a1.iy > 100 and a0.y == 100 and a1.y == 100


def test_b_snaps_a_point_onto_another_point_of_the_same_path_then_turns_off(win):
    c, d, n = _setup(win, ((100, 100), (300, 100), (300, 300), (110, 104)))
    D = Driver(c)
    D.click((110, 104))
    D.key(Qt.Key_B)
    assert c.tool.vertex_snap
    D.press((110, 104))
    D.move((104, 102))
    D.move((103, 101))
    D.release((103, 101))
    last = n.subpaths[0].anchors[3]
    assert (last.x, last.y) == (100, 100)
    assert not c.tool.vertex_snap


def test_b_twice_cancels(win):
    c, d, n = _setup(win)
    D = Driver(c)
    D.key(Qt.Key_B)
    D.key(Qt.Key_B)
    assert not c.tool.vertex_snap


def test_palette_marks_the_selected_swatch(win):
    from vectorflow.palette import PALETTE
    strip = win.colorbar.rows["fill"][2]
    assert strip._index_of(None) == 0
    assert strip._index_of(PALETTE[5]) == 6
    assert strip._index_of((1, 2, 3, 255)) is None
