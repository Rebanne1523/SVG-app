"""Geometry helpers: beziers, flattening, simplification, arcs."""
from __future__ import annotations

import math

KAPPA = 0.5522847498307936


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def bez(p0, c1, c2, p1, t):
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    d = t * t * t
    return (
        a * p0[0] + b * c1[0] + c * c2[0] + d * p1[0],
        a * p0[1] + b * c1[1] + c * c2[1] + d * p1[1],
    )


def bez_tangent(p0, c1, c2, p1, t):
    mt = 1.0 - t
    dx = 3 * mt * mt * (c1[0] - p0[0]) + 6 * mt * t * (c2[0] - c1[0]) + 3 * t * t * (p1[0] - c2[0])
    dy = 3 * mt * mt * (c1[1] - p0[1]) + 6 * mt * t * (c2[1] - c1[1]) + 3 * t * t * (p1[1] - c2[1])
    return (dx, dy)


def split_cubic(p0, c1, c2, p1, t):
    a = lerp(p0, c1, t)
    b = lerp(c1, c2, t)
    c = lerp(c2, p1, t)
    d = lerp(a, b, t)
    e = lerp(b, c, t)
    f = lerp(d, e, t)
    return (p0, a, d, f), (f, e, c, p1)


def is_line(p0, c1, c2, p1, eps=1e-9):
    return dist(p0, c1) < eps and dist(c2, p1) < eps


def flatten_cubic(p0, c1, c2, p1, per_px=0.35):
    """Return points (excluding p0, including p1) approximating the cubic."""
    if is_line(p0, c1, c2, p1):
        return [p1]
    length = dist(p0, c1) + dist(c1, c2) + dist(c2, p1)
    n = int(max(4, min(96, math.sqrt(length) * 1.6 * (per_px / 0.35))))
    return [bez(p0, c1, c2, p1, i / n) for i in range(1, n + 1)]


def rdp(points, eps):
    """Ramer-Douglas-Peucker polyline simplification."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        ax, ay = points[lo]
        bx, by = points[hi]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(lo + 1, hi):
            px, py = points[i]
            if norm < 1e-12:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dx * (ay - py) - (ax - px) * dy) / norm
            if d > best:
                best, idx = d, i
        if best > eps and idx >= 0:
            keep[idx] = True
            stack.append((lo, idx))
            stack.append((idx, hi))
    return [p for p, k in zip(points, keep) if k]


def catmull_to_bezier(points, closed=False, tension=1.0):
    """Convert a polyline into a list of (anchor, in_handle, out_handle) with smooth handles."""
    n = len(points)
    out = []
    for i in range(n):
        p = points[i]
        prev = points[i - 1] if i > 0 else (points[-1] if closed else p)
        nxt = points[i + 1] if i < n - 1 else (points[0] if closed else p)
        tx, ty = (nxt[0] - prev[0]) / 6.0 * tension, (nxt[1] - prev[1]) / 6.0 * tension
        ih = (p[0] - tx, p[1] - ty) if (closed or i > 0) else p
        oh = (p[0] + tx, p[1] + ty) if (closed or i < n - 1) else p
        out.append((p, ih, oh))
    return out


def nearest_on_polyline(pts, p, closed=False):
    """Return (distance, point, segment_index, t) of the closest point on a polyline."""
    best = (float("inf"), None, -1, 0.0)
    n = len(pts)
    count = n if closed else n - 1
    for i in range(count):
        a, b = pts[i], pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
        q = (a[0] + dx * t, a[1] + dy * t)
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if d < best[0]:
            best = (d, q, i, t)
    return best


def arc_to_cubics(x1, y1, rx, ry, phi_deg, large, sweep, x2, y2):
    """SVG elliptical arc -> list of cubic segments ((c1), (c2), (end))."""
    if (x1 == x2 and y1 == y2) or rx == 0 or ry == 0:
        return [((x1, y1), (x2, y2), (x2, y2))]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg % 360)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cp * dx + sp * dy
    y1p = -sp * dx + cp * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if bool(large) == bool(sweep):
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2.0
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    nseg = max(1, int(math.ceil(abs(dth) / (math.pi / 2) - 1e-9)))
    delta = dth / nseg
    t = 4.0 / 3.0 * math.tan(delta / 4.0)
    segs = []
    a = th1
    for _ in range(nseg):
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(a + delta), math.sin(a + delta)
        e1 = (ca - t * sa, sa + t * ca)
        e2 = (cb + t * sb, sb - t * cb)
        e3 = (cb, sb)

        def tr(pt):
            x, y = pt[0] * rx, pt[1] * ry
            return (cp * x - sp * y + cx, sp * x + cp * y + cy)

        segs.append((tr(e1), tr(e2), tr(e3)))
        a += delta
    # make the final point exact
    c1, c2, _ = segs[-1]
    segs[-1] = (c1, c2, (x2, y2))
    return segs


def angle_deg(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def constrain_angle(origin, pt, step_deg=45.0):
    """Project ``pt`` onto the nearest ray (multiple of step_deg) from origin."""
    dx, dy = pt[0] - origin[0], pt[1] - origin[1]
    r = math.hypot(dx, dy)
    if r < 1e-9:
        return pt
    a = math.atan2(dy, dx)
    step = math.radians(step_deg)
    a = round(a / step) * step
    return (origin[0] + math.cos(a) * r * 1.0, origin[1] + math.sin(a) * r * 1.0)


def constrain_angle_projected(origin, pt, step_deg=45.0):
    """Like constrain_angle but keeps the projection length (so the cursor feels attached)."""
    dx, dy = pt[0] - origin[0], pt[1] - origin[1]
    if math.hypot(dx, dy) < 1e-9:
        return pt
    a = math.atan2(dy, dx)
    step = math.radians(step_deg)
    ar = round(a / step) * step
    ux, uy = math.cos(ar), math.sin(ar)
    proj = dx * ux + dy * uy
    return (origin[0] + ux * proj, origin[1] + uy * proj)
