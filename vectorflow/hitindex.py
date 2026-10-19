"""Flat, numpy-backed index of the selectable leaves, so picking and marquee selection don't walk
the whole scene tree in Python on every mouse move."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF

from .model import box4


class HitIndex:
    def __init__(self, doc):
        leaves, chains, rows = [], [], []

        def rec(node, chain):
            if not node.visible or node.locked:
                return
            if node.clip:
                chain = chain + (node,)
            if node.is_group():
                for c in node.children:
                    rec(c, chain)
                return
            st = getattr(node, "style", None)
            leaves.append(node)
            chains.append(chain)
            rows.append(box4(node) + (st.width if st is not None else 0.0,))

        for c in doc.root.children:
            rec(c, ())
        self.leaves = leaves
        self.chains = chains
        a = np.asarray(rows, dtype=float).reshape(-1, 5)
        self.l, self.t, self.r, self.b, self.w = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]
        self._solid = None

    def hit(self, p, tol, accept=None):
        """Topmost leaf under document point ``p`` (``tol`` = pick radius in document units)."""
        if not self.leaves:
            return None
        pad = tol + self.w + 2.0
        x, y = p
        mask = (x >= self.l - pad) & (x <= self.r + pad) & (y >= self.t - pad) & (y <= self.b + pad)
        pt = QPointF(x, y)
        rect = QRectF(x - tol, y - tol, 2 * tol, 2 * tol)
        for i in np.flatnonzero(mask)[::-1]:
            node = self.leaves[i]
            ok = True
            for g in self.chains[i]:
                cp = g.clip_path()
                if cp is not None and not cp.contains(pt):
                    ok = False
                    break
            if not ok:
                continue
            if accept is not None and not accept(node):
                continue
            if node.touches(rect):
                return node
        return None

    def in_rect(self, rect: QRectF):
        """Leaves (bottom to top) whose shape touches ``rect``."""
        if not self.leaves:
            return []
        # a perfectly horizontal / vertical line has an empty bounding box, and a thick stroke (or its
        # miter) sticks out of it: pad by one unit plus the stroke width
        pad = self.w * 2.0 + 1.0
        cand = np.flatnonzero((self.r + pad >= rect.left()) & (self.l - pad <= rect.right()) &
                              (self.b + pad >= rect.top()) & (self.t - pad <= rect.bottom()))
        if cand.size == 0:
            return []
        # leaves whose whole (stroked) box lies inside the rectangle certainly touch it
        pw = self.w[cand] * 2.0 + 2.0
        inside = ((self.l[cand] - pw >= rect.left()) & (self.r[cand] + pw <= rect.right()) &
                  (self.t[cand] - pw >= rect.top()) & (self.b[cand] + pw <= rect.bottom()))
        out = []
        for k, i in enumerate(cand):
            node = self.leaves[i]
            if inside[k]:
                if node.kind == "path":
                    if node.qpath().isEmpty():
                        continue
                    out.append(node)
                    continue
            if node.touches(rect):
                out.append(node)
        return out
