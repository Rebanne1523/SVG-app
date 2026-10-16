"""The drawing surface: view transform, painting, hit testing, snapping and event routing."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, QTransform)
from PySide6.QtWidgets import QInputDialog, QWidget

from .render import render_document
from .snap import EdgeIndex, SnapIndex

BG = QColor(58, 58, 60)
SEL_COLOR = QColor(0, 140, 255)
HOVER_COLOR = QColor(110, 190, 255)


class Ev:
    """A mouse/keyboard event translated into document coordinates."""
    __slots__ = ("p", "vp", "button", "buttons", "shift", "ctrl", "alt", "raw")

    def __init__(self, canvas, e, button=None):
        pos = e.position()
        self.vp = (pos.x(), pos.y())
        self.p = canvas.to_doc(self.vp)
        mods = e.modifiers()
        self.shift = bool(mods & Qt.ShiftModifier)
        self.ctrl = bool(mods & Qt.ControlModifier)
        self.alt = bool(mods & Qt.AltModifier)
        self.button = e.button() if button is None else button
        self.buttons = e.buttons()
        self.raw = e

    @property
    def x(self):
        return self.p[0]

    @property
    def y(self):
        return self.p[1]


class Canvas(QWidget):
    zoomChanged = Signal(float)
    cursorMoved = Signal(float, float)
    message = Signal(str)
    toolChanged = Signal(str)
    viewChanged = Signal()

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAcceptDrops(False)
        self.zoom = 1.0
        self.origin = QPointF(40, 40)
        self.tools = {}
        self.tool = None
        self.doc = None
        self.snap_enabled = True
        self.snap_px = 8.0
        self.scale_strokes = False
        self.select_level = "item"  # or "folder"
        self.hover = None
        self.snap_marker = None  # (point, label)
        self.guides = []  # [("x", value) | ("y", value)]
        self.text_defaults = {"family": "DejaVu Sans", "size": 24.0, "bold": False, "italic": False}
        self._doc_rev = 0
        self._snap_cache = None
        self._edge_cache = None
        self._space = False
        self._pan = None
        self._tmp_tool = None
        self._fitted = False
        self.set_document(doc)

    # ------------------------------------------------------------ document
    def set_document(self, doc):
        if self.doc is not None:
            for sig, slot in ((self.doc.contentChanged, self._on_content), (self.doc.selectionChanged, self.update),
                              (self.doc.restored, self._on_restored)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self.doc = doc
        doc.contentChanged.connect(self._on_content)
        doc.selectionChanged.connect(self.update)
        doc.restored.connect(self._on_restored)
        self._doc_rev += 1
        self.hover = None
        if self.tool:
            self.tool.reset()
        self._fitted = False
        self.update()

    def _on_content(self):
        self._doc_rev += 1
        self.update()

    def _on_restored(self):
        self._doc_rev += 1
        self.hover = None
        if self.tool:
            self.tool.reset()

    # ------------------------------------------------------------ tools
    def register_tool(self, tool):
        self.tools[tool.name] = tool

    def set_tool(self, name):
        if name not in self.tools:
            return
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = self.tools[name]
        self.tool.activate()
        self.guides = []
        self.snap_marker = None
        self.update_cursor()
        self.toolChanged.emit(name)
        self.update()

    def update_cursor(self):
        if self._space or self._pan is not None:
            self.setCursor(Qt.ClosedHandCursor if self._pan is not None else Qt.OpenHandCursor)
        elif self.tool is not None:
            self.setCursor(self.tool.cursor())

    # ------------------------------------------------------------ view
    def to_view(self, p):
        return (p[0] * self.zoom + self.origin.x(), p[1] * self.zoom + self.origin.y())

    def to_doc(self, vp):
        return ((vp[0] - self.origin.x()) / self.zoom, (vp[1] - self.origin.y()) / self.zoom)

    def view_transform(self):
        return QTransform(self.zoom, 0, 0, self.zoom, self.origin.x(), self.origin.y())

    def view_rect_doc(self):
        a = self.to_doc((0, 0))
        b = self.to_doc((self.width(), self.height()))
        return QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1])

    def fit_view(self):
        W, H = max(1.0, self.doc.width), max(1.0, self.doc.height)
        m = 40
        z = min((self.width() - 2 * m) / W, (self.height() - 2 * m) / H)
        self.zoom = max(0.02, min(64.0, z if z > 0 else 1.0))
        self.origin = QPointF((self.width() - W * self.zoom) / 2, (self.height() - H * self.zoom) / 2)
        self._view_changed()

    def fit_selection(self):
        if not self.doc.selection:
            return self.fit_view()
        r = self.doc.bounds_of(self.doc.selection)
        if r.width() < 1e-6 and r.height() < 1e-6:
            return
        m = 60
        z = min((self.width() - 2 * m) / max(r.width(), 1e-6), (self.height() - 2 * m) / max(r.height(), 1e-6))
        self.zoom = max(0.02, min(64.0, z))
        c = r.center()
        self.origin = QPointF(self.width() / 2 - c.x() * self.zoom, self.height() / 2 - c.y() * self.zoom)
        self._view_changed()

    def set_zoom(self, z, vp=None):
        z = max(0.02, min(64.0, z))
        if vp is None:
            vp = (self.width() / 2, self.height() / 2)
        d = self.to_doc(vp)
        self.zoom = z
        self.origin = QPointF(vp[0] - d[0] * z, vp[1] - d[1] * z)
        self._view_changed()

    def zoom_by(self, f, vp=None):
        self.set_zoom(self.zoom * f, vp)

    def pan_by(self, dx, dy):
        self.origin = QPointF(self.origin.x() + dx, self.origin.y() + dy)
        self._view_changed()

    def _view_changed(self):
        self.zoomChanged.emit(self.zoom)
        self.viewChanged.emit()
        self.update()

    def resizeEvent(self, e):
        if not self._fitted and self.width() > 100:
            self._fitted = True
            self.fit_view()
        super().resizeEvent(e)

    # ------------------------------------------------------------ painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        vt = self.view_transform()
        W, H = self.doc.width, self.doc.height
        # page shadow + page
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        tl = self.to_view((0, 0))
        p.drawRect(QRectF(tl[0] + 4, tl[1] + 4, W * self.zoom, H * self.zoom))
        p.setBrush(QColor(255, 255, 255))
        p.drawRect(QRectF(tl[0], tl[1], W * self.zoom, H * self.zoom))
        p.save()
        p.setTransform(vt)
        p.setClipRect(self.view_rect_doc().adjusted(-2, -2, 2, 2))
        render_document(p, self.doc, cull=self.view_rect_doc())
        p.restore()
        p.setRenderHint(QPainter.Antialiasing, True)
        self._paint_selection(p, vt)
        self._paint_guides(p)
        if self.tool is not None:
            self.tool.paint(p)
        self._paint_marker(p)
        p.end()

    def _paint_selection(self, p, vt):
        sel = self.doc.selection
        pen = QPen(SEL_COLOR)
        pen.setWidthF(1.0)
        p.setBrush(Qt.NoBrush)
        if self.hover is not None and self.hover not in sel and self.hover.visible:
            hp = QPen(HOVER_COLOR)
            hp.setWidthF(1.2)
            p.setPen(hp)
            p.drawPath(vt.map(self._outline(self.hover)))
        p.setPen(pen)
        if len(sel) <= 300:
            for n in sel:
                if n.visible:
                    p.drawPath(vt.map(self._outline(n)))

    def _outline(self, node):
        if node.is_group():
            path = QPainterPath()
            path.addRect(node.bounds())
            return path
        if node.kind == "path" or node.kind == "text":
            return node.qpath()
        path = QPainterPath()
        path.addRect(node.bounds())
        return path

    def _paint_guides(self, p):
        if not self.guides:
            return
        pen = QPen(QColor(255, 60, 200))
        pen.setWidthF(1.0)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        for axis, v in self.guides:
            if axis == "x":
                x = self.to_view((v, 0))[0]
                p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            else:
                y = self.to_view((0, v))[1]
                p.drawLine(QPointF(0, y), QPointF(self.width(), y))

    def _paint_marker(self, p):
        if self.snap_marker is None:
            return
        pt, label = self.snap_marker
        vx, vy = self.to_view(pt)
        pen = QPen(QColor(255, 60, 200))
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(vx, vy), 6, 6)
        if label:
            f = QFont(self.font())
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255))
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(label) + 10
            r = QRectF(vx + 10, vy + 8, w, fm.height() + 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 60, 200, 230))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor(255, 255, 255))
            p.drawText(r, Qt.AlignCenter, label)

    # ------------------------------------------------------------ hit testing
    def hit_test(self, p, tol_px=4.0, level=None, accept=None):
        tol = tol_px / self.zoom
        rect = QRectF(p[0] - tol, p[1] - tol, 2 * tol, 2 * tol)
        pt = QPointF(*p)

        def rec(node):
            if not node.visible or node.locked:
                return None
            if node.clip:
                cp = node.clip_path()
                if cp is not None and not cp.contains(pt):
                    return None
            if node.is_group():
                for c in reversed(node.children):
                    r = rec(c)
                    if r is not None:
                        return r
                return None
            st = getattr(node, "style", None)
            pad = tol + (st.width if st is not None else 0.0) + 2.0
            if not node.bounds().adjusted(-pad, -pad, pad, pad).contains(pt):
                return None
            if accept is not None and not accept(node):
                return None
            return node if node.shape_path().intersects(rect) else None

        hit = None
        for c in reversed(self.doc.root.children):
            hit = rec(c)
            if hit is not None:
                break
        if hit is None:
            return None
        level = level or self.select_level
        if level == "folder":
            n = hit
            while n.parent is not None and n.parent.parent is not None and n.parent.parent.parent is not None:
                n = n.parent
            # n is now a direct child of a top level layer (or of root)
            return n
        return hit

    def nodes_in_rect(self, rect: QRectF, level=None):
        out = []

        def rec(node):
            if not node.visible or node.locked:
                return
            if node.is_group():
                for c in node.children:
                    rec(c)
                return
            if rect.intersects(node.bounds()) and node.shape_path().intersects(rect):
                out.append(node)

        for c in self.doc.root.children:
            rec(c)
        level = level or self.select_level
        if level == "folder":
            res = []
            for n in out:
                while n.parent is not None and n.parent.parent is not None and n.parent.parent.parent is not None:
                    n = n.parent
                if n not in res:
                    res.append(n)
            return res
        return out

    # ------------------------------------------------------------ snapping
    def _index(self, exclude):
        key = (self._doc_rev, tuple(sorted(id(n) for n in exclude)), round(self.zoom, 4),
               round(self.origin.x()), round(self.origin.y()))
        if self._snap_cache is None or self._snap_cache[0] != key:
            self._snap_cache = (key, SnapIndex(self.doc, exclude, self.view_rect_doc()))
        return self._snap_cache[1]

    def _edges(self, exclude):
        key = (self._doc_rev, tuple(sorted(id(n) for n in exclude)), round(self.zoom, 4),
               round(self.origin.x()), round(self.origin.y()))
        if self._edge_cache is None or self._edge_cache[0] != key:
            self._edge_cache = (key, EdgeIndex(self.doc, exclude, self.view_rect_doc()))
        return self._edge_cache[1]

    def clear_snap(self):
        self.guides = []
        self.snap_marker = None

    def snap_point(self, p, exclude=(), edges=False, axes=True, force=False):
        """Snap a document point. Returns (point, label|None). Updates guides/marker."""
        self.guides = []
        self.snap_marker = None
        if not (self.snap_enabled or force):
            return p, None
        thr = self.snap_px / self.zoom
        idx = self._index(exclude)
        hit = idx.nearest_point(p, thr)
        if hit is not None:
            pt, label = hit
            self.snap_marker = (pt, label)
            self.guides = []
            return pt, label
        if edges:
            q = self._edges(exclude).nearest(p, thr)
            if q is not None:
                self.snap_marker = (q, "Edge")
                return q, "Edge"
        if not axes:
            return p, None
        x, y = p
        lab = None
        gx = idx.nearest_x(x, thr)
        gy = idx.nearest_y(y, thr)
        if gx is not None:
            x = gx[0]
            self.guides.append(("x", x))
            lab = gx[1]
        if gy is not None:
            y = gy[0]
            self.guides.append(("y", y))
            lab = lab or gy[1]
        return (x, y), lab

    def snap_move(self, key_points, delta, exclude=(), allow_x=True, allow_y=True, xs=(), ys=()):
        """Snap a translation. ``key_points`` are doc points of the moving object that may snap
        exactly to anchors; ``xs``/``ys`` are x / y coordinates that may align to guide lines."""
        self.guides = []
        self.snap_marker = None
        if not self.snap_enabled:
            return delta
        thr = self.snap_px / self.zoom
        idx = self._index(exclude)
        dx, dy = delta
        best = None
        for kp in key_points:
            q = (kp[0] + dx, kp[1] + dy)
            hit = idx.nearest_point(q, thr)
            if hit is not None:
                d = math.hypot(hit[0][0] - q[0], hit[0][1] - q[1])
                if best is None or d < best[0]:
                    best = (d, hit)
        if best is not None and allow_x and allow_y:
            pt, label = best[1]
            # find which key point produced it
            for kp in key_points:
                q = (kp[0] + dx, kp[1] + dy)
                if math.hypot(pt[0] - q[0], pt[1] - q[1]) <= thr + 1e-9:
                    dx, dy = pt[0] - kp[0], pt[1] - kp[1]
                    self.snap_marker = (pt, label)
                    return (dx, dy)
        sx = None
        if allow_x:
            for x in xs:
                g = idx.nearest_x(x + dx, thr)
                if g is not None and (sx is None or abs(g[0] - (x + dx)) < abs(sx[0] - sx[1])):
                    sx = (g[0], x + dx)
        sy = None
        if allow_y:
            for y in ys:
                g = idx.nearest_y(y + dy, thr)
                if g is not None and (sy is None or abs(g[0] - (y + dy)) < abs(sy[0] - sy[1])):
                    sy = (g[0], y + dy)
        if sx is not None:
            dx += sx[0] - sx[1]
            self.guides.append(("x", sx[0]))
        if sy is not None:
            dy += sy[0] - sy[1]
            self.guides.append(("y", sy[0]))
        return (dx, dy)

    # ------------------------------------------------------------ text dialog
    def ask_text(self, title, label, initial="", multiline=True):
        if multiline:
            text, ok = QInputDialog.getMultiLineText(self, title, label, initial)
        else:
            text, ok = QInputDialog.getText(self, title, label, text=initial)
        return text if ok else None

    def edit_node_text(self, node):
        if node.kind == "measure":
            t = self.ask_text("Measurement", "Measurement text:", node.text, multiline=False)
        else:
            t = self.ask_text("Edit text", "Text:", node.text)
        if t is None or t == node.text:
            return
        with self.doc.edit():
            node.text = t
            node.touch()

    # ------------------------------------------------------------ events
    def _active_tool(self):
        return self._tmp_tool or self.tool

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MiddleButton or (self._space and e.button() == Qt.LeftButton):
            self._pan = (e.position().x(), e.position().y())
            self.update_cursor()
            return
        if self.tool is None:
            return
        self.tool.press(Ev(self, e))
        self.update()

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            x, y = e.position().x(), e.position().y()
            self.pan_by(x - self._pan[0], y - self._pan[1])
            self._pan = (x, y)
            return
        ev = Ev(self, e, Qt.NoButton)
        self.cursorMoved.emit(ev.p[0], ev.p[1])
        if self.tool is not None:
            self.tool.move(ev)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self.update_cursor()
            return
        if self.tool is not None:
            self.tool.release(Ev(self, e))
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.tool is not None and e.button() == Qt.LeftButton:
            self.tool.double_click(Ev(self, e))
            self.update()

    def wheelEvent(self, e):
        mods = e.modifiers()
        dy = e.angleDelta().y()
        dx = e.angleDelta().x()
        ev = Ev(self, e, Qt.NoButton)
        if self.tool is not None and not (mods & (Qt.AltModifier | Qt.ControlModifier)):
            if self.tool.wheel(ev, dy):
                self.update()
                e.accept()
                return
        if mods & (Qt.AltModifier | Qt.ControlModifier):
            self.zoom_by(1.15 ** (dy / 120.0), ev.vp)
        elif mods & Qt.ShiftModifier:
            self.pan_by(dy / 2.0 or dx / 2.0, 0)
        else:
            self.pan_by(dx / 2.0, dy / 2.0)
        e.accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self.update_cursor()
            return
        if self.tool is not None and self.tool.key_press(e):
            self.update()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self.update_cursor()
            return
        if self.tool is not None and self.tool.key_release(e):
            self.update()
            return
        super().keyReleaseEvent(e)

    def leaveEvent(self, e):
        self.clear_snap()
        self.hover = None
        self.update()
