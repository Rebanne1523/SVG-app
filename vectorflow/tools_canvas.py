"""Canvas tool (C): resize the current sheet (the page) without touching anything drawn on it."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .numfield import NumField
from .tools_base import Tool

HANDLES = [(0, 0), (0.5, 0), (1, 0), (1, 0.5), (1, 1), (0.5, 1), (0, 1), (0, 0.5)]
CURSORS = [Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor,
           Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor]
ACCENT = QColor(0, 140, 255)
MIN_SIZE = 1.0


class CanvasTool(Tool):
    name = "canvas"
    label = "Canvas"
    shortcut = "C"
    hint = ("Drag the handles of the page to change its size; nothing drawn on it moves. Shift = keep the "
            "proportions, Alt = from the centre. Type an exact width / height in the bar above. "
            "Click another page to work on it.")

    def __init__(self, canvas):
        super().__init__(canvas)
        self.reset()
        self._w = self._h = None

    def reset(self):
        self.handle = None
        self.hover = None
        self.orig = None
        self.sheet = None

    def cursor(self):
        if self.hover is not None:
            return QCursor(CURSORS[self.hover])
        return QCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------ options bar
    def options_widget(self, parent=None):
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        self._w, self._h = NumField(), NumField()
        for lab, sp, attr in (("Width", self._w, "width"), ("Height", self._h, "height")):
            sp.setRange(MIN_SIZE, 100000)
            sp.setDecimals(2)
            sp.setSuffix(" px")
            sp.setToolTip("Size of the current page, measured from its top-left corner")
            sp.valueChanged.connect(lambda v, a=attr: self._typed(a, v))
            lay.addWidget(QLabel(lab))
            lay.addWidget(sp)
        self.doc.sheetChanged.connect(self.sync)
        self.doc.contentChanged.connect(self.sync)
        self.sync()
        return w

    def sync(self, *_):
        sh = self.doc.current_sheet()
        for sp, v in ((self._w, sh.width if sh else 0), (self._h, sh.height if sh else 0)):
            try:
                if sp is not None and sh is not None:
                    sp.blockSignals(True)
                    sp.setValue(v)
                    sp.blockSignals(False)
            except RuntimeError:
                pass                    # the bar was rebuilt

    def _typed(self, attr, v):
        sh = self.doc.current_sheet()
        if sh is None or abs(getattr(sh, attr) - v) < 1e-9:
            return
        with self.doc.edit(structure=True, merge_key="canvas-" + attr):
            setattr(sh, attr, float(v))
        self.canvas.update()

    # ------------------------------------------------------------ geometry
    def _handle_views(self, sh):
        r = sh.rect()
        out = []
        for fx, fy in HANDLES:
            out.append(self.canvas.to_view((r.left() + fx * r.width(), r.top() + fy * r.height())))
        return out

    def _hit(self, vp):
        sh = self.doc.current_sheet()
        if sh is None:
            return None
        for i, v in enumerate(self._handle_views(sh)):
            if abs(v[0] - vp[0]) <= 7 and abs(v[1] - vp[1]) <= 7:
                return i
        return None

    def press(self, ev):
        if ev.button != Qt.LeftButton:
            return
        i = self._hit(ev.vp)
        if i is None:
            sh = self.doc.sheet_at(ev.p) or self.canvas.hit_sheet_label(ev.vp)
            if sh is not None and sh is not self.doc.current_sheet():
                self.doc.set_current_sheet(sh)
                self.sync()
                self.canvas.update()
            return
        self.sheet = self.doc.current_sheet()
        self.handle = i
        self.orig = (self.sheet.x, self.sheet.y, self.sheet.width, self.sheet.height)
        self.doc.begin_edit()

    def _resize(self, ev):
        x0, y0, w0, h0 = self.orig
        fx, fy = HANDLES[self.handle]
        p, _ = self.canvas.snap_point(ev.p, ())
        left, top, right, bottom = x0, y0, x0 + w0, y0 + h0
        cx, cy = x0 + w0 / 2, y0 + h0 / 2
        if fx == 0:
            left = min(p[0], right - MIN_SIZE)
        elif fx == 1:
            right = max(p[0], left + MIN_SIZE)
        if fy == 0:
            top = min(p[1], bottom - MIN_SIZE)
        elif fy == 1:
            bottom = max(p[1], top + MIN_SIZE)
        if ev.alt:                                   # mirrored around the centre
            if fx != 0.5:
                half = max(abs((right if fx == 1 else left) - cx), MIN_SIZE / 2)
                left, right = cx - half, cx + half
            if fy != 0.5:
                half = max(abs((bottom if fy == 1 else top) - cy), MIN_SIZE / 2)
                top, bottom = cy - half, cy + half
        if ev.shift and w0 > 0 and h0 > 0:           # keep the proportions
            w, h = right - left, bottom - top
            ratio = w0 / h0
            if fx != 0.5 and fy != 0.5:
                if w / w0 >= h / h0:
                    h = w / ratio
                else:
                    w = h * ratio
                right, bottom = (left + w, top + h) if fx == 1 else (right, bottom)
                if fx == 0:
                    left = right - w
                if fy == 0:
                    top = bottom - h
                else:
                    bottom = top + h
            elif fx != 0.5:
                h = w / ratio
                top, bottom = cy - h / 2, cy + h / 2
            else:
                w = h * ratio
                left, right = cx - w / 2, cx + w / 2
        sh = self.sheet
        sh.x, sh.y, sh.width, sh.height = left, top, right - left, bottom - top
        sh.touch()
        self.sync()
        self.say(f"Canvas {sh.width:.2f} × {sh.height:.2f} px")

    def move(self, ev):
        if self.handle is not None:
            self._resize(ev)
            self.canvas.update()
            return
        h = self._hit(ev.vp)
        if h != self.hover:
            self.hover = h
            self.canvas.update_cursor()

    def release(self, ev):
        if self.handle is None:
            return
        self.handle = None
        self.canvas.clear_snap()
        self.doc.end_edit(True, structure=True)
        self.sync()

    def key_press(self, e):
        if e.key() == Qt.Key_Escape and self.handle is not None and self.orig is not None:
            sh = self.sheet
            sh.x, sh.y, sh.width, sh.height = self.orig
            sh.touch()
            self.doc.cancel_edit()
            self.handle = None
            self.canvas.clear_snap()
            self.sync()
            self.canvas.update()
            return True
        return False

    def paint(self, p: QPainter):
        sh = self.doc.current_sheet()
        if sh is None:
            return
        pen = QPen(ACCENT, 1.5, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        vs = self._handle_views(sh)
        tl, br = vs[0], vs[4]
        p.drawRect(QRectF(QPointF(*tl), QPointF(*br)))
        p.setPen(QPen(ACCENT, 1.2))
        p.setBrush(QColor(255, 255, 255))
        for v in vs:
            p.drawRect(QRectF(v[0] - 4, v[1] - 4, 8, 8))
