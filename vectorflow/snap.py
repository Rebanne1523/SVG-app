"""Snapping: anchors, bounding-box alignment lines and stroke edges."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF

from .geometry import flatten_cubic
from .model import leaves


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


_LABELS = ["Center", "Anchor", "Corner", "Sheet corner", "Sheet center"]
_XL = ["Left edge", "Center", "Right edge", "Sheet edge", "Sheet center"]
_YL = ["Top edge", "Center", "Bottom edge", "Sheet edge", "Sheet center"]


def _node_points(n):
    """Snap points of a leaf as an (N, 2) array and a matching label index (cached on the node)."""
    c = n.__dict__.get("_c_snappts")
    if c is not None:
        return c
    b = n.bounds()
    l, t, r, bt = b.left(), b.top(), b.right(), b.bottom()
    pts = [((l + r) / 2, (t + bt) / 2)]
    lab = [0]
    if n.kind == "path":
        for sp in n.subpaths:
            for a in sp.anchors:
                pts.append((a.x, a.y))
                lab.append(1)
    else:
        for q in ((l, t), (r, t), (l, bt), (r, bt)):
            pts.append(q)
            lab.append(2)
    if n.kind == "measure":
        g = n.geometry()
        for s0, s1 in g["segs"]:
            pts.append(tuple(s0))
            pts.append(tuple(s1))
            lab += [1, 1]
    res = (np.asarray(pts, dtype=float).reshape(-1, 2), np.asarray(lab, dtype=np.int8),
           (l, (l + r) / 2, r, t, (t + bt) / 2, bt))
    n.__dict__["_c_snappts"] = res
    return res


class SnapIndex:
    """Anchors, centres, corners and alignment lines of every visible vector, in sorted numpy arrays
    so a lookup costs microseconds however big the drawing is. Built once per document state;
    :meth:`view` hides the vectors being dragged."""

    def __init__(self, doc, exclude=(), view_rect: QRectF | None = None, page=True):
        self.leaves = leaves_ = visible_leaves(doc)
        n = len(leaves_)
        self.index_of = {id(m): i for i, m in enumerate(leaves_)}
        pts, labs, counts, bb = [], [], [], []
        for m in leaves_:
            p, lab, box = _node_points(m)
            pts.append(p)
            labs.append(lab)
            counts.append(len(p))
            bb.append(box)
        owner = np.repeat(np.arange(n, dtype=np.int64), counts) if n else np.empty(0, dtype=np.int64)
        B = np.asarray(bb, dtype=float).reshape(-1, 6)
        ar = np.arange(n, dtype=np.int64)
        xv, xl, xo = B[:, 0:3].ravel(), np.tile(np.array([0, 1, 2], dtype=np.int8), n), np.repeat(ar, 3)
        yv, yl, yo = B[:, 3:6].ravel(), xl, xo
        owners = [owner] if n else []
        if page:
            extra, elab = [], []
            sx, sy = [], []
            for sh in doc.sheets():
                x0, y0, W, H = sh.x, sh.y, sh.width, sh.height
                sx.append((x0, x0 + W / 2, x0 + W))
                sy.append((y0, y0 + H / 2, y0 + H))
                for pt in ((x0, y0), (x0 + W, y0), (x0, y0 + H), (x0 + W, y0 + H)):
                    extra.append(pt)
                    elab.append(3)
                extra.append((x0 + W / 2, y0 + H / 2))
                elab.append(4)
            if extra:
                pts.append(np.asarray(extra, dtype=float))
                labs.append(np.asarray(elab, dtype=np.int8))
                owners.append(np.full(len(extra), -1, dtype=np.int64))
                k = len(sx)
                sl = np.tile(np.array([3, 4, 3], dtype=np.int8), k)
                so = np.full(3 * k, -1, dtype=np.int64)
                xv = np.concatenate([xv, np.asarray(sx, dtype=float).ravel()])
                yv = np.concatenate([yv, np.asarray(sy, dtype=float).ravel()])
                xl = np.concatenate([xl, sl])
                yl = np.concatenate([yl, sl])
                xo = np.concatenate([xo, so])
                yo = np.concatenate([yo, so])
        if pts:
            P = np.concatenate(pts)
            L = np.concatenate(labs)
            O = np.concatenate(owners)
            order = np.argsort(P[:, 0], kind="stable")
            self._px, self._py, self._pl, self._po = P[order, 0], P[order, 1], L[order], O[order]
        else:
            self._px = self._py = np.empty(0)
            self._pl = np.empty(0, dtype=np.int8)
            self._po = np.empty(0, dtype=np.int64)
        self._xv, self._xl, self._xo = self._sorted(xv, xl, xo)
        self._yv, self._yl, self._yo = self._sorted(yv, yl, yo)
        self._views = {}

    @staticmethod
    def _sorted(vals, labs, owners):
        v = np.asarray(vals, dtype=float)
        o = np.argsort(v, kind="stable")
        return v[o], np.asarray(labs, dtype=np.int8)[o], np.asarray(owners, dtype=np.int64)[o]

    def view(self, exclude=()):
        """Index that ignores ``exclude`` (nodes or folders)."""
        key = frozenset(id(n) for n in exclude)
        v = self._views.get(key)
        if v is None:
            excl = np.zeros(len(self.leaves) + 1, dtype=bool)     # last slot (owner -1: sheets) stays False
            for n in exclude:
                for m in (leaves(n) if n.is_group() else (n,)):
                    i = self.index_of.get(id(m))
                    if i is not None:
                        excl[i] = True
            v = _SnapView(self, excl)
            if len(self._views) > 8:
                self._views.clear()
            self._views[key] = v
        return v

    def nearest_point(self, pt, thr):
        return self.view().nearest_point(pt, thr)

    def nearest_x(self, x, thr):
        return self.view().nearest_x(x, thr)

    def nearest_y(self, y, thr):
        return self.view().nearest_y(y, thr)


class _SnapView:
    def __init__(self, base, excl):
        self.b = base
        self.excl = excl

    def nearest_point(self, pt, thr):
        b = self.b
        px = b._px
        if px.size == 0:
            return None
        i0 = np.searchsorted(px, pt[0] - thr, "left")
        i1 = np.searchsorted(px, pt[0] + thr, "right")
        if i1 <= i0:
            return None
        d = np.hypot(px[i0:i1] - pt[0], b._py[i0:i1] - pt[1])
        d[self.excl[b._po[i0:i1]]] = np.inf
        k = int(np.argmin(d))
        if d[k] > thr:
            return None
        j = i0 + k
        return (float(px[j]), float(b._py[j])), _LABELS[int(b._pl[j])]

    def _nearest(self, vals, labs, owners, names, v, thr):
        if vals.size == 0:
            return None
        i0 = int(np.searchsorted(vals, v - thr, "left"))
        i1 = int(np.searchsorted(vals, v + thr, "right"))
        if i1 <= i0:
            return None
        d = np.abs(vals[i0:i1] - v)
        d[self.excl[owners[i0:i1]]] = np.inf
        k = int(np.argmin(d))
        if d[k] > thr:
            return None
        j = i0 + k
        return float(vals[j]), names[int(labs[j])]

    def nearest_x(self, x, thr):
        b = self.b
        return self._nearest(b._xv, b._xl, b._xo, _XL, x, thr)

    def nearest_y(self, y, thr):
        b = self.b
        return self._nearest(b._yv, b._yl, b._yo, _YL, y, thr)


def _node_segments(n):
    """All segments of a leaf's outline as an (N, 4) array [x1, y1, x2, y2] (cached on the node)."""
    c = n.__dict__.get("_c_segarr")
    if c is not None:
        return c
    rows = []
    for pts, closed in polylines_of(n):
        m = len(pts)
        for i in range(m - 1):
            rows.append((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))
        if closed and m > 2:
            rows.append((pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]))
    c = np.asarray(rows, dtype=float).reshape(-1, 4)
    n.__dict__["_c_segarr"] = c
    return c


class EdgeIndex:
    """Nearest point on the outline of visible vectors (for the measure tool)."""

    def __init__(self, doc, exclude=(), view_rect: QRectF | None = None):
        arrs, owners = [], []
        self.index_of = {}
        for n in visible_leaves(doc):
            if n.kind not in ("path", "measure"):
                continue
            a = _node_segments(n)
            if a.size:
                self.index_of[id(n)] = len(self.index_of)
                arrs.append(a)
                owners.append(np.full(len(a), len(self.index_of) - 1, dtype=np.int64))
        S = np.concatenate(arrs) if arrs else np.empty((0, 4))
        O = np.concatenate(owners) if owners else np.empty(0, dtype=np.int64)
        # sort by the segment's smallest x so a query only looks at a window of them
        mn = np.minimum(S[:, 0], S[:, 2])
        order = np.argsort(mn, kind="stable")
        self._S = S[order]
        self._O = O[order]
        self._mn = mn[order]
        self._mx_cum = np.maximum.accumulate(np.maximum(self._S[:, 0], self._S[:, 2])) if len(S) else mn
        self._n = len(self.index_of)
        self._excl = np.zeros(self._n + 1, dtype=bool)
        self._excl_key = frozenset()
        self.set_exclude(exclude)

    def set_exclude(self, exclude):
        key = frozenset(id(n) for n in exclude)
        if key == self._excl_key:
            return
        self._excl_key = key
        self._excl = np.zeros(self._n + 1, dtype=bool)
        for n in exclude:
            for m in (leaves(n) if n.is_group() else (n,)):
                i = self.index_of.get(id(m))
                if i is not None:
                    self._excl[i] = True

    def nearest(self, pt, thr):
        S = self._S
        if len(S) == 0:
            return None
        # segments whose x-extent can reach [pt.x - thr, pt.x + thr]
        hi = int(np.searchsorted(self._mn, pt[0] + thr, "right"))
        lo = int(np.searchsorted(self._mx_cum, pt[0] - thr, "left"))
        if hi <= lo:
            return None
        W = S[lo:hi]
        ax, ay, bx, by = W[:, 0], W[:, 1], W[:, 2], W[:, 3]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(l2 < 1e-18, 0.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / l2)
        t = np.clip(t, 0.0, 1.0)
        qx, qy = ax + dx * t, ay + dy * t
        d = np.hypot(pt[0] - qx, pt[1] - qy)
        d[self._excl[self._O[lo:hi]]] = np.inf
        k = int(np.argmin(d))
        if d[k] > thr:
            return None
        return (float(qx[k]), float(qy[k]))
