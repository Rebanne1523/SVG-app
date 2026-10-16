"""Exporting sheets and selections (no GUI here, so it can be tested)."""
from __future__ import annotations

import os

from .project import selection_document
from .render import export_sheet_png, export_sheets_pdf
from .svg_io import save_svg

FORMATS = {"pdf": "PDF", "svg": "SVG", "png": "PNG"}


def safe_filename(name):
    bad = '/\\:*?"<>|\0'
    out = "".join("_" if c in bad else c for c in name).strip().strip(".")
    return out or "export"


def plan_unit_paths(units, folder, ext):
    """Output path for every unit. A unit is a list of sheets exported together; it is named after its
    first sheet, i.e. after the file that was imported. Equal names get " (2)", " (3)"..."""
    used = {}
    paths = []
    for unit in units:
        base = safe_filename(unit[0].name)
        n = used.get(base.lower(), 0) + 1
        used[base.lower()] = n
        fname = f"{base}.{ext}" if n == 1 else f"{base} ({n}).{ext}"
        paths.append(os.path.join(folder, fname))
    return paths


def export_unit(doc, sheets, path, fmt, scale=1.0):
    if fmt == "pdf":
        export_sheets_pdf(sheets, path)
    elif fmt == "svg":
        save_svg(doc, path, sheets[0])
    elif fmt == "png":
        export_sheet_png(sheets[0], path, scale, transparent=False)
    else:
        raise ValueError(fmt)


def export_units(doc, units, paths, fmt, scale=1.0):
    """units[i] is exported to paths[i]. SVG/PNG hold a single sheet, so merged units are only
    meaningful for PDF (the dialog enforces that)."""
    for unit, path in zip(units, paths):
        export_unit(doc, unit, path, fmt, scale)
    return paths


def export_selection(doc, nodes, path, fmt, scale=1.0):
    """Export only ``nodes`` (cropped to their bounding box)."""
    tmp = selection_document(nodes)
    export_unit(tmp, tmp.sheets(), path, fmt, scale)
    return path
