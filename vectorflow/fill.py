"""Smart paint bucket.

Instead of flood-filling pixels of the current view, the fill is computed from the vector
geometry itself (centre lines of every visible path), so it does not depend on zoom or on
what is on top of what. Small gaps in outlines are closed with a tolerance in document units.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, unary_union

from .model import Anchor, PathNode, SubPath
from .snap import polylines_of, visible_leaves


@dataclass
class FillResult:
    polygon: Polygon | None
    error: str | None = None
    closed_gap: bool = False


def collect_lines(doc, exclude=()):
    lines = []
    for n in visible_leaves(doc, exclude):
        if n.kind != "path":
            continue
        for pts, closed in polylines_of(n):
            if len(pts) < 2:
                continue
            pts = list(pts)
            if closed and pts[0] != pts[-1]:
                pts.append(pts[0])
            # drop consecutive duplicates
            clean = [pts[0]]
            for q in pts[1:]:
                if abs(q[0] - clean[-1][0]) > 1e-9 or abs(q[1] - clean[-1][1]) > 1e-9:
                    clean.append(q)
            if len(clean) >= 2:
                lines.append(LineString(clean))
    return lines


def collect_widths(doc, exclude=()):
    """Stroke width of every line collect_lines() returns, in the same order."""
    widths = []
    for n in visible_leaves(doc, exclude):
        if n.kind != "path":
            continue
        w = n.style.width if (n.style.stroke and n.style.width > 0) else 0.0
        for pts, closed in polylines_of(n):
            if len(pts) < 2:
                continue
            pts = list(pts)
            clean = [pts[0]]
            for q in pts[1:] + ([pts[0]] if closed and pts[0] != pts[-1] else []):
                if abs(q[0] - clean[-1][0]) > 1e-9 or abs(q[1] - clean[-1][1]) > 1e-9:
                    clean.append(q)
            if len(clean) >= 2:
                widths.append(w)
    return widths


def _gap_region(lines, union, P, gap, page, widths):
    """Free-space component under P after thickening every outline (by the larger of the gap tolerance
    and its own stroke width, i.e. what looks closed on screen counts as closed)."""
    minx, miny, maxx, maxy = union.bounds
    if page is not None:
        minx, miny = min(minx, 0.0), min(miny, 0.0)
        maxx, maxy = max(maxx, page[0]), max(maxy, page[1])
    m = max(20.0, 0.05 * max(maxx - minx, maxy - miny))
    frame = box(minx - m, miny - m, maxx + m, maxy + m)
    if widths and len(widths) == len(lines):
        parts = [ln.buffer(max(gap, w) / 2.0, cap_style=1, join_style=1, quad_segs=8)
                 for ln, w in zip(lines, widths)]
        barrier = unary_union(parts)
    else:
        barrier = union.buffer(gap / 2.0, cap_style=1, join_style=1, quad_segs=8)
    if barrier.contains(P):
        return None, "You clicked on a line (or a gap narrower than the tolerance). Click inside the area."
    space = frame.difference(barrier)
    comps = list(space.geoms) if hasattr(space, "geoms") else [space]
    comp = next((g for g in comps if g.contains(P)), None)
    if comp is None:
        return None, "Could not find an area at that point."
    if comp.exterior.intersects(frame.exterior):
        return None, ("The area is open: there is a gap larger than the tolerance. "
                      "Increase 'Close gaps' or close the outline.")
    grown = comp.buffer(gap / 2.0, join_style=2, mitre_limit=4.0)
    return grown, None


def find_region(lines, pt, gap=3.0, page=None, widths=None):
    if not lines:
        return FillResult(None, "There is nothing to fill against - draw some outlines first.")
    P = Point(pt)
    union = unary_union(lines)
    # 1. exact, perfectly closed faces
    best = None
    for f in polygonize(union):
        if f.contains(P) and (best is None or f.area < best.area):
            best = f
    if gap <= 0:
        if best is not None:
            return FillResult(best.simplify(0.02))
        return FillResult(None, "This area is not closed. Increase the gap tolerance or close the outline.")
    # 2. gap closing. An outline that only *looks* closed leaves the exact face leaking into a much
    #    bigger one (the surrounding area), so the gap-closed region wins whenever it is smaller.
    grown, err = _gap_region(lines, union, P, gap, page, widths)
    if best is not None and (grown is None or grown.area >= best.area * 0.98):
        return FillResult(best.simplify(0.02))
    if grown is None:
        return FillResult(None, err)
    return FillResult(grown.simplify(0.02), closed_gap=True)


def polygon_to_subpaths(poly):
    subs = []
    rings = [poly.exterior] + list(poly.interiors)
    for r in rings:
        coords = list(r.coords)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        if len(coords) >= 3:
            subs.append(SubPath([Anchor(x, y) for x, y in coords], True))
    return subs


def make_fill_node(poly, color, name="Fill"):
    from .model import Style
    st = Style(fill=color, stroke=None, width=0.0, fill_rule="evenodd")
    return PathNode(polygon_to_subpaths(poly), st, name)


def fill_at(doc, pt, color, gap=3.0):
    r = doc.sheets_rect()
    res = find_region(collect_lines(doc), pt, gap, (r.right(), r.bottom()), collect_widths(doc))
    if res.polygon is None:
        return None, res
    geoms = list(res.polygon.geoms) if isinstance(res.polygon, MultiPolygon) else [res.polygon]
    poly = max(geoms, key=lambda g: g.area)
    return make_fill_node(poly, color), res
