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
