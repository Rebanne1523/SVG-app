"""The cached / time-sliced canvas must look exactly like painting the document directly."""
import random
import time

import pytest
from PySide6.QtCore import QEventLoop, QPointF, Qt
from PySide6.QtGui import QImage

from helpers import Driver, app
from vectorflow import model, scenecache
from vectorflow.canvas import LIVE_LAYER_MIN, Canvas
from vectorflow.model import Anchor, Document, PathNode, Style, SubPath, walk


def make_doc(n, seed=3, w=1000, h=800):
    random.seed(seed)
    doc = Document(w, h)
    for i in range(n):
        x, y = random.uniform(20, w - 100), random.uniform(20, h - 100)
        sp = SubPath([Anchor(x, y), Anchor(x + random.uniform(10, 60), y + random.uniform(-30, 30)),
                      Anchor(x + random.uniform(10, 60), y + random.uniform(10, 60))], i % 2 == 0)
        st = Style(fill=(random.randrange(256), random.randrange(256), random.randrange(256), 255) if i % 3 else None,
                   stroke=(0, 0, 0, 255), width=random.choice([0.5, 1, 3]))
        doc.add_node(PathNode([sp], st, name=f"p{i}"))
    return doc


def settle(canvas, limit=30):
    a = app()
    t0 = time.time()
    n = 0
    while time.time() - t0 < limit:
        a.processEvents(QEventLoop.AllEvents, 20)
        n += 1
        busy = canvas.scene.busy() or canvas.live_scene.busy() or canvas._linger is not None
        if not busy and n > 3:
            break
    a.processEvents()


def grab(canvas):
    return canvas.grab().toImage().convertToFormat(QImage.Format_ARGB32)


def mismatch(a, b, tol=12):
    """Fraction of pixels that differ visibly (compositing the cached bitmap rounds by a few levels)."""
    assert a.size() == b.size()
    bad = 0
    for y in range(a.height()):
        for x in range(a.width()):
            p, q = a.pixel(x, y), b.pixel(x, y)
            if p != q and max(abs(((p >> s) & 255) - ((q >> s) & 255)) for s in (0, 8, 16)) > tol:
                bad += 1
    return bad / (a.width() * a.height())


@pytest.fixture
def cv():
    app()
    c = Canvas(make_doc(60))
    c.resize(500, 400)
    c.show()
    from vectorflow.tools_select import SelectTool
    c.register_tool(SelectTool(c))
    c.set_tool("select")
    c.snap_enabled = False
    c.fit_view()
    settle(c)
    yield c
    c.close()


def direct(c):
    """Same canvas painted without any cache."""
    scenecache.ENABLED = False
    try:
        return grab(c)
    finally:
        scenecache.ENABLED = True


def test_cached_picture_equals_direct(cv):
    assert mismatch(grab(cv), direct(cv)) < 0.002


def test_pan_zoom_and_edit_stay_in_sync(cv):
    cv.pan_by(37, -21)
    settle(cv)
    assert mismatch(grab(cv), direct(cv)) < 0.002
    cv.zoom_by(1.7, (250, 200))
    settle(cv)
    assert mismatch(grab(cv), direct(cv)) < 0.002
    leaves = [x for x in walk(cv.doc.root) if not x.is_group()]
    with cv.doc.edit():
        leaves[0].style.fill = (255, 0, 0, 255)
        leaves[0].touch()
    settle(cv)
    assert mismatch(grab(cv), direct(cv)) < 0.002
    with cv.doc.edit():                      # a style change that never calls touch() still shows up
        leaves[1].style.stroke = (0, 0, 255, 255)
        leaves[1].style.width = 6
    settle(cv)
    assert mismatch(grab(cv), direct(cv)) < 0.002


def test_heavy_scene_is_time_sliced_and_correct(cv, monkeypatch):
    monkeypatch.setattr(scenecache, "SLICE_MS", 0.0)       # force many tiny slices
    monkeypatch.setattr(scenecache, "LIGHT_MS", 0.0)
    cv.scene.render_ms = 100.0
    cv.pan_by(500, 500)                                    # far outside the cached margin
    cv.update()
    cv.repaint()
    assert cv.scene.busy() or cv.scene.pix is not None
    settle(cv)
    cv.fit_view()
    settle(cv)
    assert mismatch(grab(cv), direct(cv)) < 0.002


def _drag(cv, p0, p1):
    d = Driver(cv)
    d.press(p0)
    for i in range(1, 6):
        d.move((p0[0] + (p1[0] - p0[0]) * i / 5, p0[1] + (p1[1] - p0[1]) * i / 5))
    return d


def test_small_drag_is_drawn_live_and_patched_on_release(cv):
    doc = cv.doc
    target = [n for n in walk(doc.root) if not n.is_group()][-1]
    doc.set_selection([target])
    settle(cv)
    p0 = target.subpaths[0].anchors[0].p                     # on the (topmost) vector itself (document coords)
    d = _drag(cv, p0, (p0[0] + 60, p0[1] + 40))
    assert cv.live is not None and not cv.live["layer"]
    cv.repaint()
    assert mismatch(grab(cv), direct(cv)) < 0.002          # mid-drag picture is right
    d.release((p0[0] + 60, p0[1] + 40))
    settle(cv)
    assert cv.live is None
    assert mismatch(grab(cv), direct(cv)) < 0.002          # patched region matches a full render
    cv.doc.undo()
    settle(cv)
    assert mismatch(grab(cv), direct(cv)) < 0.002


def test_big_drag_moves_a_bitmap_then_applies_the_transform(cv, monkeypatch):
    monkeypatch.setattr("vectorflow.canvas.LIVE_LAYER_MIN", 10)
    doc = cv.doc
    nodes = list(walk(doc.root))
    nodes = [n for n in nodes if not n.is_group()]
    nodes = nodes[-30:]                                      # the topmost ones
    doc.set_selection(nodes)
    settle(cv)
    before = {n.id: [(a.x, a.y) for sp in n.subpaths for a in sp.anchors] for n in nodes}
    p0 = nodes[-1].subpaths[0].anchors[0].p
    d = Driver(cv)
    d.press(p0)
    for i in range(1, 6):
        d.move((p0[0] + 10 * i, p0[1] + 6 * i))
    assert cv.live is not None and cv.live["layer"]
    now = {n.id: [(a.x, a.y) for sp in n.subpaths for a in sp.anchors] for n in nodes}
    assert now == before                                  # untouched until release
    d.release((p0[0] + 50, p0[1] + 30))
    settle(cv)
    moved = {n.id: [(a.x, a.y) for sp in n.subpaths for a in sp.anchors] for n in nodes}
    dx = 50.0
    assert all(abs(moved[i][0][0] - before[i][0][0] - dx) < 1e-6 for i in before)
    assert mismatch(grab(cv), direct(cv)) < 0.002
    doc.undo()
    settle(cv)
    undone = {n.id: [(a.x, a.y) for sp in n.subpaths for a in sp.anchors] for n in doc.all_nodes() if n.id in before}
    assert undone == before
    assert mismatch(grab(cv), direct(cv)) < 0.002


def test_undo_redo_keep_unchanged_nodes_and_restore_changed_ones():
    app()
    old = model._CHECK_SNAPSHOTS
    model._CHECK_SNAPSHOTS = True                          # every snapshot / restore is verified against a deep copy
    try:
        doc = make_doc(80)
        leaves = [n for n in walk(doc.root) if not n.is_group()]
        keep = leaves[40]
        for step in range(12):
            tgt = leaves[step]
            with doc.edit():
                if step % 3 == 0:
                    tgt.transform((1, 0, 0, 1, 5, 7))
                elif step % 3 == 1:
                    tgt.style.width += 1
                else:
                    tgt.name = f"renamed {step}"
        for _ in range(12):
            doc.undo()
        assert doc.find(keep.id) is keep                   # an untouched vector survives undo as the same object
        for _ in range(12):
            doc.redo()
        names = [n.name for n in leaves[:12] if n.name.startswith("renamed")]
        assert len(names) == 4
    finally:
        model._CHECK_SNAPSHOTS = old


def test_tool_editing_without_signals_is_drawn_live(cv):
    """A tool that moves anchors / adds a path and only calls touch() (node tool, pen) must show at once,
    even when the scene is heavy and the cached picture can't be redrawn every frame."""
    cv.scene.render_ms = 80.0                               # pretend the drawing is heavy
    leaves = [n for n in walk(cv.doc.root) if not n.is_group()]
    n = leaves[5]
    n.subpaths[0].anchors[0].move_to(n.subpaths[0].anchors[0].x + 70, n.subpaths[0].anchors[0].y + 40)
    n.touch()
    cv.repaint()
    assert cv.live is not None and cv.live.get("auto")
    assert mismatch(grab(cv), direct(cv)) < 0.002
    for dx in (10, 20, 30):                                 # keep dragging the same anchor
        n.subpaths[0].anchors[0].move_to(n.subpaths[0].anchors[0].x + dx, n.subpaths[0].anchors[0].y)
        n.touch()
        cv.repaint()
        assert mismatch(grab(cv), direct(cv)) < 0.002
    new = PathNode([SubPath([Anchor(50, 50), Anchor(200, 120)], False)], Style(stroke=(255, 0, 0, 255), width=4), "pen")
    cv.doc.add_node(new)                                    # like the pen tool: no signal, just touch
    new.touch()
    cv.repaint()
    assert mismatch(grab(cv), direct(cv)) < 0.002
    with cv.doc.edit():                                     # the tool commits
        pass
    settle(cv)
    assert cv.live is None
    assert mismatch(grab(cv), direct(cv)) < 0.002


def test_many_nodes_hit_testing_and_marquee_match_brute_force(cv):
    doc = cv.doc
    leaves = [n for n in walk(doc.root) if not n.is_group()]
    from PySide6.QtCore import QRectF
    random.seed(11)
    for _ in range(40):
        x, y = random.uniform(0, 1000), random.uniform(0, 800)
        r = QRectF(x, y, random.uniform(1, 300), random.uniform(1, 300))
        want = [n for n in leaves if n.shape_path().intersects(r)]
        got = cv.nodes_in_rect(r, level="item")
        assert set(map(id, got)) == set(map(id, want))
        p = (x, y)
        tol = 4.0 / cv.zoom
        pr = QRectF(p[0] - tol, p[1] - tol, 2 * tol, 2 * tol)
        brute = None
        for n in reversed(leaves):
            st = n.style
            pad = tol + st.width + 2.0
            if n.bounds().adjusted(-pad, -pad, pad, pad).contains(QPointF(*p)) and n.shape_path().intersects(pr):
                brute = n
                break
        assert cv.hit_test(p, level="item") is brute


def test_direct_tool_vectorised_hits_match_brute_force():
    from vectorflow.geometry import dist
    from vectorflow.tools_select import DirectTool, segment_hit
    app()
    random.seed(21)
    doc = Document(1000, 800)
    sps = []
    for k in range(6):
        pts = [Anchor(random.uniform(0, 1000), random.uniform(0, 800)) for _ in range(120)]
        for a in pts[::3]:
            a.ox, a.oy = a.x + random.uniform(-40, 40), a.y + random.uniform(-40, 40)
            a.ix, a.iy = a.x - random.uniform(-40, 40), a.y - random.uniform(-40, 40)
        sps.append(SubPath(pts, k % 2 == 0))
    node = PathNode(sps, Style(stroke=(0, 0, 0, 255), width=1), "multi")
    doc.add_node(node)
    c = Canvas(doc)
    c.resize(800, 600)
    c.fit_view()
    tool = DirectTool(c)
    c.register_tool(tool)
    doc.set_selection([node])
    for trial in range(60):
        p = (random.uniform(0, 1000), random.uniform(0, 800))
        vp = c.to_view(p)
        # anchors
        best, bd = None, 8.0
        for sp in node.subpaths:
            for a in sp.anchors:
                d = dist(c.to_view(a.p), vp)
                if d <= bd:
                    bd, best = d, a
        got = tool.hit_anchor(vp)
        assert (got[2] if got else None) is best
        # segments
        tol = 6.0 / c.zoom
        want = None
        for sp in node.subpaths:
            for i, a0, a1 in sp.segments():
                d, t = segment_hit(a0, a1, p)
                if d <= tol and (want is None or d < want[0]):
                    want = (d, sp, i)
        seg = tool.hit_segment(p)
        assert (seg is None) == (want is None)
        if seg:
            assert seg[2] is want[1] and seg[3] == want[2]
    # handles of a selected anchor and its neighbours
    sp = node.subpaths[0]
    tool.sel = [(node, sp.anchors[3])]
    near = {id(b) for _, _, b in tool._near_selected()}
    assert near == {id(sp.anchors[2]), id(sp.anchors[3]), id(sp.anchors[4])}
    tool.sel = [(node, sp.anchors[0])]                                  # closed subpath wraps around
    near = {id(b) for _, _, b in tool._near_selected()}
    assert near == {id(sp.anchors[-1]), id(sp.anchors[0]), id(sp.anchors[1])}
