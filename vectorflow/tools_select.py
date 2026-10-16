"""Selection (V) and Direct selection (A) tools."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from . import affine
from .geometry import (bez, constrain_angle_projected, dist, nearest_on_polyline, split_cubic)
from .model import Anchor, fresh_copy, leaves
from .tools_base import Tool, rotate_cursor

SEL = QColor(0, 140, 255)
HANDLES = [(0, 0), (0.5, 0), (1, 0), (1, 0.5), (1, 1), (0.5, 1), (0, 1), (0, 0.5)]
SCALE_CURSORS = [Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor,
                 Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor]
CORNER_ANGLE = {0: 135, 2: 45, 4: -45, 6: -135}


def movable(nodes):
    """Selection without locked nodes / nodes below locked folders, pruned of descendants."""
    ids = {id(n) for n in nodes}
    out = []
    for n in nodes:
        if n.locked or any(a.locked for a in n.ancestors()):
            continue
        if any(id(a) in ids for a in n.ancestors()):
            continue
        out.append(n)
    return out


def leaf_set(nodes):
    res = []
    for n in nodes:
        if n.is_group():
            res.extend(leaves(n))
        else:
            res.append(n)
    return res


class SelectTool(Tool):
    name = "select"
    label = "Move / Select"
    shortcut = "V"
    hint = ("Click to select, drag to move (Shift = 45° steps, Alt = copy). Drag handles to scale; "
            "hover just outside a corner to rotate (Shift = 15° steps).")

    def __init__(self, canvas):
        super().__init__(canvas)
        self.reset()

    def reset(self):
        self.mode = None
        self.start = None
        self.start_v = None
        self.orig = {}
        self.nodes = []
        self.orig_rect = None
        self.handle = None
        self.dragging = False
        self.marquee = None
        self.angle_readout = None
        self.pending_toggle = None
        self.canvas.hover = None
        if self.doc is not None:
            pass

    def cursor(self):
        return QCursor(Qt.ArrowCursor)

    def options_widget(self, parent=None):
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(QLabel("Click selects:"))
        cb = QComboBox()
        cb.addItem("Item", "item")
        cb.addItem("Top-level item of layer", "folder")
        cb.setToolTip("Item: the exact vector under the cursor.\nTop-level item: the whole folder it sits in, "
                      "directly under its layer.")
        cb.setCurrentIndex(0 if self.canvas.select_level == "item" else 1)
        cb.currentIndexChanged.connect(lambda i: setattr(self.canvas, "select_level", cb.itemData(i)))
        lay.addWidget(cb)
        sc = QCheckBox("Scale strokes")
        sc.setChecked(self.canvas.scale_strokes)
        sc.toggled.connect(lambda v: setattr(self.canvas, "scale_strokes", v))
        lay.addWidget(sc)
        return w

    # --------------------------------------------------------------- helpers
    def sel_rect(self):
        sel = self.doc.selection
        if not sel:
            return None
        r = self.doc.bounds_of(sel)
        if r.isNull() and r.width() == 0 and r.height() == 0 and not sel:
            return None
        return r

    def _view_rect(self, r):
        a = self.canvas.to_view((r.left(), r.top()))
        b = self.canvas.to_view((r.right(), r.bottom()))
        return QRectF(QPointF(*a), QPointF(*b)).normalized()

    def hit_handle(self, vp):
        r = self.sel_rect()
        if r is None:
            return None
        vr = self._view_rect(r)
        pts = [(vr.left() + fx * vr.width(), vr.top() + fy * vr.height()) for fx, fy in HANDLES]
        for i in (0, 2, 4, 6, 1, 3, 5, 7):
            if abs(vp[0] - pts[i][0]) <= 6 and abs(vp[1] - pts[i][1]) <= 6:
                return ("scale", i)
        if not vr.adjusted(-1, -1, 1, 1).contains(QPointF(*vp)):
            for i in (0, 2, 4, 6):
                if dist(vp, pts[i]) <= 26:
                    return ("rotate", i)
        return None

    # --------------------------------------------------------------- events
    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        self.start = ev.p
        self.start_v = ev.vp
        self.dragging = False
        self.pending_toggle = None
        lab = self.canvas.hit_sheet_label(ev.vp)
        if lab is not None:
            # dragging a sheet's name tag moves the whole sheet with everything on it
            self.doc.set_selection([])
            self.doc.set_current_sheet(lab)
            self.mode = "sheet"
            self.sheet = lab
            self.doc.begin_edit()
            self.orig = {lab: lab.get_geom()}
            self.nodes = [lab]
            return
        h = None if ev.alt else self.hit_handle(ev.vp)
        if h is not None:
            self.nodes = movable(self.doc.selection)
            if not self.nodes:
                return
            self.mode = h[0]
            self.handle = h[1]
            self._begin_transform()
            return
        node = self.canvas.hit_test(ev.p)
        if node is not None:
            if ev.shift:
                if node in self.doc.selection:
                    # Shift+click toggles it off, Shift+drag still moves (constrained)
                    self.pending_toggle = node
                else:
                    self.doc.set_selection(self.doc.selection + [node])
            elif node not in self.doc.selection:
                self.doc.set_selection([node])
            self.nodes = movable(self.doc.selection)
            if not self.nodes:
                self.mode = None
                return
            self.mode = "move"
            self._begin_transform()
            self.copy_on_drag = ev.alt
        else:
            if not ev.shift:
                self.doc.set_selection([])
            under = self.doc.sheet_at(ev.p)
            if under is not None:
                self.doc.set_current_sheet(under)   # clicking an empty spot of a page selects that sheet
            self.mode = "marquee"
            self.marquee = QRectF(QPointF(*ev.p), QPointF(*ev.p))

    def _begin_transform(self):
        self.doc.begin_edit()
        self.orig = {n: n.get_geom() for n in self.nodes}
        self.orig_rect = QRectF(self.doc.bounds_of(self.nodes))
        self.dragging = False
        self.copy_on_drag = False
        self._exclude = leaf_set(self.nodes)

    def _restore(self):
        for n, g in self.orig.items():
            n.set_geom(g)

    def move(self, ev):
        if self.mode is None:
            self._hover(ev)
            return
        if not (ev.buttons & Qt.LeftButton):
            return
        if self.mode == "marquee":
            self.marquee = QRectF(QPointF(*self.start), QPointF(*ev.p)).normalized()
            return
        if not self.dragging:
            if dist(ev.vp, self.start_v) < 3:
                return
            self.dragging = True
            if self.mode == "move" and self.copy_on_drag:
                self._copy_selection()
        if self.mode == "sheet":
            dx, dy = ev.x - self.start[0], ev.y - self.start[1]
            if ev.shift:
                dx, dy = constrain_angle_projected((0, 0), (dx, dy), 90.0)
            self.sheet.set_geom(self.orig[self.sheet])
            self.sheet.transform(affine.translate(dx, dy))
            self.say(f"Sheet position  x {self.sheet.x:.1f}  y {self.sheet.y:.1f}")
        elif self.mode == "move":
            self._do_move(ev)
        elif self.mode == "scale":
            self._do_scale(ev)
        elif self.mode == "rotate":
            self._do_rotate(ev)

    def _hover(self, ev):
        c = self.canvas
        if c.hit_sheet_label(ev.vp) is not None:
            c.setCursor(Qt.SizeAllCursor)
            c.hover = None
            return
        h = self.hit_handle(ev.vp)
        if h is not None:
            if h[0] == "scale":
                c.setCursor(SCALE_CURSORS[h[1]])
            else:
                c.setCursor(rotate_cursor(CORNER_ANGLE[h[1]]))
            c.hover = None
            return
        c.setCursor(Qt.ArrowCursor)
        n = c.hit_test(ev.p)
        if n is not c.hover:
            c.hover = n
            c.update()

    def _copy_selection(self):
        """Alt-drag: leave the originals in place and drag copies."""
        self._restore()
        copies = []
        for n in self.nodes:
            cp = fresh_copy(n)
            n.parent.add(cp, n.parent.children.index(n) + 1)
            copies.append(cp)
        self.nodes = copies
        self.doc.set_selection(copies)
        self.orig = {n: n.get_geom() for n in copies}
        self._exclude = leaf_set(copies)
        self.doc.structureChanged.emit()
        self._structure_changed = True

    def _do_move(self, ev):
        dx, dy = ev.x - self.start[0], ev.y - self.start[1]
        allow_x = allow_y = True
        snap = True
        if ev.shift:
            dx, dy = constrain_angle_projected((0, 0), (dx, dy), 45.0)
            if abs(dy) < 1e-9:
                allow_y = False
            elif abs(dx) < 1e-9:
                allow_x = False
            else:
                snap = False
        if snap and self.canvas.snap_enabled:
            r = self.orig_rect
            keys = [(r.left(), r.top()), (r.right(), r.top()), (r.left(), r.bottom()), (r.right(), r.bottom()),
                    (r.center().x(), r.center().y())]
            count = 0
            for n in self._exclude:
                if n.kind == "path":
                    for sp in n.subpaths:
                        for a in sp.anchors:
                            if count < 120:
                                keys.append(a.p)
                                count += 1
            dx, dy = self.canvas.snap_move(keys, (dx, dy), self._exclude, allow_x, allow_y,
                                           xs=(r.left(), r.center().x(), r.right()),
                                           ys=(r.top(), r.center().y(), r.bottom()))
        else:
            self.canvas.clear_snap()
        m = affine.translate(dx, dy)
        for n in self.nodes:
            n.set_geom(self.orig[n])
            n.transform(m)
        self.say(f"Move  Δx {dx:.2f}  Δy {dy:.2f}")

    def _handle_point(self, r, i):
        fx, fy = HANDLES[i]
        return (r.left() + fx * r.width(), r.top() + fy * r.height())

    def _do_scale(self, ev):
        r = self.orig_rect
        i = self.handle
        hp = self._handle_point(r, i)
        cur = ev.p
        if not ev.shift:
            cur, _ = self.canvas.snap_point(cur, self._exclude, axes=True)
        else:
            self.canvas.clear_snap()
        anchor = self._handle_point(r, (i + 4) % 8)
        ctr = (r.center().x(), r.center().y())
        if ev.alt:
            anchor = ctr
        fx, fy = HANDLES[i]
        affects_x = fx != 0.5
        affects_y = fy != 0.5
        sx = sy = 1.0
        if affects_x and abs(hp[0] - anchor[0]) > 1e-9:
            sx = (cur[0] - anchor[0]) / (hp[0] - anchor[0])
        if affects_y and abs(hp[1] - anchor[1]) > 1e-9:
            sy = (cur[1] - anchor[1]) / (hp[1] - anchor[1])
        ax, ay = anchor
        if ev.shift:
            if affects_x and affects_y:
                s = max(abs(sx), abs(sy))
                sx = math.copysign(s, sx if sx != 0 else 1.0)
                sy = math.copysign(s, sy if sy != 0 else 1.0)
            elif affects_x:
                sy = sx
                ay = ctr[1]
            else:
                sx = sy
                ax = ctr[0]
        sx = sx if abs(sx) > 1e-3 else math.copysign(1e-3, sx or 1.0)
        sy = sy if abs(sy) > 1e-3 else math.copysign(1e-3, sy or 1.0)
        m = (sx, 0.0, 0.0, sy, ax * (1 - sx), ay * (1 - sy))
        for n in self.nodes:
            n.set_geom(self.orig[n])
            n.transform(m, self.canvas.scale_strokes)
        self.say(f"Scale  {sx * 100:.1f}% × {sy * 100:.1f}%")

    def _do_rotate(self, ev):
        r = self.orig_rect
        c = (r.center().x(), r.center().y())
        a0 = math.degrees(math.atan2(self.start[1] - c[1], self.start[0] - c[0]))
        a1 = math.degrees(math.atan2(ev.y - c[1], ev.x - c[0]))
        d = (a1 - a0 + 180) % 360 - 180
        nearest = round(d / 15.0) * 15.0
        if ev.shift or abs(d - nearest) < 2.5:
            d = nearest
        m = affine.rotate(d, c[0], c[1])
        for n in self.nodes:
            n.set_geom(self.orig[n])
            n.transform(m)
        self.angle_readout = (ev.vp, d)
        self.say(f"Rotate  {d:.1f}°")

    def release(self, ev):
        if ev.button != Qt.LeftButton:
            return
        mode = self.mode
        if mode == "marquee":
            rect = self.marquee
            self.marquee = None
            self.mode = None
            if rect is not None and (rect.width() * self.canvas.zoom > 3 or rect.height() * self.canvas.zoom > 3):
                found = self.canvas.nodes_in_rect(rect)
                if ev.shift:
                    found = self.doc.selection + [n for n in found if n not in self.doc.selection]
                self.doc.set_selection(found)
            return
        if mode == "sheet":
            if self.dragging:
                self.doc.end_edit(True)
            else:
                self.doc.cancel_edit()
            self.mode = None
            self.dragging = False
            self.say("")
            return
        if mode in ("move", "scale", "rotate"):
            changed = self.dragging
            if not changed and self.pending_toggle is not None and mode == "move":
                self.doc.cancel_edit()
                self.doc.set_selection([n for n in self.doc.selection if n is not self.pending_toggle])
                self.pending_toggle = None
                self.mode = None
                return
            struct = getattr(self, "_structure_changed", False)
            self._structure_changed = False
            if changed:
                if mode == "move" and self.doc.reassign_to_sheets(self.nodes):
                    struct = True      # dropped onto another sheet -> it now belongs to that sheet
                self.doc.end_edit(True, structure=struct)
                self.doc.set_selection(self.doc.selection)
            else:
                self.doc.cancel_edit()
            self.mode = None
            self.angle_readout = None
            self.canvas.clear_snap()
            self.canvas.update_cursor()
            self.say("")

    def double_click(self, ev):
        node = self.canvas.hit_test(ev.p, level="item")
        if node is None:
            return
        if node.kind in ("text", "measure"):
            self.canvas.edit_node_text(node)

    def key_press(self, e):
        key = e.key()
        step = 10.0 if e.modifiers() & Qt.ShiftModifier else 1.0
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}.get(key)
        if d and self.doc.selection and self.mode is None:
            nodes = movable(self.doc.selection)
            if nodes:
                with self.doc.edit(merge_key="nudge"):
                    for n in nodes:
                        n.transform(affine.translate(*d))
                return True
        if key == Qt.Key_Escape and self.mode in ("move", "scale", "rotate", "sheet"):
            self._restore()
            self.doc.cancel_edit()
            self.mode = None
            self.canvas.clear_snap()
            return True
        return False

    # --------------------------------------------------------------- painting
    def paint(self, p: QPainter):
        c = self.canvas
        if self.mode == "marquee" and self.marquee is not None:
            a = c.to_view((self.marquee.left(), self.marquee.top()))
            b = c.to_view((self.marquee.right(), self.marquee.bottom()))
            r = QRectF(QPointF(*a), QPointF(*b))
            pen = QPen(SEL)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(0, 140, 255, 30))
            p.drawRect(r)
        r = self.sel_rect()
        if r is None:
            return
        if self.mode in ("move",) and self.dragging:
            r = self.doc.bounds_of(self.doc.selection)
        vr = self._view_rect(r)
        pen = QPen(SEL)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(vr)
        p.setBrush(QColor(255, 255, 255))
        for fx, fy in HANDLES:
            x = vr.left() + fx * vr.width()
            y = vr.top() + fy * vr.height()
            p.drawRect(QRectF(x - 4, y - 4, 8, 8))
        if self.angle_readout:
            (vx, vy), ang = self.angle_readout
            text = f"{ang:+.1f}°"
            fm = p.fontMetrics()
            rr = QRectF(vx + 14, vy + 14, fm.horizontalAdvance(text) + 10, fm.height() + 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 20, 220))
            p.drawRoundedRect(rr, 3, 3)
            p.setPen(QColor(255, 255, 255))
            p.drawText(rr, Qt.AlignCenter, text)


# =============================================================================================
def segment_hit(a0: Anchor, a1: Anchor, p, samples=40):
    """(distance, t) for the closest point on the segment a0->a1 to p."""
    if not a0.has_out() and not a1.has_in():
        dx, dy = a1.x - a0.x, a1.y - a0.y
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a0.x) * dx + (p[1] - a0.y) * dy) / l2))
        q = (a0.x + dx * t, a0.y + dy * t)
        return dist(p, q), t
    pts = [bez(a0.p, a0.hout, a1.hin, a1.p, i / samples) for i in range(samples + 1)]
    d, q, i, tl = nearest_on_polyline(pts, p)
    return d, (i + tl) / samples


def split_segment(sp, seg_index, t):
    """Insert an anchor into subpath ``sp`` at parameter t of segment ``seg_index``. Returns the new anchor."""
    a = sp.anchors[seg_index]
    b = sp.anchors[(seg_index + 1) % len(sp.anchors)]
    if not a.has_out() and not b.has_in():
        q = (a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)
        new = Anchor(*q)
    else:
        l, r = split_cubic(a.p, a.hout, b.hin, b.p, t)
        new = Anchor(l[3][0], l[3][1], l[2][0], l[2][1], r[1][0], r[1][1], True)
        a.ox, a.oy = l[1]
        b.ix, b.iy = r[2]
    sp.anchors.insert(seg_index + 1, new)
    return new


def make_smooth(sp, i):
    a = sp.anchors[i]
    n = len(sp.anchors)
    prev = sp.anchors[i - 1] if (i > 0 or sp.closed) else None
    nxt = sp.anchors[(i + 1) % n] if (i < n - 1 or sp.closed) else None
    if prev is None and nxt is None:
        return
    p0 = prev.p if prev else a.p
    p1 = nxt.p if nxt else a.p
    tx, ty = p1[0] - p0[0], p1[1] - p0[1]
    l = math.hypot(tx, ty)
    if l < 1e-9:
        return
    tx, ty = tx / l, ty / l
    lin = dist(a.p, p0) / 3.0 if prev else 0.0
    lout = dist(a.p, p1) / 3.0 if nxt else 0.0
    a.ix, a.iy = a.x - tx * lin, a.y - ty * lin
    a.ox, a.oy = a.x + tx * lout, a.y + ty * lout
    a.smooth = True


class DirectTool(Tool):
    name = "direct"
    label = "Direct Selection"
    shortcut = "A"
    hint = ("Click a path to show its points. Drag points/handles/segments. Double-click a point to toggle "
            "smooth/corner, double-click a segment to add a point. Shift = 45° steps, Alt = break handle.")

    def __init__(self, canvas):
        super().__init__(canvas)
        self.scroll_mode = "path"   # "path": follow the path, "area": nearby points
        self.reset()

    def options_widget(self, parent=None):
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(QLabel("Scroll over a point selects:"))
        cb = QComboBox()
        cb.addItem("Connected points (along the path)", "path")
        cb.addItem("Nearby points (area)", "area")
        cb.setCurrentIndex(0 if self.scroll_mode == "path" else 1)
        cb.setToolTip("Hover a point and scroll up/down.\nConnected: grows along the path to BOTH sides of the "
                      "point you started on.\nArea: grows to every point near it, like Inkscape.")
        cb.currentIndexChanged.connect(lambda i: self._set_scroll_mode(cb.itemData(i)))
        lay.addWidget(cb)
        return w

    def _set_scroll_mode(self, mode):
        self.scroll_mode = mode
        self.scroll_origin = None
        self.scroll_steps = 0

    def reset(self):
        self.sel = []  # list of (node, anchor)
        self.scroll_origin = None
        self.scroll_steps = 0
        self._acc = 0
        self.mode = None
        self.start = None
        self.start_v = None
        self.orig = None
        self.marquee = None
        self.dragging = False
        self.drag_handle = None
        self.seg = None
        self.canvas.hover = None

    def cursor(self):
        return QCursor(Qt.ArrowCursor)

    def activate(self):
        super().activate()
        self.doc.selectionChanged.connect(self._prune)

    def deactivate(self):
        try:
            self.doc.selectionChanged.disconnect(self._prune)
        except (RuntimeError, TypeError):
            pass
        super().deactivate()

    def _prune(self):
        paths = set(id(n) for n in self.paths())
        self.sel = [(n, a) for n, a in self.sel if id(n) in paths]

    # --------------------------------------------------------------- helpers
    def paths(self):
        out = []
        for n in self.doc.selection:
            if n.is_group():
                out.extend(x for x in leaves(n) if x.kind == "path" and x.visible and not x.locked)
            elif n.kind == "path" and not n.locked:
                out.append(n)
        return out

    def is_sel(self, a):
        return any(x is a for _, x in self.sel)

    def hit_anchor(self, vp):
        best = None
        bd = 8.0
        for n in self.paths():
            for sp in n.subpaths:
                for a in sp.anchors:
                    v = self.canvas.to_view(a.p)
                    d = dist(v, vp)
                    if d <= bd:
                        bd, best = d, (n, sp, a)
        return best

    def hit_handle(self, vp):
        relevant = set()
        for n, a in self.sel:
            relevant.add(id(a))
        for n in self.paths():
            for sp in n.subpaths:
                cnt = len(sp.anchors)
                for i, a in enumerate(sp.anchors):
                    near = id(a) in relevant
                    if not near:
                        for j in (i - 1, i + 1):
                            if (0 <= j < cnt or sp.closed) and id(sp.anchors[j % cnt]) in relevant:
                                near = True
                    if not near:
                        continue
                    for which, has, pt in (("in", a.has_in(), a.hin), ("out", a.has_out(), a.hout)):
                        if has and dist(self.canvas.to_view(pt), vp) <= 7:
                            return (n, sp, a, which)
        return None

    def hit_segment(self, p):
        tol = 6.0 / self.canvas.zoom
        best = None
        for n in self.paths():
            for sp in n.subpaths:
                for i, a0, a1 in sp.segments():
                    d, t = segment_hit(a0, a1, p)
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, n, sp, i, t)
        return best

    # --------------------------------------------------------------- events
    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        self.start = ev.p
        self.start_v = ev.vp
        self.dragging = False
        self.mode = None
        self.scroll_origin = None
        h = self.hit_handle(ev.vp)
        if h is not None:
            n, sp, a, which = h
            self.mode = "handle"
            self.drag_handle = h
            self.doc.begin_edit()
            return
        hit = self.hit_anchor(ev.vp)
        if hit is not None:
            n, sp, a = hit
            if ev.shift:
                if self.is_sel(a):
                    self.sel = [(x, y) for x, y in self.sel if y is not a]
                    return
                self.sel.append((n, a))
            elif not self.is_sel(a):
                self.sel = [(n, a)]
            self.mode = "anchors"
            self.primary = (n, a)
            self.doc.begin_edit()
            self.orig = [(x, y, (y.x, y.y, y.ix, y.iy, y.ox, y.oy)) for x, y in self.sel]
            return
        seg = self.hit_segment(ev.p) if self.paths() else None
        if seg is not None:
            _, n, sp, i, t = seg
            self.mode = "segment"
            self.seg = (n, sp, i, t)
            a0 = sp.anchors[i]
            a1 = sp.anchors[(i + 1) % len(sp.anchors)]
            self.sel = [(n, a0), (n, a1)]
            self.doc.begin_edit()
            self.orig = [(n, a0, (a0.x, a0.y, a0.ix, a0.iy, a0.ox, a0.oy)),
                         (n, a1, (a1.x, a1.y, a1.ix, a1.iy, a1.ox, a1.oy))]
            return
        node = self.canvas.hit_test(ev.p, level="item", accept=lambda x: x.kind == "path")
        if node is not None:
            if ev.shift and node in self.doc.selection:
                pass
            else:
                self.doc.set_selection(self.doc.selection + [node] if ev.shift else [node])
            self.sel = []
            return
        # empty space -> marquee
        if not ev.shift:
            self.sel = []
            if not self.paths():
                self.doc.set_selection([])
        self.mode = "marquee"
        self.marquee = QRectF(QPointF(*ev.p), QPointF(*ev.p))

    def _restore_orig(self):
        for n, a, o in self.orig:
            a.x, a.y, a.ix, a.iy, a.ox, a.oy = o

    def move(self, ev):
        c = self.canvas
        if self.mode is None:
            if not (ev.buttons & Qt.LeftButton):
                n = c.hit_test(ev.p, accept=lambda x: x.kind == "path")
                if n is not c.hover:
                    c.hover = n
                hh = self.hit_handle(ev.vp) or self.hit_anchor(ev.vp)
                c.setCursor(Qt.PointingHandCursor if hh else Qt.ArrowCursor)
            return
        if not (ev.buttons & Qt.LeftButton):
            return
        if self.mode == "marquee":
            self.marquee = QRectF(QPointF(*self.start), QPointF(*ev.p)).normalized()
            return
        if not self.dragging:
            if dist(ev.vp, self.start_v) < 3:
                return
            self.dragging = True
        exclude = list({id(n): n for n in self.paths()}.values())
        if self.mode == "anchors":
            pn, pa = self.primary
            o = next(o for x, y, o in self.orig if y is pa)
            target = (o[0] + ev.x - self.start[0], o[1] + ev.y - self.start[1])
            if ev.shift:
                target = constrain_angle_projected((o[0], o[1]), (target[0], target[1]), 45.0)
                self.canvas.clear_snap()
            else:
                target, _ = self.canvas.snap_point(target, exclude)
            dx, dy = target[0] - o[0], target[1] - o[1]
            for n, a, o in self.orig:
                a.x, a.y, a.ix, a.iy, a.ox, a.oy = (o[0] + dx, o[1] + dy, o[2] + dx, o[3] + dy, o[4] + dx, o[5] + dy)
            for n in {id(n): n for n, _ in self.sel}.values():
                n.touch()
            self.say(f"Move point  Δx {dx:.2f}  Δy {dy:.2f}")
        elif self.mode == "handle":
            n, sp, a, which = self.drag_handle
            target = ev.p
            if ev.shift:
                target = constrain_angle_projected(a.p, target, 45.0)
                self.canvas.clear_snap()
            else:
                target, _ = self.canvas.snap_point(target, exclude)
            if ev.alt:
                a.smooth = False
            if which == "out":
                a.set_out(target[0], target[1])
            else:
                a.set_in(target[0], target[1])
            n.touch()
        elif self.mode == "segment":
            self._drag_segment(ev)

    def _drag_segment(self, ev):
        n, sp, i, t = self.seg
        dx, dy = ev.x - self.start[0], ev.y - self.start[1]
        self._restore_orig()
        a0 = sp.anchors[i]
        a1 = sp.anchors[(i + 1) % len(sp.anchors)]
        if not a0.has_out() and not a1.has_in():
            for _, a, o in self.orig:
                a.x, a.y, a.ix, a.iy, a.ox, a.oy = (o[0] + dx, o[1] + dy, o[2] + dx, o[3] + dy, o[4] + dx, o[5] + dy)
        else:
            tt = max(0.15, min(0.85, t))
            w = 1.0 / (3.0 * tt * (1.0 - tt))
            a0.set_out(a0.ox + dx * w, a0.oy + dy * w)
            a1.set_in(a1.ix + dx * w, a1.iy + dy * w)
        n.touch()

    def release(self, ev):
        if ev.button != Qt.LeftButton:
            return
        mode = self.mode
        self.mode = None
        if mode == "marquee":
            rect = self.marquee
            self.marquee = None
            if rect is None:
                return
            small = rect.width() * self.canvas.zoom < 3 and rect.height() * self.canvas.zoom < 3
            if small:
                return
            if self.paths():
                found = []
                for n in self.paths():
                    for sp in n.subpaths:
                        for a in sp.anchors:
                            if rect.contains(QPointF(a.x, a.y)):
                                found.append((n, a))
                if ev.shift:
                    ids = {id(a) for _, a in self.sel}
                    self.sel += [(n, a) for n, a in found if id(a) not in ids]
                else:
                    self.sel = found
            else:
                nodes = [n for n in self.canvas.nodes_in_rect(rect, "item") if n.kind == "path"]
                self.doc.set_selection(nodes)
            return
        if mode in ("anchors", "handle", "segment"):
            if self.dragging:
                self.doc.end_edit(True)
            else:
                self.doc.cancel_edit()
            self.dragging = False
            self.canvas.clear_snap()
            self.say("")

    def double_click(self, ev):
        hit = self.hit_anchor(ev.vp)
        if hit is not None:
            n, sp, a = hit
            i = sp.anchors.index(a)
            with self.doc.edit():
                if a.has_in() or a.has_out():
                    a.collapse()
                else:
                    make_smooth(sp, i)
                n.touch()
            return
        seg = self.hit_segment(ev.p)
        if seg is not None:
            _, n, sp, i, t = seg
            with self.doc.edit():
                new = split_segment(sp, i, t)
                n.touch()
            self.sel = [(n, new)]

    # --- scroll-wheel point selection ----------------------------------------------------
    def wheel(self, ev, delta):
        """Hover a point and scroll: grow (up) / shrink (down) the selection from that point,
        either along the path to both sides ("path") or to all nearby points ("area")."""
        if not self.paths():
            return False
        hit = self.hit_anchor(ev.vp)
        if hit is None:
            o = self.scroll_origin
            if o is None or dist(self.canvas.to_view(o[2].p), ev.vp) > 40:
                self.scroll_origin = None
                return False
        elif self.scroll_origin is None or hit[2] is not self.scroll_origin[2]:
            self.scroll_origin = hit
            self.scroll_steps = 0
            self._acc = 0
            self.sel = [(hit[0], hit[2])]
        self._acc += delta
        notches = int(self._acc / 120)
        if notches == 0:
            return True
        self._acc -= notches * 120
        self.scroll_steps = max(0, self.scroll_steps + notches)
        self._apply_scroll_selection()
        return True

    def _apply_scroll_selection(self):
        node, sp, a = self.scroll_origin
        steps = self.scroll_steps
        if self.scroll_mode == "path":
            anchors = sp.anchors
            n = len(anchors)
            idx = next((i for i, x in enumerate(anchors) if x is a), 0)
            chosen = [a]
            for k in range(1, min(steps, n) + 1):
                for direction in (1, -1):
                    j = idx + direction * k
                    if sp.closed:
                        j %= n
                    elif not 0 <= j < n:
                        continue
                    if not any(x is anchors[j] for x in chosen):
                        chosen.append(anchors[j])
            self.sel = [(node, x) for x in chosen]
        else:
            radius = 28.0 / self.canvas.zoom * steps
            res = []
            for nd in self.paths():
                for sub in nd.subpaths:
                    for x in sub.anchors:
                        if x is a or dist(x.p, a.p) <= radius:
                            res.append((nd, x))
            self.sel = res
        self.say(f"{len(self.sel)} point(s) selected")

    def on_delete(self):
        if not self.sel:
            return False
        with self.doc.edit(structure=True):
            for n, a in list(self.sel):
                for sp in list(n.subpaths):
                    if any(x is a for x in sp.anchors):
                        sp.anchors = [x for x in sp.anchors if x is not a]
                        if len(sp.anchors) < 2:
                            n.subpaths.remove(sp)
                        elif len(sp.anchors) == 2 and sp.closed:
                            pass
                n.touch()
            for n in {id(n): n for n, _ in self.sel}.values():
                if not n.subpaths and n.parent is not None:
                    n.parent.children.remove(n)
                    n.parent = None
        self.sel = []
        self.doc.selection = [n for n in self.doc.selection if n.parent is not None]
        self.doc.selectionChanged.emit()
        return True

    def key_press(self, e):
        step = 10.0 if e.modifiers() & Qt.ShiftModifier else 1.0
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}.get(e.key())
        if d and self.sel and self.mode is None:
            with self.doc.edit(merge_key="nudge-anchor"):
                for n, a in self.sel:
                    a.move_to(a.x + d[0], a.y + d[1])
                    n.touch()
            return True
        if e.key() == Qt.Key_Escape and self.mode in ("anchors", "handle", "segment"):
            if self.orig:
                self._restore_orig()
                for n in {id(n): n for n, _, _ in self.orig}.values():
                    n.touch()
            self.doc.cancel_edit()
            self.mode = None
            return True
        if e.key() == Qt.Key_Escape and self.sel:
            self.sel = []
            return True
        return False

    # --------------------------------------------------------------- painting
    def paint(self, p: QPainter):
        c = self.canvas
        if self.mode == "marquee" and self.marquee is not None:
            a = c.to_view((self.marquee.left(), self.marquee.top()))
            b = c.to_view((self.marquee.right(), self.marquee.bottom()))
            pen = QPen(SEL)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(0, 140, 255, 30))
            p.drawRect(QRectF(QPointF(*a), QPointF(*b)))
        sel_ids = {id(a) for _, a in self.sel}
        for n in self.paths():
            for sp in n.subpaths:
                cnt = len(sp.anchors)
                for i, a in enumerate(sp.anchors):
                    show = id(a) in sel_ids
                    if not show:
                        for j in (i - 1, i + 1):
                            if (0 <= j < cnt or sp.closed) and id(sp.anchors[j % cnt]) in sel_ids:
                                show = True
                    if show:
                        v = c.to_view(a.p)
                        pen = QPen(SEL)
                        pen.setWidthF(1.0)
                        p.setPen(pen)
                        for has, pt in ((a.has_in(), a.hin), (a.has_out(), a.hout)):
                            if has:
                                hv = c.to_view(pt)
                                p.drawLine(QPointF(*v), QPointF(*hv))
                                p.setBrush(QColor(255, 255, 255))
                                p.drawEllipse(QPointF(*hv), 3.5, 3.5)
                for a in sp.anchors:
                    v = c.to_view(a.p)
                    selected = id(a) in sel_ids
                    pen = QPen(SEL)
                    pen.setWidthF(1.2)
                    p.setPen(pen)
                    p.setBrush(SEL if selected else QColor(255, 255, 255))
                    r = QRectF(v[0] - 3.5, v[1] - 3.5, 7, 7)
                    if a.smooth:
                        p.drawEllipse(r)
                    else:
                        p.drawRect(r)
