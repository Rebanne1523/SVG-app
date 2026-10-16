import math
import textwrap

import pytest

from vectorflow.model import MeasureNode, PathNode, walk
from vectorflow.svg_io import export_svg_string, import_svg_bytes, load_document, parse_path_d, save_svg

SVG = textwrap.dedent("""\
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
         width="210mm" height="297mm" viewBox="0 0 210 297">
      <style>.red{fill:#f00;stroke:#00f;stroke-width:2}</style>
      <defs><clipPath id="c"><rect x="0" y="0" width="5" height="5"/></clipPath></defs>
      <g inkscape:groupmode="layer" inkscape:label="Back">
        <rect class="red" x="10" y="10" width="100" height="60" rx="8"/>
        <g clip-path="url(#c)"><circle cx="1" cy="1" r="30"/></g>
      </g>
      <g inkscape:groupmode="layer" inkscape:label="Hidden" style="display:none" transform="translate(5,5)">
        <path d="M0,0 L10,10 a10,10 0 0 1 20,0 z" stroke="black" fill="none" stroke-dasharray="4 2"/>
      </g>
    </svg>""")


def test_import_structure_and_styles(qapp):
    doc = import_svg_bytes(SVG)
    assert (doc.width, doc.height) == (210, 297)
    names = [c.name for c in doc.root.children]
    assert names == ["Back", "Hidden"]
    assert not doc.root.children[1].visible
    rect = doc.root.children[0].children[0]
    assert rect.style.fill == (255, 0, 0, 255) and rect.style.stroke == (0, 0, 255, 255)
    assert rect.bounds().getRect() == (10, 10, 100, 60)
    clipped = doc.root.children[0].children[1]
    assert clipped.clip  # clip-path survived


def test_roundtrip_keeps_layers_and_measure(qapp):
    doc = import_svg_bytes(SVG)
    m = MeasureNode((0, 0), (100, 0), 30, "100", "leg", "line")
    doc.root.children[0].add(m)
    doc.root.children[0].children[0].style.arrow_end = "triangle"
    doc.root.children[0].children[0].style.dash = [4.0, 3.0]
    text = export_svg_string(doc)
    assert 'inkscape:groupmode="layer"' in text
    doc2 = import_svg_bytes(text)
    assert [c.name for c in doc2.root.children] == ["Back", "Hidden"]
    ms = [n for n in walk(doc2.root) if n.kind == "measure"]
    assert len(ms) == 1 and ms[0].text == "100" and ms[0].mode_b == "line" and ms[0].offset == 30
    p = [n for n in walk(doc2.root) if n.kind == "path"][0]
    assert p.style.arrow_end == "triangle" and p.style.dash == [4.0, 3.0]


@pytest.mark.parametrize("d,count", [("M0,0 L10,0 L10,10 Z", 1), ("M0,0 h5 v5 m10,10 l1,1", 2),
                                     ("M0,0 a5 5 0 1 1 10 0 a5 5 0 1 1 -10 0", 1),
                                     ("M0 0c1 1 2 2 3 3s4 4 5 5q1 1 2 2t3 3", 1)])
def test_path_parser(qapp, d, count):
    assert len(parse_path_d(d)) == count


def test_arc_ends_exactly(qapp):
    sp = parse_path_d("M10,10 A20,20 0 0 1 50,10")[0]
    assert (sp.anchors[-1].x, sp.anchors[-1].y) == pytest.approx((50, 10))


def test_pdf_import(qapp, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(20, 20, 120, 100))
    shape.finish(fill=(1, 0.8, 0.2), color=(0, 0, 1), width=3)
    shape.commit()
    page.insert_text((30, 150), "Hello", fontsize=20)
    path = tmp_path / "a.pdf"
    pdf.save(str(path))
    doc = load_document(str(path))
    assert (doc.width, doc.height) == (300, 200)
    kinds = [n.kind for n in walk(doc.root)]
    assert kinds.count("path") >= 2


def test_save_and_open(qapp, tmp_path):
    doc = import_svg_bytes(SVG)
    out = tmp_path / "o.svg"
    save_svg(doc, str(out))
    again = load_document(str(out))
    assert len(list(walk(again.root))) == len(list(walk(doc.root)))
