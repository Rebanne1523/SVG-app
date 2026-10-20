"""Numpy view of the anchors of a path node (shared by the Direct tool and the renderer)."""
from __future__ import annotations

import numpy as np


class AnchorTable:
    """Numpy view of every anchor of a path node (cached on the node, dropped on touch())."""
    __slots__ = ("flat", "loc", "X", "Y", "IX", "IY", "OX", "OY", "nxt", "_pos", "sub")

    def __init__(self, node):
        flat, loc, nxt = [], [], []
        base = 0
        for sp in node.subpaths:
            cnt = len(sp.anchors)
            for i, a in enumerate(sp.anchors):
                flat.append((sp, a))
                loc.append(i)
                nxt.append(base + i + 1 if i + 1 < cnt else (base if sp.closed and cnt > 1 else -1))
            base += cnt
        self.flat, self.loc = flat, loc
        n = len(flat)
        self.nxt = np.asarray(nxt, dtype=np.int64)
        f = np.fromiter
        self.X = f((a.x for _, a in flat), float, n)
        self.Y = f((a.y for _, a in flat), float, n)
        self.IX = f((a.ix for _, a in flat), float, n)
        self.IY = f((a.iy for _, a in flat), float, n)
        self.OX = f((a.ox for _, a in flat), float, n)
        self.OY = f((a.oy for _, a in flat), float, n)
        self._pos = None
        self.sub = None

    def sub_ids(self, node):
        """Index of the owning sub-path for every anchor (lazily built)."""
        if self.sub is None:
            self.sub = np.fromiter((i for i, sp in enumerate(node.subpaths) for _ in sp.anchors), np.int64,
                                   len(self.flat))
        return self.sub

    def position_of(self, anchor):
        """(index in the flat table) of an anchor object."""
        if self._pos is None:
            self._pos = {id(a): i for i, (_, a) in enumerate(self.flat)}
        return self._pos.get(id(anchor))


def anchor_table(node):
    t = node.__dict__.get("_c_atab")
    if t is None:
        t = node.__dict__["_c_atab"] = AnchorTable(node)
    return t
