#!/usr/bin/env python3
"""Read-only per-source-page PDF/Word audit of a local export evidence directory.

DIRECTORY contains document.docx/pdf, pagination-report.json and request.json.
No OCR/model calls. Images stay in DIRECTORY (use private storage for real text).
"""

import json
from pathlib import Path
import re
import sys
from collections import Counter
import fitz
from docx import Document
from PIL import Image, ImageDraw
from nas_filetools.document_sample import document_paragraphs
from nas_filetools.standalone.source_pagination import body_text

root = Path(sys.argv[1])
report = json.loads((root / "pagination-report.json").read_text())
request = json.loads((root / "request.json").read_text())
body = Document(root / "document.docx")
word_text = "".join(p.text for p in document_paragraphs(body))
rows, images = [], []
with fitz.open(root / "document.pdf") as pdf:
    all_text = "".join(body_text(p) for p in pdf)
    assert re.sub(r"\s", "", word_text) == all_text
    for g in report["groups"]:
        actual = [pdf[n - 1] for n in g["output_pages"]]
        group_index = report["groups"].index(g) + 1
        selected = len(g["attempts"])
        path = root / "pagination-work" / f"group-{group_index}-attempt-{selected}" / "group.pdf"
        with fitz.open(path) as isolated:
            assert [body_text(p) for p in actual] == [body_text(p) for p in isolated]
        missing, outside, overlaps, font_names = [], [], [], set()
        for page in actual:
            for font in page.get_fonts():
                font_names.add(font[3])
                assert font[0] > 0 and pdf.extract_font(font[0])[3], "PDF font not embedded"
            for span in page.get_texttrace():
                for code, glyph, _, box in span["chars"]:
                    if code == 0xFFFD or glyph == 0 and not chr(code).isspace():
                        missing.append(f"U+{code:04X}")
                    if not chr(code).isspace() and not page.rect.contains(fitz.Rect(box)):
                        outside.append(list(box))
            lines = [
                fitz.Rect(line["bbox"])
                for b in page.get_text("dict")["blocks"]
                for line in b.get("lines", [])
            ]
            for i, a in enumerate(lines):
                for b in lines[i + 1 :]:
                    overlap = a & b
                    if overlap.width > 2 and overlap.height > min(a.height, b.height) * 0.25:
                        overlaps.append([list(a), list(b)])
        row = {
            "source_page": g["source_page"],
            "output_pages": g["output_pages"],
            "actual_page_count": len(actual),
            "body_pt": g["attempts"][-1]["body_pt"],
            "attempts": g["attempts"],
            "per_source_content_equal": True,
            "missing_glyphs": missing,
            "outside_page": outside,
            "overlapping_lines": overlaps,
            "embedded_pdf_fonts": sorted(font_names),
        }
        rows.append(row)
        assert not missing and not outside and not overlaps, row
        pix = actual[0].get_pixmap(matrix=fitz.Matrix(0.85, 0.85), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        canvas = Image.new("RGB", (image.width, image.height + 24), "white")
        canvas.paste(image, (0, 24))
        ImageDraw.Draw(canvas).text(
            (8, 5),
            f"Source {g['source_page']} -> Output {g['output_pages']} / {row['body_pt']} pt",
            fill="black",
        )
        images.append(canvas)
    for start in range(0, len(images), 4):
        group = images[start : start + 4]
        w = max(i.width for i in group)
        h = max(i.height for i in group)
        sheet = Image.new("RGB", (w * 2, h * 2), "#dddddd")
        for j, im in enumerate(group):
            sheet.paste(im, ((j % 2) * w, (j // 2) * h))
        sheet.save(root / f"contact-{start // 4 + 1}.png")
result = {
    "schema": "per-source-export-audit-v1",
    "template": request["template_data"]["record"],
    "source_artifact_id": request["source_artifact_id"],
    "source_sha256": request["source_sha256"],
    "word_pdf_body_equal": True,
    "pages": rows,
    "font_distribution": dict(Counter(x["body_pt"] for x in rows)),
    "not_single_page": [x["source_page"] for x in rows if x["actual_page_count"] != 1],
    "manual_visual_review": "contact sheets available; record review separately",
    "desktop_word": "not available; actual LibreOffice Word rendering verified",
}
(root / "per-page-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(
    json.dumps(
        {
            "pages": len(rows),
            "font_distribution": result["font_distribution"],
            "not_single_page": result["not_single_page"],
        }
    )
)
