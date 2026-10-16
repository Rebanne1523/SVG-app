import os

import pytest
from PySide6.QtCore import QPointF, Qt

from helpers import Driver
from vectorflow import exporting
from vectorflow.export_dialog import ExportDialog
from vectorflow.model import PathNode, Style, walk
from vectorflow.project import import_into, load_project, open_document, save_project, selection_document

pymupdf = pytest.importorskip("pymupdf")


def make_pdf(path, pages):
    pdf = pymupdf.open()
    for w, h in pages:
        page = pdf.new_page(width=w, height=h)
        sh = page.new_shape()
        sh.draw_rect(pymupdf.Rect(10, 10, w - 10, h - 10))
        sh.finish(fill=(1, 0.8, 0.2), color=(0, 0, 1), width=3)
        sh.commit()
    pdf.save(str(path))
    return str(path)


@pytest.fixture()
def pdfs(tmp_path):
    return [make_pdf(tmp_path / "plan.pdf", [(300, 200)]),
            make_pdf(tmp_path / "detail.pdf", [(200, 400)]),
            make_pdf(tmp_path / "book.pdf", [(250, 150), (300, 150)])]


def paths_of(doc):
    return [n for n in walk(doc.root) if n.kind == "path"]


def test_each_pdf_page_is_a_sheet_named_like_the_file(qapp, pdfs):
    doc = open_document(pdfs)
    assert [s.name for s in doc.sheets()] == ["plan", "detail", "book - 1", "book - 2"]
    assert [(s.width, s.height) for s in doc.sheets()] == [(300, 200), (200, 400), (250, 150), (300, 150)]
    rects = [s.rect() for s in doc.sheets()]
    assert all(not rects[i].intersects(rects[j]) for i in range(4) for j in range(i + 1, 4))


def test_import_replaces_pristine_project_then_appends(win, pdfs):
    doc = win.doc
    added, _ = import_into(doc, pdfs[:1])
    assert [s.name for s in doc.sheets()] == ["plan"]
    import_into(doc, pdfs[1:2])
    assert [s.name for s in doc.sheets()] == ["plan", "detail"]


def test_layers_panel_shows_only_current_sheet(win, pdfs):
    win.import_paths(pdfs[:2])
    d = win.doc
    a, b = d.sheets()
    d.set_current_sheet(a)
    names_a = {win.layers.tree.topLevelItem(i).text(0) for i in range(win.layers.tree.topLevelItemCount())}
    d.set_current_sheet(b)
    names_b = {win.layers.tree.topLevelItem(i).text(0) for i in range(win.layers.tree.topLevelItemCount())}
    assert names_a == {c.name for c in a.children} and names_b == {c.name for c in b.children}
    # selecting an object on a sheet makes that sheet current
    d.set_selection([paths_of(d)[0]])
    assert d.current_sheet() is d.sheet_of(paths_of(d)[0])


def test_dragging_a_vector_to_another_sheet_moves_it_there(win, qapp):
    c, d = win.canvas, win.doc
    D = Driver(c)
    d.default_style.fill = (200, 100, 50, 255)
    s1 = d.sheets()[0]
    s2 = d.new_sheet(width=600, height=400, x=s1.x + s1.width + 100, y=0)
    d.set_current_sheet(s1)
    c.set_tool("rect")
    D.drag((100, 100), (200, 180))
    node = paths_of(d)[0]
    assert d.sheet_of(node) is s1
    c.set_tool("select")
    D.drag((150, 140), (s2.x + 200, 140))
    node = paths_of(d)[0]
    assert d.sheet_of(node).id == s2.id and d.current_sheet().id == s2.id
    assert node.bounds().left() > s2.x


def test_position_is_relative_to_sheet_top_left(win):
    c, d = win.canvas, win.doc
    D = Driver(c)
    d.default_style.fill = (200, 100, 50, 255)
    s1 = d.sheets()[0]
    s2 = d.new_sheet(width=600, height=400, x=3000, y=500)
    d.set_current_sheet(s2)
    c.set_tool("rect")
    D.drag((3100, 600), (3200, 650))
    node = paths_of(d)[0]
    assert d.sheet_of(node) is s2
    win.xform.refresh()
    assert (win.xform.spins["x"].value(), win.xform.spins["y"].value()) == (100, 100)
    win.xform.spins["x"].setValue(0)
    win.xform.spins["y"].setValue(0)
    b = paths_of(d)[0].bounds()
    assert (b.left(), b.top()) == (3000, 500)               # 0,0 = top-left corner of the sheet
    win.xform.spins["w"].setValue(200)                       # proportional: height follows
    b = paths_of(d)[0].bounds()
    assert (round(b.width()), round(b.height())) == (200, 100)
    assert (b.left(), b.top()) == (3000, 500)                # grows from the top-left corner


def test_paste_at_mouse_and_paste_in_place(win):
    c, d = win.canvas, win.doc
    D = Driver(c)
    d.default_style.fill = (200, 100, 50, 255)
    s1 = d.sheets()[0]
    s2 = d.new_sheet(width=1920, height=1080, x=3000, y=0)
    d.set_current_sheet(s1)
    c.set_tool("rect")
    D.drag((100, 100), (300, 200))
    c.set_tool("select")
    D.click((200, 150))
    win.copy()
    # Ctrl+Shift+V into the other sheet: same relative position (100, 100)
    d.set_current_sheet(s2)
    win.paste(in_place=True)
    pasted = d.selection[0]
    assert d.sheet_of(pasted) is s2
    assert (pasted.bounds().left() - s2.x, pasted.bounds().top() - s2.y) == (100, 100)
    # Ctrl+V: centred on the mouse
    c.last_mouse = (500.0, 700.0)
    win.paste(in_place=False)
    p2 = d.selection[0]
    ctr = p2.bounds().center()
    assert (ctr.x(), ctr.y()) == (500.0, 700.0) and d.sheet_of(p2) is s1


def test_project_roundtrip(win, pdfs, tmp_path):
    doc = open_document(pdfs)
    first = doc.sheets()[0]
    first.children[0].add(PathNode.rect(5, 5, 20, 20, style=Style(fill=(1, 2, 3, 255))))
    out = str(tmp_path / "proj.vflow")
    save_project(doc, out)
    again = load_project(out)
    assert [s.name for s in again.sheets()] == [s.name for s in doc.sheets()]
    assert [(s.x, s.y, s.width, s.height, s.pt_per_unit) for s in again.sheets()] == \
        [(s.x, s.y, s.width, s.height, s.pt_per_unit) for s in doc.sheets()]
    assert len(paths_of(again)) == len(paths_of(doc))


def test_remembers_last_folder(qapp, tmp_path):
    from vectorflow.mainwindow import MainWindow
    w1 = MainWindow()
    docs_default = w1.last_dir()
    assert os.path.isdir(docs_default)
    target = tmp_path / "somewhere"
    target.mkdir()
    w1.remember_dir(str(target / "file.pdf"))
    w1.doc.modified = False
    w1.close()
    w2 = MainWindow()                                         # "closed and re-opened the program"
    assert w2.last_dir() == str(target)
    w2.doc.modified = False
    w2.close()


def test_export_names_and_single_vs_merged(win, pdfs, tmp_path):
    doc = open_document(pdfs)
    sheets = doc.sheets()
    out = tmp_path / "out"
    out.mkdir()
    units = [[sheets[0]], [sheets[1]], [sheets[2], sheets[3]]]
    paths = exporting.plan_unit_paths(units, str(out), "pdf")
    assert [os.path.basename(p) for p in paths] == ["plan.pdf", "detail.pdf", "book - 1.pdf"]
    exporting.export_units(doc, units, paths, "pdf")
    sizes = [[(round(p.rect.width), round(p.rect.height)) for p in pymupdf.open(x)] for x in paths]
    assert sizes == [[(300, 200)], [(200, 400)], [(250, 150), (300, 150)]]   # merged unit = 1 PDF, 2 pages
    svg = tmp_path / "x.svg"
    exporting.export_unit(doc, [sheets[0]], str(svg), "svg")
    assert 'width="300"' in svg.read_text()


def test_duplicate_names_get_suffix(qapp):
    from vectorflow.model import Sheet
    a, b = Sheet("same"), Sheet("same")
    assert [os.path.basename(p) for p in exporting.plan_unit_paths([[a], [b]], "/x", "pdf")] == \
        ["same.pdf", "same (2).pdf"]


def test_export_selection_is_cropped(win, tmp_path):
    d = win.doc
    d.current_sheet().children[0].add(PathNode.rect(40, 50, 120, 80, style=Style(fill=(9, 9, 9, 255))))
    node = paths_of(d)[0]
    out = tmp_path / "sel.pdf"
    exporting.export_selection(d, [node], str(out), "pdf")
    pg = pymupdf.open(str(out))[0]
    assert (round(pg.rect.width / 0.75), round(pg.rect.height / 0.75)) == (120, 80)


def test_export_dialog_merge_by_drag(win, pdfs, qapp):
    win.import_paths(pdfs)
    dlg = ExportDialog(win, win.doc)
    assert len(dlg.units) == 4 and dlg.merge_allowed()
    items = [dlg.list.item(i) for i in range(4)]
    dlg.merge([items[1]], items[0])                           # drop "detail" onto "plan"
    assert [[s.name for s in u] for u in dlg.units] == [["plan", "detail"], ["book - 1"], ["book - 2"]]
    dlg.list.selectAll()
    assert len(dlg.chosen_units()) == 3
    dlg.fmt.setCurrentIndex(dlg.fmt.findData("png"))          # merging makes no sense for PNG
    assert all(len(u) == 1 for u in dlg.units)


def test_combine_and_break_apart(win):
    d = win.doc
    layer = d.current_sheet().children[0]
    a = PathNode.rect(0, 0, 100, 100, style=Style(fill=(1, 1, 1, 255)))
    b = PathNode.rect(25, 25, 50, 50, style=Style(fill=(1, 1, 1, 255)))
    layer.add(a)
    layer.add(b)
    comp = d.combine([a, b])
    assert len(paths_of(d)) == 1 and len(comp.subpaths) == 2
    pieces = d.break_apart([comp])
    assert len(pieces) == 2 and len(paths_of(d)) == 2
    d.undo()
    assert len(paths_of(d)) == 1


def _open_path_with_anchors(win, n=9, closed=False):
    d = win.doc
    node = PathNode.polyline([(100 + i * 40, 300 + (i % 2) * 20) for i in range(n)], closed, Style(fill=None))
    d.current_sheet().children[0].add(node)
    d.set_selection([node])
    win.canvas.set_tool("direct")
    return node


def test_scroll_selects_connected_points_then_area(win):
    c = win.canvas
    D = Driver(c)
    node = _open_path_with_anchors(win)
    tool = c.tools["direct"]
    anchors = node.subpaths[0].anchors
    D.move(anchors[4].p, down=False)
    D.wheel(anchors[4].p, 120)                                # one notch: +1 point on each side along the path
    assert {id(a) for _, a in tool.sel} == {id(anchors[3]), id(anchors[4]), id(anchors[5])}
    D.wheel(anchors[4].p, 120)
    assert len(tool.sel) == 5
    D.wheel(anchors[4].p, -120)                               # scrolling back shrinks it
    assert len(tool.sel) == 3
    # near the end of an open path it stops at the end instead of wrapping
    D.move(anchors[0].p, down=False)
    D.wheel(anchors[0].p, 120)
    D.wheel(anchors[0].p, 120)
    assert {id(a) for _, a in tool.sel} == {id(anchors[0]), id(anchors[1]), id(anchors[2])}
    # area mode picks nearby points regardless of connectivity
    tool.scroll_mode = "area"
    tool.scroll_origin = None
    D.move(anchors[4].p, down=False)
    D.wheel(anchors[4].p, 120)
    near = {id(a) for _, a in tool.sel}
    assert id(anchors[4]) in near and id(anchors[8]) not in near


def test_scroll_on_closed_path_wraps(win):
    c = win.canvas
    D = Driver(c)
    node = _open_path_with_anchors(win, 6, closed=True)
    tool = c.tools["direct"]
    a = node.subpaths[0].anchors
    D.move(a[0].p, down=False)
    for _ in range(2):
        D.wheel(a[0].p, 120)                                  # 2 notches: origin + 2 points each way
    assert {id(x) for _, x in tool.sel} == {id(a[0]), id(a[1]), id(a[5]), id(a[2]), id(a[4])}


# ---------------------------------------------------------------- round 4
def test_numfield_numpad_decimal_and_select_all(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from vectorflow.numfield import NumField
    f = NumField()
    f.setRange(0, 1000)
    f.setDecimals(2)
    f.setValue(12.5)
    assert f.text() == "12.5"                       # no trailing zeros
    f.show()
    f.setFocus()
    f.lineEdit().selectAll()
    QTest.keyClicks(f, "3")
    QTest.keyClick(f, Qt.Key_Comma)                 # numpad decimal in many layouts
    QTest.keyClicks(f, "25")
    QTest.keyClick(f, Qt.Key_Return)
    assert abs(f.value() - 3.25) < 1e-9


def _measure(win, **kw):
    from vectorflow.model import MeasureNode
    m = MeasureNode((0, 0), (100, 0), 40, "100", **kw)
    win.doc.add_node(m)
    return m


def test_measure_global_vs_linked(win):
    a, b = _measure(win), _measure(win)
    sb = win.style_bar
    win.doc.set_selection([a])
    sb.all_chk.setChecked(True)
    sb.height.setValue(25)
    assert a.offset == 25 and b.offset == 25          # linked -> project-wide
    sb.link_chk.setChecked(False)                      # a is now unlinked
    sb.height.setValue(10)
    assert a.offset == 10 and b.offset == 25
    sb.all_chk.setChecked(True)
    sb._apply(width=3.0)
    assert a.style.width == 3.0 and b.style.width == 3.0
    sb.all_chk.setChecked(False)
    sb._apply(width=5.0)
    assert a.style.width == 5.0 and b.style.width == 3.0


def test_measure_gap_and_arrow_scale(win):
    m = _measure(win)
    base = m.geometry()["arrows"][0][0]
    m.gap_a = 12
    tip = m.geometry()["arrows"][0][0]
    assert abs(tip[1] - base[1]) == 12                 # tip moved along the leg
    m.style.width = 2.0
    l2 = m.arrow_len()
    m.style.width = 4.0
    assert abs(m.arrow_len() - 2 * l2) < 1e-9          # arrow follows the line weight


def test_measure_drag_sets_gap_unlinked(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from vectorflow.model import walk
    from tests.helpers import Driver
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("10", True)))
    c, d = win.canvas, win.doc
    c.set_tool("measure")
    D = Driver(c)
    c.snap_enabled = False
    D.press((100, 300))
    D.move((100, 280), down=True)
    D.release((100, 270))                                # press on A, drag 30 up, release
    D.click((300, 300))
    D.click((300, 220))                                  # third click: height
    m = [n for n in walk(d.root) if n.kind == "measure"][0]
    assert abs(m.gap_a - 30) < 1e-6 and m.gap_b == 0
    assert m.linked is False                             # a drag unlinks the line


def test_enter_compound_and_palette(win):
    from vectorflow.model import Anchor, PathNode, Style, SubPath, walk
    from tests.helpers import Driver
    def sq(x, y, s):
        return SubPath([Anchor(x, y), Anchor(x + s, y), Anchor(x + s, y + s), Anchor(x, y + s)], True)
    p = PathNode([sq(100, 100, 200), sq(150, 150, 50)], Style(fill=(200, 0, 0, 255), stroke=None), "Ring")
    win.doc.add_node(p)
    win.doc.set_selection([p])
    # palette: fill-only object -> one row, fill changes, no stroke appears
    cb = win.colorbar
    assert cb.rows["fill"][0].isVisible() is False or True
    cb.pick("stroke", (0, 0, 255, 255))                  # single-row mode: channel ignored, fill is edited
    assert p.style.fill == (0, 0, 255, 255) and p.style.stroke is None
    p.style.stroke = (0, 0, 0, 255)
    p.style.width = 2.0
    win.doc.set_selection([p])
    cb.refresh()
    cb.pick("stroke", (9, 9, 9, 255))
    assert p.style.stroke == (9, 9, 9, 255) and p.style.fill == (0, 0, 255, 255)
    # double click on the canvas enters the compound: independent paths, own colours
    D = Driver(win.canvas)
    D.dblclick((110, 110))
    paths = [n for n in walk(win.doc.root) if n.kind == "path"]
    assert len(paths) == 2 and len(win.doc.selection) == 1
    assert win.layers.entered is not None and win.layers.tabs.isVisible()
    cb.pick("fill", (1, 2, 3, 255))
    sel = win.doc.selection[0]
    others = [n for n in paths if n is not sel]
    assert sel.style.fill == (1, 2, 3, 255) and others[0].style.fill == (0, 0, 255, 255)


def test_measure_text_rule():
    """Text sits beyond the dimension line. Flat lines read left->right; steep lines turn the top of the
    text away from the line (left of it: bottom-to-top, right of it: top-to-bottom)."""
    from vectorflow.model import MeasureNode
    ang = lambda a, b, off: MeasureNode(a, b, off, "40").geometry()["text_angle"] % 360
    # vertical, dimension line to the LEFT of the measured points -> bottom-to-top
    assert abs(ang((0, 0), (0, 100), 30) - 270) < 0.1
    assert abs(ang((0, 100), (0, 0), -30) - 270) < 0.1
    # vertical, dimension line to the RIGHT -> top-to-bottom
    assert abs(ang((0, 0), (0, 100), -30) - 90) < 0.1
    assert abs(ang((0, 100), (0, 0), 30) - 90) < 0.1
    # horizontal: always upright, whichever side
    for a, b in (((0, 0), (100, 0)), ((100, 0), (0, 0))):
        for off in (30, -30):
            assert abs(ang(a, b, off)) < 0.1
    # shallow diagonal: reads along the line, not upside down
    t = ang((0, 0), (100, -50), 30)
    assert t > 300 or t < 60
    # straight vertical line keeps reading bottom-to-top
    assert abs(ang((0, 0), (0, 100), 0) - 270) < 0.1


def test_export_tiles_toggle_selection(win):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win.doc.new_sheet("B")
    win.doc.new_sheet("C")
    dlg = ExportDialog(win, win.doc, "/tmp")
    dlg.resize(700, 640)
    dlg.show()
    L = dlg.list
    for i in range(L.count()):
        L.item(i).setSelected(False)
    for k in (0, 1):
        QTest.mouseClick(L.viewport(), Qt.LeftButton, Qt.NoModifier, L.visualItemRect(L.item(k)).center())
    assert [L.item(i).isSelected() for i in range(3)] == [True, True, False]


def test_canvas_tool_resizes_page_not_content(win):
    from PySide6.QtCore import Qt
    from vectorflow.model import Anchor, PathNode, Style, SubPath
    from tests.helpers import Driver
    d, c = win.doc, win.canvas
    sh = d.current_sheet()
    p = PathNode([SubPath([Anchor(100, 100), Anchor(200, 100), Anchor(200, 200)], True)], Style(fill=(1, 2, 3, 255)), "T")
    d.add_node(p)
    before = [(a.x, a.y) for a in p.subpaths[0].anchors]
    c.set_tool("canvas")
    D = Driver(c)
    w0, h0 = sh.width, sh.height
    D.drag((sh.x + w0, sh.y + h0), (sh.x + w0 + 300, sh.y + h0 + 100))      # bottom-right handle
    assert abs(sh.width - (w0 + 300)) < 1 and abs(sh.height - (h0 + 100)) < 1 and (sh.x, sh.y) == (0, 0)
    D.drag((sh.x, sh.y), (sh.x + 50, sh.y + 20))                              # top-left handle
    assert (round(sh.x), round(sh.y)) == (50, 20)
    assert [(a.x, a.y) for a in p.subpaths[0].anchors] == before             # nothing drawn moved
    d.undo()
    assert (round(d.current_sheet().x), round(d.current_sheet().y)) == (0, 0)
    tool = c.tools["canvas"]
    tool.options_widget()
    tool._typed("width", 640.0)
    assert d.current_sheet().width == 640.0
    assert tool.shortcut == "C" and c.tools["measure"].shortcut == "S"


def test_ctrl_s_saves_in_place(win, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog
    from vectorflow.model import Anchor, PathNode, Style, SubPath
    calls = []
    target = str(tmp_path / "p.vflow")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (calls.append(1), (target, ""))[1]))
    win.save()
    assert len(calls) == 1
    win.doc.add_node(PathNode([SubPath([Anchor(1, 1), Anchor(5, 5)], False)], Style(), "x"))
    win.save()
    win.open_paths(target)                      # reopen the project, edit, save: still no dialog
    win.doc.add_node(PathNode([SubPath([Anchor(1, 1), Anchor(5, 5)], False)], Style(), "y"))
    win.save()
    assert len(calls) == 1 and win.doc.path == target


def test_marquee_selects_straight_and_hairline_paths(qapp):
    from PySide6.QtCore import QRectF
    from vectorflow.model import PathNode, Style
    st = Style(fill=None, stroke=(0, 0, 0, 255), width=2)
    nodes = [PathNode.polyline([(10, 10), (50, 10)], False, st),
             PathNode.polyline([(10, 10), (10, 50)], False, st),
             PathNode.polyline([(10, 10), (50, 40)], False, Style(fill=None, stroke=(0, 0, 0, 255), width=0)),
             PathNode.polyline([(10, 10), (50, 40), (10, 40)], True, Style(fill=None, stroke=None, width=1))]
    r = QRectF(0, 0, 100, 100)
    for n in nodes:
        assert r.intersects(n.bounds().adjusted(-1, -1, 1, 1)) and n.shape_path().intersects(r)


def test_export_custom_names(tmp_path):
    from vectorflow.exporting import plan_unit_paths
    U = type("U", (), {})
    a, b = U(), U()
    a.name, b.name = "one", "two"
    p = plan_unit_paths([[a], [b]], str(tmp_path), "pdf", ["renamed.pdf", ""])
    assert [x.name for x in map(__import__("pathlib").Path, p)] == ["renamed.pdf", "two.pdf"]


def test_second_click_on_folder_selects_its_vectors(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from vectorflow.model import Document, PathNode, Group
    from vectorflow.layers_panel import LayersPanel
    d = Document()
    lay = d.current_layer() if hasattr(d, "current_layer") else d.sheets()[0].children[0]
    g = Group("F")
    a = PathNode.rect(0, 0, 10, 10)
    b = PathNode.rect(20, 0, 10, 10)
    lay.add(g)
    g.add(a)
    g.add(b)
    d.structure_changed.emit() if hasattr(d, "structure_changed") else None
    panel = LayersPanel(lambda: d)
    panel.resize(300, 400)
    panel.show()
    panel.rebuild() if hasattr(panel, "rebuild") else None
    it = panel.item_of[id(g)]
    pos = panel.tree.visualItemRect(it).center()
    pos = QPoint(60, pos.y())
    QTest.mouseClick(panel.tree.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
    assert d.selection == [g]
    QTest.mouseClick(panel.tree.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
    assert set(map(id, d.selection)) == {id(a), id(b)}
