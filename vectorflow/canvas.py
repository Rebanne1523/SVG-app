"""The drawing surface: view transform, painting, hit testing, snapping and event routing."""
from __future__ import annotations

import math
import os
from time import perf_counter

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, QTransform)
from PySide6.QtWidgets import QInputDialog, QWidget

from . import model, scenecache
from .hitindex import HitIndex
from .model import Sheet, a_to_t, arrow_length, walk
from .render import draw_node, render_document, view_path
from .scenecache import SceneCache
from .snap import EdgeIndex, SnapIndex

LIVE_LAYER_MIN = 300     # dragging more vectors than this moves a bitmap of them instead of redrawing each

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


def _choose_backend():
    """"software" (QPainter on the CPU, the default) or "opengl" (QOpenGLWidget, experimental). Picked in
    View > Renderer (needs a restart) or with VF_RENDERER=software|opengl. If the last OpenGL start never got
    to draw a frame (no usable driver), fall back to software and say so."""
    st = QSettings("VectorFlow", "VectorFlow")
    want = os.environ.get("VF_RENDERER") or str(st.value("render/backend", "software"))
    if want != "opengl":
        return "software", None
    if str(st.value("render/pending", "false")).lower() == "true":
        st.setValue("render/pending", False)
        st.setValue("render/backend", "software")
        return "software", "OpenGL did not start last time, so VectorFlow went back to the software renderer."
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: F401
    except ImportError:
        return "software", "OpenGL widgets are not available in this build; using the software renderer."
    st.setValue("render/pending", True)
    st.sync()
    return "opengl", None


BACKEND, BACKEND_NOTE = _choose_backend()
if BACKEND == "opengl":
    from PySide6.QtOpenGLWidgets import QOpenGLWidget as _Base
else:
    _Base = QWidget


class Canvas(_Base):
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
        self.scene = SceneCache(self)         # picture of everything that is not being dragged
        self.live_scene = SceneCache(self)    # picture of the vectors being dragged (large drags only)
        self.live = None
        self._linger = None
        self._live_token = 0
        self._paint_rev = 0
        self._last_key = None
        self._idx_gen = None
        self._idx_timer = QTimer(self)
        self._idx_timer.setSingleShot(True)
        self._idx_timer.timeout.connect(self._prebuild_indexes)
        self._snap_cache = None
        self._edge_cache = None
        self._hit_cache = None
        self._space = False
        self._pan = None
        self._tmp_tool = None
        self.last_mouse = None  # last cursor position in document coordinates
        self._fitted = False
        self.set_document(doc)

    # ------------------------------------------------------------ document
    def set_document(self, doc):
        if self.doc is not None:
            for sig, slot in ((self.doc.contentChanged, self._on_content), (self.doc.selectionChanged, self.update),
                              (self.doc.insideChanged, self.update), (self.doc.restored, self._on_restored)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self.end_live(patch=False)
        self._linger = None
        self.scene.invalidate()
        self.scene.reset_stats()
        self.live_scene.invalidate()
        self.doc = doc
        doc.contentChanged.connect(self._on_content)
        doc.warmed.connect(lambda: self._idx_timer.start(250))
        doc.selectionChanged.connect(self.update)
        doc.insideChanged.connect(self.update)
        doc.restored.connect(self._on_restored)
        self._doc_rev += 1
        self.hover = None
        if self.tool:
            self.tool.reset()
        self._fitted = False
        doc.schedule_warmup(200)
        self.update()

    def _on_content(self):
        self._doc_rev += 1
        if self.live is not None and self.live.get("auto"):
            self.end_live()
        self.doc.schedule_warmup(700)
        self._idx_gen = None              # an index being built now would already be out of date
        self.update()

    def _on_restored(self):
        self._doc_rev += 1
        self.end_live(patch=False)
        self._linger = None
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
        if self.live is not None:
            self.end_live()
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

    def fit_rect(self, r, margin=40):
        if r.isNull() or r.width() < 1e-6 or r.height() < 1e-6:
            r = QRectF(0, 0, 1920, 1080)
        z = min((self.width() - 2 * margin) / r.width(), (self.height() - 2 * margin) / r.height())
        self.zoom = max(0.02, min(64.0, z if z > 0 else 1.0))
        c = r.center()
        self.origin = QPointF(self.width() / 2 - c.x() * self.zoom, self.height() / 2 - c.y() * self.zoom)
        self._view_changed()

    def fit_view(self):
        """Show every sheet."""
        self.fit_rect(self.doc.sheets_rect())

    def fit_sheet(self, sheet=None):
        sheet = sheet or self.doc.current_sheet()
        if sheet is not None:
            self.fit_rect(sheet.rect())

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
    if BACKEND == "opengl":
        def paintGL(self):
            self._paint_all()
            if not self._gl_ok:
                self._gl_ok = True              # a frame was drawn: the driver works
                QSettings("VectorFlow", "VectorFlow").setValue("render/pending", False)
    else:
        def paintEvent(self, e):
            self._paint_all()

    _gl_ok = False

    def _paint_all(self):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        vt = self.view_transform()
        cur = self.doc.current_sheet()
        for sh in self.doc.sheets():
            tl = self.to_view((sh.x, sh.y))
            w, h = sh.width * self.zoom, sh.height * self.zoom
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawRect(QRectF(tl[0] + 4, tl[1] + 4, w, h))
            p.setBrush(QColor(255, 255, 255))
            p.drawRect(QRectF(tl[0], tl[1], w, h))
        self._paint_scene(p, vt)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._paint_sheet_frames(p, cur)
        self._paint_selection(p, vt)
        self._paint_inside(p, vt)
        self._paint_guides(p)
        if self.tool is not None:
            self.tool.paint(p)
        self._paint_marker(p)
        p.end()

    def _paint_inside(self, p, vt):
        """Highlight the sub-path picked in the Layers panel while looking inside a compound path."""
        f = self.doc.inside_focus
        if f is None or not f.anchors or not any(f in n.subpaths for n in self.doc.selection if n.kind == "path"):
            return
        path = QPainterPath()
        path.moveTo(*f.anchors[0].p)
        for _, a, b in f.segments():
            if a.has_out() or b.has_in():
                path.cubicTo(*a.hout, *b.hin, *b.p)
            else:
                path.lineTo(*b.p)
        if f.closed:
            path.closeSubpath()
        p.save()
        p.setTransform(vt)
        pen = QPen(QColor(255, 140, 0), 2.5 / self.zoom)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QColor(255, 140, 0, 40))
        p.drawPath(path)
        p.restore()

    def _live_key(self):
        lv = self.live
        return (self._doc_rev, model.EPOCH, lv["token"] if lv is not None else 0)

    def _auto_live(self, touched, boxes, over):
        """A tool is editing a few vectors without telling us (node editing, pen preview ...): on a
        heavy drawing, take them out of the cached picture and draw them live on top of it."""
        if over or self.scene.render_ms < 8.0 or not touched or self._doc_rev != self._paint_rev:
            return
        lv = self.live
        if lv is not None:
            if not lv.get("auto"):
                return
            fresh = [n for n in touched if n.id not in lv["ids"]]
            if not fresh:
                return
            nodes = lv["nodes"] + fresh
        else:
            if self.scene.pix is None:
                return
            nodes = list(touched)
        count = 0
        for n in nodes:
            count += sum(1 for m in walk(n, True) if not m.is_group())
            if count > LIVE_LAYER_MIN:
                return
        # the cached picture is still right except for the touched vectors: their old boxes tell us where
        # to patch (vectors that did not exist before, e.g. a path being drawn, have none)
        old_key = None
        lk = self._last_key
        if lv is None and lk is not None and lk[0] == self._doc_rev and lk[2] == 0 and self.scene.fresh_for(lk):
            old_key = lk            # the picture matched the document at the last paint: only `touched` changed
        self.begin_live(nodes, old_key=old_key, extra_boxes=boxes)
        self.live["auto"] = True

    def _paint_direct(self, p, vt):
        p.save()
        p.setTransform(vt)
        p.setClipRect(self.view_rect_doc().adjusted(-2, -2, 2, 2))
        render_document(p, self.doc, cull=self.view_rect_doc())
        p.restore()

    def _paint_scene(self, p, vt):
        if not scenecache.ENABLED:
            self._paint_direct(p, vt)
            return
        touched, boxes, over = model.take_touched()
        if touched or over:
            self._auto_live(touched, boxes, over)
        self._paint_rev = self._doc_rev
        live = self.live
        key = self._live_key()
        p.setRenderHint(QPainter.Antialiasing, True)
        self.scene.paint(p, key, skip=live["set"] if live is not None else None)
        self._last_key = key if self.scene.shows(key) else None
        lv = live or self._linger
        if lv is None:
            return
        if live is None and self.scene.shows(key):
            self._drop_linger()
            return
        if lv["layer"]:
            m = lv["matrix"]
            vm = None
            if m is not None:
                inv, ok = vt.inverted()
                vm = inv * a_to_t(m) * vt if ok else None
            self.live_scene.paint(p, ("live", lv["token"]), only=lv["set"], matrix=vm)
            return
        p.save()
        p.setTransform(vt)
        p.setClipRect(self.view_rect_doc().adjusted(-2, -2, 2, 2))
        vr = self.view_rect_doc().adjusted(-2, -2, 2, 2)
        for n, op in lv["leaves"]:
            # while a heavy outline is being dragged, anti-aliasing is what costs (8x here); it comes back on release
            heavy = live is not None and n.kind == "path" and view_path(n, vr).elementCount() > 600
            if heavy:
                p.setRenderHint(QPainter.Antialiasing, False)
            draw_node(p, n, op, cull=vr)
            if heavy:
                p.setRenderHint(QPainter.Antialiasing, True)
        p.restore()

    def _drop_linger(self):
        self._linger = None
        self.live_scene.invalidate()
        self.update()

    # ------------------------------------------------------------ live drags
    def _region_of(self, leaves):
        """Document rectangle that contains ``leaves`` (strokes, arrow heads and anti-aliasing included)."""
        r = QRectF()
        for n in leaves:
            b = n.bounds()
            pad = 2.0
            st = getattr(n, "style", None)
            if st is not None:
                pad += st.width * 2 + arrow_length(st)
            if n.kind == "measure":
                pad += 20.0
            r = r.united(b.adjusted(-pad, -pad, pad, pad))
        e = 3.0 / self.zoom
        return r.adjusted(-e, -e, e, e)

    @staticmethod
    def _shown(n):
        """Is this vector drawn at all (itself and every folder above it visible)?"""
        while n is not None:
            if not n.visible:
                return False
            n = n.parent
        return True

    def begin_live(self, nodes, old_key=None, extra_boxes=()):
        """Called by a tool when it starts moving / scaling / rotating ``nodes``. Returns True when
        the nodes will NOT be modified until :meth:`end_live` (the tool then only reports the
        matrix with :meth:`set_live_matrix` and applies it at the end) and False when it must
        transform them every frame."""
        self.end_live()
        if self._linger is not None:
            self._drop_linger()
        leaves = []
        ids = set()
        for n in nodes:
            for m in walk(n, True):
                ids.add(m.id)
                if not m.is_group():
                    leaves.append(m)
        lset = set(leaves)
        self._live_token += 1
        layer = len(leaves) > LIVE_LAYER_MIN
        order = []
        if not layer:
            for n in walk(self.doc.root):
                if n in lset:
                    op = 1.0
                    for a in n.ancestors():
                        op *= a.opacity
                    order.append((n, op * n.opacity))
        if old_key is None:
            old_key = self._live_key()
        self.live = {"set": lset, "leaves": order, "layer": layer, "matrix": None, "token": self._live_token,
                     "nodes": list(nodes), "ids": ids, "leaf_list": leaves}
        model.set_live_ids(ids)
        self.live["epoch"] = model.EPOCH
        new_key = self._live_key()
        self.live["scene_key"] = new_key
        if self.width() > 0 and self.isVisible():
            fresh = self.scene.fresh_for(old_key)
            # On a heavy drawing never stall the start of a drag: whatever can't be prepared in a few
            # milliseconds is rendered in slices while the drag already runs.
            heavy = self.scene.render_ms > 120.0
            if layer:
                everything = fresh and all(n in lset or not self._shown(n) for n in walk(self.doc.root)
                                           if not n.is_group())
                if everything:
                    self.live_scene.adopt(self.scene, ("live", self._live_token))   # the live layer IS the picture
                elif not heavy:
                    self.live_scene.prime(("live", self._live_token), only=lset)
            region = self._region_of(leaves)
            if extra_boxes:
                pad = 2.0 + 3.0 / self.zoom + 2.0 * max((getattr(n, "style", None).width for n in leaves
                                                         if getattr(n, "style", None) is not None), default=0.0)
                for l, t, r, b in extra_boxes:
                    region = region.united(QRectF(l - pad, t - pad, r - l + 2 * pad, b - t + 2 * pad))
            vis = self.view_rect_doc()
            covers = region.intersected(vis).width() * region.intersected(vis).height() > 0.5 * vis.width() * vis.height()
            if fresh and not (heavy and covers) and self.scene.punch(region, new_key, skip=lset):
                pass
            elif not heavy:
                self.scene.prime(new_key, skip=lset)
        self.update()
        return layer

    def set_live_matrix(self, m):
        """Document-space affine matrix currently applied to the dragged vectors (layer mode)."""
        if self.live is not None:
            self.live["matrix"] = m
            self.update()

    def end_live(self, patch=True):
        """The drag is over (its result is already in the nodes). The cached picture is patched
        where the vectors landed; if that is not possible and the scene is heavy, keep drawing the
        dragged vectors on top of the old picture until the new one is ready."""
        lv, self.live = self.live, None
        if lv is None:
            return
        same = model.EPOCH == lv["epoch"]
        model.set_live_ids(None)
        key = self._live_key()
        # a few vectors: repaint just the patch they cover. A huge selection would cost as much as a
        # full render, so there the dragged bitmap stays on screen while the exact picture is redrawn.
        if patch and same and not lv["layer"] and self.isVisible() and self.scene.fresh_for(lv["scene_key"]) and \
                self.scene.punch(self._region_of(lv["leaf_list"]), key):
            self.live_scene.invalidate()
        elif patch and self.scene.render_ms >= 8.0 and self.isVisible():
            self._linger = lv
        else:
            self.live_scene.invalidate()
        self.update()

    def sheet_label_rect(self, sh, fm=None):
        """Clickable name tag above the top-left corner of a sheet (view coordinates)."""
        from PySide6.QtGui import QFontMetricsF
        fm = fm or QFontMetricsF(self.font())
        v = self.to_view((sh.x, sh.y))
        return QRectF(v[0], v[1] - 22, min(fm.horizontalAdvance(sh.name) + 14, max(60.0, sh.width * self.zoom)), 20)

    def hit_sheet_label(self, vp):
        pt = QPointF(*vp)
        for sh in reversed(self.doc.sheets()):
            if self.sheet_label_rect(sh).contains(pt):
                return sh
        return None

    def _paint_sheet_frames(self, p, cur):
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(self.font())
        p.setBrush(Qt.NoBrush)
        for sh in self.doc.sheets():
            tl = self.to_view((sh.x, sh.y))
            r = QRectF(tl[0], tl[1], sh.width * self.zoom, sh.height * self.zoom)
            is_cur = sh is cur
            pen = QPen(SEL_COLOR if is_cur else QColor(120, 120, 124))
            pen.setWidthF(1.5 if is_cur else 1.0)
            p.setPen(pen)
            p.drawRect(r)
            lab = self.sheet_label_rect(sh, fm)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(40, 110, 190) if is_cur else QColor(80, 80, 84))
            p.drawRoundedRect(lab, 3, 3)
            p.setPen(QColor(255, 255, 255))
            p.drawText(lab.adjusted(7, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(sh.name, Qt.ElideRight, lab.width() - 10))
            p.setBrush(Qt.NoBrush)

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
    def _prebuild_indexes(self):
        """While the user is idle, build the picking / snapping indexes (in slices of a few ms) so the
        next click or drag on a big drawing finds them ready."""
        self._idx_gen = None
        if self.live is not None or self.doc is None or not self.isVisible():
            return
        self._idx_gen = self._index_job()
        self._idx_step()

    def _index_job(self):
        key = (self._doc_rev, model.EPOCH)
        if self._hit_cache is None or self._hit_cache[0] != key:
            h = HitIndex.__new__(HitIndex)
            for _ in h.steps(self.doc):
                yield
            if key == (self._doc_rev, model.EPOCH):
                self._hit_cache = (key, h)
        if self._snap_cache is None or self._snap_cache[0] != key:
            sx = SnapIndex.__new__(SnapIndex)
            for _ in sx.steps(self.doc):
                yield
            if key == (self._doc_rev, model.EPOCH):
                self._snap_cache = (key, sx)

    def _idx_step(self):
        gen = self._idx_gen
        if gen is None:
            return
        t0 = perf_counter()
        try:
            while perf_counter() - t0 < 0.006:
                next(gen)
        except StopIteration:
            self._idx_gen = None
            return
        except Exception:
            self._idx_gen = None          # the drawing changed under us: the next request rebuilds it
            return
        QTimer.singleShot(6, self._idx_step)

    def hit_index(self):
        key = (self._doc_rev, model.EPOCH)
        if self._hit_cache is None or self._hit_cache[0] != key:
            self._hit_cache = (key, HitIndex(self.doc))
        return self._hit_cache[1]

    def hit_test(self, p, tol_px=4.0, level=None, accept=None):
        hit = self.hit_index().hit(p, tol_px / self.zoom, accept)
        if hit is None:
            return None
        level = level or self.select_level
        if level == "folder":
            return self._folder_level(hit)
        return hit

    def _folder_level(self, n):
        """The item directly below its layer (a whole folder when the vector sits inside one)."""
        while n.parent is not None and not self.doc.is_layer(n) and not self.doc.is_layer(n.parent):
            if isinstance(n.parent, Sheet) or n.parent is self.doc.root:
                break
            n = n.parent
        return n

    def nodes_in_rect(self, rect: QRectF, level=None):
        out = self.hit_index().in_rect(rect)
        level = level or self.select_level
        if level == "folder":
            res, seen = [], set()
            for n in out:
                n = self._folder_level(n)
                if id(n) not in seen:
                    seen.add(id(n))
                    res.append(n)
            return res
        return out

    # ------------------------------------------------------------ snapping
    def _index(self, exclude):
        key = (self._doc_rev, model.EPOCH)
        if self._snap_cache is None or self._snap_cache[0] != key:
            self._snap_cache = (key, SnapIndex(self.doc))
        return self._snap_cache[1].view(exclude)

    def _edges(self, exclude):
        key = (self._doc_rev, model.EPOCH)
        if self._edge_cache is None or self._edge_cache[0] != key:
            self._edge_cache = (key, EdgeIndex(self.doc))
        idx = self._edge_cache[1]
        idx.set_exclude(exclude)
        return idx

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
            self._pan_moved = 0.0
            self.update_cursor()
            return
        if self.tool is None:
            return
        ev = Ev(self, e)
        if e.button() == Qt.LeftButton:
            under = self.doc.sheet_at(ev.p)
            if under is not None and under is not self.doc.current_sheet():
                self.doc.set_current_sheet(under)       # work happens on the sheet that is clicked, with any tool
        self.tool.press(ev)
        self.update()

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            x, y = e.position().x(), e.position().y()
            self._pan_moved = getattr(self, "_pan_moved", 0.0) + abs(x - self._pan[0]) + abs(y - self._pan[1])
            self.pan_by(x - self._pan[0], y - self._pan[1])
            self._pan = (x, y)
            return
        ev = Ev(self, e, Qt.NoButton)
        self.last_mouse = ev.p
        self.cursorMoved.emit(ev.p[0], ev.p[1])
        if self.tool is not None:
            self.tool.move(ev)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self.update_cursor()
            if e.button() == Qt.MiddleButton and getattr(self, "_pan_moved", 0.0) < 4 and self.tool is not None:
                self.tool.middle_click(Ev(self, e))     # a click of the wheel (no drag): tools may use it
                self.update()
            return
        if self.tool is not None:
            self.tool.release(Ev(self, e))
        if self.live is not None and self.live.get("auto"):
            self.end_live()
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
        self.last_mouse = None
        self.clear_snap()
        self.hover = None
        self.update()
