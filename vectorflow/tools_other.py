"""Hand (H), Zoom (Z), Paint bucket (G) and Measure (I) tools."""
from __future__ import annotations

import math


from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QPainterPath
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QInputDialog, QLabel, QWidget)

from .numfield import NumField
from .fill import fill_at
from .geometry import constrain_angle_projected, dist
from .model import MeasureNode, Style, walk
from .render import draw_node
from .tools_base import Tool

ACCENT = QColor(0, 140, 255)
PINK = QColor(255, 60, 200)


class HandTool(Tool):
    name = "hand"
    label = "Hand"
    shortcut = "H"
    hint = "Drag to pan. Hold Space with any tool for a temporary hand."

    def __init__(self, canvas):
        super().__init__(canvas)
        self.last = None

    def cursor(self):
        return QCursor(Qt.OpenHandCursor)

    def press(self, ev):
        self.last = ev.vp
        self.canvas.setCursor(Qt.ClosedHandCursor)

    def move(self, ev):
        if self.last is not None and (ev.buttons & Qt.LeftButton):
            self.canvas.pan_by(ev.vp[0] - self.last[0], ev.vp[1] - self.last[1])
            self.last = ev.vp

    def release(self, ev):
        self.last = None
        self.canvas.setCursor(Qt.OpenHandCursor)


class ZoomTool(Tool):
    name = "zoom"
    label = "Zoom"
    shortcut = "Z"
    hint = "Click to zoom in, Alt+click to zoom out, drag a rectangle to zoom to it."

    def __init__(self, canvas):
        super().__init__(canvas)
        self.start = None
        self.rect = None

    def cursor(self):
        return QCursor(Qt.CrossCursor)

    def press(self, ev):
        self.start = ev.vp
        self.rect = None

    def move(self, ev):
        if self.start is not None and (ev.buttons & Qt.LeftButton):
            self.rect = QRectF(QPointF(*self.start), QPointF(*ev.vp)).normalized()

    def release(self, ev):
        if self.start is None:
            return
        c = self.canvas
        if self.rect is not None and self.rect.width() > 6 and self.rect.height() > 6 and not ev.alt:
            r = self.rect
            a = c.to_doc((r.left(), r.top()))
            b = c.to_doc((r.right(), r.bottom()))
            w, h = b[0] - a[0], b[1] - a[1]
            z = min(c.width() / w, c.height() / h) * 0.95
            c.set_zoom(z, (c.width() / 2, c.height() / 2))
            cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            c.origin = QPointF(c.width() / 2 - cx * c.zoom, c.height() / 2 - cy * c.zoom)
            c._view_changed()
        else:
            c.zoom_by(1 / 1.5 if ev.alt else 1.5, ev.vp)
        self.start = None
        self.rect = None

    def paint(self, p):
        if self.rect is not None:
            pen = QPen(ACCENT)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect)


def bucket_cursor():
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    for col, w in ((QColor(255, 255, 255), 3.2), (QColor(0, 0, 0), 1.4)):
        p.setPen(QPen(col, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(6, 18)
        path.lineTo(14, 10)
        path.lineTo(22, 18)
        path.lineTo(14, 26)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(14, 10, 14, 5)
        p.drawEllipse(QPointF(25, 24), 1.8, 2.6)
    p.end()
    return QCursor(pm, 25, 27)


class BucketTool(Tool):
    name = "bucket"
    label = "Paint Bucket"
    shortcut = "G"
    hint = ("Click inside an enclosed area to fill it. It works on the vector outlines, not on what is visible, "
            "and closes small gaps. Alt+click recolours the shape under the cursor instead.")

    def __init__(self, canvas):
        super().__init__(canvas)
        self.gap = 3.0

    def cursor(self):
        return bucket_cursor()

    def options_widget(self, parent=None):
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(QLabel("Close gaps up to:"))
        sp = NumField()
        sp.setRange(0, 200)
        sp.setSingleStep(0.5)
        sp.setSuffix(" px")
        sp.setValue(self.gap)
        sp.setToolTip("Gaps in an outline smaller than this are treated as closed (document units).\n"
                      "Independent of the zoom level.")
        sp.valueChanged.connect(lambda v: setattr(self, "gap", v))
        lay.addWidget(sp)
        return w

    def _color(self):
        st = self.doc.default_style
        return st.fill or st.stroke or (0, 0, 0, 255)

    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        col = self._color()
        if ev.alt:
            node = self.canvas.hit_test(ev.p, level="item", accept=lambda n: getattr(n, "style", None) is not None
                                        and n.style.fill is not None)
            if node is None:
                self.say("No filled shape under the cursor.")
                return
            self.doc.apply_style([node], fill=col)
            return
        node, res = fill_at(self.doc, ev.p, col, self.gap)
        if node is None:
            self.say(res.error or "Nothing to fill here.")
            return
        node.name = self.doc.new_name("Fill")
        parent, index = self._placement(ev.p)
        with self.doc.edit(structure=True):
            self.doc.add_node(node, parent, index)
        self.doc.set_selection([node])
        self.say("Filled" + (" (gap closed)" if res.closed_gap else ""))

    def _placement(self, pt):
        """Just above the topmost filled shape under the click, else at the bottom of the active layer."""
        from PySide6.QtCore import QPointF as P
        from .model import walk
        best = None
        for n in walk(self.doc.root):
            if n.kind == "path" and n.visible and n.style.fill and n.qpath().contains(P(*pt)):
                best = n
        if best is not None and best.parent is not None:
            return best.parent, best.parent.children.index(best) + 1
        return self.doc.active_container(), 0


class MeasureTool(Tool):
    name = "measure"
    label = "Measure"
    shortcut = "I"
    hint = ("Click point A, click point B, then click to set the offset (U / L shape) and type the value. "
            "Scroll wheel flips the arrow at the point you just placed. Shift = 45° steps. Esc cancels.")

    def __init__(self, canvas):
        super().__init__(canvas)
        self.reset()

    def reset(self):
        self.stage = 0
        self.a = None
        self.b = None
        self.cur = None
        self.offset = 0.0
        self.mode_a = "leg"
        self.mode_b = "leg"
        self.edges = getattr(self, "edges", True)
        self.drag_a = None      # press-and-drag at A / B: where the arrow starts (document point)
        self.drag_b = None
        self._down = None       # ("a" | "b", press point) while the button is held

    def cursor(self):
        return QCursor(Qt.CrossCursor)

    def options_widget(self, parent=None):
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        cb = QCheckBox("Snap to edges")
        cb.setChecked(self.edges)
        cb.toggled.connect(lambda v: setattr(self, "edges", v))
        lay.addWidget(cb)
        return w

    # ----------------------------------------------------------------
    def _snap(self, ev, ref=None):
        pt = ev.p
        if ev.shift and ref is not None:
            self.canvas.clear_snap()
            return constrain_angle_projected(ref, pt, 45.0)
        pt, _ = self.canvas.snap_point(pt, (), edges=self.edges)
        return pt

    def press(self, ev):
        if ev.button == Qt.RightButton:
            self.reset()
            self.canvas.clear_snap()
            return
        if ev.button != Qt.LeftButton:
            return
        if self.stage == 0:
            self.a = self._snap(ev)
            self.cur = self.a
            self.stage = 1
            self._down = ("a", self.a)
            self.say("Move to the second point and click. Scroll to flip the first arrow.")
        elif self.stage == 1:
            b = self._snap(ev, self.a)
            if dist(b, self.a) < 1e-6:
                return
            self.b = b
            self.stage = 2
            self._down = ("b", b)
            self.offset = 0.0
            self.say("Move to choose the side and height, then click. Scroll to flip the second arrow.")
        elif self.stage == 2:
            self._finish()

    def move(self, ev):
        if self._down is not None:
            self.cur = self._snap(ev)
            self.say("Release where the arrow should start")
            return
        if self.stage == 0:
            self.cur = self._snap(ev)
        elif self.stage == 1:
            self.cur = self._snap(ev, self.a)
            self.say(f"Length {dist(self.a, self.cur):.2f}")
        elif self.stage == 2:
            self._update_offset(ev)

    def release(self, ev):
        if self._down is None:
            return
        which, origin = self._down
        self._down = None
        pt = self._snap(ev)
        if dist(pt, origin) * self.canvas.zoom < 5:
            self.cur = origin if which == "a" else self.cur
            return
        vec = (pt[0] - origin[0], pt[1] - origin[1])
        if which == "a":
            self.drag_a = vec
            self.cur = origin
        else:
            self.drag_b = vec
        self.say("Arrow start set. " + ("Move to the second point and click." if which == "a"
                                         else "Move to choose the side and height, then click."))

    def _gap(self, vec):
        if vec is None:
            return None
        ax, ay = self.a
        bx, by = self.b
        l = dist(self.a, self.b)
        if l < 1e-9:
            return None
        nx, ny = -(by - ay) / l, (bx - ax) / l
        proj = abs(vec[0] * nx + vec[1] * ny)
        full = math.hypot(*vec)
        return proj if proj >= 0.3 * full else full

    def _template(self):
        for n in walk(self.doc.root):
            if n.kind == "measure" and n.linked:
                return n
        return None

    def _update_offset(self, ev):
        ax, ay = self.a
        bx, by = self.b
        l = dist(self.a, self.b)
        ux, uy = (bx - ax) / l, (by - ay) / l
        nx, ny = -uy, ux
        p = ev.p
        self.canvas.clear_snap()
        if self.canvas.snap_enabled and not ev.shift:
            # axis-aligned measurements may align the dimension line with other geometry
            if abs(uy) < 1e-6:
                q, _ = self.canvas.snap_point(p, (), axes=True)
                self.canvas.guides = [g for g in self.canvas.guides if g[0] == "y"]
                p = (p[0], q[1])
                self.canvas.snap_marker = None
            elif abs(ux) < 1e-6:
                q, _ = self.canvas.snap_point(p, (), axes=True)
                self.canvas.guides = [g for g in self.canvas.guides if g[0] == "x"]
                p = (q[0], p[1])
                self.canvas.snap_marker = None
        off = (p[0] - ax) * nx + (p[1] - ay) * ny
        if abs(off) * self.canvas.zoom < 6:
            off = 0.0
        self.offset = off
        self.cur = p
        self.say(f"Length {l:.2f}   offset {abs(off):.2f}")

    def wheel(self, ev, delta):
        if self.stage not in (1, 2):
            return False
        # one flip per wheel notch (120 units); touchpads send many tiny deltas
        self._acc = getattr(self, "_acc", 0) + delta
        if abs(self._acc) < 120:
            return True
        self._acc = 0
        if self.stage == 1:
            self.mode_a = "line" if self.mode_a == "leg" else "leg"
            self.say("First end: " + ("arrow along the line" if self.mode_a == "line" else "arrow along the leg"))
            return True
        if self.stage == 2:
            self.mode_b = "line" if self.mode_b == "leg" else "leg"
            self.say("Second end: " + ("arrow along the line" if self.mode_b == "line" else "arrow along the leg"))
            return True
        return True

    def key_press(self, e):
        if e.key() == Qt.Key_Escape and self.stage:
            self.reset()
            self.canvas.clear_snap()
            return True
        return False

    def _new_node(self, text=""):
        z = self.canvas.zoom
        size = max(0.5, float(f"{14.0 / z:.2g}"))
        width = max(0.2, float(f"{1.3 / z:.2g}"))
        st = Style(fill=None, stroke=(0, 0, 0, 255), width=width)
        td = self.canvas.text_defaults
        node = MeasureNode(self.a, self.b, self.offset, text, self.mode_a, self.mode_b, st,
                           family=td["family"], font_size=size, text_color=(0, 0, 0, 255),
                           bold=td["bold"], italic=td["italic"], name="Measure")
        # new lines look like the existing ones: the project-wide settings carry over
        t = self._template()
        gap_a = gap_b = 0.0
        if t is not None:
            node.style = t.style.copy()
            node.family, node.font_size = t.family, t.font_size
            node.bold, node.italic, node.text_color = t.bold, t.italic, t.text_color
            node.arrow_kind = t.arrow_kind
            gap_a, gap_b = t.gap_a, t.gap_b
        ga, gb = self._gap(self.drag_a), self._gap(self.drag_b)
        node.gap_a = gap_a if ga is None else ga
        node.gap_b = gap_b if gb is None else gb
        node.linked = ga is None and gb is None
        return node

    def _finish(self):
        length = dist(self.a, self.b)
        default = f"{length:.2f}".rstrip("0").rstrip(".")
        text, ok = QInputDialog.getText(self.canvas, "Measurement", "Measurement text:", text=default)
        if not ok:
            self.reset()
            self.canvas.clear_snap()
            return
        node = self._new_node(text)
        node.name = self.doc.new_name("Measure")
        with self.doc.edit(structure=True):
            self.doc.add_node(node)
        self.doc.set_selection([node])
        self.reset()
        self.canvas.clear_snap()
        self.say("Measurement added. Select it to change colour, line style, font and size in the top bar.")

    # ----------------------------------------------------------------
    def paint(self, p: QPainter):
        c = self.canvas
        if self.stage == 0:
            return
        p.setBrush(Qt.NoBrush)
        if self._down is not None:
            pass
        elif self.stage == 1 and self.cur is not None:
            va, vb = c.to_view(self.a), c.to_view(self.cur)
            pen = QPen(ACCENT)
            pen.setStyle(Qt.DashLine)
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.drawRect(QRectF(QPointF(*va), QPointF(*vb)).normalized())
            # live preview of the straight measurement
            if dist(self.a, self.cur) > 1e-6:
                saved = (self.b, self.offset)
                self.b = self.cur
                self.offset = 0.0
                self._draw_preview(p)
                self.b, self.offset = saved
            self._dot(p, va)
        elif self.stage == 2:
            self._draw_preview(p)
            self._dot(p, c.to_view(self.a))
            self._dot(p, c.to_view(self.b))
        if self._down is not None and self.cur is not None:
            pen = QPen(ACCENT, 1.0, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(*c.to_view(self._down[1])), QPointF(*c.to_view(self.cur)))

    def _dot(self, p, v):
        p.setPen(QPen(PINK, 1.5))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(*v), 4, 4)

    def _draw_preview(self, p):
        node = self._new_node("")
        if dist(node.a, node.b) < 1e-9:
            return
        p.save()
        p.setTransform(self.canvas.view_transform())
        p.setRenderHint(QPainter.Antialiasing, True)
        draw_node(p, node)
        p.restore()
