"""Synthetic repeated Story/font resources, using actual independent readers."""
import importlib.util
from pathlib import Path

import fitz
import pytest

from nas_filetools.document_layout_checks import check_layout
from nas_filetools.document_sample import canonical, write_pdf


@pytest.fixture
def reader_checks():
    spec = importlib.util.spec_from_file_location("reader_checks", Path(__file__).resolve().parents[1] / "scripts/check_pdf_readers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeated_units_searchable_and_visible_in_independent_readers(tmp_path, reader_checks):
    pdfium = pytest.importorskip("pypdfium2", reason="development cross-reader dependency absent")
    import shutil
    if not shutil.which("pdftoppm"):
        pytest.skip("independent Poppler renderer absent")
    font = tmp_path / "font.ttf"
    font.write_bytes(fitz.Font("cjk").buffer)
    items = [("Title", "合成多单元字体资源复用验证")]
    for number in range(1, 19):
        items.append(("Question", f"{number}. “独立排版单元”重复字形验证。" + "中文原文与顺序完整保留。" * (24 if number % 3 == 0 else 2)))
        items += [("Option", f"{letter}. 重复选项前缀与中文，ABC PDF ①②③④。") for letter in "ABCD"]
        items.append(("Source", "原PDF：第88页"))
    path = tmp_path / "sample.pdf"
    write_pdf(path, items, font)
    assert check_layout(path, items, font)["passed"]
    with fitz.open(path) as doc:
        assert len(doc) > 1
        unique_fonts = {row[0] for page in doc for row in page.get_fonts()}
        extracted = [doc.extract_font(xref) for xref in unique_fonts]
        programs = [row[3] for row in extracted]
        assert all(programs)
        # Native subsets can retain sparse original glyph IDs and large index
        # tables. Require substantial reduction, without assuming dense remapping.
        ttfs = [row[3] for row in extracted if row[1] == "ttf"]
        assert ttfs and max(map(len, ttfs)) < font.stat().st_size / 4
        assert path.stat().st_size < 300_000
    reader = pdfium.PdfDocument(path)
    try:
        texts = []
        for index in range(len(reader)):
            page = reader[index]
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
            page.close()
        actual = canonical("".join(texts))
        import re
        actual = re.sub(r"文档第\d+页", "", actual)
        assert actual == canonical("".join(value for _, value in items))
        assert actual.count("原PDF：第88页") == 18
        assert all(actual.count(letter + ".重复选项") == 18 for letter in "ABCD")
    finally:
        reader.close()
    result = reader_checks.check(path, tmp_path / "readers")
    assert result["automatic_ink_check_passed"], result["relative_ink_omissions"]
    assert result["pdfium_ordered_searchable_text_equal"]
    assert result["font_resources"]["duplicate_font_streams"] == 0


def test_simulated_missing_prefix_is_rejected_despite_complete_text(reader_checks):
    """Fault injection in a raster copy, not evidence of a reader/library bug."""
    import numpy as np
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A. searchable option", fontsize=12)
    pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7))
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).min(axis=2)
    pictures = {engine: image.copy() for engine in reader_checks.ENGINES}
    assert not reader_checks.glyph_ink_checks(page, pictures)[1]
    bbox = page.get_texttrace()[0]["chars"][0][3]
    import math
    x0, y0, x1, y1 = bbox
    pictures["pdfium"][math.floor(y0 * 1.7):math.ceil(y1 * 1.7), math.floor(x0 * 1.7):math.ceil(x1 * 1.7)] = 255
    assert "A. searchable option" in page.get_text()
    failures = reader_checks.glyph_ink_checks(page, pictures)[1]
    assert any(row["codepoint"] == ord("A") and row["ink"]["pdfium"] == 0 for row in failures)
    doc.close()
