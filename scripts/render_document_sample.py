"""Render DOCX with an available LibreOffice, compare PDF content, make previews.

Run in the isolated document test image only; no dependency installation here.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import fitz
from docx import Document
from PIL import Image, ImageDraw


def render(delivery, output):
    delivery, output = Path(delivery), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cache = Path("/tmp/filetools-document-cache")
    cache.mkdir(exist_ok=True)
    render_environment = {**os.environ, "XDG_CACHE_HOME": str(cache), "GSETTINGS_BACKEND": "memory"}
    subprocess.run(["libreoffice", "-env:UserInstallation=file:///tmp/filetools-document-lo-profile",
                    "--headless", "--convert-to", "pdf", "--outdir", str(output),
                    str(delivery / "sample.docx")], check=True, timeout=120, env=render_environment)
    expected = re.sub(r"\s+", "", "".join(p.text for p in Document(delivery / "sample.docx").paragraphs))
    results = {}
    for label, path in [("word", output / "sample.pdf"), ("pdf", delivery / "sample.pdf")]:
        with fitz.open(path) as pdf:
            actual = re.sub(r"\s+", "", "".join(p.get_text(sort=True) for p in pdf))
            if actual != expected:
                raise ValueError(f"{label}: RENDERED_CONTENT_OR_ORDER_MISMATCH")
            thumbnails, fonts = [], set()
            for number, page in enumerate(pdf, 1):
                if not page.get_text().strip() or "\ufffd" in page.get_text():
                    raise ValueError(f"{label}: EMPTY_OR_MISSING_GLYPH")
                if abs(page.rect.width - 595.28) > 1 or abs(page.rect.height - 841.89) > 1:
                    raise ValueError(f"{label}: NON_A4_PAGE")
                # LibreOffice PDFs can have an empty get_text("dict") despite
                # nonempty plain text/words. Actual drawing traces avoid a vacuous
                # geometry check and include the embedded font and glyph IDs.
                traces = page.get_texttrace()
                if not traces:
                    raise ValueError(f"{label}: NO_TEXT_DRAWING_TRACES")
                for span in traces:
                    if not page.rect.contains(fitz.Rect(span["bbox"])):
                        raise ValueError(f"{label}: CROPPED_TEXT")
                    fonts.add(span["font"])
                    for codepoint, glyph, origin, bbox in span["chars"]:
                        if codepoint == 0xfffd or (glyph == 0 and not chr(codepoint).isspace()):
                            raise ValueError(f"{label}: MISSING_DRAWN_GLYPH")
                        if not page.rect.contains(fitz.Rect(bbox)):
                            raise ValueError(f"{label}: CROPPED_GLYPH")
                png = output / f"{label}-page-{number}.png"
                page.get_pixmap(dpi=120).save(png)
                with Image.open(png) as picture:
                    thumb = picture.copy()
                thumb.thumbnail((300, 425))
                thumbnails.append(thumb)
            sheet = Image.new("RGB", (300 * 4, 455 * ((len(thumbnails) + 3) // 4)), "#ddd")
            draw = ImageDraw.Draw(sheet)
            for index, thumb in enumerate(thumbnails):
                x, y = index % 4 * 300, index // 4 * 455
                sheet.paste(thumb, (x, y + 20))
                draw.text((x + 8, y + 3), f"{label} {index + 1}", fill="black")
            sheet.save(output / f"{label}-contact.png")
            results[label] = {"pages": len(pdf), "content_equal": True, "fonts": sorted(fonts),
                              "geometry_checked": True, "visual_review": "required"}
    (output / "render-checks.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    render(args.delivery, args.output)
