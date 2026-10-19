"""SVG / PDF import and SVG export."""
from __future__ import annotations

import base64
import gzip
import json
import math
from functools import lru_cache
import os
import re
import xml.etree.ElementTree as ET

from PySide6.QtGui import QColor

from . import affine
from .geometry import arc_to_cubics, dist
from .model import (Anchor, Document, Group, ImageNode, MeasureNode, PathNode, Style,
                    SubPath, TextNode, arrow_length, arrow_path, walk)

SVG_NS = "http://www.w3.org/2000/svg"
INK_NS = "http://www.inkscape.org/namespaces/inkscape"
SOD_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
XLINK_NS = "http://www.w3.org/1999/xlink"
VF_NS = "https://github.com/Rebanne1523/SVG-app/ns"

INHERITED = {
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap",
    "stroke-linejoin", "stroke-dasharray", "stroke-miterlimit", "font-family", "font-size",
    "font-weight", "font-style", "text-anchor", "color", "visibility",
}
PRESENTATION = INHERITED | {"opacity", "display", "clip-path"}
SKIP_TAGS = {"defs", "clipPath", "mask", "marker", "pattern", "linearGradient", "radialGradient",
             "metadata", "namedview", "title", "desc", "style", "filter", "symbol", "script",
             "foreignObject", "switch"}
UNIT = {"px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0, "mm": 96.0 / 25.4, "cm": 96.0 / 2.54,
        "in": 96.0, "": 1.0}

NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


class ImportError_(Exception):
    pass


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_length(s, default=0.0, ref=100.0, font_size=16.0):
    if s is None:
        return default
    s = str(s).strip()
    m = re.match(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)$", s)
    if not m:
        return default
    v = float(m.group(1))
    u = m.group(2)
    if u == "%":
        return v / 100.0 * ref
    if u == "em":
        return v * font_size
    if u == "ex":
        return v * font_size * 0.5
    return v * UNIT.get(u, 1.0)


@lru_cache(maxsize=4096)
def parse_color(s):
    s = (s or "").strip()
    if not s or s == "none" or s == "transparent":
        return None
    low = s.lower()
    m = re.match(r"rgba?\(([^)]*)\)", low)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1).strip()) if p.strip()]
        try:
            vals = []
            for i, p in enumerate(parts[:3]):
                if p.endswith("%"):
                    vals.append(round(float(p[:-1]) * 2.55))
                else:
                    vals.append(int(round(float(p))))
            a = 255
            if len(parts) > 3:
                a = round((float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3])) * 255)
            return (max(0, min(255, vals[0])), max(0, min(255, vals[1])), max(0, min(255, vals[2])),
                    max(0, min(255, a)))
        except (ValueError, IndexError):
            return None
    q = QColor(s)
    if not q.isValid():
        return None
    return (q.red(), q.green(), q.blue(), q.alpha())


def parse_transform(s):
    m = affine.IDENTITY
    if not s:
        return m
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s):
        a = [float(x) for x in NUM_RE.findall(args)]
        try:
            if name == "matrix" and len(a) == 6:
                t = tuple(a)
            elif name == "translate":
                t = affine.translate(a[0], a[1] if len(a) > 1 else 0.0)
            elif name == "scale":
                t = affine.scale(a[0], a[1] if len(a) > 1 else a[0])
            elif name == "rotate":
                t = affine.rotate(a[0], a[1], a[2]) if len(a) >= 3 else affine.rotate(a[0])
            elif name == "skewX":
                t = affine.skew_x(a[0])
            elif name == "skewY":
                t = affine.skew_y(a[0])
            else:
                continue
        except IndexError:
            continue
        m = affine.mul(m, t)
    return m


# ---------------------------------------------------------------- path data
def _parse_path_d_slow(d):
    """Parse SVG path data into a list of SubPath (absolute coordinates) - character by character,
    handles every command including arcs with glued flags."""
    subpaths = []
    cur = None
    i = 0
    n = len(d)
    x = y = 0.0
    sx = sy = 0.0
    last_cmd = ""
    last_c2 = None
    last_q = None

    def skip_ws():
        nonlocal i
        while i < n and d[i] in " \t\r\n,":
            i += 1

    def read_num():
        nonlocal i
        skip_ws()
        m = NUM_RE.match(d, i)
        if not m:
            raise ValueError("number expected")
        i = m.end()
        return float(m.group(0))

    def read_flag():
        nonlocal i
        skip_ws()
        if i < n and d[i] in "01":
            v = d[i] == "1"
            i += 1
            return v
        raise ValueError("flag expected")

    def start(px, py):
        nonlocal cur
        cur = SubPath([Anchor(px, py)], False)
        subpaths.append(cur)

    def line_to(px, py):
        if cur is None:
            start(x, y)
        cur.anchors.append(Anchor(px, py))

    def cubic_to(c1, c2, p):
        if cur is None:
            start(x, y)
        cur.anchors[-1].ox, cur.anchors[-1].oy = c1
        cur.anchors.append(Anchor(p[0], p[1], c2[0], c2[1]))

    try:
        while True:
            skip_ws()
            if i >= n:
                break
            ch = d[i]
            if ch.isalpha():
                cmd = ch
                i += 1
            else:
                if not last_cmd:
                    break
                cmd = last_cmd
                if cmd == "M":
                    cmd = "L"
                elif cmd == "m":
                    cmd = "l"
            rel = cmd.islower()
            c = cmd.upper()
            if c == "Z":
                if cur is not None:
                    cur.closed = True
                    x, y = sx, sy
                    cur = None  # next command starts a new subpath at (x, y)
                last_cmd = cmd
                last_c2 = last_q = None
                continue
            if c == "M":
                nx, ny = read_num(), read_num()
                if rel:
                    nx, ny = x + nx, y + ny
                x, y = nx, ny
                sx, sy = x, y
                start(x, y)
                last_c2 = last_q = None
            elif c == "L":
                nx, ny = read_num(), read_num()
                if rel:
                    nx, ny = x + nx, y + ny
                line_to(nx, ny)
                x, y = nx, ny
                last_c2 = last_q = None
            elif c == "H":
                nx = read_num()
                nx = x + nx if rel else nx
                line_to(nx, y)
                x = nx
                last_c2 = last_q = None
            elif c == "V":
                ny = read_num()
                ny = y + ny if rel else ny
                line_to(x, ny)
                y = ny
                last_c2 = last_q = None
            elif c == "C":
                v = [read_num() for _ in range(6)]
                if rel:
                    v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y, v[4] + x, v[5] + y]
                cubic_to((v[0], v[1]), (v[2], v[3]), (v[4], v[5]))
                last_c2 = (v[2], v[3])
                last_q = None
                x, y = v[4], v[5]
            elif c == "S":
                v = [read_num() for _ in range(4)]
                if rel:
                    v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y]
                c1 = (2 * x - last_c2[0], 2 * y - last_c2[1]) if last_c2 else (x, y)
                cubic_to(c1, (v[0], v[1]), (v[2], v[3]))
                last_c2 = (v[0], v[1])
                last_q = None
                x, y = v[2], v[3]
            elif c == "Q":
                v = [read_num() for _ in range(4)]
                if rel:
                    v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y]
                q = (v[0], v[1])
                c1 = (x + 2.0 / 3.0 * (q[0] - x), y + 2.0 / 3.0 * (q[1] - y))
                c2 = (v[2] + 2.0 / 3.0 * (q[0] - v[2]), v[3] + 2.0 / 3.0 * (q[1] - v[3]))
                cubic_to(c1, c2, (v[2], v[3]))
                last_q = q
                last_c2 = None
                x, y = v[2], v[3]
            elif c == "T":
                v = [read_num() for _ in range(2)]
                if rel:
                    v = [v[0] + x, v[1] + y]
                q = (2 * x - last_q[0], 2 * y - last_q[1]) if last_q else (x, y)
                c1 = (x + 2.0 / 3.0 * (q[0] - x), y + 2.0 / 3.0 * (q[1] - y))
                c2 = (v[0] + 2.0 / 3.0 * (q[0] - v[0]), v[1] + 2.0 / 3.0 * (q[1] - v[1]))
                cubic_to(c1, c2, (v[0], v[1]))
                last_q = q
                last_c2 = None
                x, y = v[0], v[1]
            elif c == "A":
                rx, ry, rot = read_num(), read_num(), read_num()
                large, sweep = read_flag(), read_flag()
                nx, ny = read_num(), read_num()
                if rel:
                    nx, ny = x + nx, y + ny
                if cur is None:
                    start(x, y)
                for c1, c2, p in arc_to_cubics(x, y, rx, ry, rot, large, sweep, nx, ny):
                    if dist(p, (x, y)) < 1e-12 and c1 == c2 == p:
                        line_to(*p)
                    else:
                        cubic_to(c1, c2, p)
                    x, y = p
                x, y = nx, ny
                last_c2 = last_q = None
            else:
                break
            last_cmd = cmd
    except (ValueError, IndexError):
        pass  # keep whatever was parsed

    out = []
    for sp in subpaths:
        if len(sp.anchors) < 2 and not sp.closed:
            continue
        if sp.closed and len(sp.anchors) > 1:
            f, l = sp.anchors[0], sp.anchors[-1]
            if abs(f.x - l.x) < 1e-7 and abs(f.y - l.y) < 1e-7:
                f.ix, f.iy = l.ix, l.iy
                sp.anchors.pop()
        if sp.closed and len(sp.anchors) < 2:
            continue
        detect_smooth(sp)
        out.append(sp)
    return out


_TOK_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[A-Za-z]")


def _finish_subpaths(subpaths):
    out = []
    for sp in subpaths:
        if len(sp.anchors) < 2 and not sp.closed:
            continue
        if sp.closed and len(sp.anchors) > 1:
            f, l = sp.anchors[0], sp.anchors[-1]
            if abs(f.x - l.x) < 1e-7 and abs(f.y - l.y) < 1e-7:
                f.ix, f.iy = l.ix, l.iy
                sp.anchors.pop()
        if sp.closed and len(sp.anchors) < 2:
            continue
        detect_smooth(sp)
        out.append(sp)
    return out


def parse_path_d(d):
    """Parse SVG path data into a list of SubPath (absolute coordinates). Tokenises with one regex
    (several times faster than the character parser, which still handles paths with arcs)."""
    if "a" in d or "A" in d:
        return _parse_path_d_slow(d)
    T = _TOK_RE.findall(d)
    n = len(T)
    subpaths = []
    cur = None
    k = 0
    x = y = sx = sy = 0.0
    last_cmd = ""
    last_c2 = last_q = None
    try:
        while k < n:
            t = T[k]
            if t[0].isalpha():
                cmd = t
                k += 1
            else:
                if not last_cmd:
                    break
                cmd = last_cmd
                if cmd == "M":
                    cmd = "L"
                elif cmd == "m":
                    cmd = "l"
            rel = cmd.islower()
            c = cmd.upper()
            if c == "Z":
                if cur is not None:
                    cur.closed = True
                    x, y = sx, sy
                    cur = None
                last_cmd = cmd
                last_c2 = last_q = None
                continue
            if c == "M":
                nx, ny = float(T[k]), float(T[k + 1])
                k += 2
                if rel:
                    nx, ny = x + nx, y + ny
                x, y = nx, ny
                sx, sy = x, y
                cur = SubPath([Anchor(x, y)], False)
                subpaths.append(cur)
                last_c2 = last_q = None
            elif c == "L":
                nx, ny = float(T[k]), float(T[k + 1])
                k += 2
                if rel:
                    nx, ny = x + nx, y + ny
                if cur is None:
                    cur = SubPath([Anchor(x, y)], False)
                    subpaths.append(cur)
                cur.anchors.append(Anchor(nx, ny))
                x, y = nx, ny
                last_c2 = last_q = None
            elif c == "H":
                nx = float(T[k])
                k += 1
                nx = x + nx if rel else nx
                if cur is None:
                    cur = SubPath([Anchor(x, y)], False)
                    subpaths.append(cur)
                cur.anchors.append(Anchor(nx, y))
                x = nx
                last_c2 = last_q = None
            elif c == "V":
                ny = float(T[k])
                k += 1
                ny = y + ny if rel else ny
                if cur is None:
                    cur = SubPath([Anchor(x, y)], False)
                    subpaths.append(cur)
                cur.anchors.append(Anchor(x, ny))
                y = ny
                last_c2 = last_q = None
            elif c == "C" or c == "S" or c == "Q" or c == "T":
                cnt = 6 if c == "C" else (2 if c == "T" else 4)
                v = [float(u) for u in T[k:k + cnt]]
                if len(v) < cnt:
                    raise IndexError
                k += cnt
                if rel:
                    v = [v[i] + (x if i % 2 == 0 else y) for i in range(cnt)]
                if c == "C":
                    c1, c2, p = (v[0], v[1]), (v[2], v[3]), (v[4], v[5])
                    last_c2, last_q = c2, None
                elif c == "S":
                    c1 = (2 * x - last_c2[0], 2 * y - last_c2[1]) if last_c2 else (x, y)
                    c2, p = (v[0], v[1]), (v[2], v[3])
                    last_c2, last_q = c2, None
                else:
                    if c == "Q":
                        q, p = (v[0], v[1]), (v[2], v[3])
                    else:
                        q = (2 * x - last_q[0], 2 * y - last_q[1]) if last_q else (x, y)
                        p = (v[0], v[1])
                    c1 = (x + 2.0 / 3.0 * (q[0] - x), y + 2.0 / 3.0 * (q[1] - y))
                    c2 = (p[0] + 2.0 / 3.0 * (q[0] - p[0]), p[1] + 2.0 / 3.0 * (q[1] - p[1]))
                    last_q, last_c2 = q, None
                if cur is None:
                    cur = SubPath([Anchor(x, y)], False)
                    subpaths.append(cur)
                cur.anchors[-1].ox, cur.anchors[-1].oy = c1
                cur.anchors.append(Anchor(p[0], p[1], c2[0], c2[1]))
                x, y = p
            else:
                break
            last_cmd = cmd
    except (ValueError, IndexError):
        pass  # keep whatever was parsed
    return _finish_subpaths(subpaths)


def detect_smooth(sp):
    for a in sp.anchors:
        if a.has_in() and a.has_out():
            v1 = (a.x - a.ix, a.y - a.iy)
            v2 = (a.ox - a.x, a.oy - a.y)
            l1, l2 = math.hypot(*v1), math.hypot(*v2)
            if l1 > 1e-9 and l2 > 1e-9:
                cross = abs(v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)
                dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
                a.smooth = cross < 0.02 and dot > 0


# ---------------------------------------------------------------- import
class SvgImporter:
    def __init__(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            self.root = ET.fromstring(data)
        except ET.ParseError as e:
            raise ImportError_(f"Invalid SVG/XML: {e}")
        if local(self.root.tag) != "svg":
            raise ImportError_("Not an SVG document")
        self.ids = {}
        for el in self.root.iter():
            i = el.get("id")
            if i:
                self.ids[i] = el
        self.css = {"tag": {}, "class": {}, "id": {}}
        for st in self.root.iter():
            if local(st.tag) == "style" and st.text:
                self._parse_css(st.text)
        self.doc = None
        self.use_depth = 0
        self.warnings = set()

    # css ----------------------------------------------------------------
    def _parse_css(self, text):
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            decls = self._parse_decls(body)
            for s in sel.split(","):
                s = s.strip()
                if not s:
                    continue
                if s.startswith("."):
                    self.css["class"].setdefault(s[1:].split(".")[0].split(":")[0], {}).update(decls)
                elif s.startswith("#"):
                    self.css["id"].setdefault(s[1:], {}).update(decls)
                elif re.match(r"^[A-Za-z][\w-]*$", s):
                    self.css["tag"].setdefault(s, {}).update(decls)
                elif s == "*":
                    self.css["tag"].setdefault("*", {}).update(decls)

    @staticmethod
    def _parse_decls(body):
        out = {}
        for part in body.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip()] = v.strip().replace("!important", "").strip()
        return out

    def _resolve(self, el, parent_props):
        props = {k: v for k, v in parent_props.items() if k in INHERITED}
        tag = local(el.tag)
        for k in PRESENTATION:
            v = el.get(k)
            if v is not None:
                props[k] = v.strip()
        if "*" in self.css["tag"]:
            props.update(self.css["tag"]["*"])
        if tag in self.css["tag"]:
            props.update(self.css["tag"][tag])
        for c in (el.get("class") or "").split():
            if c in self.css["class"]:
                props.update(self.css["class"][c])
        i = el.get("id")
        if i and i in self.css["id"]:
            props.update(self.css["id"][i])
        st = el.get("style")
        if st:
            props.update(self._parse_decls(st))
        return props

    # paint ----------------------------------------------------------------
    def _gradient_color(self, el, depth=0):
        if el is None or depth > 5:
            return None
        stops = [c for c in el if local(c.tag) == "stop"]
        if not stops:
            href = el.get("{%s}href" % XLINK_NS) or el.get("href")
            if href and href.startswith("#"):
                return self._gradient_color(self.ids.get(href[1:]), depth + 1)
            return None
        st = stops[len(stops) // 2]
        props = self._parse_decls(st.get("style") or "")
        col = props.get("stop-color") or st.get("stop-color") or "black"
        c = parse_color(col)
        if c:
            op = float(props.get("stop-opacity") or st.get("stop-opacity") or 1)
            c = (c[0], c[1], c[2], int(round(c[3] * op)))
        return c

    def _paint(self, val, opacity, props):
        if val is None:
            return None
        val = val.strip()
        if val in ("none", ""):
            return None
        if val == "currentColor":
            val = props.get("color", "black")
        if val.startswith("url("):
            m = re.match(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)\s*(.*)", val)
            col = None
            if m:
                el = self.ids.get(m.group(1))
                if el is not None and local(el.tag) in ("linearGradient", "radialGradient"):
                    col = self._gradient_color(el)
                    self.warnings.add("Gradients were converted to a flat colour.")
                elif el is not None:
                    self.warnings.add("Patterns are not supported and were ignored.")
                if col is None and m.group(2):
                    col = parse_color(m.group(2))
            if col is None:
                return None
        else:
            col = parse_color(val)
        if col is None:
            return None
        return (col[0], col[1], col[2], int(round(col[3] * max(0.0, min(1.0, opacity)))))

    def _style(self, props, scale):
        fs = parse_length(props.get("font-size"), 16.0)
        fill = self._paint(props.get("fill", "black"), float(props.get("fill-opacity", 1) or 1), props)
        stroke = self._paint(props.get("stroke", "none"), float(props.get("stroke-opacity", 1) or 1), props)
        width = parse_length(props.get("stroke-width"), 1.0, font_size=fs) * scale
        dash = []
        da = props.get("stroke-dasharray", "none")
        if da and da != "none" and width > 0:
            vals = [parse_length(v, 0.0) * scale for v in re.split(r"[,\s]+", da.strip()) if v]
            if vals and sum(vals) > 0:
                if len(vals) % 2:
                    vals = vals * 2
                dash = [max(v / width, 0.001) for v in vals]
        cap = props.get("stroke-linecap", "butt")
        join = props.get("stroke-linejoin", "miter")
        if join == "miter-clip" or join == "arcs":
            join = "miter"
        st = Style(fill=fill, stroke=stroke, width=width, dash=dash,
                   cap=cap if cap in ("butt", "round", "square") else "butt",
                   join=join if join in ("miter", "round", "bevel") else "miter",
                   fill_rule="evenodd" if props.get("fill-rule") == "evenodd" else "nonzero")
        return st

    # element shapes -----------------------------------------------------
    def _shape_subpaths(self, el, props):
        tag = local(el.tag)
        fs = parse_length(props.get("font-size"), 16.0)
        vw = self.vb_w
        vh = self.vb_h
        L = lambda k, d=0.0, ref=vw: parse_length(el.get(k), d, ref, fs)
        if tag == "path":
            return parse_path_d(el.get("d") or "")
        if tag == "rect":
            x, y, w, h = L("x"), L("y", ref=vh), L("width"), L("height", ref=vh)
            if w <= 0 or h <= 0:
                return []
            rx = el.get("rx")
            ry = el.get("ry")
            rxv = parse_length(rx, 0, vw, fs) if rx is not None else None
            ryv = parse_length(ry, 0, vh, fs) if ry is not None else None
            if rxv is None and ryv is None:
                r = 0.0
            else:
                rxv = rxv if rxv is not None else ryv
                ryv = ryv if ryv is not None else rxv
                r = min(rxv, ryv)
            return PathNode.rect(x, y, w, h, r).subpaths
        if tag == "circle":
            r = L("r")
            if r <= 0:
                return []
            return PathNode.ellipse(L("cx"), L("cy", ref=vh), r, r).subpaths
        if tag == "ellipse":
            rx, ry = L("rx"), L("ry", ref=vh)
            if rx <= 0 or ry <= 0:
                return []
            return PathNode.ellipse(L("cx"), L("cy", ref=vh), rx, ry).subpaths
        if tag == "line":
            return PathNode.polyline([(L("x1"), L("y1", ref=vh)), (L("x2"), L("y2", ref=vh))]).subpaths
        if tag in ("polyline", "polygon"):
            nums = [float(v) for v in NUM_RE.findall(el.get("points") or "")]
            pts = list(zip(nums[0::2], nums[1::2]))
            if len(pts) < 2:
                return []
            return PathNode.polyline(pts, tag == "polygon").subpaths
        return []

    # clip -----------------------------------------------------------------
    def _clip_for(self, props, ctm):
        v = props.get("clip-path")
        if not v or v == "none":
            return None
        m = re.match(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)", v)
        if not m:
            return None
        cp = self.ids.get(m.group(1))
        if cp is None or local(cp.tag) != "clipPath":
            return None
        base = affine.mul(ctm, parse_transform(cp.get("transform")))
        subs = []
        for ch in cp:
            tag = local(ch.tag)
            if tag not in ("path", "rect", "circle", "ellipse", "polygon", "polyline", "line", "use"):
                continue
            cprops = self._resolve(ch, {})
            if cprops.get("display") == "none":
                continue
            cm = affine.mul(base, parse_transform(ch.get("transform")))
            if tag == "use":
                href = ch.get("{%s}href" % XLINK_NS) or ch.get("href") or ""
                ref = self.ids.get(href[1:]) if href.startswith("#") else None
                if ref is None:
                    continue
                cm = affine.mul(cm, affine.translate(parse_length(ch.get("x")), parse_length(ch.get("y"))))
                ch = ref
            for sp in self._shape_subpaths(ch, cprops):
                sp = sp.copy()
                sp.transform(cm)
                sp.closed = True
                subs.append(sp)
        return subs

    # traversal -----------------------------------------------------------
    def build(self):
        root = self.root
        vb = root.get("viewBox")
        w = root.get("width")
        h = root.get("height")
        if vb:
            nums = [float(v) for v in NUM_RE.findall(vb)]
            if len(nums) == 4 and nums[2] > 0 and nums[3] > 0:
                minx, miny, vw, vh = nums
            else:
                minx = miny = 0.0
                vw = parse_length(w, 800.0)
                vh = parse_length(h, 600.0)
        else:
            minx = miny = 0.0
            vw = parse_length(w, 800.0) if w else 800.0
            vh = parse_length(h, 600.0) if h else 600.0
        self.vb_w, self.vb_h = vw, vh
        self.doc = Document(vw, vh)
        sheet = self.doc.sheets()[0]
        sheet.children = []
        ctm = affine.translate(-minx, -miny)
        props = self._resolve(root, {})
        props.pop("display", None)
        self._children(root, sheet, props, ctm)
        if not sheet.children:
            sheet.add(Group("Layer 1"))
        elif any(not c.is_group() for c in sheet.children):
            # a plain SVG / PDF page has loose objects: put everything in one layer so the layer
            # panel always has a layer to work with
            layer = Group("Layer 1")
            for c in list(sheet.children):
                layer.add(c)          # add() detaches it from the sheet
            sheet.add(layer)
        total = sum(1 for _ in walk(sheet))
        for t in (c for c in sheet.children if c.is_group()):
            t.expanded = total < 400
        self.doc._active_id = self.doc.layer_for_sheet(sheet).id
        return self.doc

    def _children(self, el, parent, props, ctm):
        for ch in el:
            self._element(ch, parent, props, ctm)

    def _name(self, el, base):
        lab = el.get("{%s}label" % INK_NS)
        if lab:
            return lab
        return self.doc.new_name(base)

    def _element(self, el, parent, props_in, ctm):
        tag = local(el.tag)
        if not tag or tag in SKIP_TAGS:
            return
        if tag not in ("g", "a", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
                       "text", "image", "use", "svg"):
            return
        props = self._resolve(el, props_in)
        hidden = props.get("display") == "none" or props.get("visibility") in ("hidden", "collapse")
        m = affine.mul(ctm, parse_transform(el.get("transform")))
        opacity = 1.0
        try:
            opacity = max(0.0, min(1.0, float(props.get("opacity", 1))))
        except ValueError:
            pass
        clip = self._clip_for(props, m)

        node = None
        if el.get("{%s}type" % VF_NS) == "measure" and el.get("{%s}data" % VF_NS):
            try:
                node = MeasureNode.from_data(json.loads(el.get("{%s}data" % VF_NS)), self._name(el, "Measure"))
                node.transform(m, scale_stroke=True)
            except (ValueError, KeyError):
                node = None
        if node is None:
            if tag in ("g", "a", "svg"):
                node = Group(self._name(el, "Folder"))
                node.expanded = False
                self._children(el, node, props, m)
                if tag == "g" and not node.children and not el.get("{%s}label" % INK_NS):
                    return
            elif tag == "use":
                node = self._use(el, props, m)
                if node is None:
                    return
            elif tag == "text":
                node = self._text(el, props, m)
                if node is None:
                    return
            elif tag == "image":
                node = self._image(el, m)
                if node is None:
                    return
            else:
                subs = self._shape_subpaths(el, props)
                if not subs:
                    return
                scale = affine.mean_scale(m)
                st = self._style(props, scale)
                if tag in ("line", "polyline") or (tag == "path" and False):
                    pass
                node = PathNode(subs, st, self._name(el, tag.capitalize() if tag != "path" else "Path"))
                node.transform(m)
                node.style.width = st.width  # transform() does not scale stroke unless asked
                for key, attr in (("arrow_start", "arrow-start"), ("arrow_end", "arrow-end")):
                    v = el.get("{%s}%s" % (VF_NS, attr))
                    if v:
                        setattr(node.style, key, v)
                v = el.get("{%s}arrow-size" % VF_NS)
                if v:
                    node.style.arrow_size = float(v)
                if not el.get("{%s}arrow-end" % VF_NS) and not el.get("{%s}arrow-start" % VF_NS):
                    if props.get("marker-end") not in (None, "none") or el.get("marker-end") not in (None, "none"):
                        node.style.arrow_end = "triangle"
                    if props.get("marker-start") not in (None, "none") or el.get("marker-start") not in (None, "none"):
                        node.style.arrow_start = "triangle"
                if not st.fill and not st.stroke:
                    return
        if (node.is_group() and len(node.children) == 1 and not clip and opacity >= 0.999
                and not hidden and not el.get("{%s}label" % INK_NS) and el is not self.root):
            only = node.children[0]
            node.children.remove(only)
            only.parent = None
            parent.add(only)
            return
        node.visible = not hidden
        node.locked = el.get("{%s}insensitive" % SOD_NS) == "true"
        node.opacity = opacity
        if clip:
            node.clip = clip
        parent.add(node)

    def _use(self, el, props, m):
        href = el.get("{%s}href" % XLINK_NS) or el.get("href") or ""
        ref = self.ids.get(href[1:]) if href.startswith("#") else None
        if ref is None or self.use_depth > 8:
            return None
        self.use_depth += 1
        try:
            g = Group(self._name(el, "Folder"))
            g.expanded = False
            tm = affine.mul(m, affine.translate(parse_length(el.get("x")), parse_length(el.get("y"))))
            if local(ref.tag) == "symbol":
                self._children(ref, g, props, tm)
            else:
                # parse referenced element with transform handled by _element
                self._element(ref, g, props, tm)
            return g if g.children else None
        finally:
            self.use_depth -= 1

    def _image(self, el, m):
        href = el.get("{%s}href" % XLINK_NS) or el.get("href") or ""
        if not href.startswith("data:"):
            self.warnings.add("Linked (external) images are not loaded; only embedded images are.")
            return None
        try:
            payload = href.split(",", 1)[1]
            data = base64.b64decode(payload)
        except Exception:
            return None
        x, y = parse_length(el.get("x")), parse_length(el.get("y"))
        w, h = parse_length(el.get("width")), parse_length(el.get("height"))
        node = ImageNode(x, y, w, h, data, self._name(el, "Image"))
        if w <= 0 or h <= 0:
            img = node.image()
            node.w, node.h = float(img.width()), float(img.height())
        node.transform(m)
        return node

    def _text(self, el, props, m):
        fs = parse_length(props.get("font-size"), 16.0)
        fam = (props.get("font-family") or "sans-serif").split(",")[0].strip().strip("'\"")
        if fam in ("sans-serif", "serif", "monospace", ""):
            fam = {"serif": "DejaVu Serif", "monospace": "DejaVu Sans Mono"}.get(fam, "DejaVu Sans")
        bold = (props.get("font-weight") or "") in ("bold", "bolder", "600", "700", "800", "900")
        italic = (props.get("font-style") or "") in ("italic", "oblique")
        anchor = props.get("text-anchor", "start")
        pieces = []  # (x, y, text)

        def nums(attr, node):
            v = node.get(attr)
            return [parse_length(t, 0.0) for t in re.split(r"[,\s]+", v.strip())] if v else []

        x0 = nums("x", el)
        y0 = nums("y", el)
        state = {"x": x0[0] if x0 else 0.0, "y": y0[0] if y0 else 0.0}
        cur = {"text": "", "x": state["x"], "y": state["y"]}

        def flush():
            if cur["text"].strip():
                pieces.append((cur["x"], cur["y"], cur["text"]))
            cur["text"] = ""

        def visit(node, first=True):
            xs, ys = nums("x", node), nums("y", node)
            dy = nums("dy", node)
            dx = nums("dx", node)
            if node is not el and (xs or ys or dy):
                flush()
                if xs:
                    state["x"] = xs[0]
                if ys:
                    state["y"] = ys[0]
                if dy:
                    state["y"] += dy[0]
                cur["x"], cur["y"] = state["x"], state["y"]
            if dx:
                state["x"] += dx[0]
            if node.text:
                cur["text"] += re.sub(r"\s+", " ", node.text)
            for ch in node:
                if local(ch.tag) in ("tspan", "textPath", "a"):
                    visit(ch, False)
                if ch.tail:
                    cur["text"] += re.sub(r"\s+", " ", ch.tail)

        visit(el)
        flush()
        if not pieces:
            return None
        scale = affine.mean_scale(m)
        rot = affine.rotation_deg(m)
        st = self._style(props, scale)
        st.width = 0 if not st.stroke else st.width
        nodes = []
        for x, y, t in pieces:
            gx, gy = affine.apply(m, x, y)
            tn = TextNode(gx, gy, t.strip(), fam, fs * scale, bold, italic, anchor, rot, st.copy(),
                          self._name(el, "Text"))
            nodes.append(tn)
        if len(nodes) == 1:
            return nodes[0]
        g = Group(self._name(el, "Text"))
        for n in nodes:
            g.add(n)
        return g


def import_svg_bytes(data):
    """Parse SVG bytes into a Document holding a single sheet."""
    imp = SvgImporter(data)
    doc = imp.build()
    doc.warnings = sorted(imp.warnings)
    doc.modified = False
    return doc


def _detach_sheet(doc, name, source, pt_per_unit):
    sheet = doc.sheets()[0]
    doc.root.children.remove(sheet)
    sheet.parent = None
    sheet.name = name
    sheet.source = source
    sheet.pt_per_unit = pt_per_unit
    sheet.x = sheet.y = 0.0
    return sheet


def sheet_from_svg_bytes(data, name, source=None, pt_per_unit=0.75):
    doc = import_svg_bytes(data)
    return _detach_sheet(doc, name, source, pt_per_unit), doc.warnings


def sheets_from_pdf(path):
    """One detached Sheet per PDF page. A one-page PDF gives a sheet named exactly like the file."""
    import pymupdf
    stem = os.path.splitext(os.path.basename(path))[0]
    sheets, warnings = [], []
    with pymupdf.open(path) as pdf:
        n = pdf.page_count
        for i in range(n):
            svg = pdf[i].get_svg_image(text_as_path=True)
            name = stem if n == 1 else f"{stem} - {i + 1}"
            sheet, w = sheet_from_svg_bytes(svg, name, path, pt_per_unit=1.0)
            sheets.append(sheet)
            warnings.extend(w)
    return sheets, sorted(set(warnings))


def sheets_from_svg_file(path):
    with open(path, "rb") as f:
        data = f.read()
    if path.lower().endswith(".svgz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    stem = os.path.splitext(os.path.basename(path))[0]
    sheet, warnings = sheet_from_svg_bytes(data, stem, path)
    return [sheet], warnings


# ---------------------------------------------------------------- export
def fmt(v):
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def hexcol(c):
    return "#%02x%02x%02x" % (c[0], c[1], c[2])


def path_d(subpaths):
    out = []
    for sp in subpaths:
        if not sp.anchors:
            continue
        a0 = sp.anchors[0]
        out.append(f"M{fmt(a0.x)},{fmt(a0.y)}")
        for _, a, b in sp.segments():
            if not a.has_out() and not b.has_in():
                out.append(f"L{fmt(b.x)},{fmt(b.y)}")
            else:
                out.append(f"C{fmt(a.ox)},{fmt(a.oy)} {fmt(b.ix)},{fmt(b.iy)} {fmt(b.x)},{fmt(b.y)}")
        if sp.closed:
            out.append("Z")
    return " ".join(out)


def q(ns, name):
    return "{%s}%s" % (ns, name)


class SvgExporter:
    """Writes ONE sheet as a standalone SVG (coordinates relative to the sheet's top-left corner)."""

    def __init__(self, doc, sheet=None):
        self.doc = doc
        self.sheet = sheet or doc.current_sheet()
        self.clip_n = 0
        self.defs = None

    def build(self):
        ET.register_namespace("", SVG_NS)
        ET.register_namespace("inkscape", INK_NS)
        ET.register_namespace("sodipodi", SOD_NS)
        ET.register_namespace("xlink", XLINK_NS)
        ET.register_namespace("vf", VF_NS)
        sh = self.sheet
        svg = ET.Element(q(SVG_NS, "svg"), {
            "width": fmt(sh.width), "height": fmt(sh.height),
            "viewBox": f"0 0 {fmt(sh.width)} {fmt(sh.height)}", "version": "1.1"})
        self.defs = ET.SubElement(svg, q(SVG_NS, "defs"))
        kids = sh.children
        if sh.x or sh.y:
            from .model import clone_tree
            kids = [clone_tree(c) for c in sh.children]
            for k in kids:
                k.transform(affine.translate(-sh.x, -sh.y))
        for ch in kids:
            self._node(ch, svg, top=True)
        if not len(self.defs):
            svg.remove(self.defs)
        return svg

    def _common(self, node, el, top=False):
        if node.name:
            el.set(q(INK_NS, "label"), node.name)
        if node.is_group() and top:
            el.set(q(INK_NS, "groupmode"), "layer")
        if not node.visible:
            el.set("style", "display:none")
        if node.locked:
            el.set(q(SOD_NS, "insensitive"), "true")
        if node.opacity < 0.999:
            el.set("opacity", fmt(node.opacity))
        clip = node.clip_for_export() if hasattr(node, "clip_for_export") else node.clip
        if clip:
            self.clip_n += 1
            cid = f"vfclip{self.clip_n}"
            cp = ET.SubElement(self.defs, q(SVG_NS, "clipPath"), {"id": cid})
            ET.SubElement(cp, q(SVG_NS, "path"), {"d": path_d(clip)})
            el.set("clip-path", f"url(#{cid})")

    def _style_attrs(self, st, el):
        if st.fill:
            el.set("fill", hexcol(st.fill))
            if st.fill[3] < 255:
                el.set("fill-opacity", fmt(st.fill[3] / 255.0))
        else:
            el.set("fill", "none")
        if st.fill_rule == "evenodd":
            el.set("fill-rule", "evenodd")
        if st.stroke and st.width > 0:
            el.set("stroke", hexcol(st.stroke))
            if st.stroke[3] < 255:
                el.set("stroke-opacity", fmt(st.stroke[3] / 255.0))
            el.set("stroke-width", fmt(st.width))
            if st.cap != "butt":
                el.set("stroke-linecap", st.cap)
            if st.join != "miter":
                el.set("stroke-linejoin", st.join)
            if st.dash:
                el.set("stroke-dasharray", ",".join(fmt(v * st.width) for v in st.dash))

    def _marker(self, kind, length, start):
        key = (kind, round(length, 3), start)
        if not hasattr(self, "_markers"):
            self._markers = {}
        if key in self._markers:
            return self._markers[key]
        mid = f"vfmk{len(self._markers) + 1}"
        mk = ET.SubElement(self.defs, q(SVG_NS, "marker"), {
            "id": mid, "orient": "auto-start-reverse" if start else "auto", "markerUnits": "userSpaceOnUse",
            "refX": "0", "refY": "0", "markerWidth": "1", "markerHeight": "1", "style": "overflow:visible"})
        ap, filled, _ = arrow_path(kind, (0.0, 0.0), (1.0, 0.0), length)
        if ap is not None:
            d = qpath_to_d(ap)
            attrs = {"d": d}
            if filled:
                attrs.update({"fill": "context-stroke", "stroke": "none"})
            else:
                attrs.update({"fill": "none", "stroke": "context-stroke", "stroke-width": "1"})
            ET.SubElement(mk, q(SVG_NS, "path"), attrs)
        self._markers[key] = mid
        return mid

    def _node(self, node, parent, top=False):
        if node.kind == "group":
            el = ET.SubElement(parent, q(SVG_NS, "g"))
            self._common(node, el, top)
            for c in node.children:
                self._node(c, el)
        elif node.kind == "path":
            el = ET.SubElement(parent, q(SVG_NS, "path"), {"d": path_d(node.subpaths)})
            self._style_attrs(node.style, el)
            st = node.style
            L = arrow_length(st)
            if st.arrow_start != "none":
                el.set(q(VF_NS, "arrow-start"), st.arrow_start)
                el.set("marker-start", f"url(#{self._marker(st.arrow_start, L, True)})")
            if st.arrow_end != "none":
                el.set(q(VF_NS, "arrow-end"), st.arrow_end)
                el.set("marker-end", f"url(#{self._marker(st.arrow_end, L, False)})")
            if st.arrow_start != "none" or st.arrow_end != "none":
                el.set(q(VF_NS, "arrow-size"), fmt(st.arrow_size))
            self._common(node, el)
        elif node.kind == "text":
            self._text(node, parent)
        elif node.kind == "image":
            mime = "image/png" if node.data[:4] == b"\x89PNG" else "image/jpeg"
            el = ET.SubElement(parent, q(SVG_NS, "image"), {
                "x": fmt(node.x), "y": fmt(node.y), "width": fmt(node.w), "height": fmt(node.h),
                q(XLINK_NS, "href"): f"data:{mime};base64," + base64.b64encode(node.data).decode("ascii"),
                "preserveAspectRatio": "none"})
            self._common(node, el)
        elif node.kind == "measure":
            self._measure(node, parent)

    def _text(self, node, parent):
        st = node.style
        el = ET.SubElement(parent, q(SVG_NS, "text"), {
            "x": fmt(node.x), "y": fmt(node.y), "font-family": node.family,
            "font-size": fmt(node.size), "text-anchor": node.anchor})
        if node.bold:
            el.set("font-weight", "bold")
        if node.italic:
            el.set("font-style", "italic")
        if abs(node.rotation) > 1e-6:
            el.set("transform", f"rotate({fmt(node.rotation)} {fmt(node.x)} {fmt(node.y)})")
        self._style_attrs(st, el)
        el.set("xml:space", "preserve") if False else None
        lines = node.text.split("\n")
        lh = text_line_height(node.family, node.size, node.bold, node.italic)
        if len(lines) == 1:
            el.text = lines[0]
        else:
            for i, line in enumerate(lines):
                ts = ET.SubElement(el, q(SVG_NS, "tspan"), {"x": fmt(node.x)})
                if i:
                    ts.set("dy", fmt(lh))
                ts.text = line
        self._common(node, el)

    def _measure(self, node, parent):
        g = ET.SubElement(parent, q(SVG_NS, "g"))
        g.set(q(VF_NS, "type"), "measure")
        g.set(q(VF_NS, "data"), json.dumps(node.to_data(), separators=(",", ":")))
        self._common(node, g)
        path, shapes = node.line_path()
        st = node.style
        el = ET.SubElement(g, q(SVG_NS, "path"), {"d": qpath_to_d(path)})
        self._style_attrs(Style(fill=None, stroke=st.stroke, width=st.width, dash=st.dash, cap=st.cap,
                                join="miter"), el)
        for ap, filled in shapes:
            if ap is None:
                continue
            a = ET.SubElement(g, q(SVG_NS, "path"), {"d": qpath_to_d(ap)})
            if filled:
                self._style_attrs(Style(fill=st.stroke, stroke=None, width=0), a)
            else:
                self._style_attrs(Style(fill=None, stroke=st.stroke, width=st.width, join="round"), a)
        geo = node.geometry()
        tx, ty = geo["text_pos"]
        t = ET.SubElement(g, q(SVG_NS, "text"), {
            "x": "0", "y": fmt(node.font_size * 0.35), "font-family": node.family,
            "font-size": fmt(node.font_size), "text-anchor": "middle",
            "transform": f"translate({fmt(tx)} {fmt(ty)}) rotate({fmt(geo['text_angle'])})"})
        if node.bold:
            t.set("font-weight", "bold")
        if node.italic:
            t.set("font-style", "italic")
        t.set("fill", hexcol(node.text_color))
        lines = node.text.split("\n")
        t.text = lines[0]


def text_line_height(family, size, bold, italic):
    from PySide6.QtGui import QFont, QFontMetricsF
    f = QFont(family)
    f.setPixelSize(max(1, int(round(size * 8))))
    f.setBold(bold)
    f.setItalic(italic)
    return QFontMetricsF(f).height() / 8.0


def qpath_to_d(p):
    from PySide6.QtGui import QPainterPath
    out = []
    i = 0
    n = p.elementCount()
    while i < n:
        e = p.elementAt(i)
        if e.type == QPainterPath.MoveToElement:
            out.append(f"M{fmt(e.x)},{fmt(e.y)}")
        elif e.type == QPainterPath.LineToElement:
            out.append(f"L{fmt(e.x)},{fmt(e.y)}")
        elif e.type == QPainterPath.CurveToElement:
            c2 = p.elementAt(i + 1)
            end = p.elementAt(i + 2)
            out.append(f"C{fmt(e.x)},{fmt(e.y)} {fmt(c2.x)},{fmt(c2.y)} {fmt(end.x)},{fmt(end.y)}")
            i += 2
        i += 1
    return " ".join(out)


def export_svg_string(doc, sheet=None):
    svg = SvgExporter(doc, sheet).build()
    ET.indent(svg, space="  ")
    return '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + ET.tostring(svg, encoding="unicode")


def save_svg(doc, path, sheet=None):
    s = export_svg_string(doc, sheet)
    if path.lower().endswith(".svgz"):
        with gzip.open(path, "wb") as f:
            f.write(s.encode("utf-8"))
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(s)
