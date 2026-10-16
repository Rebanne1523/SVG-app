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
