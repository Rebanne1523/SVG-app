"""Painting of the document model with QPainter (canvas, PNG and PDF export)."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QPainter, QPainterPath, QPen

from .geometry import bez_tangent, dist, flatten_cubic
from .model import arrow_length, arrow_path, qcolor


def trim_polyline(pts, start_trim, end_trim):
    pts = list(pts)

    def trim_end(points, amount):
        while amount > 1e-9 and len(points) >= 2:
            seg = dist(points[-1], points[-2])
            if seg > amount + 1e-9:
                f = amount / seg
                a, b = points[-2], points[-1]
                points[-1] = (b[0] + (a[0] - b[0]) * f, b[1] + (a[1] - b[1]) * f)
                return points
            amount -= seg
            points.pop()
            if len(points) == 1:
                break
        return points

    if end_trim > 0:
        pts = trim_end(pts, end_trim)
    if start_trim > 0:
        pts.reverse()
        pts = trim_end(pts, start_trim)
        pts.reverse()
    return pts


def subpath_polyline(sp):
    """Flatten an open subpath -> (points, start_dir, end_dir) where dirs are outward unit vectors."""
    a = sp.anchors
    pts = [a[0].p]
    segs = list(sp.segments())
    for _, p0, p1 in segs:
        if not p0.has_out() and not p1.has_in():
            pts.append(p1.p)
        else:
            pts.extend(flatten_cubic(p0.p, p0.hout, p1.hin, p1.p))

    def unit(v):
        l = math.hypot(*v)
        return (v[0] / l, v[1] / l) if l > 1e-12 else (1.0, 0.0)

    # outward tangents
    _, f0, f1 = segs[0]
    if f0.has_out() or f1.has_in():
        t = bez_tangent(f0.p, f0.hout, f1.hin, f1.p, 0.0)
        if math.hypot(*t) < 1e-9:
            t = (f1.x - f0.x, f1.y - f0.y)
    else:
        t = (f1.x - f0.x, f1.y - f0.y)
    start_dir = unit((-t[0], -t[1]))
    _, l0, l1 = segs[-1]
    if l0.has_out() or l1.has_in():
        t = bez_tangent(l0.p, l0.hout, l1.hin, l1.p, 1.0)
        if math.hypot(*t) < 1e-9:
            t = (l1.x - l0.x, l1.y - l0.y)
    else:
        t = (l1.x - l0.x, l1.y - l0.y)
    end_dir = unit(t)
    return pts, start_dir, end_dir


def path_with_arrows(node):
    """Return (stroke QPainterPath, [(arrow QPainterPath, filled)]) for a PathNode with arrows."""
    cached = getattr(node, "_c_arrows", None)
    if cached is not None:
        return cached
    st = node.style
    L = arrow_length(st)
    stroke = QPainterPath()
    arrows = []
    for sp in node.subpaths:
        if len(sp.anchors) < 2 or sp.closed:
            sp.add_to(stroke)
            continue
        pts, sdir, edir = subpath_polyline(sp)
        s_trim = e_trim = 0.0
        if st.arrow_start != "none":
            ap, filled, trim = arrow_path(st.arrow_start, pts[0], sdir, L)
            if ap is not None:
                arrows.append((ap, filled))
                s_trim = trim
        if st.arrow_end != "none":
            ap, filled, trim = arrow_path(st.arrow_end, pts[-1], edir, L)
            if ap is not None:
                arrows.append((ap, filled))
                e_trim = trim
        pts = trim_polyline(pts, s_trim, e_trim)
        if len(pts) >= 2:
            stroke.moveTo(*pts[0])
            for p in pts[1:]:
                stroke.lineTo(*p)
    node._c_arrows = (stroke, arrows)
    return node._c_arrows


def has_arrows(node):
    st = node.style
    return st.arrow_start != "none" or st.arrow_end != "none"


def _draw_arrows(painter, arrows, st):
    if not st.stroke:
        return
    col = qcolor(st.stroke)
    for ap, filled in arrows:
        if filled:
            painter.fillPath(ap, QBrush(col))
        else:
            pen = QPen(col)
            pen.setWidthF(max(st.width, 0.5))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.strokePath(ap, pen)


def draw_node(painter: QPainter, node, parent_opacity=1.0, skip=None, cull=None):
    if not node.visible:
        return
    if skip and node in skip:
        return
    if cull is not None and not node.is_group():
        pad = 2.0
        st = getattr(node, "style", None)
        if st is not None:
            pad += st.width * 2 + arrow_length(st)
        if node.kind == "measure":
            pad += 20.0
        if not cull.intersects(node.bounds().adjusted(-pad, -pad, pad, pad)):
            return
    opacity = parent_opacity * node.opacity
    clip = node.clip_path() if node.clip else None
    if clip is not None:
        painter.save()
        painter.setClipPath(clip, Qt.IntersectClip)
    kind = node.kind
    if kind == "group":
        for c in node.children:
            draw_node(painter, c, opacity, skip, cull)
    elif kind == "path":
        painter.setOpacity(opacity)
        st = node.style
        path = node.qpath()
        if st.fill:
            painter.fillPath(path, QBrush(qcolor(st.fill)))
        if st.stroke and st.width > 0:
            if has_arrows(node):
                stroke, arrows = path_with_arrows(node)
                painter.strokePath(stroke, st.pen())
                _draw_arrows(painter, arrows, st)
            else:
                painter.strokePath(path, st.pen())
    elif kind == "text":
        painter.setOpacity(opacity)
        st = node.style
        path = node.qpath()
        if st.fill:
            painter.fillPath(path, QBrush(qcolor(st.fill)))
        if st.stroke and st.width > 0:
            painter.strokePath(path, st.pen())
    elif kind == "image":
        painter.setOpacity(opacity)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(node.bounds(), node.image())
    elif kind == "measure":
        painter.setOpacity(opacity)
        st = node.style
        line, shapes = node.line_path()
        if st.stroke and st.width > 0:
            painter.strokePath(line, st.pen())
            _draw_arrows(painter, shapes, st)
        painter.fillPath(node.text_path(), QBrush(qcolor(node.text_color)))
    if clip is not None:
        painter.restore()
    painter.setOpacity(parent_opacity)


def render_document(painter: QPainter, doc, skip=None, cull=None):
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    for c in doc.root.children:
        draw_node(painter, c, 1.0, skip, cull)
    painter.setOpacity(1.0)


def export_png(doc, path, scale=1.0, transparent=True):
    from PySide6.QtGui import QImage
    w, h = max(1, int(round(doc.width * scale))), max(1, int(round(doc.height * scale)))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent if transparent else Qt.white)
    p = QPainter(img)
    p.scale(scale, scale)
    render_document(p, doc)
    p.end()
    return img.save(path)


def export_pdf(doc, path):
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageSize, QPdfWriter
    w = QPdfWriter(path)
    w.setResolution(72)
    w.setPageSize(QPageSize(QSizeF(doc.width * 72 / 96, doc.height * 72 / 96), QPageSize.Point))
    w.setPageMargins(QMarginsF(0, 0, 0, 0))
    p = QPainter(w)
    # QPdfWriter at 72 dpi: 1 device unit == 1 pt; document units are px (96 dpi)
    p.scale(72 / 96.0, 72 / 96.0)
    render_document(p, doc)
    p.end()
    return True
