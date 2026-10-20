"""Drawing tools: Pen (P), Pencil (N), Rectangle / Ellipse / Line (G) and Text (T)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .numfield import NumField
from .geometry import catmull_to_bezier, constrain_angle_projected, dist, rdp
from .model import Anchor, PathNode, SubPath, TextNode
from .tools_base import Tool

ACCENT = QColor(0, 140, 255)


def reverse_subpath(sp):
    sp.anchors.reverse()
    for a in sp.anchors:
        a.ix, a.iy, a.ox, a.oy = a.ox, a.oy, a.ix, a.iy


class PenTool(Tool):
    name = "pen"
    label = "Pen"
    shortcut = "P"
    hint = ("Click for corner points, click-drag for curves. Click the first point to close. Shift = 45° steps, "
            "Alt = break handle. Enter / double-click / Esc finishes. Click the end of a selected path to continue it.")

    def __init__(self, canvas):
        super().__init__(canvas)
        self.reset()

    def reset(self):
        self.node = None
        self.sp = None
        self.drag = False
        self.drag_anchor = None
        self.cursor_pt = None
        self.began = False

    def cursor(self):
        return QCursor(Qt.CrossCursor)

    def deactivate(self):
        self.finish()
        super().deactivate()

    # ----------------------------------------------------------------
    def _endpoint_hit(self, vp):
        for n in self.doc.selection:
            cand = [n] if n.kind == "path" else []
            for node in cand:
                for sp in node.subpaths:
                    if sp.closed or len(sp.anchors) < 1:
                        continue
                    for which, a in (("first", sp.anchors[0]), ("last", sp.anchors[-1])):
                        if dist(self.canvas.to_view(a.p), vp) <= 9:
                            return node, sp, which
        return None

    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        pt = ev.p
        last = self.sp.anchors[-1] if self.sp and self.sp.anchors else None
        # close the path?
        if self.sp is not None and len(self.sp.anchors) >= 2:
            if dist(self.canvas.to_view(self.sp.anchors[0].p), ev.vp) <= 9:
                self.sp.closed = True
                self.node.touch()
                self.finish()
                return
        if self.node is None:
            hit = self._endpoint_hit(ev.vp)
            if hit is not None:
                node, sp, which = hit
                self.doc.begin_edit()
                self.began = True
                if which == "first":
                    reverse_subpath(sp)
                self.node, self.sp = node, sp
                return
        if last is not None and ev.shift:
            pt = constrain_angle_projected(last.p, pt, 45.0)
            self.canvas.clear_snap()
        else:
            pt, _ = self.canvas.snap_point(pt, (self.node,) if self.node else ())
        if self.node is None:
            self.doc.begin_edit()
            self.began = True
            st = self.doc.default_style.copy()
            self.node = PathNode([SubPath([], False)], st, self.doc.new_name("Path"))
            self.sp = self.node.subpaths[0]
            self.doc.add_node(self.node)
        a = Anchor(*pt)
        self.sp.anchors.append(a)
        self.node.touch()
        self.drag = True
        self.drag_anchor = a
        self.drag_start_v = ev.vp

    def move(self, ev):
        pt = ev.p
        last = self.sp.anchors[-1] if self.sp and self.sp.anchors else None
        if self.drag and (ev.buttons & Qt.LeftButton) and self.drag_anchor is not None:
            a = self.drag_anchor
            if dist(ev.vp, self.drag_start_v) < 3 and not a.has_out():
                return
            if ev.shift:
                pt = constrain_angle_projected(a.p, pt, 45.0)
            a.ox, a.oy = pt
            if ev.alt:
                a.smooth = False
            else:
                a.ix, a.iy = 2 * a.x - pt[0], 2 * a.y - pt[1]
                a.smooth = True
            self.node.touch()
            self.cursor_pt = None
            return
        if last is not None and ev.shift:
            pt = constrain_angle_projected(last.p, pt, 45.0)
            self.canvas.clear_snap()
        else:
            pt, _ = self.canvas.snap_point(pt, (self.node,) if self.node else ())
        self.cursor_pt = pt

    def release(self, ev):
        self.drag = False
        self.drag_anchor = None

    def double_click(self, ev):
        last = self.sp.anchors[-1] if self.sp and self.sp.anchors else None
        if last is not None and dist(self.canvas.to_view(last.p), ev.vp) <= 6:
            self.finish()          # double-click on the last point ends the path
        else:
            self.press(ev)         # fast clicking elsewhere just adds another point

    def key_press(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
            self.finish()
            return True
        if e.key() in (Qt.Key_Backspace, Qt.Key_Delete) and self.sp and self.sp.anchors:
            self.sp.anchors.pop()
            self.node.touch()
            if not self.sp.anchors:
                self.cancel()
            return True
        return False

    def cancel(self):
        if self.node is not None:
            if self.node.parent is not None:
                try:
                    self.node.parent.children.remove(self.node)
                except ValueError:
                    pass
                self.node.parent = None
            self.doc.cancel_edit()
        self.reset()

    def finish(self):
        if self.node is None:
            self.reset()
            return
        node = self.node
        sp = self.sp
        if len(sp.anchors) < 2:
            # a single point is not a path
            if node.parent is not None:
                try:
                    node.parent.children.remove(node)
                except ValueError:
                    pass
                node.parent = None
            self.doc.cancel_edit()
            self.reset()
            self.canvas.update()
            return
        self.doc.end_edit(True, structure=True)
        self.doc.set_selection([node])
        self.reset()
        self.canvas.clear_snap()

    def paint(self, p: QPainter):
        if self.sp is None or not self.sp.anchors or self.cursor_pt is None:
            return
        c = self.canvas
        last = self.sp.anchors[-1]
        pen = QPen(ACCENT)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        v0 = c.to_view(last.p)
        v1 = c.to_view(self.cursor_pt)
        path.moveTo(*v0)
        if last.has_out():
            ho = c.to_view(last.hout)
            path.cubicTo(ho[0], ho[1], v1[0], v1[1], v1[0], v1[1])
        else:
            path.lineTo(*v1)
        p.drawPath(path)
        # anchors of the path being built
        p.setBrush(QColor(255, 255, 255))
        for a in self.sp.anchors:
            v = c.to_view(a.p)
            p.drawRect(QRectF(v[0] - 3, v[1] - 3, 6, 6))
            for has, pt in ((a.has_in(), a.hin), (a.has_out(), a.hout)):
                if has:
                    hv = c.to_view(pt)
                    p.drawLine(QPointF(*v), QPointF(*hv))
                    p.drawEllipse(QPointF(*hv), 3, 3)
        if len(self.sp.anchors) >= 2 and dist(c.to_view(self.sp.anchors[0].p), v1) <= 9:
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(*c.to_view(self.sp.anchors[0].p)), 8, 8)


# =============================================================================================
class PencilTool(Tool):
    name = "pencil"
    label = "Pencil (freehand)"
    shortcut = "N"
    hint = "Drag to draw a freehand line; it is smoothed into a Bezier curve when you release."

    def __init__(self, canvas):
        super().__init__(canvas)
        self.smooth = 1.0
        self.reset()

    def reset(self):
        self.pts = []
        self.active = False

    def cursor(self):
        return QCursor(Qt.CrossCursor)

    def options_widget(self, parent=None):
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(QLabel("Smoothing:"))
        sp = NumField()
        sp.setRange(0.2, 10.0)
        sp.setSingleStep(0.2)
        sp.setValue(self.smooth)
        sp.valueChanged.connect(lambda v: setattr(self, "smooth", v))
        lay.addWidget(sp)
        return w

    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        self.pts = [ev.p]
        self.active = True

    def move(self, ev):
        if self.active and (ev.buttons & Qt.LeftButton):
            if dist(self.canvas.to_view(self.pts[-1]), ev.vp) >= 2.0:
                self.pts.append(ev.p)

    def release(self, ev):
        if not self.active:
            return
        self.active = False
        pts = self.pts
        self.pts = []
        if len(pts) < 2:
            return
        z = self.canvas.zoom
        simp = rdp(pts, 1.5 * self.smooth / z)
        closed = False
        if len(simp) >= 4 and dist(self.canvas.to_view(simp[0]), self.canvas.to_view(simp[-1])) < 10:
            simp = simp[:-1]
            closed = True
        if len(simp) < 2:
            return
        anchors = []
        for p, ih, oh in catmull_to_bezier(simp, closed):
            anchors.append(Anchor(p[0], p[1], ih[0], ih[1], oh[0], oh[1], True))
        if not closed:
            anchors[0].smooth = False
            anchors[-1].smooth = False
        node = PathNode([SubPath(anchors, closed)], self.doc.default_style.copy(), self.doc.new_name("Path"))
        with self.doc.edit(structure=True):
            self.doc.add_node(node)
        self.doc.set_selection([node])

    def paint(self, p: QPainter):
        if len(self.pts) < 2:
            return
        pen = QPen(ACCENT)
        pen.setWidthF(1.5)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(*self.canvas.to_view(self.pts[0]))
        for q in self.pts[1:]:
            path.lineTo(*self.canvas.to_view(q))
        p.drawPath(path)


# =============================================================================================
class ShapeTool(Tool):
    """Rectangle, ellipse and line share one implementation."""

    def __init__(self, canvas, kind):
        super().__init__(canvas)
        self.kind = kind
        self.radius = 0.0
        self.name = {"rect": "rect", "ellipse": "ellipse", "line": "line"}[kind]
        self.label = {"rect": "Rectangle", "ellipse": "Ellipse", "line": "Line"}[kind]
        self.shortcut = {"rect": "G", "ellipse": "", "line": "L"}[kind]
        self.hint = {"rect": "Drag to draw. Shift = square, Alt = from centre. Shift+G cycles shape tools.",
                     "ellipse": "Drag to draw. Shift = circle, Alt = from centre.",
                     "line": "Drag to draw. Shift = 45° steps, Alt = from centre."}[kind]
        self.reset()

    def reset(self):
        self.node = None
        self.start = None
        self.readout = None
        self.began = False

    def cursor(self):
        return QCursor(Qt.CrossCursor)

    def options_widget(self, parent=None):
        if self.kind != "rect":
            return None
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(QLabel("Corner radius:"))
        sp = NumField()
        sp.setRange(0, 5000)
        sp.setValue(self.radius)
        sp.valueChanged.connect(lambda v: setattr(self, "radius", v))
        lay.addWidget(sp)
        return w

    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        pt, _ = self.canvas.snap_point(ev.p)
        self.start = pt
        self.start_v = ev.vp
        self.node = None
        self.began = True
        self.doc.begin_edit()

    def _geometry(self, a, b, ev):
        ax, ay = a
        bx, by = b
        if self.kind == "line":
            if ev.shift:
                bx, by = constrain_angle_projected(a, b, 45.0)
            if ev.alt:
                return [(2 * ax - bx, 2 * ay - by), (bx, by)]
            return [(ax, ay), (bx, by)]
        dx, dy = bx - ax, by - ay
        if ev.shift:
            m = max(abs(dx), abs(dy))
            dx = math.copysign(m, dx or 1.0)
            dy = math.copysign(m, dy or 1.0)
        if ev.alt:
            x0, y0, x1, y1 = ax - dx, ay - dy, ax + dx, ay + dy
        else:
            x0, y0, x1, y1 = ax, ay, ax + dx, ay + dy
        return (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    def move(self, ev):
        if self.start is None or not (ev.buttons & Qt.LeftButton):
            self.canvas.snap_point(ev.p)
            return
        if self.node is None and dist(ev.vp, self.start_v) < 3:
            return
        pt = ev.p
        if ev.shift and self.kind == "line":
            self.canvas.clear_snap()
        else:
            pt, _ = self.canvas.snap_point(pt, (self.node,) if self.node else ())
        g = self._geometry(self.start, pt, ev)
        if self.node is None:
            self.node = PathNode([], self.doc.default_style.copy(), self.doc.new_name(self.label))
            self.doc.add_node(self.node)
        if self.kind == "line":
            self.node.subpaths = PathNode.polyline(g).subpaths
            self.readout = f"L {dist(g[0], g[1]):.2f}   {math.degrees(math.atan2(g[1][1] - g[0][1], g[1][0] - g[0][0])):.1f}°"
        elif self.kind == "rect":
            x, y, w, h = g
            self.node.subpaths = PathNode.rect(x, y, w, h, self.radius).subpaths
            self.readout = f"W {w:.2f}   H {h:.2f}"
        else:
            x, y, w, h = g
            self.node.subpaths = PathNode.ellipse(x + w / 2, y + h / 2, w / 2, h / 2).subpaths
            self.readout = f"W {w:.2f}   H {h:.2f}"
        self.node.touch()
        self.say(self.readout)

    def release(self, ev):
        if self.start is None:
            return
        node = self.node
        self.start = None
        if node is None or not node.subpaths:
            self.doc.cancel_edit()
            self.reset()
            return
        self.doc.end_edit(True, structure=True)
        self.doc.set_selection([node])
        self.reset()
        self.canvas.clear_snap()
        self.say("")

    def key_press(self, e):
        if e.key() == Qt.Key_Escape and self.start is not None:
            if self.node is not None and self.node.parent is not None:
                self.node.parent.children.remove(self.node)
                self.node.parent = None
            self.doc.cancel_edit()
            self.reset()
            return True
        return False

    def paint(self, p: QPainter):
        if self.readout and self.node is not None:
            fm = p.fontMetrics()
            pos = self.canvas.to_view(self.start)
            r = QRectF(pos[0] + 12, pos[1] - 26, fm.horizontalAdvance(self.readout) + 10, fm.height() + 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 20, 220))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor(255, 255, 255))
            p.drawText(r, Qt.AlignCenter, self.readout)


# =============================================================================================
class TextTool(Tool):
    name = "text"
    label = "Text"
    shortcut = "T"
    hint = "Click to add text, click existing text to edit it. Font, size and colour live in the top bar."

    def cursor(self):
        return QCursor(Qt.IBeamCursor)

    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        node = self.canvas.hit_test(ev.p, level="item", accept=lambda n: n.kind == "text")
        if node is not None:
            self.doc.set_selection([node])
            self.canvas.edit_node_text(node)
            return
        text = self.canvas.ask_text("Add text", "Text:", "")
        if not text:
            return
        td = self.canvas.text_defaults
        st = self.doc.default_style
        fill = st.fill or st.stroke or (0, 0, 0, 255)
        node = TextNode(ev.x, ev.y, text, td["family"], td["size"], td["bold"], td["italic"], "start", 0.0,
                        None, self.doc.new_name("Text"))
        node.style.fill = fill
        with self.doc.edit(structure=True):
            self.doc.add_node(node)
        self.doc.set_selection([node])
