"""Helpers to drive the canvas with synthetic mouse events (no display needed)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

_app = None


def app():
    global _app
    _app = QApplication.instance() or QApplication([])
    return _app


class Driver:
    def __init__(self, canvas):
        self.c = canvas

    def _ev(self, kind, p, button, buttons, mods):
        v = self.c.to_view(p)
        pt = QPointF(*v)
        return QMouseEvent(kind, pt, self.c.mapToGlobal(pt), button, buttons, mods)

    def press(self, p, mods=Qt.NoModifier, button=Qt.LeftButton):
        self.c.mousePressEvent(self._ev(QEvent.MouseButtonPress, p, button, button, mods))

    def move(self, p, mods=Qt.NoModifier, down=True):
        b = Qt.LeftButton if down else Qt.NoButton
        self.c.mouseMoveEvent(self._ev(QEvent.MouseMove, p, Qt.NoButton, b, mods))

    def release(self, p, mods=Qt.NoModifier, button=Qt.LeftButton):
        self.c.mouseReleaseEvent(self._ev(QEvent.MouseButtonRelease, p, button, Qt.NoButton, mods))

    def drag(self, a, b, mods=Qt.NoModifier, steps=6):
        self.press(a, mods)
        for i in range(1, steps + 1):
            t = i / steps
            self.move((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), mods)
        self.release(b, mods)

    def click(self, p, mods=Qt.NoModifier):
        self.press(p, mods)
        self.release(p, mods)

    def dblclick(self, p, mods=Qt.NoModifier):
        self.c.mouseDoubleClickEvent(self._ev(QEvent.MouseButtonDblClick, p, Qt.LeftButton, Qt.LeftButton, mods))
        self.release(p, mods)

    def wheel(self, p, delta=120, mods=Qt.NoModifier):
        from PySide6.QtCore import QPoint
        pt = QPointF(*self.c.to_view(p))
        ev = QWheelEvent(pt, self.c.mapToGlobal(pt), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, mods,
                         Qt.NoScrollPhase, False)
        self.c.wheelEvent(ev)

    def key(self, key, mods=Qt.NoModifier, text=""):
        e = QKeyEvent(QEvent.KeyPress, key, mods, text)
        self.c.keyPressEvent(e)
