"""Main window: menus, toolbox, option bars, layers dock and file handling."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
                               QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                               QMessageBox, QToolBar, QWidget, QDoubleSpinBox)

from . import __version__, affine
from .canvas import Canvas
from .icons import app_icon, tool_icon
from .layers_panel import LayersPanel
from .model import Document, fresh_copy
from .props import StyleBar
from .render import export_pdf, export_png
from .svg_io import ImportError_, load_document, pdf_page_count, save_svg
from .tools_draw import PenTool, PencilTool, ShapeTool, TextTool
from .tools_other import BucketTool, HandTool, MeasureTool, ZoomTool
from .tools_select import DirectTool, SelectTool

OPEN_FILTER = "Vector files (*.svg *.svgz *.pdf);;SVG (*.svg *.svgz);;PDF (*.pdf);;All files (*)"

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
<tr><td>Ctrl+C / X / V, Ctrl+J</td><td>Copy / Cut / Paste, Duplicate</td></tr>
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
        self.w = QDoubleSpinBox()
        self.h = QDoubleSpinBox()
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
        dock = QDockWidget("Layers", self)
        dock.setWidget(self.layers)
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
                  HandTool(c), ZoomTool(c)):
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
                 "measure", None, "hand", "zoom"]
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
        self._act(f, "&New…", self.new_doc, "Ctrl+N")
        self._act(f, "&Open…", self.open_dialog, "Ctrl+O")
        f.addSeparator()
        self._act(f, "&Save", self.save, "Ctrl+S")
        self._act(f, "Save &As…", self.save_as, "Ctrl+Shift+S")
        f.addSeparator()
        self._act(f, "Export &PNG…", self.export_png_dialog, "Ctrl+Alt+Shift+S")
        self._act(f, "Export P&DF…", self.export_pdf_dialog, "Ctrl+Alt+P")
        f.addSeparator()
        self._act(f, "Document &properties…", self.doc_props)
        f.addSeparator()
        self._act(f, "&Quit", self.close, "Ctrl+Q")

        e = mb.addMenu("&Edit")
        self.undo_act = self._act(e, "&Undo", lambda: self.doc.undo(), "Ctrl+Z")
        self.redo_act = self._act(e, "&Redo", lambda: self.doc.redo(), ["Ctrl+Shift+Z", "Ctrl+Y"])
        e.addSeparator()
        self._act(e, "Cu&t", self.cut, "Ctrl+X")
        self._act(e, "&Copy", self.copy, "Ctrl+C")
        self._act(e, "&Paste", self.paste, "Ctrl+V")
        self._act(e, "&Duplicate", self.duplicate, "Ctrl+J")
        self._act(e, "De&lete", self.delete, ["Delete", "Backspace"])
        e.addSeparator()
        self._act(e, "Select &all", self.select_all, "Ctrl+A")
        self._act(e, "D&eselect", lambda: self.doc.set_selection([]), "Ctrl+D")
        e.addSeparator()
        self._act(e, "&Group into folder", lambda: self.layers.group_selection(), "Ctrl+G")
        self._act(e, "&Ungroup", lambda: self.layers.ungroup_selection(), "Ctrl+Shift+G")
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
        v.addSeparator()
        self.snap_act = self._act(v, "&Snapping", self._set_snap, "Ctrl+Shift+;", checkable=True)
        self.snap_act.setChecked(True)
        v.addAction(self.layers_dock.toggleViewAction())

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
        self.style_bar.refresh()

    def _unwire_doc(self):
        d = self.doc
        for sig, slot in ((d.selectionChanged, self.style_bar.refresh), (d.contentChanged, self.style_bar.refresh),
                          (d.metaChanged, self._update_title), (d.restored, self.style_bar.refresh)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def set_document(self, doc):
        self._unwire_doc()
        self.doc = doc
        self.canvas.set_document(doc)
        self.layers.set_document()
        self._wire_doc()
        self._update_title()
        self.canvas.fit_view()
        self.canvas.set_tool(self.canvas.tool.name if self.canvas.tool else "select")

    def _update_title(self):
        name = os.path.basename(self.doc.path) if self.doc.path else (
            os.path.basename(self.doc.source) if self.doc.source else "Untitled")
        self.setWindowTitle(f"{'*' if self.doc.modified else ''}{name} — VectorFlow")

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
        dlg = NewDocDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.set_document(Document(dlg.w.value(), dlg.h.value()))

    def open_dialog(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", OPEN_FILTER)
        if path:
            self.open_path(path, check_save=False)

    def open_path(self, path, check_save=True):
        if check_save and not self.maybe_save():
            return
        page = 0
        try:
            if path.lower().endswith(".pdf"):
                n = pdf_page_count(path)
                if n > 1:
                    page, ok = QInputDialog.getInt(self, "PDF page", f"This PDF has {n} pages. Open page:", 1, 1, n)
                    if not ok:
                        return
                    page -= 1
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                doc = load_document(path, page)
            finally:
                QApplication.restoreOverrideCursor()
        except (ImportError_, OSError, ValueError) as e:
            QMessageBox.critical(self, "Could not open file", str(e))
            return
        except Exception as e:  # corrupt PDF etc.
            QMessageBox.critical(self, "Could not open file", f"{type(e).__name__}: {e}")
            return
        self.set_document(doc)
        if doc.warnings:
            self.statusBar().showMessage("Note: " + " ".join(doc.warnings), 12000)

    def save(self):
        if not self.doc.path:
            return self.save_as()
        return self._save_to(self.doc.path)

    def save_as(self):
        start = self.doc.path or (os.path.splitext(self.doc.source)[0] + ".svg" if self.doc.source else "untitled.svg")
        path, _ = QFileDialog.getSaveFileName(self, "Save as SVG", start, "SVG (*.svg);;Compressed SVG (*.svgz)")
        if not path:
            return False
        if not path.lower().endswith((".svg", ".svgz")):
            path += ".svg"
        return self._save_to(path)

    def _save_to(self, path):
        try:
            save_svg(self.doc, path)
        except OSError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return False
        self.doc.path = path
        self.doc.modified = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def export_png_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "export.png", "PNG (*.png)")
        if not path:
            return
        scale, ok = QInputDialog.getDouble(self, "Export PNG", "Scale (1 = document size):", 1.0, 0.05, 20.0, 2)
        if ok:
            if not path.lower().endswith(".png"):
                path += ".png"
            export_png(self.doc, path, scale)
            self.statusBar().showMessage(f"Exported {path}", 4000)

    def export_pdf_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "export.pdf", "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            export_pdf(self.doc, path)
            self.statusBar().showMessage(f"Exported {path}", 4000)

    def doc_props(self):
        dlg = NewDocDialog(self, self.doc.width, self.doc.height, "Document properties")
        if dlg.exec() == QDialog.Accepted:
            with self.doc.edit():
                self.doc.width, self.doc.height = dlg.w.value(), dlg.h.value()

    def closeEvent(self, e):
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".svg", ".svgz", ".pdf")):
                self.open_path(p)
                break

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
        if not nodes:
            nodes = [c for c in d.root.children if c.visible and not c.locked]
        d.set_selection(nodes)

    def copy(self):
        self.clipboard = [fresh_copy(n) for n in self.doc.selection]
        if self.clipboard:
            self.statusBar().showMessage(f"Copied {len(self.clipboard)} item(s)", 2500)

    def cut(self):
        self.copy()
        self.delete()

    def paste(self):
        if not self.clipboard:
            return
        out = []
        with self.doc.edit(structure=True):
            target = self.doc.active_container()
            for n in self.clipboard:
                c = fresh_copy(n)
                target.add(c)
                out.append(c)
        self.doc.set_selection(out)

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
    app = QApplication(argv)
    app.setApplicationName("VectorFlow")
    app.setDesktopFileName("vectorflow")
    app.setWindowIcon(app_icon())
    apply_dark_theme(app)
    path = next((a for a in argv[1:] if not a.startswith("-")), None)
    w = MainWindow(path)
    w.show()
    return app.exec()
