"""Tool base class and shared helpers."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap


class Tool:
    name = "tool"
    label = "Tool"
    shortcut = ""
    hint = ""

    def __init__(self, canvas):
        self.canvas = canvas

    @property
    def doc(self):
        return self.canvas.doc

    # lifecycle
    def activate(self):
        self.reset()

    def deactivate(self):
        self.reset()

    def reset(self):
        """Forget any in-progress interaction (document replaced / undo)."""

    def cursor(self):
        return QCursor(Qt.ArrowCursor)

    def options_widget(self, parent=None):
        return None

    # events (return value ignored unless stated)
    def press(self, ev):
        pass

    def move(self, ev):
        pass

    def release(self, ev):
        pass

    def double_click(self, ev):
        # Qt replaces the second press of a fast double click with a double-click event; tools
        # that don't use it must still see that click (e.g. quick A -> B -> offset in Measure).
        self.press(ev)

    def middle_click(self, ev):
        """The mouse wheel was clicked (not dragged)."""

    def wheel(self, ev, delta) -> bool:
        return False

    def key_press(self, e) -> bool:
        return False

    def key_release(self, e) -> bool:
        return False

    def on_delete(self) -> bool:
        """Called by Delete/Backspace; return True if the tool consumed it."""
        return False

    def paint(self, p: QPainter):
        pass

    def say(self, msg):
        self.canvas.message.emit(msg)


_cursor_cache = {}


def rotate_cursor(angle_deg=0.0):
    key = int(round(angle_deg / 15.0)) % 24
    if key in _cursor_cache:
        return _cursor_cache[key]
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(size / 2, size / 2)
    p.rotate(key * 15.0)
    for pen in (QPen(QColor(255, 255, 255), 4.2, Qt.SolidLine, Qt.RoundCap), QPen(QColor(0, 0, 0), 1.8, Qt.SolidLine, Qt.RoundCap)):
        p.setPen(pen)
        path = QPainterPath()
        path.arcMoveTo(QRectF(-9, -9, 18, 18), 20)
        path.arcTo(QRectF(-9, -9, 18, 18), 20, 230)
        p.drawPath(path)
    # arrow heads at both arc ends
    def head(ang, flip):
        a = math.radians(ang)
        cx, cy = 9 * math.cos(a), -9 * math.sin(a)
        tx, ty = math.sin(a) * (1 if flip else -1), math.cos(a) * (1 if flip else -1)
        nx, ny = math.cos(a), -math.sin(a)
        poly = [QPointF(cx + tx * 5, cy + ty * 5), QPointF(cx + nx * 4, cy + ny * 4), QPointF(cx - nx * 4, cy - ny * 4)]
        return poly
    for ang, flip in ((20, False), (250, True)):
        poly = head(ang, flip)
        for col, w in ((QColor(255, 255, 255), 3.0), (QColor(0, 0, 0), 0.6)):
            p.setPen(QPen(col, w))
            p.setBrush(QColor(0, 0, 0))
            p.drawPolygon(poly)
    p.end()
    c = QCursor(pm, size // 2, size // 2)
    _cursor_cache[key] = c
    return c


def style_for_new(doc, fill_default=None):
    st = doc.default_style.copy()
    return st
