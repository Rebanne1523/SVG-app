"""List of the project's sheets (pages). Selecting one makes it the current sheet: the layers panel then
shows only what is on that sheet."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QListWidget, QListWidgetItem, QMenu, QToolButton,
                               QVBoxLayout, QWidget)

from .icons import ui_icon


class SheetsPanel(QWidget):
    zoomRequested = Signal(object)

    def __init__(self, get_doc, parent=None):
        super().__init__(parent)
        self.get_doc = get_doc
        self._syncing = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.list.setFrameShape(QListWidget.NoFrame)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setToolTip("Sheets of this project. Click one to work on it; double-click to zoom to it.\n"
                             "Drag a sheet's name tag on the canvas to move it.")
        lay.addWidget(self.list, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 3, 6, 3)
        bar.setSpacing(2)
        add = QToolButton()
        add.setIcon(ui_icon("plus", 18))
        add.setIconSize(QSize(18, 18))
        add.setAutoRaise(True)
        add.setToolTip("Add a blank sheet")
        add.clicked.connect(self.add_sheet)
        rm = QToolButton()
        rm.setIcon(ui_icon("trash", 18))
        rm.setIconSize(QSize(18, 18))
        rm.setAutoRaise(True)
        rm.setToolTip("Delete the current sheet")
        rm.clicked.connect(self.delete_current)
        bar.addWidget(add)
        bar.addWidget(rm)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemDoubleClicked.connect(lambda it: self.zoomRequested.emit(self._sheet(it)))
        self.list.itemChanged.connect(self._renamed)
        self.list.model().rowsMoved.connect(self._reordered)
        self.list.customContextMenuRequested.connect(self._menu)
        self._doc = None
        self.set_document()

    def set_document(self):
        d = getattr(self, "_doc", None)
        if d is not None:
            for sig, slot in ((d.structureChanged, self.refresh), (d.sheetChanged, self.refresh),
                              (d.contentChanged, self.refresh_names)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._doc = self.get_doc()
        self._doc.structureChanged.connect(self.refresh)
        self._doc.sheetChanged.connect(self.refresh)
        self._doc.contentChanged.connect(self.refresh_names)
        self.refresh()

    # ------------------------------------------------------------ helpers
    def _sheet(self, item):
        sid = item.data(Qt.UserRole)
        return next((s for s in self.get_doc().sheets() if s.id == sid), None)

    def refresh(self):
        d = self.get_doc()
        self._syncing = True
        self.list.clear()
        cur = d.current_sheet()
        for s in d.sheets():
            it = QListWidgetItem(s.name)
            it.setData(Qt.UserRole, s.id)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            it.setToolTip(f"{s.width:g} × {s.height:g}" + (f"\nfrom {s.source}" if s.source else ""))
            self.list.addItem(it)
            if s is cur:
                self.list.setCurrentItem(it)
        self._syncing = False
        h = min(160, 26 * max(2, self.list.count()) + 40)
        self.setMaximumHeight(h)

    def refresh_names(self):
        self._syncing = True
        for i in range(self.list.count()):
            it = self.list.item(i)
            s = self._sheet(it)
            if s is not None and it.text() != s.name:
                it.setText(s.name)
        self._syncing = False

    # ------------------------------------------------------------ interaction
    def _row_changed(self, row):
        if self._syncing or row < 0:
            return
        s = self._sheet(self.list.item(row))
        if s is not None:
            d = self.get_doc()
            d.set_selection([])
            d.set_current_sheet(s)

    def _renamed(self, item):
        if self._syncing:
            return
        s = self._sheet(item)
        text = item.text().strip()
        if s is not None and text and text != s.name:
            d = self.get_doc()
            with d.edit():
                s.name = text

    def _reordered(self, *args):
        if self._syncing:
            return
        d = self.get_doc()
        order = [self._sheet(self.list.item(i)) for i in range(self.list.count())]
        if None in order or [s.id for s in order] == [s.id for s in d.sheets()]:
            return
        with d.edit(structure=True):
            d.root.children = order

    def add_sheet(self):
        d = self.get_doc()
        cur = d.current_sheet()
        w, h = (cur.width, cur.height) if cur else (1920.0, 1080.0)
        ppu = cur.pt_per_unit if cur else 0.75
        with d.edit(structure=True):
            d.new_sheet(width=w, height=h, pt_per_unit=ppu)
        d.set_selection([])
        d.sheetChanged.emit()
        d.selectionChanged.emit()

    def delete_current(self):
        d = self.get_doc()
        cur = d.current_sheet()
        if cur is not None:
            d.delete_sheet(cur)

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        m = QMenu(self)
        m.addAction("Add blank sheet", self.add_sheet)
        if it is not None:
            s = self._sheet(it)
            m.addAction("Rename\tF2", lambda: self.list.editItem(it))
            m.addAction("Zoom to sheet", lambda: self.zoomRequested.emit(s))
            m.addAction("Delete sheet", lambda: self.get_doc().delete_sheet(s))
        m.exec(self.list.viewport().mapToGlobal(pos))
