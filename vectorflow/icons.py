"""Procedurally drawn icons (no external assets, so the AppImage stays self-contained)."""
from __future__ import annotations


from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

FG = QColor(222, 222, 222)
ACC = QColor(70, 160, 255)


def _canvas(size, draw, color=FG, dpr=2):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 24.0, size / 24.0)
    pen = QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    draw(p, color)
    p.end()
    return pm


def icon(draw, size=24, color=FG):
    ic = QIcon()
    ic.addPixmap(_canvas(size, draw, color), QIcon.Normal)
    ic.addPixmap(_canvas(size, draw, QColor(120, 120, 120)), QIcon.Disabled)
    ic.addPixmap(_canvas(size, draw, QColor(255, 255, 255)), QIcon.Active)
    ic.addPixmap(_canvas(size, draw, QColor(255, 255, 255)), QIcon.Selected)
    return ic


def _poly(p, pts, close=True, fill=False):
    path = QPainterPath()
    path.moveTo(*pts[0])
    for q in pts[1:]:
        path.lineTo(*q)
    if close:
        path.closeSubpath()
    if fill:
        p.setBrush(p.pen().color())
    p.drawPath(path)
    p.setBrush(Qt.NoBrush)


# ------------------------------------------------------------------ tools
def d_select(p, c):
    _poly(p, [(6, 3), (6, 19), (10.5, 15), (13.5, 21), (16, 20), (13, 14), (19, 14)], fill=True)


def d_direct(p, c):
    _poly(p, [(6, 3), (6, 19), (10.5, 15), (13.5, 21), (16, 20), (13, 14), (19, 14)])


def d_pen(p, c):
    path = QPainterPath()
    path.moveTo(12, 3)
    path.lineTo(18, 11)
    path.lineTo(13, 17)
    path.lineTo(11, 17)
    path.lineTo(6, 11)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(12, 3, 12, 11)
    p.drawEllipse(QPointF(12, 12), 1.6, 1.6)
    p.drawLine(9, 21, 15, 21)
    p.drawLine(12, 17, 12, 21)


def d_pencil(p, c):
    _poly(p, [(5, 19), (6, 14), (16, 4), (20, 8), (10, 18)])
    p.drawLine(14, 6, 18, 10)
    p.drawLine(5, 19, 10, 18)


def d_rect(p, c):
    p.drawRoundedRect(QRectF(4, 6, 16, 12), 1.5, 1.5)


def d_ellipse(p, c):
    p.drawEllipse(QRectF(4, 5, 16, 14))


def d_line(p, c):
    p.drawLine(5, 19, 19, 5)


def d_text(p, c):
    p.drawLine(6, 6, 18, 6)
    p.drawLine(12, 6, 12, 19)
    p.drawLine(9, 19, 15, 19)


def d_bucket(p, c):
    _poly(p, [(4, 12), (11, 5), (18, 12), (11, 19)])
    p.drawLine(11, 5, 11, 3)
    path = QPainterPath()
    path.moveTo(20, 15)
    path.cubicTo(22, 18, 22, 20, 20, 20)
    path.cubicTo(18, 20, 18, 18, 20, 15)
    p.setBrush(c)
    p.drawPath(path)
    p.setBrush(Qt.NoBrush)


def d_hand(p, c):
    path = QPainterPath()
    path.moveTo(7, 12)
    path.lineTo(7, 7)
    path.moveTo(10, 11)
    path.lineTo(10, 4)
    path.moveTo(13, 11)
    path.lineTo(13, 5)
    path.moveTo(16, 12)
    path.lineTo(16, 8)
    path.moveTo(7, 12)
    path.cubicTo(7, 12, 5, 11, 5, 13)
    path.cubicTo(6, 17, 8, 21, 12, 21)
    path.cubicTo(16, 21, 18, 18, 17, 13)
    p.drawPath(path)


def d_zoom(p, c):
    p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
    p.drawLine(15, 15, 20, 20)
    p.drawLine(8, 10.5, 13, 10.5)
    p.drawLine(10.5, 8, 10.5, 13)


def d_measure(p, c):
    p.drawLine(4, 8, 4, 18)
    p.drawLine(20, 8, 20, 18)
    p.drawLine(4, 14, 20, 14)
    _poly(p, [(4, 14), (7.5, 12), (7.5, 16)], fill=True)
    _poly(p, [(20, 14), (16.5, 12), (16.5, 16)], fill=True)
    p.drawLine(11, 8, 13, 8)


def d_canvas(p, c):
    # crop marks
    p.drawLine(7, 3, 7, 17)
    p.drawLine(7, 17, 21, 17)
    p.drawLine(3, 7, 17, 7)
    p.drawLine(17, 7, 17, 21)


TOOL_ICONS = {
    "canvas": d_canvas,
    "select": d_select, "direct": d_direct, "pen": d_pen, "pencil": d_pencil, "rect": d_rect,
    "ellipse": d_ellipse, "line": d_line, "text": d_text, "bucket": d_bucket, "hand": d_hand,
    "zoom": d_zoom, "measure": d_measure,
}


# ------------------------------------------------------------------ ui
def d_eye(p, c):
    path = QPainterPath()
    path.moveTo(2.5, 12)
    path.cubicTo(6, 5, 18, 5, 21.5, 12)
    path.cubicTo(18, 19, 6, 19, 2.5, 12)
    p.drawPath(path)
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 12), 3, 3)


def d_eye_off(p, c):
    p.setPen(QPen(QColor(110, 110, 110), 1.6, Qt.SolidLine, Qt.RoundCap))
    path = QPainterPath()
    path.moveTo(2.5, 12)
    path.cubicTo(6, 5, 18, 5, 21.5, 12)
    path.cubicTo(18, 19, 6, 19, 2.5, 12)
    p.drawPath(path)
    p.drawLine(4, 4, 20, 20)


def d_lock(p, c):
    p.drawRoundedRect(QRectF(5, 11, 14, 10), 2, 2)
    path = QPainterPath()
    path.moveTo(8, 11)
    path.lineTo(8, 8)
    path.cubicTo(8, 2.5, 16, 2.5, 16, 8)
    path.lineTo(16, 11)
    p.drawPath(path)


def d_unlock(p, c):
    p.setPen(QPen(QColor(110, 110, 110), 1.5, Qt.SolidLine, Qt.RoundCap))
    p.drawRoundedRect(QRectF(5, 11, 14, 10), 2, 2)
    path = QPainterPath()
    path.moveTo(8, 11)
    path.lineTo(8, 8)
    path.cubicTo(8, 2.5, 16, 2.5, 16, 7)
    p.drawPath(path)


def d_folder(p, c):
    path = QPainterPath()
    path.moveTo(3, 7)
    path.lineTo(9, 7)
    path.lineTo(11, 9)
    path.lineTo(21, 9)
    path.lineTo(21, 19)
    path.lineTo(3, 19)
    path.closeSubpath()
    p.drawPath(path)


def d_layer(p, c):
    _poly(p, [(12, 4), (21, 9), (12, 14), (3, 9)])
    path = QPainterPath()
    path.moveTo(3, 13)
    path.lineTo(12, 18)
    path.lineTo(21, 13)
    p.drawPath(path)


def d_plus(p, c):
    p.drawLine(12, 5, 12, 19)
    p.drawLine(5, 12, 19, 12)


def d_trash(p, c):
    p.drawLine(5, 7, 19, 7)
    p.drawLine(9, 7, 9, 4)
    p.drawLine(9, 4, 15, 4)
    p.drawLine(15, 4, 15, 7)
    path = QPainterPath()
    path.moveTo(7, 7)
    path.lineTo(8, 20)
    path.lineTo(16, 20)
    path.lineTo(17, 7)
    p.drawPath(path)


def d_group(p, c):
    p.drawRect(QRectF(4, 4, 8, 8))
    p.drawRect(QRectF(12, 12, 8, 8))
    pen = QPen(c, 1.2, Qt.DashLine)
    p.setPen(pen)
    p.drawRect(QRectF(2.5, 2.5, 19, 19))


def d_dup(p, c):
    p.drawRect(QRectF(4, 8, 11, 11))
    p.drawRect(QRectF(9, 4, 11, 11))


UI_ICONS = {
    "eye": d_eye, "eye_off": d_eye_off, "lock": d_lock, "unlock": d_unlock, "folder": d_folder,
    "layer": d_layer, "plus": d_plus, "trash": d_trash, "group": d_group, "dup": d_dup,
}

_cache = {}


def tool_icon(name, size=24):
    k = ("t", name, size)
    if k not in _cache:
        _cache[k] = icon(TOOL_ICONS[name], size)
    return _cache[k]


def ui_icon(name, size=18):
    k = ("u", name, size)
    if k not in _cache:
        _cache[k] = icon(UI_ICONS[name], size)
    return _cache[k]


_sw_cache = {}


def swatch_icon(fill, stroke, size=16):
    """Small fill/stroke chip used in the layers list."""
    key = (fill, stroke, size)
    if key in _sw_cache:
        return _sw_cache[key]
    ic = _swatch_icon(fill, stroke, size)
    if len(_sw_cache) < 6000:
        _sw_cache[key] = ic
    return ic


def _swatch_icon(fill, stroke, size=16):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    r = QRectF(2.5, 2.5, size - 5, size - 5)
    # checkerboard for transparency
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(90, 90, 90))
    p.drawRoundedRect(r, 2, 2)
    if fill:
        p.setBrush(QColor(*fill))
        p.drawRoundedRect(r, 2, 2)
    if stroke:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(*stroke), 1.6))
        p.drawRoundedRect(r, 2, 2)
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(150, 150, 150), 0.8))
        p.drawRoundedRect(r, 2, 2)
    if not fill and not stroke:
        p.setPen(QPen(QColor(220, 60, 60), 1.2))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.top()))
    p.end()
    return QIcon(pm)


# ------------------------------------------------------------------ style previews
def preview_icon(kind, value, w=56, h=20):
    """Icons for the dash / cap / join / arrow combo boxes."""
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    col = FG
    cy = h / 2.0
    if kind == "dash":
        pen = QPen(col, 2.5)
        pen.setCapStyle(Qt.RoundCap if value in ("dotted", "dash-dot") else Qt.FlatCap)
        from .model import DASH_PRESETS
        pat = DASH_PRESETS.get(value, [])
        if pat:
            pen.setDashPattern(pat)
        p.setPen(pen)
        p.drawLine(QPointF(4, cy), QPointF(w - 4, cy))
    elif kind == "cap":
        pen = QPen(col, 8)
        pen.setCapStyle({"butt": Qt.FlatCap, "round": Qt.RoundCap, "square": Qt.SquareCap}[value])
        p.setPen(pen)
        p.drawLine(QPointF(14, cy), QPointF(w - 14, cy))
        g = QPen(QColor(255, 80, 80), 1)
        p.setPen(g)
        p.drawLine(QPointF(14, 2), QPointF(14, h - 2))
        p.drawLine(QPointF(w - 14, 2), QPointF(w - 14, h - 2))
    elif kind == "join":
        pen = QPen(col, 6)
        pen.setJoinStyle({"miter": Qt.MiterJoin, "round": Qt.RoundJoin, "bevel": Qt.BevelJoin}[value])
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(w / 2 - 14, h - 5)
        path.lineTo(w / 2, 5)
        path.lineTo(w / 2 + 14, h - 5)
        p.drawPath(path)
    elif kind == "arrow_end" or kind == "arrow_start":
        from .model import arrow_path
        p.setPen(QPen(col, 2.0))
        if kind == "arrow_end":
            p.drawLine(QPointF(4, cy), QPointF(w - 12, cy))
            ap, filled, _ = arrow_path(value, (w - 6, cy), (1, 0), 11) if value != "none" else (None, 0, 0)
        else:
            p.drawLine(QPointF(12, cy), QPointF(w - 4, cy))
            ap, filled, _ = arrow_path(value, (6, cy), (-1, 0), 11) if value != "none" else (None, 0, 0)
        if ap is not None:
            if filled:
                p.fillPath(ap, col)
            else:
                p.setPen(QPen(col, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(ap)
    p.end()
    return QIcon(pm)


def app_icon():
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(38, 42, 54))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    path = QPainterPath()
    path.moveTo(64, 176)
    path.cubicTo(64, 60, 192, 60, 192, 150)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(70, 160, 255), 14, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(path)
    p.setPen(QPen(QColor(255, 255, 255), 5))
    p.setBrush(QColor(255, 255, 255))
    for x, y in ((64, 176), (192, 150)):
        p.drawRect(QRectF(x - 12, y - 12, 24, 24))
    p.setPen(QPen(QColor(255, 90, 200), 6))
    p.drawLine(64, 206, 192, 206)
    p.drawLine(64, 196, 64, 216)
    p.drawLine(192, 196, 192, 216)
    p.end()
    return QIcon(pm)
