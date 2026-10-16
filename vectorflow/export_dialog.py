"""Export dialog: pick pages (with previews) or the current selection; drag one page onto another
to export them together as a single multi-page PDF."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QPushButton,
                               QRadioButton, QVBoxLayout)

from .render import sheet_thumbnail

TILE = QSize(210, 175)


def unit_icon(sheets):
    """Preview of one export unit: its pages fanned out like a small stack."""
    pm = QPixmap(TILE.width() - 20, 140)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    shown = sheets[:3]
    off = 14
    box_w = pm.width() - off * (len(shown) - 1)
    box_h = pm.height() - off * (len(shown) - 1)
    for i, sh in enumerate(shown):
        img = sheet_thumbnail(sh, box_w, box_h)
        x, y = i * off, i * off
        p.fillRect(x + 3, y + 3, img.width(), img.height(), QColor(0, 0, 0, 80))
        p.drawImage(x, y, img)
        p.setPen(QPen(QColor(110, 110, 115), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(x, y, img.width() - 1, img.height() - 1)
    p.end()
    return QIcon(pm)


class UnitList(QListWidget):
    """Tiles of pages. Dropping tiles onto another tile merges them into one export unit."""

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(TILE.width() - 20, 140))
        self.setGridSize(TILE)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Snap)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setWordWrap(True)
        self.setSpacing(4)

    def dropEvent(self, e):
        target = self.itemAt(e.position().toPoint())
        dragged = [i for i in self.selectedItems() if i is not target]
        e.setDropAction(Qt.IgnoreAction)
        e.accept()
        if target is not None and dragged and self.dialog.merge_allowed():
            self.dialog.merge(dragged, target)


class ExportDialog(QDialog):
    def __init__(self, parent, doc):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.resize(820, 600)
        self.doc = doc
        self.units = [[s] for s in doc.sheets()]          # list of lists of Sheet
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.r_pages = QRadioButton("Pages")
        self.r_sel = QRadioButton("Selection only")
        self.r_pages.setChecked(True)
        self.r_sel.setEnabled(bool(doc.selection))
        if not doc.selection:
            self.r_sel.setToolTip("Select something on the canvas first")
        top.addWidget(QLabel("Export:"))
        top.addWidget(self.r_pages)
        top.addWidget(self.r_sel)
        top.addStretch(1)
        top.addWidget(QLabel("Format:"))
        self.fmt = QComboBox()
        for key, label in (("pdf", "PDF (vector)"), ("svg", "SVG"), ("png", "PNG")):
            self.fmt.addItem(label, key)
        top.addWidget(self.fmt)
        self.scale_lbl = QLabel("Scale:")
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.1, 20)
        self.scale.setValue(1.0)
        self.scale.setDecimals(2)
        top.addWidget(self.scale_lbl)
        top.addWidget(self.scale)
        lay.addLayout(top)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9aa;")
        lay.addWidget(self.hint)

        self.list = UnitList(self)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.sep_btn = QPushButton("Separate selected")
        self.sep_btn.setToolTip("Undo the merge of the selected tile(s)")
        self.sep_btn.clicked.connect(self.separate)
        self.all_btn = QPushButton("Select all")
        self.all_btn.clicked.connect(self.list.selectAll)
        row.addWidget(self.all_btn)
        row.addWidget(self.sep_btn)
        row.addStretch(1)
        lay.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.ok_btn = bb.addButton("Export…", QDialogButtonBox.AcceptRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.fmt.currentIndexChanged.connect(self._format_changed)
        self.r_pages.toggled.connect(self._mode_changed)
        self.list.itemSelectionChanged.connect(self._update_ok)
        self.rebuild(select_current=True)
        self._format_changed()

    # ------------------------------------------------------------ state
    def format(self):
        return self.fmt.currentData()

    def mode(self):
        return "pages" if self.r_pages.isChecked() else "selection"

    def merge_allowed(self):
        return self.mode() == "pages" and self.format() == "pdf"

    def _format_changed(self):
        png = self.format() == "png"
        self.scale.setVisible(png)
        self.scale_lbl.setVisible(png)
        if not self.merge_allowed():
            self.separate_all()
        self._update_hint()

    def _mode_changed(self):
        pages = self.mode() == "pages"
        self.list.setEnabled(pages)
        self.sep_btn.setEnabled(pages)
        self.all_btn.setEnabled(pages)
        self._update_hint()
        self._update_ok()

    def _update_hint(self):
        if self.mode() == "selection":
            self.hint.setText("Only the selected objects are exported, cropped to their bounding box.")
        elif self.format() == "pdf":
            self.hint.setText("Select the pages to export. Each one is saved with the name of the file it was "
                              "imported from. To export several pages as ONE multi-page PDF, drag a page tile "
                              "onto another.")
        else:
            self.hint.setText("Select the pages to export; each one is saved as its own file with its "
                              "original name. (Merging pages into one file is only possible for PDF.)")

    def _update_ok(self):
        self.ok_btn.setEnabled(self.mode() == "selection" or bool(self.list.selectedItems()))

    # ------------------------------------------------------------ tiles
    def rebuild(self, select_current=False, keep=None):
        cur = self.doc.current_sheet()
        self.list.clear()
        for unit in self.units:
            it = QListWidgetItem(unit_icon(unit), self._label(unit))
            it.setData(Qt.UserRole, id(unit))
            it.setTextAlignment(Qt.AlignHCenter)
            it.setToolTip("\n".join(s.name for s in unit))
            self.list.addItem(it)
            if (select_current and cur in unit) or (keep is not None and unit is keep):
                it.setSelected(True)
        self._update_ok()

    @staticmethod
    def _label(unit):
        if len(unit) == 1:
            return unit[0].name
        return f"{unit[0].name}\n+ {len(unit) - 1} more page(s)"

    def _unit_of(self, item):
        uid = item.data(Qt.UserRole)
        return next((u for u in self.units if id(u) == uid), None)

    def merge(self, dragged_items, target_item):
        target = self._unit_of(target_item)
        moved = [self._unit_of(i) for i in dragged_items]
        for u in moved:
            if u is None or u is target:
                continue
            target.extend(u)
            self.units.remove(u)
        self.rebuild(keep=target)

    def separate(self):
        new_units = []
        for u in self.units:
            if any(self._unit_of(i) is u for i in self.list.selectedItems()) and len(u) > 1:
                new_units.extend([s] for s in u)
            else:
                new_units.append(u)
        self.units = new_units
        self.rebuild()

    def separate_all(self):
        if any(len(u) > 1 for u in self.units):
            self.units = [[s] for u in self.units for s in u]
            self.rebuild()

    # ------------------------------------------------------------ result
    def chosen_units(self):
        sel = {id(self._unit_of(i)) for i in self.list.selectedItems()}
        return [u for u in self.units if id(u) in sel]
