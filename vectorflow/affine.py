"""Tiny affine-matrix helpers.

Matrices are tuples ``(a, b, c, d, e, f)`` with SVG semantics::

    x' = a*x + c*y + e
    y' = b*x + d*y + f
"""
from __future__ import annotations

import math

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mul(m1, m2):
    """Return the matrix that applies ``m2`` first and then ``m1``."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def translate(tx, ty=0.0):
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def scale(sx, sy=None):
    if sy is None:
        sy = sx
    return (sx, 0.0, 0.0, sy, 0.0, 0.0)


def rotate(deg, cx=0.0, cy=0.0):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    m = (c, s, -s, c, 0.0, 0.0)
    if cx or cy:
        m = mul(translate(cx, cy), mul(m, translate(-cx, -cy)))
    return m


def skew_x(deg):
    return (1.0, 0.0, math.tan(math.radians(deg)), 1.0, 0.0, 0.0)


def skew_y(deg):
    return (1.0, math.tan(math.radians(deg)), 0.0, 1.0, 0.0, 0.0)


def about(m, cx, cy):
    """Conjugate ``m`` so that it acts around the point (cx, cy)."""
    return mul(translate(cx, cy), mul(m, translate(-cx, -cy)))


def det(m):
    return m[0] * m[3] - m[1] * m[2]


def mean_scale(m):
    return math.sqrt(abs(det(m)))


def rotation_deg(m):
    return math.degrees(math.atan2(m[1], m[0]))


def invert(m):
    d = det(m)
    if abs(d) < 1e-12:
        return None
    a, b, c, dd, e, f = m
    ia, ib, ic, id_ = dd / d, -b / d, -c / d, a / d
    return (ia, ib, ic, id_, -(ia * e + ic * f), -(ib * e + id_ * f))


def is_identity(m):
    return all(abs(x - y) < 1e-12 for x, y in zip(m, IDENTITY))
