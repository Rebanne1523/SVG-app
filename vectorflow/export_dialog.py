"""Export dialog: pick pages (with previews) or the current selection; drag one page onto another
to export them together as a single multi-page PDF."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QPushButton, QTabBar, QToolButton, QVBoxLayout)

from .numfield import NumField
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
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)     # a plain click keeps only that tile
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setWordWrap(True)
        self.setSpacing(4)

    def mousePressEvent(self, e):
        # the little box on a tile adds / removes just that tile; Shift or Ctrl+click extend the selection
        it = self.itemAt(e.position().toPoint())
        if it is not None and e.button() == Qt.LeftButton and not (e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)):
            r = self.visualItemRect(it)
            if QRect(r.left(), r.top(), 26, 26).contains(e.position().toPoint()):
                it.setSelected(not it.isSelected())
                return
        super().mousePressEvent(e)

    def dropEvent(self, e):
        target = self.itemAt(e.position().toPoint())
        dragged = [i for i in self.selectedItems() if i is not target]
        e.setDropAction(Qt.IgnoreAction)
        e.accept()
        if target is not None and dragged and self.dialog.merge_allowed():
            self.dialog.merge(dragged, target)


class ExportDialog(QDialog):
    """Document / Page / Selection, page tiles with previews, folder + format, one big Export button."""

    def __init__(self, parent, doc, folder="", sel_name=""):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.resize(640, 640)
        self.doc = doc
        self.bg = None                                      # None = transparent
        self.units = [[s] for s in doc.sheets()]          # list of lists of Sheet
        self.names = {}                                    # custom file names: id(unit) / "doc" / "sel"
        self.sel_name = sel_name or "selection"
        lay = QVBoxLayout(self)

        self.tabs = QTabBar()
        self.tabs.setExpanding(True)
        self.tabs.setDrawBase(True)
        self.tabs.addTab("Single file")
        self.tabs.addTab("Batch export")
        self.tabs.setTabToolTip(0, "The whole document as one file, or just the current selection")
        self.tabs.setTabToolTip(1, "Several pages at once, each as its own file")
        self.tabs.setCurrentIndex(1)
        lay.addWidget(self.tabs)

        modes = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_btns = {}
        for key, label in (("document", "Document"), ("pages", "Page"), ("selection", "Selection")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setMinimumHeight(34)
            self.mode_group.addButton(b)
            self.mode_btns[key] = b
            modes.addWidget(b, 1)
        self.mode_btns["pages"].setChecked(True)
        self.mode_btns["pages"].hide()                      # reached through the "Batch export" tab
        self.mode_btns["selection"].setEnabled(bool(doc.selection))
        if not doc.selection:
            self.mode_btns["selection"].setToolTip("Select something on the canvas first")
        self.mode_btns["document"].setToolTip("Every sheet in one multi-page PDF")
        lay.addLayout(modes)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9aa;")
        lay.addWidget(self.hint)

        self.list = UnitList(self)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.all_btn = QPushButton("Select all")
        self.all_btn.clicked.connect(self.list.selectAll)
        self.sep_btn = QPushButton("Separate selected")
        self.sep_btn.setToolTip("Undo the merge of the selected tile(s)")
        self.sep_btn.clicked.connect(self.separate)
        row.addWidget(self.all_btn)
        row.addWidget(self.sep_btn)
        row.addStretch(1)
        self.preview = QCheckBox("Preview")
        self.preview.setChecked(True)
        self.preview.setToolTip("Show a thumbnail of every page (turn off for very heavy documents)")
        row.addWidget(self.preview)
        self.only_sel = QCheckBox("Export only selection")
        self.only_sel.setEnabled(bool(doc.selection))
        row.addWidget(self.only_sel)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addStretch(1)
        self.bg_btn = QToolButton()
        self.bg_btn.setFixedSize(52, 28)
        self.bg_btn.setToolTip("Background colour (PNG and PDF). Transparent by default.")
        self.bg_btn.clicked.connect(self._pick_bg)
        row.addWidget(self.bg_btn)
        row.addWidget(QLabel("Background colour"))
        lay.addLayout(row)
        self._paint_bg()

        row = QHBoxLayout()
        row.addWidget(QLabel("File name"))
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._name_edited)
        row.addWidget(self.name_edit, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Prefix"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("added before every name")
        row.addWidget(self.prefix_edit, 1)
        row.addWidget(QLabel("Suffix"))
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("added after every name")
        row.addWidget(self.suffix_edit, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.folder_edit = QLineEdit(folder)
        self.folder_edit.setPlaceholderText("Folder to save into")
        row.addWidget(self.folder_edit, 1)
        fb = QToolButton()
        fb.setText("📁")
        fb.setToolTip("Choose folder")
        fb.clicked.connect(self._choose_folder)
        row.addWidget(fb)
        self.fmt = QComboBox()
        for key, label in (("pdf", "PDF (*.pdf)"), ("svg", "SVG (*.svg)"), ("png", "PNG (*.png)")):
            self.fmt.addItem(label, key)
        row.addWidget(self.fmt)
        self.scale_lbl = QLabel("Scale")
        self.scale = NumField()
        self.scale.setRange(0.1, 20)
        self.scale.setValue(1.0)
        self.scale.setDecimals(2)
        row.addWidget(self.scale_lbl)
        row.addWidget(self.scale)
        lay.addLayout(row)

        self.overwrite = QCheckBox("Overwrite existing files without asking")
        lay.addWidget(self.overwrite)

        self.ok_btn = QPushButton("Export")
        self.ok_btn.setMinimumHeight(36)
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        lay.addWidget(self.ok_btn)

        self.fmt.currentIndexChanged.connect(self._format_changed)
        self.mode_group.buttonToggled.connect(self._mode_changed)
        self.only_sel.toggled.connect(self._only_sel_toggled)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.preview.toggled.connect(lambda _on: self.rebuild(keep_selection=True))
        self.list.itemSelectionChanged.connect(self._sync_checks)
        self.list.itemDoubleClicked.connect(lambda _i: (self.name_edit.setFocus(), self.name_edit.selectAll()))
        self.folder_edit.textChanged.connect(self._update_ok)
        self.rebuild(select_current=True)
        self._format_changed()
        self._mode_changed()

    # ------------------------------------------------------------ state
    def format(self):
        return self.fmt.currentData()

    def mode(self):
        for k, b in self.mode_btns.items():
            if b.isChecked():
                return k
        return "pages"

    def folder(self):
        return self.folder_edit.text().strip()

    def merge_allowed(self):
        return self.mode() == "pages" and self.format() == "pdf"

    def _choose_folder(self):
        start = self.folder() or ""
        d = QFileDialog.getExistingDirectory(self, "Export to folder", start)     # the system's own dialog
        if d:
            self.folder_edit.setText(d)

    def _paint_bg(self):
        pm = QPixmap(48, 24)
        p = QPainter(pm)
        for i in range(0, 48, 8):
            for j in range(0, 24, 8):
                p.fillRect(i, j, 8, 8, QColor(170, 170, 170) if (i // 8 + j // 8) % 2 else QColor(110, 110, 110))
        if self.bg:
            p.fillRect(0, 0, 48, 24, QColor(*self.bg))
        p.end()
        self.bg_btn.setIcon(QIcon(pm))
        self.bg_btn.setIconSize(QSize(48, 24))

    def _pick_bg(self):
        start = QColor(*self.bg) if self.bg else QColor(255, 255, 255, 0)
        c = QColorDialog.getColor(start, self, "Background colour", QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.bg = None if c.alpha() == 0 else (c.red(), c.green(), c.blue(), c.alpha())
            self._paint_bg()

    def _only_sel_toggled(self, on):
        if on and self.mode_btns["selection"].isEnabled():
            self.mode_btns["selection"].setChecked(True)
        elif not on and self.mode() == "selection":
            self.mode_btns["pages"].setChecked(True)
        self.mode_btns["pages"].hide()                      # reached through the "Batch export" tab

    def _format_changed(self):
        png = self.format() == "png"
        self.scale.setVisible(png)
        self.scale_lbl.setVisible(png)
        if not self.merge_allowed():
            self.separate_all()
        self._update_hint()
        self._refresh_name()

    def _mode_changed(self, *_):
        m = self.mode()
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(1 if m == "pages" else 0)
        self.tabs.blockSignals(False)
        for key in ("document", "selection"):
            self.mode_btns[key].setVisible(m != "pages")
        for w in (self.list, self.all_btn, self.sep_btn, self.preview):
            w.setVisible(m == "pages")
        self.list.setEnabled(m == "pages")
        self.sep_btn.setEnabled(m == "pages")
        self.all_btn.setEnabled(m == "pages")
        self.only_sel.blockSignals(True)
        self.only_sel.setChecked(m == "selection")
        self.only_sel.blockSignals(False)
        self._update_hint()
        self._update_ok()
        self._refresh_name()

    def _tab_changed(self, i):
        if i == 1:
            self.mode_btns["pages"].setChecked(True)
        else:
            sel = self.mode_btns["selection"]
            (sel if sel.isEnabled() and self.doc.selection and self.only_sel.isChecked() else
             self.mode_btns["document"]).setChecked(True)

    def _update_hint(self):
        m = self.mode()
        if m == "selection":
            self.hint.setText("Only the selected objects are exported, cropped to their bounding box.")
        elif m == "document":
            self.hint.setText("Every sheet goes into one multi-page PDF." if self.format() == "pdf" else
                              "Each sheet is saved as its own file with its original name.")
        elif self.format() == "pdf":
            self.hint.setText("Pick the pages to export; each is saved with the name of the file it was imported "
                              "from. To export several pages as ONE multi-page PDF, drag a page tile onto another.")
        else:
            self.hint.setText("Pick the pages to export; each is saved as its own file with its original name. "
                              "(Merging pages is only possible for PDF.)")

    def _sync_checks(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.Checked if it.isSelected() else Qt.Unchecked)
        self._update_ok()
        self._refresh_name()

    # ------------------------------------------------------------ file names
    def _name_key(self):
        """Key of the single export target whose name the field edits (None = several / none)."""
        m = self.mode()
        if m == "selection":
            return "sel"
        if m == "document":
            return "doc" if self.format() == "pdf" else None
        sel = self.list.selectedItems()
        if len(sel) == 1:
            u = self._unit_of(sel[0])
            return id(u) if u is not None else None
        return None

    def _default_name(self, key):
        if key == "sel":
            return self.sel_name
        if key == "doc":
            return self.units[0][0].name if self.units else ""
        u = next((u for u in self.units if id(u) == key), None)
        return u[0].name if u else ""

    def _refresh_name(self):
        key = getattr(self, "name_edit", None) and self._name_key()
        if not hasattr(self, "name_edit"):
            return
        self.name_edit.blockSignals(True)
        if key is None:
            self.name_edit.setEnabled(False)
            self.name_edit.setText("")
            self.name_edit.setPlaceholderText("Each file keeps its own name (select one page to rename it)")
        else:
            self.name_edit.setEnabled(True)
            self.name_edit.setText(self.names.get(key) or self._default_name(key))
            self.name_edit.setPlaceholderText("")
        self.name_edit.blockSignals(False)

    def _name_edited(self, text):
        key = self._name_key()
        if key is None:
            return
        self.names[key] = text
        if key not in ("sel", "doc"):
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.UserRole) == key:
                    u = self._unit_of(it)
                    it.setText(self._label(u))

    def _label_name(self, unit):
        return self.names.get(id(unit)) or unit[0].name

    def target_names(self, units):
        """Custom names matching ``chosen_units()`` / the selection export ("" = default)."""
        if self.mode() == "selection":
            return [self._decorated(self.names.get("sel", ""), self.sel_name)]
        if self.mode() == "document":
            if self.format() == "pdf":
                return [self._decorated(self.names.get("doc", ""), self._default_name("doc"))]
            return [self._decorated("", u[0].name) for u in units]
        return [self._decorated(self.names.get(id(u), ""), u[0].name) for u in units]

    def _decorated(self, custom, default):
        """Prefix and suffix around the file name; an untouched name stays "" (= the default)."""
        pre, suf = self.prefix_edit.text().strip(), self.suffix_edit.text().strip()
        if not (pre or suf):
            return custom
        return f"{pre}{custom or default}{suf}"

    def _update_ok(self, *_):
        ok = bool(self.folder()) and (self.mode() != "pages" or bool(self.list.selectedItems()))
        self.ok_btn.setEnabled(ok)

    # ------------------------------------------------------------ tiles
    def rebuild(self, select_current=False, keep=None, keep_selection=False):
        cur = self.doc.current_sheet()
        kept = {it.data(Qt.UserRole) for it in self.list.selectedItems()} if keep_selection else set()
        shown = self.preview.isChecked()
        self.list.setGridSize(TILE if shown else QSize(TILE.width(), 56))
        self.list.clear()
        for unit in self.units:
            it = QListWidgetItem(unit_icon(unit) if shown else QIcon(), self._label(unit))
            it.setData(Qt.UserRole, id(unit))
            it.setTextAlignment(Qt.AlignHCenter)
            it.setToolTip("\n".join(s.name for s in unit))
            it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
            self.list.addItem(it)
            if (select_current and cur in unit) or (keep is not None and unit is keep) or id(unit) in kept:
                it.setSelected(True)
        self._sync_checks()

    def _label(self, unit):
        name = self._label_name(unit)
        if len(unit) == 1:
            return name
        return f"{name}\n+ {len(unit) - 1} more page(s)"

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
        if self.mode() == "document":
            sheets = [s for u in self.units for s in u]
            return [sheets] if self.format() == "pdf" else [[s] for s in sheets]
        sel = {id(self._unit_of(i)) for i in self.list.selectedItems()}
        return [u for u in self.units if id(u) in sel]
