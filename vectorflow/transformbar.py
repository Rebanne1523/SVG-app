"""X / Y / W / H of the selection, measured from the top-left corner of its sheet (0, 0)."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QToolBar, QToolButton

from .numfield import NumField
from . import affine
from .model import common_ancestors_pruned


class TransformBar:
    def __init__(self, get_canvas):
        self.get_canvas = get_canvas
        self._silent = False
        self.bar = QToolBar("Position and size")
        self.bar.setMovable(False)
        self.spins = {}
        self.bar.addWidget(QLabel(" Position on sheet "))
        for key, label in (("x", "X"), ("y", "Y")):
            self._add(key, label)
        self.bar.addSeparator()
        for key, label in (("w", "W"), ("h", "H")):
            self._add(key, label)
        self.link = QToolButton()
        self.link.setText("⛓")
        self.link.setCheckable(True)
        self.link.setChecked(True)
        self.link.setToolTip("Keep proportions when changing W or H")
        self.bar.addWidget(self.link)

    @property
    def doc(self):
        return self.get_canvas().doc

    def _add(self, key, label):
        self.bar.addWidget(QLabel(f" {label} "))
        sp = NumField()
        sp.setRange(-1e7, 1e7)
        sp.setDecimals(2)
        sp.setSingleStep(1.0)
        sp.setMinimumWidth(92)
        sp.setKeyboardTracking(False)
        sp.setToolTip({"x": "Distance from the sheet's left edge to the left of the selection",
                       "y": "Distance from the sheet's top edge to the top of the selection",
                       "w": "Width", "h": "Height"}[key])
        sp.valueChanged.connect(lambda v, k=key: self._edited(k, v))
        self.bar.addWidget(sp)
        self.spins[key] = sp

    # ------------------------------------------------------------ reading
    def _measure(self):
        sel = common_ancestors_pruned(self.doc.selection)
        if not sel:
            return None
        r = self.doc.bounds_of(sel)
        sh = self.doc.sheet_of(sel[0])
        ox, oy = (sh.x, sh.y) if sh is not None else (0.0, 0.0)
        return sel, r, ox, oy

    def refresh(self):
        m = self._measure()
        self._silent = True
        try:
            for sp in self.spins.values():
                sp.setEnabled(m is not None)
            self.link.setEnabled(m is not None)
            if m is None:
                return
            _, r, ox, oy = m
            self.spins["x"].setValue(r.x() - ox)
            self.spins["y"].setValue(r.y() - oy)
            self.spins["w"].setValue(r.width())
            self.spins["h"].setValue(r.height())
        finally:
            self._silent = False

    # ------------------------------------------------------------ editing
    def _edited(self, key, value):
        if self._silent:
            return
        m = self._measure()
        if m is None:
            return
        sel, r, ox, oy = m
        movable = [n for n in sel if not n.locked and not any(a.locked for a in n.ancestors())]
        if not movable:
            return
        if key in ("x", "y"):
            dx = (value + ox - r.x()) if key == "x" else 0.0
            dy = (value + oy - r.y()) if key == "y" else 0.0
            mat = affine.translate(dx, dy)
        else:
            sx = sy = 1.0
            if key == "w" and r.width() > 1e-9 and value > 0:
                sx = value / r.width()
                sy = sx if self.link.isChecked() else 1.0
            elif key == "h" and r.height() > 1e-9 and value > 0:
                sy = value / r.height()
                sx = sy if self.link.isChecked() else 1.0
            if sx == 1.0 and sy == 1.0:
                return
            mat = affine.about((sx, 0.0, 0.0, sy, 0.0, 0.0), r.x(), r.y())   # grow from the top-left corner
        with self.doc.edit(merge_key="xform"):
            for n in movable:
                n.transform(mat, self.get_canvas().scale_strokes)
