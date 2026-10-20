"""Quick colour bar along the bottom of the window.

Context aware: an object that only has a stroke gets a stroke colour, one that only has a fill gets a
fill colour (nothing is ever added); when the selection has both, two bars appear, one per channel.
"""
from __future__ import annotations

import colorsys

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolBar, QVBoxLayout, QWidget

from .model import leaves, qcolor


def build_palette():
    cols = []
    for i in range(16):                                 # greys, white -> black
        v = round(255 * (1 - i / 15))
        cols.append((v, v, v, 255))
    for h in range(18):                                 # hue columns, dark -> light
        hue = h / 18
        for sat, val in ((1.0, 0.35), (1.0, 0.6), (1.0, 0.95), (0.6, 1.0), (0.3, 1.0)):
            r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
            cols.append((round(r * 255), round(g * 255), round(b * 255), 255))
    return cols


PALETTE = build_palette()


class Strip(QWidget):
    picked = Signal(object)      # colour tuple, or None for "no colour"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.current = None
        self.entries = [None] + PALETTE

    def _w(self):
        return self.width() / len(self.entries)

    def paintEvent(self, e):
        p = QPainter(self)
        w = self._w()
        for i, c in enumerate(self.entries):
            r = QRectF(i * w, 0, w + 0.6, self.height())
            if c is None:
                p.fillRect(r, QColor(235, 235, 235))
                p.setPen(QPen(QColor(210, 40, 40), 1.5))
                p.drawLine(r.bottomLeft(), r.topRight())
            else:
                p.fillRect(r, qcolor(c))
        p.setPen(QPen(QColor(0, 0, 0, 90)))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        k = self._index_of(self.current)
        if k is not None:                       # a dot marks the swatch that is currently selected
            cx, cy = (k + 0.5) * w, self.height() / 2.0
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 220), 3.0))
            p.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))

    def _index_of(self, c):
        if c is None:
            return 0
        for i, e in enumerate(self.entries):
            if e is not None and tuple(e[:3]) == tuple(c[:3]):
                return i
        return None

    def _at(self, x):
        i = int(x / self._w())
        return self.entries[max(0, min(len(self.entries) - 1, i))]

    def mouseMoveEvent(self, e):
        c = self._at(e.position().x())
        self.setToolTip("No colour" if c is None else "#%02x%02x%02x" % c[:3])

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self._at(e.position().x()))


class Chip(QLabel):
    """Shows the current colour of a channel."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.setFixedSize(54, 16)
        self.color = None

    def set_color(self, c):
        self.color = c
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(0, 0, 14, 16, qcolor(self.color) if self.color else QColor(60, 60, 60))
        if not self.color:
            p.setPen(QColor(230, 60, 60))
            p.drawLine(0, 15, 14, 1)
        p.setPen(self.palette().text().color())
        p.drawText(18, 12, self.text)


class PaletteBar:
    def __init__(self, win, get_canvas):
        self.win = win
        self.get_canvas = get_canvas
        self.bar = QToolBar("Colours")
        self.bar.setMovable(False)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        self.rows = {}
        for ch, label in (("fill", "Fill"), ("stroke", "Stroke")):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            chip = Chip(label)
            strip = Strip()
            strip.picked.connect(lambda c, ch=ch: self.pick(ch, c))
            h.addWidget(chip)
            h.addWidget(strip, 1)
            lay.addWidget(row)
            self.rows[ch] = (row, chip, strip)
        self.bar.addWidget(host)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.refresh()

    @property
    def doc(self):
        return self.get_canvas().doc

    # --------------------------------------------------------------
    def _leaves(self):
        out = []
        for n in self.doc.selection:
            out.extend(leaves(n) if n.is_group() else [n])
        return out

    @staticmethod
    def _channels(n):
        """Which colour channels this node actually has."""
        if n.kind == "measure":
            return {"stroke"}
        st = getattr(n, "style", None)
        if st is None:
            return set()
        ch = set()
        if st.fill:
            ch.add("fill")
        if st.stroke and st.width > 0:
            ch.add("stroke")
        return ch

    def refresh(self, *a):
        sel = self.doc.selection
        first = None
        if sel:
            has_fill = has_stroke = False
            seen = 0
            for top in sel:
                for n in (leaves(top) if top.is_group() else (top,)):
                    if first is None:
                        first = n
                    st = getattr(n, "style", None)
                    if n.kind == "measure":
                        has_stroke = True
                    elif st is not None:
                        has_fill = has_fill or bool(st.fill)
                        has_stroke = has_stroke or bool(st.stroke and st.width > 0)
                    seen += 1
                    if (has_fill and has_stroke) or seen > 2000:     # decided (or a huge selection: sample it)
                        break
                else:
                    continue
                break
        if first is None:
            ds = self.doc.default_style
            show = ["fill"] if ds.fill and not ds.stroke else ["stroke"]
            cur = {"fill": ds.fill, "stroke": ds.stroke}
        else:
            show = ["fill", "stroke"] if (has_fill and has_stroke) else (["fill"] if has_fill else ["stroke"])
            st = getattr(first, "style", None)
            cur = {"fill": st.fill if st else None, "stroke": st.stroke if st else None}
        for ch, (row, chip, strip) in self.rows.items():
            row.setVisible(ch in show)
            chip.set_color(cur[ch])
            if strip.current != cur[ch]:
                strip.current = cur[ch]
                strip.update()
            chip.text = ("Fill" if ch == "fill" else "Stroke") if len(show) == 2 else "Colour"
            chip.update()

    def pick(self, channel, color):
        doc = self.doc
        ls = self._leaves()
        if not ls:
            ds = doc.default_style
            setattr(ds, channel, color)
            self.refresh()
            return
        both_rows = self.rows["fill"][0].isVisible() and self.rows["stroke"][0].isVisible()
        only_one = not both_rows
        groups = {"fill": [], "stroke": []}
        for n in ls:
            ch = self._channels(n)
            if only_one:
                for c in ch:
                    groups[c].append(n)
                if not ch:
                    groups[channel].append(n)
            elif channel in ch:
                groups[channel].append(n)
        with doc.edit():
            for c, nodes in groups.items():
                if not nodes:
                    continue
                for n in nodes:
                    if n.kind == "measure":
                        n.style.stroke = color
                        if color:
                            n.text_color = color
                    else:
                        setattr(n.style, c, color)
                    n.touch()
        self.refresh()
