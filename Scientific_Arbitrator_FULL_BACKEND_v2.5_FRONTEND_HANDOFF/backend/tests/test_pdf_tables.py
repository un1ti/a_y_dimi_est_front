import pymupdf
from app.services.pdf_parser import parse_pdf
from app.services.retrieval import find_relevant_fragments
from types import SimpleNamespace


def test_table_parser_preserves_header_and_both_devices():
    pdf = pymupdf.open()
    page = pdf.new_page()
    rows = [
        ("Device", "Jsc", "Voc", "FF", "PCE"),
        ("Control", "20.18", "1.170", "78.38", "18.51"),
        ("DiOC2(3)", "22.59", "1.193", "79.80", "21.50"),
    ]
    xs, ys = (40, 135, 215, 295, 375, 465), (70, 100, 130, 160)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), color=(0, 0, 0))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), color=(0, 0, 0))
    for row_num, row in enumerate(rows):
        for col, value in enumerate(row):
            page.insert_text((xs[col] + 3, ys[row_num] + 21), value, fontsize=10)
    result = parse_pdf(pdf.tobytes())
    table_fragments = [frag for frag in result.fragments if frag.text.startswith("EXTRACTED TABLE")]
    assert table_fragments
    selected = find_relevant_fragments(
        [SimpleNamespace(id=str(i), page=f.page, position=f.position, text=f.text) for i, f in enumerate(result.fragments)],
        "solar",
    )
    assert any("Control | 20.18 | 1.170 | 78.38 | 18.51" in f.text and "DiOC2(3) | 22.59 | 1.193 | 79.80 | 21.50" in f.text for f in selected)
