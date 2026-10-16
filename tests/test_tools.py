import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QInputDialog

from helpers import Driver
from vectorflow.model import walk

P = QAbstractItemView.DropIndicatorPosition


def paths(doc):
    return [n for n in walk(doc.root) if n.kind == "path"]


def test_shapes_and_constraints(win):
    c, d = win.canvas, win.doc
    D = Driver(c)
    c.set_tool("rect")
    D.drag((100, 100), (300, 200))
    assert paths(d)[0].bounds().getRect() == (100, 100, 200, 100)
    c.set_tool("ellipse")
    D.drag((400, 100), (560, 180), mods=Qt.ShiftModifier)
    b = paths(d)[1].bounds()
    assert abs(b.width() - b.height()) < 1e-6
    c.set_tool("line")
    D.drag((100, 400), (300, 440), mods=Qt.ShiftModifier)
    b = paths(d)[2].bounds()
    assert b.height() == 0 and b.width() == 200


def test_move_snaps_and_shift_constrains(win):
    c, d = win.canvas, win.doc
    d.default_style.fill = (200, 100, 50, 255)       # unfilled shapes are only clickable on their outline
    D = Driver(c)
    c.set_tool("rect")
    D.drag((100, 100), (300, 200))
    D.drag((500, 300), (650, 420))
    c.set_tool("select")
    D.click((560, 360))
    D.drag((560, 360), (560 - 196, 360 - 150))         # left edge 304 -> snaps to 300
    assert paths(d)[1].bounds().left() == 300
    d.undo()
    D.drag((560, 360), (460, 330), mods=Qt.ShiftModifier)  # constrained to horizontal
    b = paths(d)[1].bounds()
    assert (b.left(), b.top()) == (400, 300)


def test_scale_and_rotate_with_snapping(win):
    c, d = win.canvas, win.doc
    d.default_style.fill = (200, 100, 50, 255)
    D = Driver(c)
    c.set_tool("rect")
    D.drag((500, 300), (650, 420))
    c.set_tool("select")
    D.click((560, 360))
    r = paths(d)[0].bounds()
    D.drag((r.right(), r.bottom()), (r.right() + 60, r.bottom() + 10), mods=Qt.ShiftModifier)
    b = paths(d)[0].bounds()
    assert round(b.width() / 150, 6) == round(b.height() / 120, 6) == 1.4
    d.undo()
    r = paths(d)[0].bounds()
    cx, cy = r.center().x(), r.center().y()
    start = (r.right() + 8, r.top() - 8)           # just outside the corner -> rotate zone
    D.move(start, down=False)
    assert c.cursor().pixmap().width() > 0          # custom rotate cursor
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    end = (cx + math.cos(a0 + math.radians(32)) * 150, cy + math.sin(a0 + math.radians(32)) * 150)
    D.drag(start, end)
    a = paths(d)[0].subpaths[0].anchors
    assert round(math.degrees(math.atan2(a[1].y - a[0].y, a[1].x - a[0].x)), 6) == 30.0  # snapped to 30


def test_layers_drag_and_drop(win):
    c, d, L = win.canvas, win.doc, win.layers
    d.default_style.fill = (200, 100, 50, 255)
    D = Driver(c)
    c.set_tool("rect")
    for i in range(3):
        D.drag((100 + i * 120, 100), (180 + i * 120, 180))
    l1 = d.current_sheet().children[0]
    l2 = d.new_folder(as_layer=True)
    r1, r2, r3 = l1.children
    assert L.apply_drop([r1], l2, P.OnItem)
    assert [n.name for n in l2.children] == ["Rectangle 1"]
    g = d.group([r2, r3])
    assert g.parent is l1 and len(g.children) == 2
    assert L.apply_drop([g], r1, P.AboveItem)
    assert l2.children[-1] is g                           # in front of Rectangle 1
    assert not L.apply_drop([g], g, P.OnItem)             # can't drop a folder into itself
    d.undo()
    assert len(list(walk(d.root))) == 7
    # canvas click <-> panel selection
    c.set_tool("select")
    D.click((120, 140))
    assert [it.text(0) for it in L.tree.selectedItems()] == [d.selection[0].name]


def test_hide_and_lock(win):
    c, d, L = win.canvas, win.doc, win.layers
    d.default_style.fill = (200, 100, 50, 255)
    D = Driver(c)
    c.set_tool("rect")
    D.drag((100, 100), (200, 200))
    c.set_tool("select")
    node = paths(d)[0]
    L.toggle_lock(node)
    D.click((150, 150))
    assert d.selection == []                               # locked -> not selectable
    L.toggle_lock(paths(d)[0])
    L.toggle_visible(paths(d)[0])
    D.click((150, 150))
    assert d.selection == []                               # hidden -> not selectable


def test_pen_and_direct_tool(win):
    c, d = win.canvas, win.doc
    D = Driver(c)
    c.set_tool("pen")
    D.press((100, 300)); D.move((140, 260)); D.release((140, 260))
    D.press((300, 300)); D.move((340, 340)); D.release((340, 340))
    D.click((500, 200))
    D.key(Qt.Key_Return)
    node = paths(d)[0]
    an = node.subpaths[0].anchors
    assert len(an) == 3 and an[0].smooth and not an[2].smooth
    c.set_tool("direct")
    D.click((500, 200))
    D.drag((500, 200), (560, 150))
    assert node.subpaths[0].anchors[2].p == (560, 150)
    win.delete()                                            # deletes the selected point
    assert len(paths(d)[0].subpaths[0].anchors) == 2


def test_measure_tool_flow(win, monkeypatch):
    c, d = win.canvas, win.doc
    D = Driver(c)
    c.set_tool("rect")
    D.drag((100, 100), (300, 200))
    c.set_tool("measure")
    mt = c.tools["measure"]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("200 mm", True)))
    D.move((101, 99), down=False)
    assert c.snap_marker is not None and c.snap_marker[0] == (100, 100)    # snapped to the corner
    D.click((101, 99))
    D.wheel((250, 80), 120)                                  # flips the first arrow
    assert mt.mode_a == "line"
    D.click((300, 100))
    D.move((300, 60), down=False)
    D.wheel((300, 60), 120)
    assert mt.mode_b == "line"
    D.click((300, 60))
    ms = [n for n in walk(d.root) if n.kind == "measure"]
    assert len(ms) == 1
    m = ms[0]
    assert m.text == "200 mm" and (m.mode_a, m.mode_b) == ("line", "line") and abs(m.offset) == 40
    # edit through the top bar
    d.set_selection([m])
    win.style_bar.width.setValue(3.0)
    assert m.style.width == 3.0
    d.undo()
    assert [n for n in walk(d.root) if n.kind == "measure"][0].style.width != 3.0


def test_bucket_tool(win):
    c, d = win.canvas, win.doc
    D = Driver(c)
    c.set_tool("rect")
    D.drag((100, 100), (300, 200))
    d.default_style.fill = (10, 200, 30, 255)
    c.set_tool("bucket")
    D.click((200, 150))
    fills = [n for n in paths(d) if n.name.startswith("Fill")]
    assert len(fills) == 1 and fills[0].style.fill == (10, 200, 30, 255)
    assert d.active_container().children[0] is fills[0]      # behind the outline


def test_shortcuts(win, qapp):
    from PySide6.QtTest import QTest
    c = win.canvas
    c.setFocus()
    for key, name in [(Qt.Key_P, "pen"), (Qt.Key_V, "select"), (Qt.Key_A, "direct"), (Qt.Key_G, "bucket"),
                      (Qt.Key_I, "measure"), (Qt.Key_U, "rect"), (Qt.Key_T, "text"), (Qt.Key_H, "hand")]:
        QTest.keyClick(c, key)
        assert c.tool.name == name


def test_large_document_is_responsive(win, qapp, tmp_path):
    import random
    import time
    from vectorflow.project import open_document
    random.seed(3)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1500">']
    for g in range(5):
        parts.append("<g>")
        for i in range(400):
            parts.append(f'<path d="M{random.random()*1900:.1f},{random.random()*1400:.1f} l30,10 l-10,30z" fill="#336699"/>')
        parts.append("</g>")
    parts.append("</svg>")
    f = tmp_path / "big.svg"
    f.write_text("".join(parts))
    t = time.time()
    doc = open_document(str(f))
    win.set_document(doc)
    qapp.processEvents()
    doc.undo_stack.append(doc._snapshot())
    doc.undo()
    assert time.time() - t < 15
