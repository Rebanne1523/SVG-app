"""Cached, time-sliced rendering of the document for the canvas.

Painting every vector on every mouse move is what makes a heavy drawing unusable, so the scene is
rendered once into a bitmap (a bit larger than the viewport so small pans cost nothing) and the
canvas only blits it. Big documents are drawn in slices across event-loop turns: the UI stays
responsive, and while a new picture is being prepared the previous one is shown, scaled/shifted to
the new view.
"""
from __future__ import annotations

import os
import sys
from math import ceil
from time import perf_counter

from PySide6.QtCore import QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap, QTransform

from .render import iter_render_document

PROFILE = bool(os.environ.get("VF_PROFILE"))     # VF_PROFILE=1 prints what every re-render costs (stderr)
ENABLED = not os.environ.get("VF_NO_CACHE")      # VF_NO_CACHE=1 paints every frame directly (debugging)
LIGHT_MS = 8.0          # a scene that renders faster than this is drawn synchronously
SLICE_MS = 9.0          # time budget per event-loop turn for a heavy scene
REFINE_MS = 180         # after this long without panning, redraw a heavy scene at the exact position
DEBOUNCE_MS = 25        # wait this long for the view to settle before re-rendering a heavy scene
MARGIN = 0.2            # extra area rendered around the viewport (fraction of width / height)
MIN_PX = 0.4            # vectors smaller than this many screen pixels are not drawn
TINY_PX = 1.5           # vectors smaller than this are drawn as a flat rectangle of their colour


class _Job:
    __slots__ = ("pix", "painter", "gen", "rect", "zoom", "origin", "key", "dpr", "size", "spent", "slices", "slow",
                 "leaves", "wall")


class SceneCache(QObject):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.pix = None
        self.r_rect = None          # area (view coordinates at render time) the bitmap covers
        self.r_zoom = 1.0
        self.r_origin = None
        self.r_key = None
        self.r_size = None
        self.r_dpr = 1.0
        self.job = None
        self.render_ms = 0.0        # duration of the last complete render (0 = not measured yet)
        self._sig = None
        self._req = None
        self._tick = QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self._on_tick)
        self._exact_now = False
        self._refine = QTimer(self)
        self._refine.setSingleShot(True)
        self._refine.timeout.connect(self._on_refine)
        self._defer = QTimer(self)
        self._defer.setSingleShot(True)
        self._defer.timeout.connect(self._on_defer)

    # ------------------------------------------------------------ public
    def invalidate(self):
        self._cancel()
        self.pix = None
        self.r_key = None

    def reset_stats(self):
        """Forget how long a render takes (a different document was loaded)."""
        self.render_ms = 0.0

    def adopt(self, other, key):
        """Become a copy of ``other``'s finished picture (pixmaps are shared copy-on-write)."""
        self._cancel()
        self.pix, self.r_rect, self.r_zoom = other.pix.copy(), other.r_rect, other.r_zoom
        self.r_origin, self.r_size, self.r_dpr = other.r_origin, other.r_size, other.r_dpr
        self.r_key = key
        self.render_ms = other.render_ms

    def fresh_for(self, key):
        return self.pix is not None and self.job is None and self.r_key == key

    def punch(self, region, key, skip=None, only=None):
        """Repaint just ``region`` (document coordinates) of the finished picture, leaving the rest
        untouched, and declare the picture valid for ``key``. Much cheaper than a full render when
        a few vectors changed or are being picked up. Returns False if there is no picture to patch."""
        c = self.canvas
        if self.pix is None or self.job is not None:
            return False
        z0 = self.r_zoom
        o0 = self.r_origin
        vt = QTransform(z0, 0, 0, z0, o0.x(), o0.y())
        vis = vt.inverted()[0].mapRect(self.r_rect)
        r = region.intersected(vis)
        painter = QPainter(self.pix)
        painter.translate(-self.r_rect.x(), -self.r_rect.y())
        painter.setTransform(vt, True)
        if not r.isEmpty():
            painter.setClipRect(r)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(r, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            for _ in iter_render_document(painter, c.doc, skip, r, MIN_PX / z0, only, TINY_PX / z0):
                pass
        painter.end()
        self.r_key = key
        return True

    def prime(self, key, skip=None, only=None):
        """Render the picture for the current view completely, right now (used when a drag starts)."""
        c = self.canvas
        self._cancel()
        self._req = (key, (c.width(), c.height()), c.devicePixelRatioF(), skip, only)
        self._start()
        self._advance(None)

    def shows(self, key):
        return self.pix is not None and self.r_key == key and self.job is None

    def busy(self):
        return self.job is not None or self._defer.isActive()

    def paint(self, p, key, skip=None, only=None, matrix=None):
        """Draw the scene (in view coordinates) on ``p``. ``key`` identifies the document state."""
        c = self.canvas
        size = (c.width(), c.height())
        dpr = c.devicePixelRatioF()
        if not self._valid(key, size, dpr):
            self._request(key, size, dpr, skip, only)
        if self.pix is not None:
            self._blit(p, matrix)
        elif self.job is not None:
            j = self.job
            p.save()
            if matrix is not None:
                p.setTransform(matrix)
            p.drawPixmap(j.rect.topLeft(), j.pix)
            p.restore()

    # ------------------------------------------------------------ cache state
    def _valid(self, key, size, dpr):
        if self.pix is None or key != self.r_key or size != self.r_size or dpr != self.r_dpr:
            return False
        c = self.canvas
        if abs(c.zoom - self.r_zoom) > 1e-12:
            return False
        o = c.origin
        dx, dy = self.r_origin.x() - o.x(), self.r_origin.y() - o.y()
        if not self.r_rect.contains(QRectF(0, 0, size[0], size[1]).translated(dx, dy)):
            return False
        ax, ay = dx * dpr, dy * dpr
        if abs(ax - round(ax)) > 1e-6 or abs(ay - round(ay)) > 1e-6:
            # panned by a fraction of a device pixel: blitting would be off by up to half a pixel. A cheap
            # scene is simply redrawn exactly; a heavy one keeps the shifted picture while the user is
            # still moving and refines it once the view has settled.
            if self.render_ms < LIGHT_MS or self._exact_now:
                return False
            self._refine.start(REFINE_MS)
        return True

    def _blit(self, p, matrix):
        c = self.canvas
        s = c.zoom / self.r_zoom
        o, o0 = c.origin, self.r_origin
        p.save()
        if matrix is not None:
            p.setTransform(matrix)
        p.translate(o.x() - o0.x() * s, o.y() - o0.y() * s)
        if abs(s - 1.0) > 1e-12:
            p.scale(s, s)
        if abs(s - 1.0) > 1e-12 or matrix is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(self.r_rect.topLeft(), self.pix)
        p.restore()

    # ------------------------------------------------------------ requests
    def _request(self, key, size, dpr, skip, only):
        c = self.canvas
        o = c.origin
        sig = (key, size, dpr, c.zoom, o.x(), o.y())
        self._req = (key, size, dpr, skip, only)
        if self.job is not None:
            j = self.job
            if j.key == key and j.size == size and j.dpr == dpr and abs(j.zoom - c.zoom) < 1e-12 and \
                    j.rect.contains(QRectF(0, 0, size[0], size[1]).translated(j.origin.x() - o.x(), j.origin.y() - o.y())):
                return                      # the render in progress will cover this view
            self._cancel()
        if self.pix is None or self.render_ms < LIGHT_MS:
            # first picture, or a cheap scene: draw it right now (anything that turns out slower than
            # a couple of frames carries on in slices, so a mis-estimate can't freeze the window)
            self._start()
            self._advance(SLICE_MS * 2 if self.render_ms < LIGHT_MS else SLICE_MS)
            return
        if sig != self._sig:
            self._sig = sig
            self._defer.start(DEBOUNCE_MS)  # the view is still changing: keep showing the old picture

    def _on_refine(self):
        self._exact_now = True
        self.canvas.update()

    def _on_defer(self):
        if self.job is None and self._req is not None:
            self._start()
            self._advance(SLICE_MS)
            self.canvas.update()

    def _start(self):
        c = self.canvas
        key, size, dpr, skip, only = self._req
        w, h = size
        mx, my = w * MARGIN, h * MARGIN
        rect = QRectF(-mx, -my, w + 2 * mx, h + 2 * my)
        pix = QPixmap(max(1, ceil(rect.width() * dpr)), max(1, ceil(rect.height() * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.translate(-rect.x(), -rect.y())
        painter.setTransform(QTransform(c.zoom, 0, 0, c.zoom, c.origin.x(), c.origin.y()), True)
        z = c.zoom
        a, b = c.to_doc((rect.left(), rect.top())), c.to_doc((rect.right(), rect.bottom()))
        cull = QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1])
        j = _Job()
        j.pix, j.painter, j.rect, j.zoom, j.origin = pix, painter, rect, z, c.origin
        j.key, j.dpr, j.size, j.spent = key, dpr, size, 0.0
        j.slices, j.slow, j.leaves, j.wall = 0, [], 0, perf_counter()
        j.gen = iter_render_document(painter, c.doc, skip, cull, MIN_PX / z, only, TINY_PX / z)
        self.job = j

    def _cancel(self):
        self._defer.stop()
        self._refine.stop()
        self._tick.stop()
        j, self.job = self.job, None
        if j is not None:
            j.gen.close()
            j.painter.end()

    def _advance(self, budget_ms):
        """Run the current job for ``budget_ms`` (None = to completion). True when it finished."""
        j = self.job
        if j is None:
            return True
        t0 = perf_counter()
        n = 0
        done = True
        if PROFILE:
            t1 = t0
            j.slices += 1
        for node in j.gen:
            n += 1
            if PROFILE:
                t2 = perf_counter()
                j.leaves += 1
                if node is not None and t2 - t1 > 0.004:
                    j.slow.append(((t2 - t1) * 1000.0, node))
                t1 = t2
            if budget_ms is not None and (n & 15) == 0 and (perf_counter() - t0) * 1000.0 > budget_ms:
                done = False
                break
        j.spent += perf_counter() - t0
        if done:
            j.painter.end()
            self.pix, self.r_rect, self.r_zoom = j.pix, j.rect, j.zoom
            self.r_origin, self.r_key, self.r_size, self.r_dpr = j.origin, j.key, j.size, j.dpr
            ms = j.spent * 1000.0
            if PROFILE:
                _report(self.canvas, j, ms)
            self.render_ms = ms if self.render_ms == 0.0 else 0.5 * (self.render_ms + ms)
            self.render_ms = max(self.render_ms, 0.01)
            self.job = None
            self._sig = None
            self._exact_now = False
        else:
            self._tick.start(0)
        return done

    def _on_tick(self):
        if self.job is None:
            return
        finished = self._advance(SLICE_MS)
        if finished or self.pix is None:
            self.canvas.update()


def _report(canvas, j, ms):
    """One line per finished re-render, then the single objects that took 4 ms or more."""
    wall = (perf_counter() - j.wall) * 1000.0
    print(f"[vf] render {ms:6.1f} ms work, {wall:6.1f} ms wall, {j.slices} slices, {j.leaves} objects, "
          f"zoom {j.zoom:.3g}, view {j.size[0]}x{j.size[1]} dpr {j.dpr:g}", file=sys.stderr, flush=True)
    for t, node in sorted(j.slow, key=lambda x: -x[0])[:5]:
        segs = sum(len(sp.anchors) for sp in getattr(node, "subpaths", ()))
        print(f"[vf]    slow object: {t:6.1f} ms  {node.kind} {getattr(node, 'name', '') or ''!r}"
              f"  subpaths={len(getattr(node, 'subpaths', ()))} anchors={segs}", file=sys.stderr, flush=True)
