"""The style bar: colours, stroke, dashes, caps, arrows, fonts and measurement options."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFontComboBox, QLabel, QToolBar,
                               QToolButton, QWidget)

from .numfield import NumField
from .icons import preview_icon
from .model import ARROW_TYPES, CAPS, DASH_PRESETS, JOINS, leaves, qcolor


class ColorButton(QToolButton):
    colorChanged = Signal(object)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self._color = None
        self.setFixedSize(34, 26)
        self.setToolTip(f"{title} colour (click to change)")
        self.clicked.connect(self._pick)
        self._paint()

    def color(self):
        return self._color

    def set_color(self, c):
        self._color = tuple(c) if c else None
        self._paint()

    def _paint(self):
        pm = QPixmap(30, 22)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        # checkerboard
        for i in range(0, 30, 6):
            for j in range(0, 22, 6):
                p.fillRect(i, j, 6, 6, QColor(150, 150, 150) if (i // 6 + j // 6) % 2 else QColor(100, 100, 100))
        if self._color:
            p.fillRect(0, 0, 30, 22, qcolor(self._color))
        else:
            p.fillRect(0, 0, 30, 22, QColor(70, 70, 70))
            p.setPen(QColor(230, 60, 60))
            p.drawLine(2, 20, 28, 2)
        p.setPen(QColor(20, 20, 20))
        p.setBrush(Qt.NoBrush)
        p.drawRect(0, 0, 29, 21)
        p.end()
        self.setIcon(QIcon(pm))
        self.setIconSize(QSize(30, 22))

    def _pick(self):
        start = qcolor(self._color) if self._color else QColor(0, 0, 0)
        c = QColorDialog.getColor(start, self, f"{self.title} colour", QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self._color = (c.red(), c.green(), c.blue(), c.alpha())
            self._paint()
            self.colorChanged.emit(self._color)


def combo_with_icons(kind, values, labels=None, width=96):
    cb = QComboBox()
    cb.setIconSize(QSize(56, 20))
    for i, v in enumerate(values):
        cb.addItem(preview_icon(kind, v), "" if kind != "dash" else "", v)
        cb.setItemData(i, labels[i] if labels else v.title(), Qt.ToolTipRole)
    cb.setMinimumWidth(width)
    return cb


# measurement settings that follow the "apply to all measurements" checkbox
MEASURE_GLOBAL = {"width", "stroke", "dash", "cap", "arrow_size", "arrow_kind", "size", "family", "bold",
                  "italic", "text_color"}


class StyleBar:
    """Owns two toolbars: row 1 = vector style, row 2 = text / measurement options."""

    def __init__(self, win, get_canvas):
        self.win = win
        self.get_canvas = get_canvas
        self._silent = False
        self._acts = {}
        self.bar1 = QToolBar("Style")
        self.bar2 = QToolBar("Text and measurement")
        self.bar3 = QToolBar("Measurement project settings")
        for b in (self.bar1, self.bar2, self.bar3):
            b.setMovable(False)
            b.setIconSize(QSize(20, 20))
        self._build_row1()
        self._build_row2()

    @property
    def doc(self):
        return self.get_canvas().doc

    # ------------------------------------------------------------ building
    def _add(self, bar, w):
        self._acts[w] = bar.addWidget(w)
        return w

    def _lab(self, bar, text):
        l = QLabel(f" {text} ")
        self._add(bar, l)
        return l

    def _build_row1(self):
        b = self.bar1
        self.fill_lbl = self._lab(b, "Fill")
        self.fill = ColorButton("Fill")
        self.fill.colorChanged.connect(lambda c: self._apply(fill=c))
        self._add(b, self.fill)
        self.fill_none = QToolButton()
        self.fill_none.setText("∅")
        self.fill_none.setToolTip("No fill")
        self.fill_none.clicked.connect(lambda: self._set_color("fill", None))
        self._add(b, self.fill_none)
        self.stroke_lbl = self._lab(b, "Stroke")
        self.stroke = ColorButton("Stroke")
        self.stroke.colorChanged.connect(lambda c: self._apply(stroke=c))
        self._add(b, self.stroke)
        self.stroke_none = QToolButton()
        self.stroke_none.setText("∅")
        self.stroke_none.setToolTip("No stroke")
        self.stroke_none.clicked.connect(lambda: self._set_color("stroke", None))
        self._add(b, self.stroke_none)
        b.addSeparator()
        self._lab(b, "Width")
        self.width = NumField()
        self.width.setRange(0.0, 1000.0)
        self.width.setDecimals(2)
        self.width.setSingleStep(0.5)
        self.width.setSuffix(" px")
        self.width.valueChanged.connect(lambda v: self._apply(merge="width", width=v))
        self._add(b, self.width)
        self._lab(b, "Line")
        self.dash = combo_with_icons("dash", list(DASH_PRESETS), width=86)
        self.dash.setToolTip("Line type: solid, dashed, dotted ...")
        self.dash.currentIndexChanged.connect(self._dash_changed)
        self._add(b, self.dash)
        self._lab(b, "Ends")
        self.cap = combo_with_icons("cap", CAPS, ["Butt (flat) end", "Round end", "Square end"], 78)
        self.cap.setToolTip("Line end: flat / round / square")
        self.cap.currentIndexChanged.connect(lambda i: self._apply(cap=self.cap.itemData(i)))
        self._add(b, self.cap)
        self._lab(b, "Corners")
        self.join = combo_with_icons("join", JOINS, ["Sharp corner", "Round corner", "Bevel corner"], 78)
        self.join.currentIndexChanged.connect(lambda i: self._apply(join=self.join.itemData(i)))
        self._add(b, self.join)
        b.addSeparator()
        self.arrow_lbl = self._lab(b, "Start")
        self.arrow_start = combo_with_icons("arrow_start", ARROW_TYPES, width=86)
        self.arrow_start.setToolTip("Arrow at the start of the line")
        self.arrow_start.currentIndexChanged.connect(lambda i: self._arrow_changed("start", i))
        self._add(b, self.arrow_start)
        self.arrow_end_lbl = self._lab(b, "End")
        self.arrow_end = combo_with_icons("arrow_end", ARROW_TYPES, width=86)
        self.arrow_end.setToolTip("Arrow at the end of the line")
        self.arrow_end.currentIndexChanged.connect(lambda i: self._arrow_changed("end", i))
        self._add(b, self.arrow_end)
        self.arrow_size_lbl = self._lab(b, "Arrow size")
        self.arrow_size = NumField()
        self.arrow_size.setRange(0.2, 20.0)
        self.arrow_size.setSingleStep(0.1)
        self.arrow_size.setValue(1.0)
        self.arrow_size.valueChanged.connect(lambda v: self._apply(merge="asize", arrow_size=v))
        self._add(b, self.arrow_size)

    def _build_row2(self):
        b = self.bar2
        self.font_widgets = []
        self.font_lbl = self._lab(b, "Font")
        self.font = QFontComboBox()
        self.font.setMinimumWidth(170)
        self.font.currentFontChanged.connect(lambda f: self._apply(family=f.family()))
        self._add(b, self.font)
        self.size = NumField()
        self.size.setRange(1.0, 5000.0)
        self.size.setDecimals(1)
        self.size.setSuffix(" px")
        self.size.valueChanged.connect(lambda v: self._apply(merge="fsize", size=v))
        self.size_lbl = self._lab(b, "Size")
        self._add(b, self.size)
        self.bold = QToolButton()
        self.bold.setText("B")
        f = self.bold.font()
        f.setBold(True)
        self.bold.setFont(f)
        self.bold.setCheckable(True)
        self.bold.toggled.connect(lambda v: self._apply(bold=v))
        self._add(b, self.bold)
        self.italic = QToolButton()
        self.italic.setText("I")
        f = self.italic.font()
        f.setItalic(True)
        self.italic.setFont(f)
        self.italic.setCheckable(True)
        self.italic.toggled.connect(lambda v: self._apply(italic=v))
        self._add(b, self.italic)
        self.tcolor_lbl = self._lab(b, "Text colour")
        self.tcolor = ColorButton("Text")
        self.tcolor.colorChanged.connect(lambda c: self._apply(text_color=c or (0, 0, 0, 255)))
        self._add(b, self.tcolor)
        self.m_sep = b.addSeparator()
        self.mode_a_lbl = self._lab(b, "First end")
        self.mode_a = QComboBox()
        self.mode_a.addItem("Arrow on leg", "leg")
        self.mode_a.addItem("Arrow along line", "line")
        self.mode_a.currentIndexChanged.connect(lambda i: self._apply(mode_a=self.mode_a.itemData(i)))
        self._add(b, self.mode_a)
        self.mode_b_lbl = self._lab(b, "Second end")
        self.mode_b = QComboBox()
        self.mode_b.addItem("Arrow on leg", "leg")
        self.mode_b.addItem("Arrow along line", "line")
        self.mode_b.currentIndexChanged.connect(lambda i: self._apply(mode_b=self.mode_b.itemData(i)))
        self._add(b, self.mode_b)
        self.flip = QToolButton()
        self.flip.setText("Flip side")
        self.flip.setToolTip("Put the measurement on the other side")
        self.flip.clicked.connect(self._flip)
        self._add(b, self.flip)
        self.edit_text = QToolButton()
        self.edit_text.setText("Edit text…")
        self.edit_text.clicked.connect(self._edit_text)
        self._add(b, self.edit_text)
        self.all_chk = QCheckBox("Apply to all measurements")
        self.all_chk.setChecked(True)
        self.all_chk.setToolTip("On: size, thickness, colour, style, height and arrow distance edit every "
                                "measurement in the project. Off: only the selected one.")
        self._add(self.bar3, self.all_chk)
        self.height_lbl = self._lab(self.bar3, "Height")
        self.height = NumField()
        self.height.setRange(0.0, 100000.0)
        self.height.setDecimals(2)
        self.height.setSuffix(" px")
        self.height.setToolTip("Height of the U / L (distance from the measured points to the dimension line)")
        self.height.valueChanged.connect(lambda v: self._apply_geom("height", v))
        self._add(self.bar3, self.height)
        self.gap_lbl = self._lab(self.bar3, "Arrow distance")
        self.gapf = NumField()
        self.gapf.setRange(0.0, 100000.0)
        self.gapf.setDecimals(2)
        self.gapf.setSuffix(" px")
        self.gapf.setToolTip("How far each arrow sits from the point it measures")
        self.gapf.valueChanged.connect(lambda v: self._apply_geom("gap", v))
        self._add(self.bar3, self.gapf)
        self.link_chk = QCheckBox("Link height")
        self.link_chk.setChecked(True)
        self.link_chk.setToolTip("Linked: Height and Arrow distance follow the project-wide value. "
                                 "Unlinked: this measurement keeps its own.")
        self.link_chk.toggled.connect(self._link_toggled)
        self._add(self.bar3, self.link_chk)
        self.row3_measure = [self.all_chk, self.height_lbl, self.height, self.gap_lbl, self.gapf, self.link_chk]
        self.row2_measure = [self.m_sep, self.mode_a_lbl, self.mode_a, self.mode_b_lbl, self.mode_b, self.flip,
                             self.edit_text, self.tcolor_lbl, self.tcolor]
        self.row2_text = [self.font_lbl, self.font, self.size_lbl, self.size, self.bold, self.italic]

    def _set_vis(self, widgets, vis):
        for w in widgets:
            act = self._acts.get(w, w if not isinstance(w, QWidget) else None)
            if act is not None:
                act.setVisible(vis)

    # ------------------------------------------------------------ state
    def _selection_kinds(self):
        sel = self.doc.selection
        kinds = set()
        for n in sel:
            for l in (leaves(n) if n.is_group() else [n]):
                kinds.add(l.kind)
        return sel, kinds

    def refresh(self):
        doc = self.doc
        sel, kinds = self._selection_kinds()
        tool = self.get_canvas().tool.name if self.get_canvas().tool else ""
        self._silent = True
        try:
            first = None
            for n in sel:
                for l in (leaves(n) if n.is_group() else [n]):
                    first = l
                    break
                if first:
                    break
            st = first.style if first is not None and hasattr(first, "style") else doc.default_style
            self.fill.set_color(st.fill)
            self.stroke.set_color(st.stroke)
            self.width.setValue(st.width)
            dn = st.dash_name()
            for i in range(self.dash.count()):
                if self.dash.itemData(i) == dn:
                    self.dash.setCurrentIndex(i)
            self.cap.setCurrentIndex(max(0, CAPS.index(st.cap)))
            self.join.setCurrentIndex(max(0, JOINS.index(st.join)))
            if first is not None and first.kind == "measure":
                self.arrow_start.setCurrentIndex(0)
                self.arrow_end.setCurrentIndex(ARROW_TYPES.index(first.arrow_kind))
            else:
                self.arrow_start.setCurrentIndex(ARROW_TYPES.index(st.arrow_start))
                self.arrow_end.setCurrentIndex(ARROW_TYPES.index(st.arrow_end))
            self.arrow_size.setValue(st.arrow_size)
            if first is not None and first.kind in ("text", "measure"):
                self.font.setCurrentFont(QFont(first.family))
                self.size.setValue(first.size if first.kind == "text" else first.font_size)
                self.bold.setChecked(first.bold)
                self.italic.setChecked(first.italic)
            else:
                td = self.get_canvas().text_defaults
                self.font.setCurrentFont(QFont(td["family"]))
                self.size.setValue(td["size"])
                self.bold.setChecked(td["bold"])
                self.italic.setChecked(td["italic"])
            if first is not None and first.kind == "measure":
                self.tcolor.set_color(first.text_color)
                self.mode_a.setCurrentIndex(0 if first.mode_a == "leg" else 1)
                self.mode_b.setCurrentIndex(0 if first.mode_b == "leg" else 1)
                self.height.setValue(abs(first.offset))
                self.gapf.setValue(first.gap_a)
                self.link_chk.setChecked(first.linked)
        finally:
            self._silent = False
        has_measure = "measure" in kinds
        has_text = "text" in kinds
        only_measure = bool(kinds) and kinds == {"measure"}
        text_ctx = has_text or has_measure or tool in ("text", "measure")
        self.bar2.setVisible(text_ctx)
        self._set_vis(self.row2_measure, has_measure)
        self.bar3.setVisible(has_measure)
        self._set_vis([self.fill_lbl, self.fill, self.fill_none], not only_measure)
        arrows_ok = (not kinds) or bool(kinds & {"path", "measure"})
        self._set_vis([self.arrow_end_lbl, self.arrow_end, self.arrow_size_lbl, self.arrow_size], arrows_ok)
        self._set_vis([self.arrow_lbl, self.arrow_start], arrows_ok and not only_measure)
        self.arrow_end_lbl.setText(" Arrow " if only_measure else " End ")

    # ------------------------------------------------------------ applying
    def _apply(self, merge=None, **kv):
        if self._silent:
            return
        doc = self.doc
        sel = doc.selection
        if sel:
            gk = {k: v for k, v in kv.items() if k in MEASURE_GLOBAL}
            allm = self._all_measures() if gk and self.all_chk.isChecked() and self._sel_measures() else []
            if allm and not self._others_selected():
                nodes = list(sel) + [m for m in allm if m not in self._sel_measures()]
                doc.apply_style(nodes, merge_key=merge, **kv)
            else:
                doc.apply_style(sel, merge_key=merge, **kv)
                if allm:
                    doc.apply_style(allm, merge_key=merge, **gk)
            # new shapes keep using the last style the user picked (like Illustrator / Photoshop)
            if any(l.kind == "path" for n in sel for l in (leaves(n) if n.is_group() else [n])):
                for k, v in kv.items():
                    if k in doc.default_style.__dict__:
                        setattr(doc.default_style, k, list(v) if isinstance(v, list) else v)
        else:
            canvas = self.get_canvas()
            td = canvas.text_defaults
            for k, v in kv.items():
                if k in ("family", "bold", "italic"):
                    td[k] = v
                elif k == "size":
                    td["size"] = v
                elif k in doc.default_style.__dict__:
                    setattr(doc.default_style, k, v)
        self.refresh_silent_dependents()

    def refresh_silent_dependents(self):
        pass

    def _set_color(self, which, c):
        getattr(self, which).set_color(c)
        self._apply(**{which: c})

    def _dash_changed(self, i):
        if self._silent:
            return
        name = self.dash.itemData(i)
        extra = {}
        if name in ("dotted", "dash-dot"):
            extra["cap"] = "round"
        elif name in ("dashed", "long dash", "solid"):
            pass
        self._apply(dash=list(DASH_PRESETS[name]), **extra)
        if extra:
            self._silent = True
            self.cap.setCurrentIndex(CAPS.index("round"))
            self._silent = False

    def _arrow_changed(self, which, i):
        if self._silent:
            return
        v = ARROW_TYPES[i]
        sel = self.doc.selection
        measures = []
        others = []
        for n in sel:
            for l in (leaves(n) if n.is_group() else [n]):
                (measures if l.kind == "measure" else others).append(l)
        if measures:
            self.doc.apply_style(measures, arrow_kind=v if v != "none" else "triangle")
        if others or not sel:
            self._apply(**{"arrow_" + which: v})

    def _sel_measures(self):
        return [l for n in self.doc.selection for l in (leaves(n) if n.is_group() else [n]) if l.kind == "measure"]

    def _others_selected(self):
        return any(l.kind != "measure" for n in self.doc.selection for l in (leaves(n) if n.is_group() else [n]))

    def _all_measures(self):
        return [l for l in leaves(self.doc.root) if l.kind == "measure"]

    def _apply_geom(self, what, v):
        if self._silent:
            return
        sel = self._sel_measures()
        if not sel:
            return
        targets = list(sel)
        if self.all_chk.isChecked() and all(m.linked for m in sel):
            targets += [m for m in self._all_measures() if m.linked and m not in sel]
        with self.doc.edit(merge_key="mgeom-" + what):
            for m in targets:
                if what == "height":
                    m.offset = v if m.offset >= 0 else -v
                else:
                    m.gap_a = m.gap_b = v
                m.touch()

    def _link_toggled(self, on):
        if self._silent:
            return
        sel = self._sel_measures()
        if not sel:
            return
        with self.doc.edit():
            for m in sel:
                m.linked = on

    def _flip(self):
        sel = [l for n in self.doc.selection for l in (leaves(n) if n.is_group() else [n]) if l.kind == "measure"]
        if not sel:
            return
        with self.doc.edit():
            for m in sel:
                m.offset = -m.offset
                m.touch()

    def _edit_text(self):
        sel = [l for n in self.doc.selection for l in (leaves(n) if n.is_group() else [n]) if l.kind in ("measure", "text")]
        if sel:
            self.get_canvas().edit_node_text(sel[0])

    # shortcuts
    def swap(self):
        f, s = self.fill.color(), self.stroke.color()
        self._silent = True
        self.fill.set_color(s)
        self.stroke.set_color(f)
        self._silent = False
        self._apply(fill=s, stroke=f)

    def defaults(self):
        self._silent = True
        self.fill.set_color(None)
        self.stroke.set_color((0, 0, 0, 255))
        self._silent = False
        self._apply(fill=None, stroke=(0, 0, 0, 255))
