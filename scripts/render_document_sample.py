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

from nas_filetools.document_sample import page_body
from nas_filetools.document_layout_checks import check_layout


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
    word_document = Document(delivery / "sample.docx")
    items = [(p.style.name, p.text) for p in word_document.paragraphs]
    template = json.loads((delivery / "validation.json").read_text()).get("template")
    for label, path in [("word", output / "sample.pdf"), ("pdf", delivery / "sample.pdf")]:
        layout_checks = check_layout(path, items, "/usr/share/fonts/truetype/filetools/DroidSansFallback.ttf", template)
        (output / f"{label}-layout-checks.json").write_text(json.dumps(layout_checks, ensure_ascii=False, indent=2))
        if not layout_checks["passed"]:
            raise ValueError(f"{label}: LAYOUT_BOUNDARY_FAILED {layout_checks['failures']}")
        with fitz.open(path) as pdf:
            actual = re.sub(r"\s+", "", "".join(page_body(p, number, template) for number, p in enumerate(pdf, 1)))
            if actual != expected:
                raise ValueError(f"{label}: RENDERED_CONTENT_OR_ORDER_MISMATCH")
            fonts = set()
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
            results[label] = {"pages": len(pdf), "content_equal": True, "fonts": sorted(fonts),
                              "geometry_checked": True, "pagination_boundaries": "checked", "text_black": layout_checks["text_black"], "document_page_numbers": "checked", "visual_review": "required"}
        # Use a second PDF engine: fixed MuPDF previews sometimes omit prefixes
        # even when the text and drawing traces are complete. Never infer visual
        # success from those traces alone.
        rasterize(path, output, label)
        results[label]["raster_engine"] = "Poppler pdftoppm"
    (output / "render-checks.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False))
    return results


def raster_page(path, number, png):
    """Independent real PDF rendering; missing Poppler is an explicit failure."""
    png = Path(png)
    subprocess.run(["pdftoppm", "-f", str(number), "-l", str(number),
                    "-singlefile", "-r", "120", "-png", str(path), str(png.with_suffix(""))],
                   check=True, timeout=30)
    if not png.is_file():
        raise ValueError("PDF_RASTER_OUTPUT_MISSING")


def rasterize(path, output, label):
    """Rasterize with Poppler, independent of the text/layout checking engine."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    thumbnails = []
    with fitz.open(path) as pdf:
        page_count = len(pdf)
    for number in range(1, page_count + 1):
        png = output / f"{label}-page-{number}.png"
        raster_page(path, number, png)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delivery", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--raster-only", type=Path)
    parser.add_argument("--raster-page", type=Path)
    parser.add_argument("--page", type=int)
    parser.add_argument("--label", choices=("word", "pdf"), default="pdf")
    args = parser.parse_args()
    if args.raster_page:
        if not args.page or args.page < 1:
            parser.error("--page must be a positive page number")
        raster_page(args.raster_page, args.page, args.output)
    elif args.raster_only:
        rasterize(args.raster_only, args.output, args.label)
    elif args.delivery:
        render(args.delivery, args.output)
    else:
        parser.error("--delivery or --raster-only is required")
