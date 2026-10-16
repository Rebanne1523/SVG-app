"""Document model: nodes (groups, paths, text, images, measurements), styles, undo."""
from __future__ import annotations

import copy
import itertools
import math
import sys
import time
from contextlib import contextmanager

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainterPath,
                           QPainterPathStroker, QPolygonF, QTransform)

from . import affine
from .geometry import KAPPA, dist

sys.setrecursionlimit(20000)

_ids = itertools.count(1)

Color = tuple  # (r, g, b, a) 0-255 or None

DASH_PRESETS = {
    "solid": [],
    "dashed": [4.0, 3.0],
    "long dash": [8.0, 4.0],
    "dotted": [0.001, 2.0],
    "dash-dot": [4.0, 2.0, 0.001, 2.0],
}
ARROW_TYPES = ["none", "triangle", "open", "circle", "square", "diamond"]
CAPS = ["butt", "round", "square"]
JOINS = ["miter", "round", "bevel"]


def qcolor(c: Color | None) -> QColor:
    return QColor(*c) if c else QColor(0, 0, 0, 0)


def color_tuple(q: QColor) -> Color:
    return (q.red(), q.green(), q.blue(), q.alpha())


def a_to_t(m) -> QTransform:
    return QTransform(m[0], m[1], m[2], m[3], m[4], m[5])


class Style:
    def __init__(self, fill=None, stroke=(0, 0, 0, 255), width=2.0, dash=None, cap="butt",
                 join="miter", arrow_start="none", arrow_end="none", arrow_size=1.0,
                 fill_rule="nonzero"):
        self.fill = fill
        self.stroke = stroke
        self.width = width
        self.dash = list(dash) if dash else []
        self.cap = cap
        self.join = join
        self.arrow_start = arrow_start
        self.arrow_end = arrow_end
        self.arrow_size = arrow_size
        self.fill_rule = fill_rule

    def copy(self) -> "Style":
        s = Style.__new__(Style)
        s.__dict__.update(self.__dict__)
        s.dash = list(self.dash)
        return s

    def dash_name(self) -> str:
        for k, v in DASH_PRESETS.items():
            if len(v) == len(self.dash) and all(abs(a - b) < 1e-6 for a, b in zip(v, self.dash)):
                return k
        return "custom"

    def pen(self, scale_width=1.0):
        from PySide6.QtGui import QPen
        if not self.stroke or self.width <= 0:
            return QPen(Qt.NoPen)
        pen = QPen(qcolor(self.stroke))
        pen.setWidthF(self.width * scale_width)
        pen.setCapStyle({"butt": Qt.FlatCap, "round": Qt.RoundCap, "square": Qt.SquareCap}[self.cap])
        pen.setJoinStyle({"miter": Qt.MiterJoin, "round": Qt.RoundJoin, "bevel": Qt.BevelJoin}[self.join])
        pen.setMiterLimit(4.0)
        if self.dash:
            pen.setDashPattern(list(self.dash))
        return pen


def arrow_length(style: Style) -> float:
    return style.arrow_size * (6.0 + 2.0 * style.width)


def arrow_path(kind: str, tip, direction, length: float):
    """Return (QPainterPath, filled, trim) for an arrow whose tip sits at ``tip`` and
    which points along unit vector ``direction``. ``trim`` is how much of the line
    the arrow covers (so the line can be shortened underneath it)."""
    dx, dy = direction
    nx, ny = -dy, dx
    hw = length * 0.38
    p = QPainterPath()
    tx, ty = tip
    if kind == "triangle":
        p.moveTo(tx, ty)
        p.lineTo(tx - dx * length + nx * hw, ty - dy * length + ny * hw)
        p.lineTo(tx - dx * length - nx * hw, ty - dy * length - ny * hw)
        p.closeSubpath()
        return p, True, length * 0.85
    if kind == "open":
        p.moveTo(tx - dx * length + nx * hw, ty - dy * length + ny * hw)
        p.lineTo(tx, ty)
        p.lineTo(tx - dx * length - nx * hw, ty - dy * length - ny * hw)
        return p, False, 0.0
    r = length * 0.4
    if kind == "circle":
        p.addEllipse(QPointF(tx, ty), r, r)
        return p, True, 0.0
    if kind == "square":
        poly = QPolygonF([QPointF(tx + dx * r + nx * r, ty + dy * r + ny * r),
                          QPointF(tx + dx * r - nx * r, ty + dy * r - ny * r),
                          QPointF(tx - dx * r - nx * r, ty - dy * r - ny * r),
                          QPointF(tx - dx * r + nx * r, ty - dy * r + ny * r)])
        p.addPolygon(poly)
        p.closeSubpath()
        return p, True, 0.0
    if kind == "diamond":
        poly = QPolygonF([QPointF(tx + dx * r * 1.4, ty + dy * r * 1.4),
                          QPointF(tx + nx * r, ty + ny * r),
                          QPointF(tx - dx * r * 1.4, ty - dy * r * 1.4),
                          QPointF(tx - nx * r, ty - ny * r)])
        p.addPolygon(poly)
        p.closeSubpath()
        return p, True, 0.0
    return None, False, 0.0


def build_text_path(text, family, size, bold, italic, anchor="start", line_gap=1.2) -> QPainterPath:
    font = QFont(family)
    font.setPixelSize(max(1, int(round(size * 8))))  # build at 8x for precision, scaled below
    font.setBold(bold)
    font.setItalic(italic)
    fm = QFontMetricsF(font)
    path = QPainterPath()
    y = 0.0
    for line in (text or "").split("\n"):
        w = fm.horizontalAdvance(line)
        x = 0.0
        if anchor == "middle":
            x = -w / 2.0
        elif anchor == "end":
            x = -w
        path.addText(x, y, font, line)
        y += fm.height() * line_gap / 1.2
    return QTransform().scale(1 / 8.0, 1 / 8.0).map(path)


class Anchor:
    __slots__ = ("x", "y", "ix", "iy", "ox", "oy", "smooth")

    def __init__(self, x, y, ix=None, iy=None, ox=None, oy=None, smooth=False):
        self.x, self.y = float(x), float(y)
        self.ix, self.iy = (self.x, self.y) if ix is None else (float(ix), float(iy))
        self.ox, self.oy = (self.x, self.y) if ox is None else (float(ox), float(oy))
        self.smooth = smooth

    def copy(self):
        return Anchor(self.x, self.y, self.ix, self.iy, self.ox, self.oy, self.smooth)

    @property
    def p(self):
        return (self.x, self.y)

    @property
    def hin(self):
        return (self.ix, self.iy)

    @property
    def hout(self):
        return (self.ox, self.oy)

    def has_in(self):
        return abs(self.ix - self.x) > 1e-9 or abs(self.iy - self.y) > 1e-9

    def has_out(self):
        return abs(self.ox - self.x) > 1e-9 or abs(self.oy - self.y) > 1e-9

    def move_to(self, x, y):
        dx, dy = x - self.x, y - self.y
        self.x, self.y = x, y
        self.ix += dx
        self.iy += dy
        self.ox += dx
        self.oy += dy

    def transform(self, m):
        self.x, self.y = affine.apply(m, self.x, self.y)
        self.ix, self.iy = affine.apply(m, self.ix, self.iy)
        self.ox, self.oy = affine.apply(m, self.ox, self.oy)

    def collapse(self):
        self.ix, self.iy, self.ox, self.oy = self.x, self.y, self.x, self.y
        self.smooth = False

    def set_out(self, x, y, mirror=True):
        """Move the outgoing handle; keep the other handle collinear when smooth."""
        self.ox, self.oy = x, y
        if self.smooth and mirror and self.has_in():
            lin = math.hypot(self.ix - self.x, self.iy - self.y)
            dx, dy = self.x - x, self.y - y
            l = math.hypot(dx, dy)
            if l > 1e-9:
                self.ix, self.iy = self.x + dx / l * lin, self.y + dy / l * lin

    def set_in(self, x, y, mirror=True):
        self.ix, self.iy = x, y
        if self.smooth and mirror and self.has_out():
            lout = math.hypot(self.ox - self.x, self.oy - self.y)
            dx, dy = self.x - x, self.y - y
            l = math.hypot(dx, dy)
            if l > 1e-9:
                self.ox, self.oy = self.x + dx / l * lout, self.y + dy / l * lout


class SubPath:
    def __init__(self, anchors=None, closed=False):
        self.anchors = anchors or []
        self.closed = closed

    def copy(self):
        return SubPath([a.copy() for a in self.anchors], self.closed)

    def segments(self):
        """Yield (index, a0, a1) for every segment, including the closing one."""
        n = len(self.anchors)
        for i in range(n - 1):
            yield i, self.anchors[i], self.anchors[i + 1]
        if self.closed and n > 1:
            yield n - 1, self.anchors[-1], self.anchors[0]

    def add_to(self, path: QPainterPath):
        if not self.anchors:
            return
        first = self.anchors[0]
        path.moveTo(first.x, first.y)
        for _, a, b in self.segments():
            if not a.has_out() and not b.has_in():
                path.lineTo(b.x, b.y)
            else:
                path.cubicTo(a.ox, a.oy, b.ix, b.iy, b.x, b.y)
        if self.closed:
            path.closeSubpath()

    def transform(self, m):
        for a in self.anchors:
            a.transform(m)


class Node:
    kind = "node"

    def __init__(self, name=""):
        self.id = next(_ids)
        self.name = name
        self.visible = True
        self.locked = False
        self.opacity = 1.0
        self.parent = None
        self.clip = None  # list[SubPath] in document coordinates
        self._rev = 0

    # caches (attributes starting with _c_) are never copied
    def __getstate__(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_c_")}

    def touch(self):
        self._rev += 1
        for k in [k for k in self.__dict__ if k.startswith("_c_")]:
            del self.__dict__[k]

    def is_group(self):
        return False

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def clip_path(self):
        if not self.clip:
            return None
        p = QPainterPath()
        for sp in self.clip:
            sp.add_to(p)
        return p

    # geometry protocol -------------------------------------------------
    def get_geom(self):
        raise NotImplementedError

    def set_geom(self, g):
        raise NotImplementedError

    def transform(self, m, scale_stroke=False):
        raise NotImplementedError

    def _transform_clip(self, m):
        if self.clip:
            for sp in self.clip:
                sp.transform(m)

    def bounds(self) -> QRectF:
        return QRectF()

    def shape_path(self) -> QPainterPath:
        """Path used for hit testing (fill area + stroke area)."""
        return QPainterPath()


class Group(Node):
    kind = "group"

    def __init__(self, name="Folder"):
        super().__init__(name)
        self.children = []
        self.expanded = True

    def is_group(self):
        return True

    def add(self, node, index=None):
        if node.parent is not None:
            node.parent.children.remove(node)
        node.parent = self
        if index is None:
            self.children.append(node)
        else:
            self.children.insert(index, node)

    def get_geom(self):
        return ([c.get_geom() for c in self.children], copy.deepcopy(self.clip))

    def set_geom(self, g):
        geoms, clip = g
        for c, cg in zip(self.children, geoms):
            c.set_geom(cg)
        self.clip = copy.deepcopy(clip)
        self.touch()

    def transform(self, m, scale_stroke=False):
        for c in self.children:
            c.transform(m, scale_stroke)
        self._transform_clip(m)
        self.touch()

    def bounds(self):
        r = QRectF()
        for c in self.children:
            if c.visible:
                b = c.bounds()
                if not b.isNull() or b.width() or b.height():
                    r = b if r.isNull() else r.united(b)
        return r


class Sheet(Group):
    """A page of the project. Sheets live directly under the document root and their children are
    the layers. Everything inside uses absolute canvas coordinates; (x, y) is the page's top-left
    corner, so "position on the sheet" = canvas position - (x, y)."""

    def __init__(self, name="Sheet", x=0.0, y=0.0, width=1920.0, height=1080.0, pt_per_unit=0.75,
                 source=None):
        super().__init__(name)
        self.x, self.y = float(x), float(y)
        self.width, self.height = float(width), float(height)
        self.pt_per_unit = pt_per_unit  # 1.0 for PDF imports (1 unit = 1 pt), 0.75 for SVG px
        self.source = source

    def rect(self) -> QRectF:
        return QRectF(self.x, self.y, self.width, self.height)

    def get_geom(self):
        return (super().get_geom(), self.x, self.y)

    def set_geom(self, g):
        super().set_geom(g[0])
        self.x, self.y = g[1], g[2]

    def transform(self, m, scale_stroke=False):
        super().transform(m, scale_stroke)
        self.x, self.y = affine.apply(m, self.x, self.y)  # pages only ever translate

    def bounds(self):
        return self.rect()


class PathNode(Node):
    kind = "path"

    def __init__(self, subpaths=None, style=None, name="Path"):
        super().__init__(name)
        self.subpaths = subpaths or []
        self.style = style or Style()

    # constructors
    @staticmethod
    def polyline(points, closed=False, style=None, name="Path"):
        sp = SubPath([Anchor(x, y) for x, y in points], closed)
        return PathNode([sp], style, name)

    @staticmethod
    def rect(x, y, w, h, r=0.0, style=None, name="Rectangle"):
        r = max(0.0, min(r, abs(w) / 2, abs(h) / 2))
        if r <= 0:
            return PathNode.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True, style, name)
        k = r * (1 - KAPPA)
        x2, y2 = x + w, y + h
        pts = [
            Anchor(x + r, y, x + r, y, x + r, y),
            Anchor(x2 - r, y, x2 - r, y, x2 - r, y),
            Anchor(x2, y + r, x2, y + k, x2, y + r),
            Anchor(x2, y2 - r, x2, y2 - r, x2, y2 - r),
            Anchor(x2 - r, y2, x2 - k, y2, x2 - r, y2),
            Anchor(x + r, y2, x + r, y2, x + r, y2),
            Anchor(x, y2 - r, x, y2 - k, x, y2 - r),
            Anchor(x, y + r, x, y + r, x, y + r),
        ]
        # corner handles
        pts[1].ox, pts[1].oy = x2 - k, y
        pts[2].ix, pts[2].iy = x2, y + k
        pts[3].ox, pts[3].oy = x2, y2 - k
        pts[4].ix, pts[4].iy = x2 - k, y2
        pts[5].ox, pts[5].oy = x + k, y2
        pts[6].ix, pts[6].iy = x, y2 - k
        pts[7].ox, pts[7].oy = x, y + k
        pts[0].ix, pts[0].iy = x + k, y
        return PathNode([SubPath(pts, True)], style, name)

    @staticmethod
    def ellipse(cx, cy, rx, ry, style=None, name="Ellipse"):
        kx, ky = rx * KAPPA, ry * KAPPA
        a = [
            Anchor(cx + rx, cy, cx + rx, cy - ky, cx + rx, cy + ky, True),
            Anchor(cx, cy + ry, cx + kx, cy + ry, cx - kx, cy + ry, True),
            Anchor(cx - rx, cy, cx - rx, cy + ky, cx - rx, cy - ky, True),
            Anchor(cx, cy - ry, cx - kx, cy - ry, cx + kx, cy - ry, True),
        ]
        return PathNode([SubPath(a, True)], style, name)

    # geometry
    def qpath(self) -> QPainterPath:
        p = getattr(self, "_c_path", None)
        if p is None:
            p = QPainterPath()
            for sp in self.subpaths:
                sp.add_to(p)
            p.setFillRule(Qt.OddEvenFill if self.style.fill_rule == "evenodd" else Qt.WindingFill)
            self._c_path = p
        return p

    def get_geom(self):
        return ([sp.copy() for sp in self.subpaths], copy.deepcopy(self.clip))

    def set_geom(self, g):
        sps, clip = g
        self.subpaths = [sp.copy() for sp in sps]
        self.clip = copy.deepcopy(clip)
        self.touch()

    def transform(self, m, scale_stroke=False):
        for sp in self.subpaths:
            sp.transform(m)
        if scale_stroke:
            s = affine.mean_scale(m)
            self.style.width *= s
        self._transform_clip(m)
        self.touch()

    def bounds(self):
        b = getattr(self, "_c_bounds", None)
        if b is None:
            b = self.qpath().boundingRect()
            self._c_bounds = b
        return b

    def shape_path(self):
        sp = getattr(self, "_c_shape", None)
        if sp is None:
            path = self.qpath()
            st = self.style
            sp = QPainterPath()
            if st.fill:
                sp = QPainterPath(path)
            if st.stroke and st.width > 0:
                stroker = QPainterPathStroker()
                stroker.setWidth(max(st.width, 0.001))
                stroker.setCapStyle({"butt": Qt.FlatCap, "round": Qt.RoundCap, "square": Qt.SquareCap}[st.cap])
                stroker.setJoinStyle({"miter": Qt.MiterJoin, "round": Qt.RoundJoin, "bevel": Qt.BevelJoin}[st.join])
                sp = sp.united(stroker.createStroke(path))
            self._c_shape = sp
        return sp

    def anchor_count(self):
        return sum(len(s.anchors) for s in self.subpaths)


class TextNode(Node):
    kind = "text"

    def __init__(self, x, y, text="Text", family="DejaVu Sans", size=24.0, bold=False, italic=False,
                 anchor="start", rotation=0.0, style=None, name="Text"):
        super().__init__(name)
        self.x, self.y = x, y
        self.text = text
        self.family = family
        self.size = size
        self.bold = bold
        self.italic = italic
        self.anchor = anchor
        self.rotation = rotation
        self.style = style or Style(fill=(0, 0, 0, 255), stroke=None, width=0)

    def qpath(self):
        p = getattr(self, "_c_path", None)
        if p is None:
            base = build_text_path(self.text, self.family, self.size, self.bold, self.italic, self.anchor)
            t = QTransform().translate(self.x, self.y).rotate(self.rotation)
            p = t.map(base)
            self._c_path = p
        return p

    def get_geom(self):
        return (self.x, self.y, self.size, self.rotation, copy.deepcopy(self.clip))

    def set_geom(self, g):
        self.x, self.y, self.size, self.rotation, clip = g
        self.clip = copy.deepcopy(clip)
        self.touch()

    def transform(self, m, scale_stroke=False):
        self.x, self.y = affine.apply(m, self.x, self.y)
        self.size *= affine.mean_scale(m)
        self.rotation += affine.rotation_deg(m)
        self._transform_clip(m)
        self.touch()

    def bounds(self):
        return self.qpath().boundingRect()

    def shape_path(self):
        r = self.qpath().boundingRect()
        p = QPainterPath()
        p.addRect(r.adjusted(-1, -1, 1, 1))
        return p


class ImageNode(Node):
    kind = "image"

    def __init__(self, x, y, w, h, data: bytes, name="Image"):
        super().__init__(name)
        self.x, self.y, self.w, self.h = x, y, w, h
        self.data = data

    def image(self) -> QImage:
        img = getattr(self, "_c_img", None)
        if img is None:
            img = QImage()
            img.loadFromData(self.data)
            self._c_img = img
        return img

    def get_geom(self):
        return (self.x, self.y, self.w, self.h, copy.deepcopy(self.clip))

    def set_geom(self, g):
        self.x, self.y, self.w, self.h, clip = g
        self.clip = copy.deepcopy(clip)
        self.touch()

    def transform(self, m, scale_stroke=False):
        pts = [affine.apply(m, self.x, self.y), affine.apply(m, self.x + self.w, self.y),
               affine.apply(m, self.x, self.y + self.h), affine.apply(m, self.x + self.w, self.y + self.h)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        self.x, self.y = min(xs), min(ys)
        self.w, self.h = max(xs) - min(xs), max(ys) - min(ys)
        self._transform_clip(m)
        self.touch()

    def bounds(self):
        return QRectF(self.x, self.y, self.w, self.h)

    def shape_path(self):
        p = QPainterPath()
        p.addRect(self.bounds())
        return p


class MeasureNode(Node):
    """A dimension line: two measured points A and B, an offset and a text."""
    kind = "measure"

    def __init__(self, a, b, offset, text="", mode_a="leg", mode_b="leg", style=None,
                 family="DejaVu Sans", font_size=14.0, text_color=(0, 0, 0, 255),
                 bold=False, italic=False, name="Measure", gap_a=0.0, gap_b=0.0, linked=True):
        super().__init__(name)
        self.a, self.b = tuple(a), tuple(b)
        self.gap_a, self.gap_b = float(gap_a), float(gap_b)   # arrow tip distance from the measured point
        self.linked = bool(linked)                            # follows the project-wide height / gap
        self.offset = float(offset)
        self.text = text
        self.mode_a, self.mode_b = mode_a, mode_b
        self.style = style or Style(fill=None, stroke=(0, 0, 0, 255), width=1.0, arrow_end="none")
        if self.style.arrow_start == "none":
            pass
        self.family = family
        self.font_size = font_size
        self.text_color = text_color
        self.bold = bold
        self.italic = italic
        self.arrow_kind = "triangle"

    # geometry --------------------------------------------------------
    def frame(self):
        ax, ay = self.a
        bx, by = self.b
        dx, dy = bx - ax, by - ay
        l = math.hypot(dx, dy)
        if l < 1e-9:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = dx / l, dy / l
        return ux, uy, -uy, ux, l

    def length(self):
        return dist(self.a, self.b)

    def geometry(self):
        ux, uy, nx, ny, _ = self.frame()
        d = self.offset
        straight = abs(d) < 1e-6
        a2 = (self.a[0] + nx * d, self.a[1] + ny * d)
        b2 = (self.b[0] + nx * d, self.b[1] + ny * d)
        segs = [(a2, b2)]
        arrows = []
        sgn = 1.0 if d >= 0 else -1.0
        for pt, p2, mode, out, gap in ((self.a, a2, self.mode_a, (-ux, -uy), self.gap_a),
                                       (self.b, b2, self.mode_b, (ux, uy), self.gap_b)):
            if straight or mode == "line":
                arrows.append((p2, out))
            else:
                g = min(max(gap, 0.0), abs(d) * 0.9)
                tip = (pt[0] + nx * sgn * g, pt[1] + ny * sgn * g)
                segs.append((p2, tip))
                arrows.append((tip, (-nx * sgn, -ny * sgn)))
        theta = math.degrees(math.atan2(uy, ux))
        if abs(abs(theta) - 90.0) < 0.01:
            theta = -90.0         # vertical text always reads bottom-to-top
        elif theta > 90.0:
            theta -= 180
        elif theta < -90.0:
            theta += 180
        tr = math.radians(theta)
        up = (math.sin(tr), -math.cos(tr))
        outer = up if straight else (nx * sgn, ny * sgn)
        gap = self.font_size * 0.7 + self.style.width * 0.5
        mid = ((a2[0] + b2[0]) / 2 + outer[0] * gap, (a2[1] + b2[1]) / 2 + outer[1] * gap)
        return {"segs": segs, "arrows": arrows, "text_pos": mid, "text_angle": theta}

    def arrow_len(self):
        # proportional to the line weight, so thickening the line enlarges the arrows
        return self.style.arrow_size * self.style.width * 7.0

    def text_path(self):
        p = getattr(self, "_c_text", None)
        if p is None:
            g = self.geometry()
            base = build_text_path(self.text, self.family, self.font_size, self.bold, self.italic, "middle")
            # centre vertically on the baseline offset
            fm_h = self.font_size * 0.35
            t = QTransform().translate(g["text_pos"][0], g["text_pos"][1]).rotate(g["text_angle"]).translate(0, fm_h)
            p = t.map(base)
            self._c_text = p
        return p

    def line_path(self, trimmed=True):
        """Dimension lines as a QPainterPath (shortened under arrows) and arrow shapes."""
        g = self.geometry()
        L = self.arrow_len()
        kind = self.arrow_kind
        shapes = []
        trims = []
        for tip, d in g["arrows"]:
            ap, filled, trim = arrow_path(kind, tip, d, L)
            shapes.append((ap, filled))
            trims.append((tip, d, trim))
        path = QPainterPath()
        for s0, s1 in g["segs"]:
            p0, p1 = s0, s1
            for tip, d, trim in trims:
                if trim <= 0:
                    continue
                # shorten if this segment ends at the tip
                for end in (0, 1):
                    pe = p0 if end == 0 else p1
                    if dist(pe, tip) < 1e-6:
                        other = p1 if end == 0 else p0
                        seglen = dist(pe, other)
                        if seglen > 1e-9:
                            f = min(trim, seglen * 0.95) / seglen
                            ne = (pe[0] + (other[0] - pe[0]) * f, pe[1] + (other[1] - pe[1]) * f)
                            if end == 0:
                                p0 = ne
                            else:
                                p1 = ne
            path.moveTo(*p0)
            path.lineTo(*p1)
        return path, shapes

    def get_geom(self):
        return (self.a, self.b, self.offset, self.font_size, self.style.width, copy.deepcopy(self.clip),
                self.gap_a, self.gap_b)

    def set_geom(self, g):
        self.a, self.b, self.offset, self.font_size, self.style.width, clip, self.gap_a, self.gap_b = g
        self.clip = copy.deepcopy(clip)
        self.touch()

    def transform(self, m, scale_stroke=False):
        ax, ay = affine.apply(m, *self.a)
        bx, by = affine.apply(m, *self.b)
        s = affine.mean_scale(m)
        ux, uy, nx, ny, _ = self.frame()
        # keep the sign of the offset relative to the new orientation
        n_new = affine.apply((m[0], m[1], m[2], m[3], 0.0, 0.0), nx, ny)
        self.a, self.b = (ax, ay), (bx, by)
        nux, nuy, nnx, nny, _ = self.frame()
        dot = n_new[0] * nnx + n_new[1] * nny
        self.offset = self.offset * s * (1.0 if dot >= 0 else -1.0)
        self.font_size *= s
        self.gap_a *= s
        self.gap_b *= s
        if scale_stroke:
            self.style.width *= s
        self._transform_clip(m)
        self.touch()

    def _stroke_shape(self):
        path, shapes = self.line_path()
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.style.width, 1.0))
        res = stroker.createStroke(path)
        for ap, _ in shapes:
            if ap is not None:
                res = res.united(ap)
        return res

    def bounds(self):
        b = getattr(self, "_c_bounds", None)
        if b is None:
            b = self._stroke_shape().boundingRect().united(self.text_path().boundingRect())
            self._c_bounds = b
        return b

    def shape_path(self):
        sp = getattr(self, "_c_shape", None)
        if sp is None:
            sp = self._stroke_shape().united(self.text_path())
            self._c_shape = sp
        return sp

    def to_data(self):
        return {"a": list(self.a), "b": list(self.b), "offset": self.offset, "text": self.text,
                "mode_a": self.mode_a, "mode_b": self.mode_b, "family": self.family,
                "font_size": self.font_size, "text_color": list(self.text_color),
                "bold": self.bold, "italic": self.italic, "width": self.style.width,
                "stroke": list(self.style.stroke) if self.style.stroke else None,
                "dash": self.style.dash, "cap": self.style.cap, "arrow_size": self.style.arrow_size,
                "arrow_kind": self.arrow_kind, "gap_a": self.gap_a, "gap_b": self.gap_b,
                "linked": self.linked}

    @staticmethod
    def from_data(d, name="Measure"):
        st = Style(fill=None, stroke=tuple(d["stroke"]) if d.get("stroke") else None,
                   width=d.get("width", 1.0), dash=d.get("dash"), cap=d.get("cap", "butt"),
                   arrow_size=d.get("arrow_size", 1.0))
        m = MeasureNode(d["a"], d["b"], d["offset"], d.get("text", ""), d.get("mode_a", "leg"),
                        d.get("mode_b", "leg"), st, d.get("family", "DejaVu Sans"),
                        d.get("font_size", 14.0), tuple(d.get("text_color", (0, 0, 0, 255))),
                        d.get("bold", False), d.get("italic", False), name,
                        d.get("gap_a", 0.0), d.get("gap_b", 0.0), d.get("linked", True))
        m.arrow_kind = d.get("arrow_kind", "triangle")
        return m


# --------------------------------------------------------------------------------------
def walk(node, include_self=False):
    """Depth-first, back-to-front traversal of all descendants."""
    if include_self:
        yield node
    if node.is_group():
        for c in node.children:
            yield from walk(c, True)


def leaves(node):
    for n in walk(node):
        if not n.is_group():
            yield n


_SKIP_CLONE = ("parent", "children", "subpaths", "style", "clip")


def clone_tree(node, parent=None):
    """Fast structural copy of a node and its subtree (keeps ids, drops caches)."""
    c = node.__class__.__new__(node.__class__)
    d = c.__dict__
    for k, v in node.__dict__.items():
        if k in _SKIP_CLONE or k.startswith("_c_"):
            continue
        d[k] = v
    c.parent = parent
    c.clip = [sp.copy() for sp in node.clip] if node.clip else None
    if "style" in node.__dict__:
        c.style = node.style.copy()
    if "subpaths" in node.__dict__:
        c.subpaths = [sp.copy() for sp in node.subpaths]
    if node.is_group():
        c.children = [clone_tree(ch, c) for ch in node.children]
    return c


def fresh_copy(node):
    """Copy of a node (and subtree) with brand-new ids and no parent."""
    c = clone_tree(node, None)
    for n in walk(c, True):
        n.id = next(_ids)
    return c


def common_ancestors_pruned(nodes):
    """Drop nodes whose ancestor is also in the list."""
    ids = {id(n) for n in nodes}
    res = []
    for n in nodes:
        if not any(id(a) in ids for a in n.ancestors()):
            res.append(n)
    return res


class Document(QObject):
    structureChanged = Signal()
    contentChanged = Signal()
    selectionChanged = Signal()
    restored = Signal()
    metaChanged = Signal()
    sheetChanged = Signal()
    entered = Signal(object)       # a compound path was opened into a folder of independent paths

    def __init__(self, width=1920.0, height=1080.0, pt_per_unit=0.75):
        super().__init__()
        self.root = Group("root")
        self.selection: list[Node] = []
        self.path = None
        self.modified = False
        self.default_style = Style(fill=None, stroke=(0, 0, 0, 255), width=2.0)
        self.undo_stack = []
        self.redo_stack = []
        self._pending = None
        self._merge = (None, 0.0)
        self._active_id = None
        self._current_id = None
        self._counters = {}
        self.warnings = []
        self.source = None
        self.new_sheet(width=width, height=height, pt_per_unit=pt_per_unit)

    # sheets ----------------------------------------------------------
    def sheets(self):
        return [c for c in self.root.children if isinstance(c, Sheet)]

    def sheet_of(self, node):
        n = node
        while n is not None:
            if isinstance(n, Sheet):
                return n
            n = n.parent
        return None

    def current_sheet(self):
        for c in self.root.children:
            if c.id == self._current_id and isinstance(c, Sheet):
                return c
        sh = self.sheets()
        self._current_id = sh[0].id if sh else None
        return sh[0] if sh else None

    def sheet_at(self, pt):
        p = QPointF(*pt)
        for s in reversed(self.sheets()):
            if s.rect().contains(p):
                return s
        return None

    def sheets_rect(self):
        r = QRectF()
        for s in self.sheets():
            r = s.rect() if r.isNull() else r.united(s.rect())
        return r

    def is_layer(self, node):
        return isinstance(node.parent, Sheet)

    def layer_for_sheet(self, sheet):
        """Where new things go inside ``sheet``: the active container if it lives there, else its top layer."""
        ac = self.find(self._active_id) if self._active_id else None
        if ac is not None and ac.is_group() and ac is not sheet and self.sheet_of(ac) is sheet:
            return ac
        groups = [c for c in sheet.children if c.is_group()]
        if groups:
            return groups[-1]
        layer = Group(self.new_name("Layer"))
        sheet.add(layer)
        return layer

    def set_current_sheet(self, sheet):
        if sheet is None or sheet.id == self._current_id:
            return
        self._current_id = sheet.id
        ac = self.find(self._active_id) if self._active_id else None
        if ac is None or self.sheet_of(ac) is not sheet:
            self._active_id = self.layer_for_sheet(sheet).id
        self.sheetChanged.emit()
        self.selectionChanged.emit()

    def next_sheet_position(self, width, height):
        sh = self.sheets()
        if not sh:
            return 0.0, 0.0
        r = self.sheets_rect()
        return r.right() + 80.0, r.top()

    def new_sheet(self, name=None, width=1920.0, height=1080.0, x=None, y=None, pt_per_unit=0.75,
                  source=None, add_layer=True):
        """Create a blank sheet and append it to the project (no undo step; callers wrap it)."""
        if x is None or y is None:
            x, y = self.next_sheet_position(width, height)
        sheet = Sheet(name or self.new_name("Sheet"), x, y, width, height, pt_per_unit, source)
        if add_layer:
            sheet.add(Group(self.new_name("Layer")))
        self.root.add(sheet)
        self._current_id = sheet.id
        self._active_id = self.layer_for_sheet(sheet).id
        return sheet

    def add_sheet_object(self, sheet, x=None, y=None):
        """Insert a detached Sheet (e.g. from an imported file) at (x, y), moving its content there."""
        if x is None or y is None:
            x, y = self.next_sheet_position(sheet.width, sheet.height)
        dx, dy = x - sheet.x, y - sheet.y
        if dx or dy:
            sheet.transform(affine.translate(dx, dy))
        sheet.x, sheet.y = x, y
        if not sheet.children:
            sheet.add(Group(self.new_name("Layer")))
        self.root.add(sheet)
        return sheet

    def is_pristine(self):
        """True for a brand new, untouched, empty project (so an import can replace it)."""
        sh = self.sheets()
        return (len(sh) == 1 and not self.modified and not self.undo_stack
                and not any(True for _ in leaves(sh[0])))

    def delete_sheet(self, sheet):
        with self.edit(structure=True):
            self.root.children.remove(sheet)
            sheet.parent = None
            if not self.sheets():
                self.new_sheet()
        alive = self.sheets()
        self.selection = [n for n in self.selection if self.sheet_of(n) in alive]
        self._current_id = None
        cur = self.current_sheet()
        self._active_id = self.layer_for_sheet(cur).id
        self.sheetChanged.emit()
        self.selectionChanged.emit()

    def move_sheet(self, sheet, dx, dy):
        sheet.transform(affine.translate(dx, dy))

    def reassign_to_sheets(self, nodes):
        """Nodes dragged so that their centre lies on another sheet become part of that sheet."""
        moved = False
        for n in common_ancestors_pruned(nodes):
            b = n.bounds()
            if b.isNull() and not (b.width() or b.height()):
                continue
            target = self.sheet_at((b.center().x(), b.center().y()))
            if target is None or target is self.sheet_of(n):
                continue
            dest = self.layer_for_sheet(target)
            if n.parent is not None:
                n.parent.children.remove(n)
            n.parent = None
            dest.add(n)
            moved = True
        return moved

    # naming ----------------------------------------------------------
    def new_name(self, base):
        n = self._counters.get(base, 0) + 1
        self._counters[base] = n
        return f"{base} {n}"

    # lookup ----------------------------------------------------------
    def find(self, node_id):
        for n in walk(self.root, True):
            if n.id == node_id:
                return n
        return None

    def all_nodes(self):
        return list(walk(self.root))

    # selection -------------------------------------------------------
    def set_selection(self, nodes, emit=True):
        nodes = [n for n in nodes if n is not None]
        seen = set()
        uniq = []
        for n in nodes:
            if id(n) not in seen:
                seen.add(id(n))
                uniq.append(n)
        changed = [id(n) for n in uniq] != [id(n) for n in self.selection]
        self.selection = uniq
        if uniq:
            sh = self.sheet_of(uniq[0])
            if sh is not None and sh.id != self._current_id:
                self._current_id = sh.id
                if emit:
                    self.sheetChanged.emit()
                changed = True
        if len(uniq) == 1:
            n = uniq[0]
            self._active_id = n.id if n.is_group() else (n.parent.id if n.parent else self._active_id)
        elif uniq:
            parents = {id(n.parent) for n in uniq}
            if len(parents) == 1 and uniq[0].parent is not None:
                self._active_id = uniq[0].parent.id
        if emit and changed:
            self.selectionChanged.emit()

    def toggle_selection(self, node):
        if node in self.selection:
            self.set_selection([n for n in self.selection if n is not node])
        else:
            self.set_selection(self.selection + [node])

    def active_container(self) -> Group:
        g = self.find(self._active_id) if self._active_id else None
        cur = self.current_sheet()
        if g is None or not g.is_group() or (cur is not None and self.sheet_of(g) is not cur):
            g = self.layer_for_sheet(cur) if cur is not None else self.root
        return g

    def set_active_container(self, g):
        if g is not None and g.is_group():
            self._active_id = g.id
            self.selectionChanged.emit()

    # undo ------------------------------------------------------------
    def _snapshot(self):
        return (clone_tree(self.root), [n.id for n in self.selection], self._active_id, self._current_id)

    def _restore(self, snap):
        root, sel_ids, active, current = snap
        self.root = clone_tree(root)
        self._active_id = active
        self._current_id = current
        self.selection = [n for n in (self.find(i) for i in sel_ids) if n is not None]
        self.restored.emit()
        self.structureChanged.emit()
        self.contentChanged.emit()
        self.selectionChanged.emit()
        self.sheetChanged.emit()

    def begin_edit(self, merge_key=None):
        key, t = self._merge
        if merge_key is not None and merge_key == key and time.monotonic() - t < 1.5:
            self._pending = "merge"
            self._merge = (merge_key, time.monotonic())
            return
        self._pending = self._snapshot()
        self._merge = (merge_key, time.monotonic())

    def end_edit(self, changed=True, structure=False):
        pend, self._pending = self._pending, None
        if pend is None:
            return
        if not changed:
            return
        if pend != "merge":
            self.undo_stack.append(pend)
            if len(self.undo_stack) > 60:
                self.undo_stack.pop(0)
            self.redo_stack.clear()
        self.modified = True
        if structure:
            self.structureChanged.emit()
        self.contentChanged.emit()
        self.metaChanged.emit()

    def cancel_edit(self):
        self._pending = None

    @contextmanager
    def edit(self, structure=False, merge_key=None):
        self.begin_edit(merge_key)
        try:
            yield
        except Exception:
            self.cancel_edit()
            raise
        self.end_edit(True, structure)

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())
        self.modified = True
        self._merge = (None, 0.0)
        self.metaChanged.emit()

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())
        self.modified = True
        self._merge = (None, 0.0)
        self.metaChanged.emit()

    # structure ops ---------------------------------------------------
    def add_node(self, node, parent=None, index=None):
        parent = parent or self.active_container()
        if not node.name:
            node.name = self.new_name(node.kind.capitalize())
        parent.add(node, index)
        return node

    def delete(self, nodes):
        nodes = common_ancestors_pruned(nodes)
        with self.edit(structure=True):
            for n in nodes:
                if n.parent:
                    n.parent.children.remove(n)
                    n.parent = None
            self.selection = [n for n in self.selection if n.parent is not None]
        self.selectionChanged.emit()

    def duplicate(self, nodes, offset=(0.0, 0.0)):
        nodes = common_ancestors_pruned(nodes)
        out = []
        with self.edit(structure=True):
            for n in nodes:
                c = fresh_copy(n)
                if offset != (0.0, 0.0):
                    c.transform(affine.translate(*offset))
                c.name = n.name + " copy" if n.is_group() else n.name
                p = n.parent
                p.add(c, p.children.index(n) + 1)
                out.append(c)
        self.set_selection(out)
        return out

    def group(self, nodes, name=None):
        nodes = common_ancestors_pruned(nodes)
        if not nodes:
            return None
        nodes.sort(key=lambda n: self._z_key(n))
        ref = nodes[-1]
        parent = ref.parent
        with self.edit(structure=True):
            g = Group(name or self.new_name("Folder"))
            ref_idx = parent.children.index(ref)
            removed_before = sum(1 for n in nodes if n.parent is parent and parent.children.index(n) < ref_idx)
            for n in nodes:
                n.parent.children.remove(n)
                n.parent = None
            parent.add(g, ref_idx - removed_before)
            for n in nodes:
                g.add(n)
        self.set_selection([g])
        return g

    def ungroup(self, groups):
        out = []
        with self.edit(structure=True):
            for g in groups:
                if not g.is_group() or g.parent is None:
                    continue
                p = g.parent
                idx = p.children.index(g)
                kids = list(g.children)
                p.children.remove(g)
                g.parent = None
                for k in kids:
                    k.parent = None
                    if g.clip and not k.clip:
                        k.clip = copy.deepcopy(g.clip)
                    if g.opacity < 1.0:
                        k.opacity *= g.opacity
                    p.add(k, idx)
                    idx += 1
                    out.append(k)
        self.set_selection(out)

    def _z_key(self, node):
        key = []
        n = node
        while n.parent is not None:
            key.append(n.parent.children.index(n))
            n = n.parent
        return list(reversed(key))

    def move_nodes(self, nodes, new_parent, index):
        """Move nodes (kept in their current z order) into new_parent at ``index``
        (index refers to new_parent.children before removal of the moved nodes)."""
        nodes = common_ancestors_pruned(nodes)
        for n in nodes:
            if n is new_parent or new_parent in walk(n, False):
                return False
        nodes.sort(key=lambda n: self._z_key(n))
        with self.edit(structure=True):
            before = new_parent.children[:index]
            removed_before = sum(1 for n in nodes if n.parent is new_parent and n in before)
            for n in nodes:
                n.parent.children.remove(n)
                n.parent = None
            idx = index - removed_before
            for n in nodes:
                new_parent.add(n, idx)
                idx += 1
        return True

    def arrange(self, nodes, how):
        """how: 'front', 'back', 'forward', 'backward'."""
        nodes = common_ancestors_pruned(nodes)
        if not nodes:
            return
        with self.edit(structure=True):
            by_parent = {}
            for n in nodes:
                by_parent.setdefault(id(n.parent), (n.parent, []))[1].append(n)
            for parent, ns in by_parent.values():
                ch = parent.children
                sel = [c for c in ch if c in ns]
                if how == "front":
                    rest = [c for c in ch if c not in ns]
                    parent.children = rest + sel
                elif how == "back":
                    rest = [c for c in ch if c not in ns]
                    parent.children = sel + rest
                elif how == "forward":
                    for c in reversed(sel):
                        i = ch.index(c)
                        if i < len(ch) - 1 and ch[i + 1] not in sel:
                            ch[i], ch[i + 1] = ch[i + 1], ch[i]
                elif how == "backward":
                    for c in sel:
                        i = ch.index(c)
                        if i > 0 and ch[i - 1] not in sel:
                            ch[i], ch[i - 1] = ch[i - 1], ch[i]

    def new_folder(self, parent=None, name=None, as_layer=False):
        with self.edit(structure=True):
            g = Group(name or self.new_name("Layer" if as_layer else "Folder"))
            if as_layer:
                self.current_sheet().add(g)
            else:
                (parent or self.active_container()).add(g)
        self.set_selection([g])
        return g

    def combine(self, nodes):
        """Merge several paths into one compound path (each shape stays a sub-path; holes work)."""
        paths = [l for n in nodes for l in (leaves(n) if n.is_group() else [n]) if l.kind == "path"]
        if len(paths) < 2:
            return None
        paths.sort(key=lambda n: self._z_key(n))
        top = paths[-1]
        parent = top.parent
        with self.edit(structure=True):
            ref_idx = parent.children.index(top)
            removed_before = sum(1 for p in paths if p.parent is parent and parent.children.index(p) < ref_idx)
            subs = []
            for p in paths:
                subs.extend(sp.copy() for sp in p.subpaths)
            new = PathNode(subs, top.style.copy(), self.new_name("Path"))
            new.style.fill_rule = "evenodd"
            new.opacity = top.opacity
            for p in paths:
                p.parent.children.remove(p)
                p.parent = None
            parent.add(new, ref_idx - removed_before)
        self.set_selection([new])
        return new

    def break_apart(self, nodes):
        """Split compound paths into one path per sub-path."""
        paths = [l for n in nodes for l in (leaves(n) if n.is_group() else [n])
                 if l.kind == "path" and len(l.subpaths) > 1]
        if not paths:
            return []
        out = []
        with self.edit(structure=True):
            for p in paths:
                parent = p.parent
                idx = parent.children.index(p)
                parent.children.remove(p)
                p.parent = None
                for k, sp in enumerate(p.subpaths):
                    piece = PathNode([sp.copy()], p.style.copy(), self.new_name("Path"))
                    piece.opacity = p.opacity
                    piece.clip = [c.copy() for c in p.clip] if p.clip else None
                    parent.add(piece, idx + k)
                    out.append(piece)
        self.set_selection(out)
        return out

    def enter_compound(self, path):
        """Open a compound path: it becomes a folder holding one independent path per sub-path, each
        with its own fill and stroke. Returns the folder."""
        if path.kind != "path" or len(path.subpaths) < 2 or path.parent is None:
            return None
        parent = path.parent
        idx = parent.children.index(path)
        grp = Group(path.name or "Compound")
        grp.opacity = path.opacity
        with self.edit(structure=True):
            parent.children.remove(path)
            path.parent = None
            parent.add(grp, idx)
            for sp in path.subpaths:
                piece = PathNode([sp.copy()], path.style.copy(), self.new_name("Path"))
                piece.clip = [c.copy() for c in path.clip] if path.clip else None
                grp.add(piece)
        self.set_selection(list(grp.children[:1]))
        self.entered.emit(grp)
        return grp

    # style ------------------------------------------------------------
    def style_targets(self, nodes):
        out = []
        for n in nodes:
            if n.is_group():
                out.extend(x for x in leaves(n))
            else:
                out.append(n)
        return out

    def apply_style(self, nodes, merge_key=None, **kv):
        """Set style attributes on nodes (recursing into groups). Special keys for
        text/measure are handled here too."""
        targets = self.style_targets(nodes)
        if not targets:
            return
        with self.edit(merge_key=merge_key):
            for n in targets:
                for k, v in kv.items():
                    if k == "opacity":
                        n.opacity = v
                    elif hasattr(n, "style") and k in n.style.__dict__:
                        setattr(n.style, k, v if not isinstance(v, list) else list(v))
                    elif k in ("family", "bold", "italic", "text_color", "mode_a", "mode_b",
                               "arrow_kind", "anchor") and hasattr(n, k):
                        setattr(n, k, v)
                    elif k == "size" and isinstance(n, TextNode):
                        n.size = v
                    elif k == "size" and isinstance(n, MeasureNode):
                        n.font_size = v
                    elif k == "text_fill" and isinstance(n, TextNode):
                        n.style.fill = v
                n.touch()

    def bounds_of(self, nodes):
        r = QRectF()
        first = True
        for n in nodes:
            b = n.bounds()
            if first:
                r, first = QRectF(b), False
            else:
                r = r.united(b)
        return r
