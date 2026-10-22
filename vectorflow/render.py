"""Painting of the document model with QPainter (canvas, PNG and PDF export)."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen

from .atable import anchor_table
from .geometry import bez_tangent, dist, flatten_cubic
from .model import arrow_length, arrow_path, box4, qcolor


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


_BRUSHES: dict = {}


def brush_of(c):
    c = tuple(c)
    b = _BRUSHES.get(c)
    if b is None:
        if len(_BRUSHES) > 4096:
            _BRUSHES.clear()
        b = _BRUSHES[c] = QBrush(qcolor(c))
    return b


def _culled(node, cull, min_size):
    """True when a leaf lies outside ``cull`` or is too small to be seen (``min_size`` in document units)."""
    pad = 2.0
    st = getattr(node, "style", None)
    if st is not None:
        pad += st.width * 2 + arrow_length(st)
    kind = node.kind
    if kind == "measure":
        pad += 20.0
    l, t, r, b = box4(node)
    if cull is not None and (r + pad < cull.left() or l - pad > cull.right() or
                             b + pad < cull.top() or t - pad > cull.bottom()):
        return True
    if min_size > 0.0 and kind != "measure" and kind != "image":
        w = st.width if st is not None and st.stroke else 0.0
        if r - l + w < min_size and b - t + w < min_size:
            return True
    return False


def _draw_tiny(painter, node, opacity):
    """A vector smaller than a couple of pixels: a flat rectangle of its colour looks the same and is
    several times cheaper than anti-aliased path painting."""
    st = node.style
    col = st.fill if st.fill else (st.stroke if st.stroke and st.width > 0 else None)
    if col is None:
        return
    l, t, r, b = box4(node)
    painter.setOpacity(opacity)
    painter.fillRect(QRectF(l, t, max(r - l, 0.0), max(b - t, 0.0)), brush_of(col))


def view_path(node, cull):
    """Seen from close up, a path made of many sub-paths only needs the ones that can reach the visible
    area: painting (and stroking) the whole thing for a few points on screen is what makes zooming into a
    big imported drawing slow. The result is identical for fill and stroke."""
    path = node.qpath()
    n = len(node.subpaths)
    if cull is None or n < 8 or path.elementCount() < 1500:
        return path
    key = (cull.left(), cull.top(), cull.right(), cull.bottom())
    d = node.__dict__
    c = d.get("_c_vp")
    if c is not None and c[0] == key:
        return c[1]
    st = node.style
    pad = st.width * 4.0 + 2.0
    if not st.fill and not st.dash:
        out = _visible_segments(node, key, pad)
    else:
        boxes = d.get("_c_spb")
        sps = node._sub_paths()
        if boxes is None:
            boxes = d["_c_spb"] = np.array([(r.left(), r.top(), r.right(), r.bottom())
                                            for r in (q.boundingRect() for q in sps)], dtype=float).reshape(-1, 4)
        mask = ((boxes[:, 2] + pad >= key[0]) & (boxes[:, 0] - pad <= key[2]) &
                (boxes[:, 3] + pad >= key[1]) & (boxes[:, 1] - pad <= key[3]))
        if mask.all():
            out = path
        else:
            out = QPainterPath()
            for i in np.flatnonzero(mask):
                out.addPath(sps[i])
            out.setFillRule(path.fillRule())
    d["_c_vp"] = (key, out)
    return out


SEG_CHUNK = 256         # segments per cached block of a big outline


def _segment_chunks(node):
    """A big outline cut into blocks of consecutive segments, each with a bounding box. A block's path is
    built the first time it is on screen and kept, so painting a view only adds the blocks that reach it
    instead of walking every segment in Python. Cached on the node (dropped on touch())."""
    d = node.__dict__
    c = d.get("_c_seg")
    if c is not None:
        return c
    t = anchor_table(node)
    k = np.flatnonzero(t.nxt >= 0)
    nx = t.nxt[k]
    xs = np.stack([t.X[k], t.OX[k], t.IX[nx], t.X[nx]])
    ys = np.stack([t.Y[k], t.OY[k], t.IY[nx], t.Y[nx]])
    starts = np.arange(0, len(k), SEG_CHUNK)
    if not len(starts):
        c = d["_c_seg"] = (np.zeros((0, 4)), [], np.zeros(0, bool), None)
        return c
    boxes = np.stack([np.minimum.reduceat(xs.min(0), starts), np.minimum.reduceat(ys.min(0), starts),
                      np.maximum.reduceat(xs.max(0), starts), np.maximum.reduceat(ys.max(0), starts)], axis=1)
    joined = np.zeros(len(starts), bool)        # block continues the previous one: keep the line join
    joined[1:] = k[starts[1:]] == nx[starts[1:] - 1]
    c = d["_c_seg"] = (boxes, [None] * len(starts), joined, (t, k, nx))
    return c


def _chunk_path(chunks, i):
    boxes, paths, joined, (t, k, nx) = chunks
    q = paths[i]
    if q is not None:
        return q
    q = QPainterPath()
    cur = -1
    X, Y, OX, OY, IX, IY = t.X, t.Y, t.OX, t.OY, t.IX, t.IY
    for j in range(i * SEG_CHUNK, min((i + 1) * SEG_CHUNK, len(k))):
        a, b = int(k[j]), int(nx[j])
        if cur != a:
            q.moveTo(float(X[a]), float(Y[a]))
        if OX[a] == X[a] and OY[a] == Y[a] and IX[b] == X[b] and IY[b] == Y[b]:
            q.lineTo(float(X[b]), float(Y[b]))
        else:
            q.cubicTo(float(OX[a]), float(OY[a]), float(IX[b]), float(IY[b]), float(X[b]), float(Y[b]))
        cur = b
    paths[i] = q
    return q


def _visible_segments(node, key, pad):
    """Only the segments of an outline (no fill, solid line) that can reach the visible area, so a big
    path seen from close up costs what is on screen. Cut ends lie outside the view."""
    chunks = _segment_chunks(node)
    boxes, _, joined, _ = chunks
    mask = ((boxes[:, 2] + pad >= key[0]) & (boxes[:, 0] - pad <= key[2]) &
            (boxes[:, 3] + pad >= key[1]) & (boxes[:, 1] - pad <= key[3]))
    if mask.all():
        return node.qpath()
    out = QPainterPath()
    last = -2
    for i in np.flatnonzero(mask):
        i = int(i)
        q = _chunk_path(chunks, i)
        if i == last + 1 and joined[i]:
            out.connectPath(q)
        else:
            out.addPath(q)
        last = i
    return out


def _draw_leaf(painter, node, opacity, cull=None):
    kind = node.kind
    if kind == "path":
        painter.setOpacity(opacity)
        st = node.style
        path = view_path(node, cull) if not has_arrows(node) else node.qpath()
        if st.fill:
            painter.fillPath(path, brush_of(st.fill))
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
            painter.fillPath(path, brush_of(st.fill))
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
        painter.fillPath(node.text_path(), brush_of(node.text_color))


def draw_node(painter: QPainter, node, parent_opacity=1.0, skip=None, cull=None, min_size=0.0):
    if not node.visible:
        return
    if skip and node in skip:
        return
    leaf = not node.is_group()
    if leaf and (cull is not None or min_size > 0.0) and _culled(node, cull, min_size):
        return
    opacity = parent_opacity * node.opacity
    clip = node.clip_path() if node.clip else None
    if clip is not None:
        painter.save()
        painter.setClipPath(clip, Qt.IntersectClip)
    if not leaf:
        for c in node.children:
            draw_node(painter, c, opacity, skip, cull, min_size)
    else:
        _draw_leaf(painter, node, opacity, cull)
    if clip is not None:
        painter.restore()
    painter.setOpacity(parent_opacity)


def iter_draw_node(painter: QPainter, node, parent_opacity=1.0, skip=None, cull=None, min_size=0.0, only=None,
                   tiny=0.0):
    """Generator twin of :func:`draw_node`: yields after every painted leaf so the caller can
    time-slice a big drawing across event-loop turns. ``only`` (a set of nodes) restricts the
    painting to those leaves."""
    if not node.visible:
        return
    if skip and node in skip:
        return
    leaf = not node.is_group()
    if leaf:
        if only is not None and node not in only:
            return
        if (cull is not None or min_size > 0.0) and _culled(node, cull, min_size):
            yield          # skipped, but let the caller check its time budget (building bounds can be slow)
            return
    opacity = parent_opacity * node.opacity
    clip = node.clip_path() if node.clip else None
    if clip is not None:
        painter.save()
        painter.setClipPath(clip, Qt.IntersectClip)
    if not leaf:
        for c in node.children:
            yield from iter_draw_node(painter, c, opacity, skip, cull, min_size, only, tiny)
    else:
        if tiny > 0.0 and node.kind == "path" and not node.clip and not has_arrows(node):
            l, t, r, b = box4(node)
            if r - l < tiny and b - t < tiny:
                _draw_tiny(painter, node, opacity)
                yield node
                painter.setOpacity(parent_opacity)
                return
        _draw_leaf(painter, node, opacity, cull)
        yield node
    if clip is not None:
        painter.restore()
    painter.setOpacity(parent_opacity)


def render_document(painter: QPainter, doc, skip=None, cull=None, min_size=0.0):
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    for c in doc.root.children:
        draw_node(painter, c, 1.0, skip, cull, min_size)
    painter.setOpacity(1.0)


def iter_render_document(painter: QPainter, doc, skip=None, cull=None, min_size=0.0, only=None, tiny=0.0):
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    for c in doc.root.children:
        yield from iter_draw_node(painter, c, 1.0, skip, cull, min_size, only, tiny)
    painter.setOpacity(1.0)


def render_sheet(painter: QPainter, sheet):
    """Paint one sheet with its top-left corner at the painter origin, clipped to the page."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.translate(-sheet.x, -sheet.y)
    painter.setClipRect(sheet.rect())
    draw_node(painter, sheet)
    painter.restore()
    painter.setOpacity(1.0)


def sheet_image(sheet, scale=1.0, transparent=False, bg=None):
    from PySide6.QtGui import QImage
    w, h = max(1, int(round(sheet.width * scale))), max(1, int(round(sheet.height * scale)))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(*bg) if bg else (Qt.transparent if transparent else Qt.white))
    p = QPainter(img)
    p.scale(scale, scale)
    render_sheet(p, sheet)
    p.end()
    return img


def sheet_thumbnail(sheet, max_w=220, max_h=160):
    s = min(max_w / max(sheet.width, 1.0), max_h / max(sheet.height, 1.0))
    return sheet_image(sheet, s)


def export_sheet_png(sheet, path, scale=1.0, transparent=True, bg=None):
    return sheet_image(sheet, scale, transparent, bg).save(path)


def export_sheets_pdf(sheets, path, bg=None):
    """Vector PDF with one page per sheet; each page keeps its own size (1 unit = pt_per_unit points)."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageSize, QPdfWriter
    w = QPdfWriter(path)
    w.setResolution(72)
    painter = None
    for sh in sheets:
        w.setPageSize(QPageSize(QSizeF(sh.width * sh.pt_per_unit, sh.height * sh.pt_per_unit), QPageSize.Point))
        w.setPageMargins(QMarginsF(0, 0, 0, 0))
        if painter is None:
            painter = QPainter(w)
        else:
            w.newPage()
        painter.save()
        painter.scale(sh.pt_per_unit, sh.pt_per_unit)
        if bg:
            painter.fillRect(QRectF(0, 0, sh.width, sh.height), QColor(*bg))
        render_sheet(painter, sh)
        painter.restore()
    if painter is not None:
        painter.end()
    return True
