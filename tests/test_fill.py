from vectorflow.fill import fill_at
from vectorflow.model import Document, PathNode, Style


def doc_with_shapes():
    d = Document(400, 300)
    d.add_node(PathNode.rect(20, 20, 100, 80, style=Style(fill=None)))
    d.add_node(PathNode.ellipse(250, 100, 50, 50, style=Style(fill=None)))
    # a "C" shaped outline with a 3px gap
    d.add_node(PathNode.polyline([(60, 250), (20, 250), (20, 180), (100, 180), (100, 250), (66, 250)], False,
                                 Style(fill=None)))
    return d


def test_closed_regions(qapp):
    d = doc_with_shapes()
    node, res = fill_at(d, (60, 60), (255, 0, 0, 255))
    assert node is not None and node.bounds().getRect() == (20, 20, 100, 80)
    node, res = fill_at(d, (250, 100), (255, 0, 0, 255))
    assert node is not None and round(node.bounds().width()) == 100


def test_gap_closing_is_independent_of_view(qapp):
    d = doc_with_shapes()
    node, res = fill_at(d, (60, 215), (255, 0, 0, 255), gap=2.0)
    assert node is None and "open" in res.error
    node, res = fill_at(d, (60, 215), (255, 0, 0, 255), gap=8.0)
    assert node is not None and res.closed_gap
    r = node.bounds()
    assert r.left() == 20 and r.top() == 180


def test_outside_is_not_filled(qapp):
    d = doc_with_shapes()
    node, res = fill_at(d, (380, 280), (255, 0, 0, 255), gap=3.0)
    assert node is None


def test_looks_closed_but_has_tiny_gaps():
    """A frame made of four separate strokes that nearly touch at the corners, inside a closed outer outline:
    the exact faces only see the OUTER area, but the fill must stay inside the visible frame."""
    from shapely.geometry import LineString
    from vectorflow.fill import find_region
    outer = LineString([(0, 0), (400, 0), (400, 400), (0, 400), (0, 0)])
    g = 2.0
    segs = [LineString([(100 + g, 100), (300 - g, 100)]), LineString([(300, 100 + g), (300, 300 - g)]),
            LineString([(300 - g, 300), (100 + g, 300)]), LineString([(100, 300 - g), (100, 100 + g)])]
    res = find_region([outer] + segs, (200, 200), gap=3.0, page=(400, 400), widths=[1.0] * 5)
    assert res.polygon is not None
    assert res.polygon.area < 200 * 200 * 1.1           # not the 400x400 outer area
    assert res.polygon.contains(__import__("shapely.geometry", fromlist=["Point"]).Point(200, 200))


def test_page_edge_closes_a_shape_that_leaves_the_sheet():
    from vectorflow.model import Document, Sheet
    from vectorflow.fill import fill_at
    import math
    d = Document()
    sh = d.sheets()[0]
    # half a circle poking out through the left edge of the sheet: only its arc is drawn
    cx, cy, r = sh.x, sh.y + 100, 60
    pts = [(cx + r * math.cos(a / 20 * math.pi - math.pi / 2), cy + r * math.sin(a / 20 * math.pi - math.pi / 2))
           for a in range(0, 21)]
    from vectorflow.model import PathNode, SubPath, Anchor, Style
    n = PathNode([SubPath([Anchor(x, y) for x, y in pts], False)], Style(fill=None, stroke=(0, 0, 0, 255), width=1.0), "arc")
    d.active_container().add(n)
    node, res = fill_at(d, (sh.x + 20, cy), (255, 0, 0, 255))
    assert node is not None, res.error
    b = node.bounds()
    assert b.left() >= sh.x - 2 and b.right() <= sh.x + r + 2
