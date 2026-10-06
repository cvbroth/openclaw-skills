"""Independent PDFium/Poppler/MuPDF raster evidence, not a visual pass certificate.

Private PDFs, glyph positions and images must stay in an ignored sample directory.
Pixel comparisons catch omissions; a human must inspect every page and boundaries.
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

SCALE = 1.7  # Match the reported PDFium call, without rounding via DPI division.
DPI = SCALE * 72
ENGINES = ("pdfium", "poppler", "mupdf")


def glyph_ink_checks(page, pictures):
    failures, checked = [], 0
    for span in page.get_texttrace():
        for codepoint, gid, origin, bbox in span["chars"]:
            if chr(codepoint).isspace():
                continue
            x0, y0, x1, y1 = bbox
            inset = (x1 - x0) * 0.10  # Exclude adjacent punctuation.
            clip = [math.floor((x0 + inset) * SCALE), math.floor(y0 * SCALE),
                    math.ceil((x1 - inset) * SCALE), math.ceil(y1 * SCALE)]
            ink = {engine: int(np.count_nonzero(pic[max(0, clip[1]):clip[3], max(0, clip[0]):clip[2]] < 180))
                   for engine, pic in pictures.items()}
            checked += 1
            maximum = max(ink.values())
            if (chr(codepoint).isalnum() and min(ink.values()) == 0) or (maximum >= 8 and min(ink.values()) < maximum * 0.15):
                failures.append({"page": page.number + 1, "codepoint": codepoint, "bbox": bbox, "ink": ink})
    return checked, failures


def font_resources(doc):
    def reference(xref, key):
        value = doc.xref_get_key(xref, key)[1]
        match = re.search(r"(\d+) 0 R", value)
        return int(match.group(1)) if match else None

    rows = [row for page in doc for row in page.get_fonts()]
    programs = []
    for xref in sorted({row[0] for row in rows}):
        name, extension, kind, data = doc.extract_font(xref)
        descendant = reference(xref, "DescendantFonts") or xref
        descriptor = reference(descendant, "FontDescriptor")
        stream = (reference(descriptor, "FontFile2") or reference(descriptor, "FontFile3")) if descriptor else None
        programs.append({"xref": xref, "name": name, "extension": extension,
                         "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                         "stream_xref": stream, "compressed_bytes": len(doc.xref_stream_raw(stream)) if stream else None})
    return {"page_font_references": len(rows), "programs": programs,
            "distinct_font_streams": len({p["stream_xref"] for p in programs if p["stream_xref"]}),
            "duplicate_font_streams": len({(p["stream_xref"], p["sha256"]) for p in programs if p["stream_xref"]}) - len({p["sha256"] for p in programs if p["stream_xref"]})}


def paint(path, page_number, engine, output):
    if engine == "poppler":
        subprocess.run(["pdftoppm", "-f", str(page_number), "-l", str(page_number),
                        "-singlefile", "-r", str(DPI), "-png", str(path),
                        str(output.with_suffix(""))], check=True, timeout=30)
    elif engine == "pdfium":
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        try:
            page = doc[page_number - 1]
            bitmap = page.render(scale=SCALE)
            bitmap.to_pil().convert("RGB").save(output)
            bitmap.close()
            page.close()
        finally:
            doc.close()
    else:
        with fitz.open(path) as doc:
            doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), alpha=False).save(output)


def check(path, output):
    import pypdfium2 as pdfium
    output.mkdir(parents=True, exist_ok=True)
    versions = {"pdfium": str(pdfium.PDFIUM_INFO), "pypdfium2": str(pdfium.PYPDFIUM_INFO),
                "mupdf": fitz.version,
                "poppler": subprocess.run(["pdftoppm", "-v"], capture_output=True, text=True, check=True).stderr.strip()}
    failures, checked = [], 0
    pdfium_doc = pdfium.PdfDocument(path)
    pdfium_text = []
    try:
        for index in range(len(pdfium_doc)):
            page = pdfium_doc[index]
            textpage = page.get_textpage()
            pdfium_text.append(textpage.get_text_range())
            textpage.close()
            page.close()
    finally:
        pdfium_doc.close()
    with fitz.open(path) as doc:
        page_count = len(doc)
        resources = font_resources(doc)
        text_equal = re.sub(r"\s+", "", "".join(pdfium_text)) == re.sub(r"\s+", "", "".join(page.get_text(sort=True) for page in doc))
        for number, page in enumerate(doc, 1):
            pictures = {}
            for engine in ENGINES:
                png = output / f"{engine}-page-{number}.png"
                # Fresh process for each engine/page, including MuPDF; text
                # inspection cannot contaminate the raster process's state.
                subprocess.run([sys.executable, str(Path(__file__).resolve()), "--paint", engine,
                                "--pdf", str(path), "--page", str(number), "--output", str(png)],
                               check=True, timeout=40)
                with Image.open(png) as im:
                    pictures[engine] = np.min(np.asarray(im.convert("RGB")), axis=2)
            count, omissions = glyph_ink_checks(page, pictures)
            checked += count
            failures.extend(omissions)
    result = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
              "versions": versions, "dpi": DPI, "scale": SCALE, "background": "white",
              "annotations": "renderer defaults; samples have no annotations", "pages": page_count, "checked_nonspace_glyphs": checked,
              "relative_ink_omissions": failures, "automatic_ink_check_passed": not failures,
              "pdfium_ordered_searchable_text_equal": text_equal,
              "font_resources": resources,
              "manual_review": "required; pixel checks are not proof of complete visual compatibility"}
    (output / "reader-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "relative_ink_omissions"}, ensure_ascii=False))
    print("omission candidates:", len(failures))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paint", choices=ENGINES)
    parser.add_argument("--page", type=int)
    args = parser.parse_args()
    if args.paint:
        if not args.page or args.page < 1:
            parser.error("--page must be positive")
        paint(args.pdf, args.page, args.paint, args.output)
    else:
        result = check(args.pdf, args.output)
        sys.exit(0 if result["automatic_ink_check_passed"] and result["pdfium_ordered_searchable_text_equal"] else 2)
