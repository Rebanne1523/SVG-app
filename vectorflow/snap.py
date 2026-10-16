"""Snapping: anchors, bounding-box alignment lines and stroke edges."""
from __future__ import annotations

import bisect
import math

from PySide6.QtCore import QRectF

from .geometry import dist, flatten_cubic, nearest_on_polyline


def visible_leaves(doc, exclude=()):
    ex = set(id(n) for n in exclude)
    out = []

    def rec(n, hidden):
        if not n.visible:
            return
        if id(n) in ex:
            return
        if n.is_group():
            for c in n.children:
                rec(c, hidden)
        else:
            out.append(n)

    for c in doc.root.children:
        rec(c, False)
    return out


def polylines_of(node):
    """Flattened polylines for a path node: list of (points, closed)."""
    res = getattr(node, "_c_polys", None)
    if res is not None:
        return res
    res = []
    if node.kind == "path":
        for sp in node.subpaths:
            if not sp.anchors:
                continue
            pts = [sp.anchors[0].p]
            for _, a, b in sp.segments():
                if not a.has_out() and not b.has_in():
                    pts.append(b.p)
                else:
                    pts.extend(flatten_cubic(a.p, a.hout, b.hin, b.p))
            res.append((pts, sp.closed))
    elif node.kind == "measure":
        g = node.geometry()
        for a, b in g["segs"]:
            res.append(([a, b], False))
    node._c_polys = res
    return res


class SnapIndex:
    def __init__(self, doc, exclude=(), view_rect: QRectF | None = None, page=True):
        self.points = []
        self.grid = {}
        self.cell = 24.0
        xs, ys = [], []
        nodes = visible_leaves(doc, exclude)
        if view_rect is not None:
            infl = view_rect.adjusted(-view_rect.width() * 0.25, -view_rect.height() * 0.25,
                                      view_rect.width() * 0.25, view_rect.height() * 0.25)
        for n in nodes:
            b = n.bounds()
            if view_rect is not None and not infl.intersects(b.adjusted(-1, -1, 1, 1)):
                continue
            l, t, r, bt = b.left(), b.top(), b.right(), b.bottom()
            cx, cy = (l + r) / 2, (t + bt) / 2
            xs += [(l, "Left edge"), (cx, "Center"), (r, "Right edge")]
            ys += [(t, "Top edge"), (cy, "Center"), (bt, "Bottom edge")]
            self._add_point((cx, cy), "Center")
            if n.kind == "path":
                for sp in n.subpaths:
                    for a in sp.anchors:
                        self._add_point(a.p, "Anchor")
            else:
                for p in ((l, t), (r, t), (l, bt), (r, bt)):
                    self._add_point(p, "Corner")
            if n.kind == "measure":
                g = n.geometry()
                for s0, s1 in g["segs"]:
                    self._add_point(s0, "Anchor")
                    self._add_point(s1, "Anchor")
        if page:
            W, H = doc.width, doc.height
            xs += [(0.0, "Page edge"), (W / 2, "Page center"), (W, "Page edge")]
            ys += [(0.0, "Page edge"), (H / 2, "Page center"), (H, "Page edge")]
            for p in ((0, 0), (W, 0), (0, H), (W, H)):
                self._add_point(p, "Page corner")
            self._add_point((W / 2, H / 2), "Page center")
        xs.sort()
        ys.sort()
        self.xs = xs
        self.ys = ys
        self._xk = [v for v, _ in xs]
        self._yk = [v for v, _ in ys]

    def _add_point(self, p, label):
        self.points.append((p, label))
        key = (int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell)))
        self.grid.setdefault(key, []).append((p, label))

    def nearest_point(self, pt, thr):
        best = None
        bd = thr
        cx, cy = int(math.floor(pt[0] / self.cell)), int(math.floor(pt[1] / self.cell))
        r = int(math.ceil(thr / self.cell))
        for ix in range(cx - r, cx + r + 1):
            for iy in range(cy - r, cy + r + 1):
                for p, label in self.grid.get((ix, iy), ()):
                    d = dist(p, pt)
                    if d <= bd:
                        bd, best = d, (p, label)
        return best

    @staticmethod
    def _nearest(keys, items, v, thr):
        i = bisect.bisect_left(keys, v)
        best = None
        bd = thr
        for j in (i - 1, i):
            if 0 <= j < len(keys):
                d = abs(keys[j] - v)
                if d <= bd:
                    bd, best = d, items[j]
        return best

    def nearest_x(self, x, thr):
        return self._nearest(self._xk, self.xs, x, thr)

    def nearest_y(self, y, thr):
        return self._nearest(self._yk, self.ys, y, thr)


class EdgeIndex:
    """Nearest point on the outline of visible vectors (for the measure tool)."""

    def __init__(self, doc, exclude=(), view_rect: QRectF | None = None):
        self.items = []
        for n in visible_leaves(doc, exclude):
            if n.kind not in ("path", "measure"):
                continue
            b = n.bounds()
            if view_rect is not None and not view_rect.intersects(b.adjusted(-1, -1, 1, 1)):
                continue
            self.items.append((b, polylines_of(n)))

    def nearest(self, pt, thr):
        best = None
        bd = thr
        for b, polys in self.items:
            if (pt[0] < b.left() - thr or pt[0] > b.right() + thr or
                    pt[1] < b.top() - thr or pt[1] > b.bottom() + thr):
                continue
            for pts, closed in polys:
                d, q, _, _ = nearest_on_polyline(pts, pt, closed)
                if q is not None and d <= bd:
                    bd, best = d, q
        return best
