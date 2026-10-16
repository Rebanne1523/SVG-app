"""Projects: several sheets (pages) in one canvas, saved as a single .vflow file.

A .vflow file is a zip with one standalone SVG per sheet (so every sheet can be opened in any
other editor) plus a manifest.json that remembers names, positions and sizes.
"""
from __future__ import annotations

import json
import zipfile

from PySide6.QtCore import QRectF

from . import affine
from .model import Document, common_ancestors_pruned, fresh_copy
from .svg_io import (ImportError_, export_svg_string, sheet_from_svg_bytes, sheets_from_pdf,
                     sheets_from_svg_file)

PROJECT_EXT = ".vflow"
SUPPORTED = (".vflow", ".svg", ".svgz", ".pdf")


def empty_document():
    doc = Document()
    doc.root.children = []
    doc._current_id = None
    doc._active_id = None
    return doc


def save_project(doc, path):
    sheets = doc.sheets()
    manifest = {"format": "vectorflow-project", "version": 1, "sheets": [],
                "current": next((i for i, s in enumerate(sheets) if s is doc.current_sheet()), 0)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, sh in enumerate(sheets):
            fname = f"sheet-{i + 1:03d}.svg"
            z.writestr(fname, export_svg_string(doc, sh))
            manifest["sheets"].append({
                "file": fname, "name": sh.name, "x": sh.x, "y": sh.y, "width": sh.width,
                "height": sh.height, "pt_per_unit": sh.pt_per_unit, "source": sh.source})
        z.writestr("manifest.json", json.dumps(manifest, indent=2))


def _read_project(path):
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json"))
            out = []
            warnings = []
            for e in manifest["sheets"]:
                sheet, w = sheet_from_svg_bytes(z.read(e["file"]), e["name"], e.get("source"),
                                                e.get("pt_per_unit", 0.75))
                sheet.width, sheet.height = e["width"], e["height"]
                out.append((sheet, e["x"], e["y"]))
                warnings.extend(w)
    except (zipfile.BadZipFile, KeyError, ValueError) as ex:
        raise ImportError_(f"Not a valid VectorFlow project: {ex}")
    return out, manifest.get("current", 0), sorted(set(warnings))


def load_project(path):
    items, current, warnings = _read_project(path)
    doc = empty_document()
    for sheet, x, y in items:
        doc.add_sheet_object(sheet, x, y)
    if not doc.sheets():
        doc.new_sheet()
    sh = doc.sheets()
    target = sh[current] if 0 <= current < len(sh) else sh[0]
    doc._current_id = target.id
    doc._active_id = doc.layer_for_sheet(target).id
    doc.path = path
    doc.warnings = warnings
    doc.modified = False
    return doc


def load_sheets(path):
    """Detached sheets for a file (laid out later). Returns (sheets, warnings)."""
    low = path.lower()
    if low.endswith(".pdf"):
        return sheets_from_pdf(path)
    if low.endswith(".vflow"):
        items, _, warnings = _read_project(path)
        return [s for s, _, _ in items], warnings
    return sheets_from_svg_file(path)


def open_document(paths):
    """A new project from one or more files. A single .vflow opens as it was saved."""
    if isinstance(paths, str):
        paths = [paths]
    if len(paths) == 1 and paths[0].lower().endswith(PROJECT_EXT):
        return load_project(paths[0])
    doc = empty_document()
    warnings = []
    for p in paths:
        sheets, w = load_sheets(p)
        warnings.extend(w)
        for sh in sheets:
            doc.add_sheet_object(sh)
    if not doc.sheets():
        doc.new_sheet()
    doc._current_id = doc.sheets()[0].id
    doc._active_id = doc.layer_for_sheet(doc.sheets()[0]).id
    doc.source = paths[0]
    doc.warnings = sorted(set(warnings))
    doc.modified = False
    return doc


def import_into(doc, paths):
    """Add the files' pages to ``doc`` as new sheets (one undo step). Returns (added, warnings)."""
    loaded, warnings = [], []
    for p in paths:
        sheets, w = load_sheets(p)
        loaded.extend(sheets)
        warnings.extend(w)
    if not loaded:
        return [], warnings
    replace_default = doc.is_pristine()
    doc.begin_edit()
    if replace_default:
        for s in list(doc.sheets()):
            doc.root.children.remove(s)
            s.parent = None
    for sh in loaded:
        doc.add_sheet_object(sh)
    doc._current_id = loaded[0].id
    doc._active_id = doc.layer_for_sheet(loaded[0]).id
    doc.selection = []
    doc.end_edit(True, structure=True)
    doc.sheetChanged.emit()
    doc.selectionChanged.emit()
    return loaded, sorted(set(warnings))


def selection_document(nodes):
    """A one-sheet document sized to the bounding box of ``nodes`` (for exporting a selection)."""
    nodes = common_ancestors_pruned(nodes)
    rect = QRectF()
    for n in nodes:
        b = n.bounds()
        rect = QRectF(b) if rect.isNull() and not rect.width() else rect.united(b)
    doc = Document(max(rect.width(), 1.0), max(rect.height(), 1.0))
    layer = doc.sheets()[0].children[0]
    for n in nodes:
        c = fresh_copy(n)
        c.transform(affine.translate(-rect.x(), -rect.y()))
        layer.add(c)
    return doc
