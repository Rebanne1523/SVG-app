"""Main window: menus, toolbox, option bars, layers dock and file handling."""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, QSettings, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QSplitter, QToolBar, QWidget, QLineEdit)

from .numfield import NumField
from . import __version__, affine
from .canvas import Canvas
from .icons import app_icon, tool_icon
from .layers_panel import LayersPanel
from .export_dialog import ExportDialog
from .exporting import FORMATS, export_selection, export_units, plan_unit_paths, safe_filename
from .model import Document, common_ancestors_pruned, fresh_copy
from .project import PROJECT_EXT, import_into, open_document, save_project
from .palette import PaletteBar
from .props import StyleBar
from .sheets_panel import SheetsPanel
from .svg_io import ImportError_
from .transformbar import TransformBar
from .tools_draw import PenTool, PencilTool, ShapeTool, TextTool
from .tools_canvas import CanvasTool
from .tools_other import BucketTool, HandTool, MeasureTool, ZoomTool
from .tools_select import DirectTool, SelectTool

OPEN_FILTER = ("Projects and vector files (*.vflow *.svg *.svgz *.pdf);;VectorFlow project (*.vflow);;"
               "SVG (*.svg *.svgz);;PDF (*.pdf);;All files (*)")
IMPORT_FILTER = "PDF and SVG (*.pdf *.svg *.svgz);;PDF (*.pdf);;SVG (*.svg *.svgz);;All files (*)"

SHORTCUTS_HELP = """
<h3>Tools (same letters as Photoshop where possible)</h3>
<table cellpadding=3>
<tr><td><b>V</b></td><td>Move / Select &mdash; drag handles to scale, hover just outside a corner to rotate</td></tr>
<tr><td><b>A</b></td><td>Direct Selection &mdash; edit points, handles and segments</td></tr>
<tr><td><b>P</b></td><td>Pen &mdash; click = corner, click-drag = curve, Enter = finish</td></tr>
<tr><td><b>B</b></td><td>Pencil (freehand, smoothed)</td></tr>
<tr><td><b>U</b> / <b>E</b> / <b>L</b></td><td>Rectangle / Ellipse / Line</td></tr>
<tr><td><b>T</b></td><td>Text</td></tr>
<tr><td><b>G</b></td><td>Paint Bucket (Alt+click recolours a shape)</td></tr>
<tr><td><b>I</b></td><td>Measure &mdash; A, B, offset, type the value; scroll flips the arrow</td></tr>
<tr><td><b>H</b> / <b>Z</b></td><td>Hand / Zoom (Space = temporary hand)</td></tr>
</table>
<h3>Sheets, files and export</h3>
<table cellpadding=3>
<tr><td><b>Ctrl+I</b></td><td>Import PDFs / SVGs: every page becomes its own sheet (named like the file)</td></tr>
<tr><td><b>Ctrl+S</b></td><td>Save the project (.vflow, all sheets in one file)</td></tr>
<tr><td><b>Ctrl+Shift+E</b></td><td>Export pages (pick them; drag one tile onto another for a multi-page PDF) or only the selection</td></tr>
<tr><td><b>Ctrl+V</b> / <b>Ctrl+Shift+V</b></td><td>Paste centred on the mouse / paste at the same position on the selected sheet</td></tr>
<tr><td><b>Ctrl+J</b> / <b>Ctrl+Shift+J</b></td><td>Combine paths into one compound path / break it apart</td></tr>
<tr><td><b>Ctrl+Shift+0</b></td><td>Zoom to the current sheet</td></tr>
<tr><td>Drag a sheet's name tag</td><td>Move the whole sheet. Drag a vector onto another sheet and it moves to that sheet.</td></tr>
<tr><td>Scroll over a point (A tool)</td><td>Grow / shrink the selection along the path, to both sides</td></tr>
</table>
<h3>Modifiers</h3>
<table cellpadding=3>
<tr><td><b>Shift</b></td><td>Constrain to 0/45/90&deg; while drawing or moving; proportional scale; 15&deg; steps when rotating</td></tr>
<tr><td><b>Alt</b></td><td>Draw/scale from the centre; Alt-drag copies; Alt+wheel zooms</td></tr>
<tr><td><b>Ctrl+wheel</b></td><td>Zoom at cursor (wheel scrolls, Shift+wheel scrolls sideways)</td></tr>
<tr><td><b>Arrows</b></td><td>Nudge selection (Shift = 10 px)</td></tr>
</table>
<h3>Edit</h3>
<table cellpadding=3>
<tr><td>Ctrl+Z / Ctrl+Shift+Z</td><td>Undo / Redo</td></tr>
<tr><td>Ctrl+C / X / V, Ctrl+D</td><td>Copy / Cut / Paste, Duplicate</td></tr>
<tr><td>Ctrl+G / Ctrl+Shift+G</td><td>Group into folder / Ungroup</td></tr>
<tr><td>Ctrl+] / Ctrl+[</td><td>Bring forward / send backward (add Shift for front / back)</td></tr>
<tr><td>X / D</td><td>Swap fill &amp; stroke / default colours</td></tr>
<tr><td>Ctrl+0 / Ctrl+1</td><td>Fit page / 100%</td></tr>
<tr><td>Ctrl+Shift+;</td><td>Toggle snapping</td></tr>
</table>
"""


def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(48, 49, 52))
    p.setColor(QPalette.WindowText, QColor(225, 225, 225))
    p.setColor(QPalette.Base, QColor(36, 37, 39))
    p.setColor(QPalette.AlternateBase, QColor(44, 45, 48))
    p.setColor(QPalette.ToolTipBase, QColor(30, 30, 30))
    p.setColor(QPalette.ToolTipText, QColor(235, 235, 235))
    p.setColor(QPalette.Text, QColor(225, 225, 225))
    p.setColor(QPalette.Button, QColor(62, 63, 67))
    p.setColor(QPalette.ButtonText, QColor(225, 225, 225))
    p.setColor(QPalette.BrightText, QColor(255, 80, 80))
    p.setColor(QPalette.Link, QColor(80, 170, 255))
    p.setColor(QPalette.Highlight, QColor(40, 110, 190))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(120, 120, 120))
    app.setPalette(p)
    app.setStyleSheet("""
        QToolTip { color: #eee; background: #1e1e1e; border: 1px solid #555; padding: 3px; }
        QToolBar { spacing: 3px; padding: 2px; border: 0; }
        QToolButton:checked { background: #2c6fb5; border-radius: 4px; }
        QToolButton:hover { background: #4a4b50; border-radius: 4px; }
        QDockWidget::title { padding: 6px; background: #3a3b3f; }
        QTreeView::item { padding: 2px 0; }
        QTreeView::item:selected { background: #2c6fb5; }
    """)


class NewDocDialog(QDialog):
    PRESETS = [("Custom", None), ("HD 1920 × 1080", (1920, 1080)), ("A4 portrait (794 × 1123)", (794, 1123)),
               ("A4 landscape (1123 × 794)", (1123, 794)), ("Square 1000 × 1000", (1000, 1000)),
               ("Letter portrait (816 × 1056)", (816, 1056))]

    def __init__(self, parent=None, w=1920, h=1080, title="New document"):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QFormLayout(self)
        self.preset = QComboBox()
        for name, _ in self.PRESETS:
            self.preset.addItem(name)
        self.w = NumField()
        self.h = NumField()
        for s in (self.w, self.h):
            s.setRange(1, 100000)
            s.setDecimals(2)
            s.setSuffix(" px")
        self.w.setValue(w)
        self.h.setValue(h)
        lay.addRow("Preset", self.preset)
        lay.addRow("Width", self.w)
        lay.addRow("Height", self.h)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.preset.currentIndexChanged.connect(self._preset)

    def _preset(self, i):
        v = self.PRESETS[i][1]
        if v:
            self.w.setValue(v[0])
            self.h.setValue(v[1])


class MainWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.setWindowIcon(app_icon())
        self.resize(1500, 920)
        self.doc = Document(1920, 1080)
        self.clipboard = []
        self.canvas = Canvas(self.doc)
        self.setCentralWidget(self.canvas)
        sysfont = QApplication.font().family()
        self.canvas.text_defaults["family"] = sysfont
        self._build_tools()
        self.layers = LayersPanel(lambda: self.doc)
        self.sheets_panel = SheetsPanel(lambda: self.doc)
        self.sheets_panel.zoomRequested.connect(lambda sh: self.canvas.fit_sheet(sh))
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.sheets_panel)
        split.addWidget(self.layers)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        dock = QDockWidget("Sheets and layers", self)
        dock.setWidget(split)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setMinimumWidth(270)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.layers_dock = dock
        self._build_bars()
        self._build_actions()
        self._build_status()
        self._wire_doc()
        self.canvas.set_tool("select")
        self._update_title()
        self.setAcceptDrops(True)
        if path:
            QTimer.singleShot(0, lambda: self.open_path(path))

    # ------------------------------------------------------------ building
    def _build_tools(self):
        c = self.canvas
        for t in (SelectTool(c), DirectTool(c), PenTool(c), PencilTool(c), ShapeTool(c, "rect"),
                  ShapeTool(c, "ellipse"), ShapeTool(c, "line"), TextTool(c), BucketTool(c), MeasureTool(c),
                  HandTool(c), ZoomTool(c), CanvasTool(c)):
            if t.name == "text":
                t.name, t.label, t.shortcut = "text", "Text", "T"
            c.register_tool(t)
        c.tools["ellipse"].shortcut = "E"
        c.tools["line"].shortcut = "L"
        c.tools["rect"].shortcut = "U"

    def _build_bars(self):
        # toolbox
        self.toolbox = QToolBar("Tools")
        self.toolbox.setOrientation(Qt.Vertical)
        self.toolbox.setIconSize(QSize(26, 26))
        self.toolbox.setMovable(False)
        self.addToolBar(Qt.LeftToolBarArea, self.toolbox)
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions = {}
        order = ["select", "direct", "pen", "pencil", None, "rect", "ellipse", "line", "text", None, "bucket",
                 "measure", "canvas", None, "hand", "zoom"]
        for name in order:
            if name is None:
                self.toolbox.addSeparator()
                continue
            t = self.canvas.tools[name]
            a = QAction(tool_icon(name, 26), t.label, self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(t.shortcut))
            a.setToolTip(f"{t.label}  ({t.shortcut})\n{t.hint}")
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(lambda checked=False, n=name: self.canvas.set_tool(n))
            self.tool_group.addAction(a)
            self.toolbox.addAction(a)
            self.tool_actions[name] = a
        # tool options bar (+ hint)
        self.opt_bar = QToolBar("Tool options")
        self.opt_bar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.opt_bar)
        self.opt_title = QLabel()
        self.opt_title.setStyleSheet("font-weight: bold; padding: 0 6px;")
        self.opt_title.setMinimumWidth(120)
        self.opt_bar.addWidget(self.opt_title)
        self.opt_holder = QWidget()
        self.opt_holder_lay = QHBoxLayout(self.opt_holder)
        self.opt_holder_lay.setContentsMargins(0, 0, 0, 0)
        self.opt_bar.addWidget(self.opt_holder)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.style_bar = StyleBar(self, lambda: self.canvas)
        self.addToolBar(Qt.TopToolBarArea, self.style_bar.bar1)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.style_bar.bar2)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.style_bar.bar3)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.xform = TransformBar(lambda: self.canvas)
        self.addToolBar(Qt.TopToolBarArea, self.xform.bar)
        self.colorbar = PaletteBar(self, lambda: self.canvas)
        self.addToolBar(Qt.BottomToolBarArea, self.colorbar.bar)
        self.canvas.toolChanged.connect(self._tool_changed)

    def _tool_changed(self, name):
        t = self.canvas.tools[name]
        self.tool_actions[name].setChecked(True)
        self.opt_title.setText(t.label)
        self.opt_title.setToolTip(t.hint)
        self.statusBar().showMessage(t.hint)
        while self.opt_holder_lay.count():
            it = self.opt_holder_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        w = t.options_widget(self.opt_holder)
        if w is not None:
            self.opt_holder_lay.addWidget(w)
        self.style_bar.refresh()

    def _act(self, menu, text, slot, shortcut=None, checkable=False, icon=None):
        a = QAction(text, self)
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        if checkable:
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda checked=False: slot())
        menu.addAction(a)
        return a

    def _build_actions(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._act(f, "&New project…", self.new_doc, "Ctrl+N")
        self._act(f, "&Open…", self.open_dialog, "Ctrl+O")
        self._act(f, "&Import PDF / SVG as sheets…", self.import_dialog, "Ctrl+I")
        f.addSeparator()
        self._act(f, "&Save project", self.save, "Ctrl+S")
        self._act(f, "Save project &as…", self.save_as, "Ctrl+Shift+S")
        f.addSeparator()
        self._act(f, "&Export…", self.export_dialog, "Ctrl+Shift+E")
        f.addSeparator()
        self._act(f, "&Quit", self.close, "Ctrl+Q")

        e = mb.addMenu("&Edit")
        self.undo_act = self._act(e, "&Undo", lambda: self.doc.undo(), "Ctrl+Z")
        self.redo_act = self._act(e, "&Redo", lambda: self.doc.redo(), ["Ctrl+Shift+Z", "Ctrl+Y"])
        e.addSeparator()
        self._act(e, "Cu&t", self.cut, "Ctrl+X")
        self._act(e, "&Copy", self.copy, "Ctrl+C")
        self._act(e, "&Paste (at the mouse)", lambda: self.paste(False), "Ctrl+V")
        self._act(e, "Paste in &place (same position on the sheet)", lambda: self.paste(True), "Ctrl+Shift+V")
        self._act(e, "&Duplicate", self.duplicate, "Ctrl+D")
        self._act(e, "De&lete", self.delete, ["Delete", "Backspace"])
        e.addSeparator()
        self._act(e, "Select &all", self.select_all, "Ctrl+A")
        self._act(e, "D&eselect", lambda: self.doc.set_selection([]), "Ctrl+Shift+A")
        e.addSeparator()
        self._act(e, "&Group into folder", lambda: self.layers.group_selection(), "Ctrl+G")
        self._act(e, "&Ungroup", lambda: self.layers.ungroup_selection(), "Ctrl+Shift+G")
        self._act(e, "Co&mbine paths", self.combine, "Ctrl+J")
        self._act(e, "Break &apart paths", self.break_apart, "Ctrl+Shift+J")
        ar = e.addMenu("&Arrange")
        self._act(ar, "Bring to front", lambda: self.arrange("front"), "Ctrl+Shift+]")
        self._act(ar, "Bring forward", lambda: self.arrange("forward"), "Ctrl+]")
        self._act(ar, "Send backward", lambda: self.arrange("backward"), "Ctrl+[")
        self._act(ar, "Send to back", lambda: self.arrange("back"), "Ctrl+Shift+[")
        tr = e.addMenu("&Transform")
        self._act(tr, "Flip horizontal", lambda: self.flip(True))
        self._act(tr, "Flip vertical", lambda: self.flip(False))
        self._act(tr, "Rotate 90° clockwise", lambda: self.rotate90(90))
        self._act(tr, "Rotate 90° counter-clockwise", lambda: self.rotate90(-90))
        e.addSeparator()
        self._act(e, "Swap fill and stroke", self.style_bar.swap, "X")
        self._act(e, "Default colours", self.style_bar.defaults, "D")

        v = mb.addMenu("&View")
        self._act(v, "Zoom &in", lambda: self.canvas.zoom_by(1.25), ["Ctrl+=", "Ctrl++"])
        self._act(v, "Zoom &out", lambda: self.canvas.zoom_by(0.8), "Ctrl+-")
        self._act(v, "&Fit page", self.canvas.fit_view, "Ctrl+0")
        self._act(v, "Zoom to &selection", self.canvas.fit_selection, "Ctrl+Alt+0")
        self._act(v, "&Actual size (100%)", lambda: self.canvas.set_zoom(1.0), "Ctrl+1")
        self._act(v, "Zoom to &sheet", lambda: self.canvas.fit_sheet(), "Ctrl+Shift+0")
        v.addSeparator()
        self.snap_act = self._act(v, "&Snapping", self._set_snap, "Ctrl+Shift+;", checkable=True)
        self.snap_act.setChecked(True)
        v.addAction(self.layers_dock.toggleViewAction())

        sm = mb.addMenu("S&heets")
        self._act(sm, "&Add blank sheet", self.sheets_panel.add_sheet)
        self._act(sm, "&Delete current sheet", self.sheets_panel.delete_current)
        self._act(sm, "Sheet &properties…", self.sheet_props)

        h = mb.addMenu("&Help")
        self._act(h, "&Keyboard shortcuts", self.show_help, "F1")
        self._act(h, "&About VectorFlow", self.about)

    def _build_status(self):
        sb = self.statusBar()
        self.coord_lbl = QLabel("x 0   y 0")
        self.coord_lbl.setMinimumWidth(130)
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setMinimumWidth(60)
        self.snap_chk = QCheckBox("Snap")
        self.snap_chk.setChecked(True)
        self.snap_chk.toggled.connect(self.snap_act.setChecked)
        sb.addPermanentWidget(self.snap_chk)
        sb.addPermanentWidget(self.coord_lbl)
        sb.addPermanentWidget(self.zoom_lbl)
        self.canvas.cursorMoved.connect(lambda x, y: self.coord_lbl.setText(f"x {x:.1f}   y {y:.1f}"))
        self.canvas.zoomChanged.connect(lambda z: self.zoom_lbl.setText(f"{z * 100:.0f}%"))
        self.canvas.message.connect(lambda m: self.statusBar().showMessage(m, 8000 if m else 1))

    def _set_snap(self, on):
        self.canvas.snap_enabled = on
        chk = getattr(self, "snap_chk", None)
        if chk is not None:
            chk.blockSignals(True)
            chk.setChecked(on)
            chk.blockSignals(False)
        self.canvas.clear_snap()
        self.canvas.update()

    def _wire_doc(self):
        d = self.doc
        d.selectionChanged.connect(self.style_bar.refresh)
        d.contentChanged.connect(self.style_bar.refresh)
        d.metaChanged.connect(self._update_title)
        d.restored.connect(self.style_bar.refresh)
        d.selectionChanged.connect(self.xform.refresh)
        d.contentChanged.connect(self.xform.refresh)
        d.restored.connect(self.xform.refresh)
        d.sheetChanged.connect(self._update_title)
        for sig in (d.selectionChanged, d.contentChanged, d.restored):
            sig.connect(self.colorbar.refresh)
        self.style_bar.refresh()
        self.colorbar.refresh()
        self.xform.refresh()

    def _unwire_doc(self):
        d = self.doc
        for sig, slot in ((d.selectionChanged, self.style_bar.refresh), (d.contentChanged, self.style_bar.refresh),
                          (d.metaChanged, self._update_title), (d.restored, self.style_bar.refresh),
                          (d.selectionChanged, self.xform.refresh), (d.contentChanged, self.xform.refresh),
                          (d.restored, self.xform.refresh), (d.sheetChanged, self._update_title),
                          (d.selectionChanged, self.colorbar.refresh), (d.contentChanged, self.colorbar.refresh),
                          (d.restored, self.colorbar.refresh)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def set_document(self, doc):
        self._unwire_doc()
        self.doc = doc
        self.canvas.set_document(doc)
        self.layers.set_document()
        self.sheets_panel.set_document()
        self._wire_doc()
        self._update_title()
        self.canvas.fit_view()
        self.canvas.set_tool(self.canvas.tool.name if self.canvas.tool else "select")

    def _update_title(self):
        name = os.path.basename(self.doc.path) if self.doc.path else (
            os.path.basename(self.doc.source) if self.doc.source else "Untitled")
        self.setWindowTitle(f"{'*' if self.doc.modified else ''}{name} — VectorFlow")

    # ------------------------------------------------------------ remembered folder
    @staticmethod
    def settings():
        return QSettings("VectorFlow", "VectorFlow")

    def last_dir(self):
        """Last folder used in any open / import / save / export dialog (default: Documents)."""
        d = self.settings().value("lastDir", "", type=str)
        if d and os.path.isdir(d):
            return d
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        return docs if docs and os.path.isdir(docs) else os.path.expanduser("~")

    def remember_dir(self, path):
        if not path:
            return
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder and os.path.isdir(folder):
            st = self.settings()
            st.setValue("lastDir", folder)
            st.sync()

    # ------------------------------------------------------------ files
    def maybe_save(self):
        if not self.doc.modified:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save changes before continuing?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return self.save()
        return True

    def new_doc(self):
        if not self.maybe_save():
            return
        dlg = NewDocDialog(self, title="New project (size of the first sheet)")
        if dlg.exec() == QDialog.Accepted:
            self.set_document(Document(dlg.w.value(), dlg.h.value()))

    def open_dialog(self):
        if not self.maybe_save():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Open", self.last_dir(), OPEN_FILTER)
        if paths:
            self.remember_dir(paths[0])
            self.open_paths(paths, check_save=False)

    def open_paths(self, paths, check_save=True):
        """Open files as a NEW project (every PDF page / SVG becomes a sheet)."""
        if isinstance(paths, str):
            paths = [paths]
        if check_save and not self.maybe_save():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc = open_document(paths)
        except (ImportError_, OSError, ValueError) as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Could not open file", str(e))
            return
        except Exception as e:  # corrupt PDF etc.
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Could not open file", f"{type(e).__name__}: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.remember_dir(paths[0])
        self.set_document(doc)
        if doc.warnings:
            self.statusBar().showMessage("Note: " + " ".join(doc.warnings), 12000)

    open_path = open_paths

    def import_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import as sheets", self.last_dir(), IMPORT_FILTER)
        if paths:
            self.remember_dir(paths[0])
            self.import_paths(paths)

    def import_paths(self, paths):
        """Add the pages of PDFs / SVGs to this project as independent sheets."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            added, warnings = import_into(self.doc, paths)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Could not import", f"{type(e).__name__}: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.remember_dir(paths[0])
        if added:
            self.canvas.fit_view()
            msg = f"Imported {len(added)} sheet(s)"
            if warnings:
                msg += ". Note: " + " ".join(warnings)
            self.statusBar().showMessage(msg, 10000)

    def save(self):
        if not self.doc.path:
            return self.save_as()
        return self._save_to(self.doc.path)

    def save_as(self):
        sheets = self.doc.sheets()
        base = safe_filename(sheets[0].name) if len(sheets) == 1 else "project"
        start = self.doc.path or os.path.join(self.last_dir(), base + PROJECT_EXT)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", start, "VectorFlow project (*.vflow)")
        if not path:
            return False
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT
        return self._save_to(path)

    def _save_to(self, path):
        try:
            save_project(self.doc, path)
        except OSError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return False
        self.remember_dir(path)
        self.doc.path = path
        self.doc.modified = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    # ------------------------------------------------------------ export
    def export_dialog(self):
        cur = self.doc.current_sheet()
        dlg = ExportDialog(self, self.doc, self.last_dir(), cur.name if cur else "")
        if dlg.exec() != QDialog.Accepted:
            return
        fmt = dlg.format()
        ext = fmt
        scale = dlg.scale.value()
        bg = dlg.bg
        folder = dlg.folder()
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Export", f"The folder does not exist:\n{folder}")
            return
        if dlg.mode() == "selection":
            nodes = common_ancestors_pruned(self.doc.selection)
            if not nodes:
                return
            sh = self.doc.sheet_of(nodes[0])
            fake = type("U", (), {"name": sh.name if sh else "selection"})()
            paths = plan_unit_paths([[fake]], folder, ext, dlg.target_names([[fake]]))
            job = lambda: export_selection(self.doc, nodes, paths[0], fmt, scale, bg)
        else:
            units = dlg.chosen_units()
            if not units:
                return
            paths = plan_unit_paths(units, folder, ext, dlg.target_names(units))
            job = lambda: export_units(self.doc, units, paths, fmt, scale, bg)
        clash = [os.path.basename(p) for p in paths if os.path.exists(p)]
        if clash:
            r = QMessageBox.question(self, "Overwrite?", "These files already exist and will be replaced:\n\n"
                                     + "\n".join(clash[:15]), QMessageBox.Yes | QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return
        self._run_export(job, paths)

    def _run_export(self, fn, paths):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            fn()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Export failed", f"{type(e).__name__}: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.remember_dir(paths[0])
        self.statusBar().showMessage(f"Exported {len(paths)} file(s) to {os.path.dirname(paths[0])}", 8000)

    def sheet_props(self):
        sh = self.doc.current_sheet()
        if sh is None:
            return
        dlg = NewDocDialog(self, sh.width, sh.height, f"Sheet properties \u2014 {sh.name}")
        name = QLineEdit(sh.name)
        dlg.layout().insertRow(0, "Name", name)
        if dlg.exec() == QDialog.Accepted:
            with self.doc.edit(structure=True):
                sh.width, sh.height = dlg.w.value(), dlg.h.value()
                sh.name = name.text().strip() or sh.name

    def closeEvent(self, e):
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith((".svg", ".svgz", ".pdf", PROJECT_EXT))]
        if len(paths) == 1 and paths[0].lower().endswith(PROJECT_EXT):
            self.open_paths(paths)                    # a dropped project opens as the project (Ctrl+S then just saves)
        elif paths:
            self.import_paths([q for q in paths if not q.lower().endswith(PROJECT_EXT)] or paths)

    # ------------------------------------------------------------ edit commands
    def delete(self):
        tool = self.canvas.tool
        if tool is not None and tool.on_delete():
            return
        sel = self.doc.selection
        if sel:
            self.doc.delete(sel)

    def select_all(self):
        d = self.doc
        container = d.active_container()
        nodes = [c for c in container.children if c.visible and not c.locked]
        d.set_selection(nodes)

    def combine(self):
        self.doc.combine(self.doc.selection)

    def break_apart(self):
        self.doc.break_apart(self.doc.selection)

    def copy(self):
        nodes = common_ancestors_pruned(self.doc.selection)
        if not nodes:
            return
        r = self.doc.bounds_of(nodes)
        sh = self.doc.sheet_of(nodes[0])
        ox, oy = (sh.x, sh.y) if sh is not None else (0.0, 0.0)
        self.clipboard = {"nodes": [fresh_copy(n) for n in nodes], "rect": QRectF(r),
                          "rel": (r.x() - ox, r.y() - oy)}
        self.statusBar().showMessage(f"Copied {len(nodes)} item(s)", 2500)

    def cut(self):
        self.copy()
        self.delete()

    def paste(self, in_place=False):
        """Ctrl+V pastes centred on the mouse; Ctrl+Shift+V keeps the same position relative to the
        top-left corner of the sheet (pasted into the sheet that is currently selected)."""
        cb = self.clipboard
        if not cb:
            return
        doc = self.doc
        rect = cb["rect"]
        if in_place:
            sheet = doc.current_sheet()
            tl = (sheet.x + cb["rel"][0], sheet.y + cb["rel"][1])
            dx, dy = tl[0] - rect.x(), tl[1] - rect.y()
        else:
            pos = self.canvas.last_mouse
            if pos is None:
                pos = self.canvas.to_doc((self.canvas.width() / 2, self.canvas.height() / 2))
            sheet = doc.sheet_at(pos) or doc.current_sheet()
            dx, dy = pos[0] - rect.center().x(), pos[1] - rect.center().y()
        out = []
        with doc.edit(structure=True):
            container = doc.layer_for_sheet(sheet)
            for n in cb["nodes"]:
                c = fresh_copy(n)
                c.transform(affine.translate(dx, dy))
                container.add(c)
                out.append(c)
        doc.set_selection(out)

    def duplicate(self):
        if self.doc.selection:
            self.doc.duplicate(self.doc.selection, (10.0, 10.0))

    def arrange(self, how):
        if self.doc.selection:
            self.doc.arrange(self.doc.selection, how)

    def _transform_sel(self, make):
        sel = self.doc.selection
        if not sel:
            return
        r = self.doc.bounds_of(sel)
        cx, cy = r.center().x(), r.center().y()
        m = affine.about(make(), cx, cy)
        with self.doc.edit():
            for n in sel:
                n.transform(m)

    def flip(self, horizontal):
        self._transform_sel(lambda: affine.scale(-1, 1) if horizontal else affine.scale(1, -1))

    def rotate90(self, deg):
        self._transform_sel(lambda: affine.rotate(deg))

    # ------------------------------------------------------------ help
    def show_help(self):
        m = QMessageBox(self)
        m.setWindowTitle("Keyboard shortcuts")
        m.setTextFormat(Qt.RichText)
        m.setText(SHORTCUTS_HELP)
        m.exec()

    def about(self):
        QMessageBox.about(self, "About VectorFlow",
                          f"<b>VectorFlow {__version__}</b><br>A vector editor built around an easy-to-use layer "
                          "system, quick snapping and measurement lines.<br>Opens SVG and PDF, saves SVG "
                          "(Inkscape-compatible layers).")


def main(argv=None):
    import sys
    argv = list(sys.argv if argv is None else argv)
    # Ask the desktop for its own file dialogs (Dolphin on KDE) through xdg-desktop-portal; the Qt that
    # ships with the app has no KDE platform theme of its own.
    if os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen", "minimal") \
            and os.environ.get("VECTORFLOW_QT_DIALOGS") != "1":
        os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
    app = QApplication(argv)
    app.setApplicationName("VectorFlow")
    app.setDesktopFileName("vectorflow")
    app.setWindowIcon(app_icon())
    apply_dark_theme(app)
    path = next((a for a in argv[1:] if not a.startswith("-")), None)
    w = MainWindow(path)
    w.show()
    return app.exec()
