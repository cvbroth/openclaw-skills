"""Bounded document formatter worker; known exam styles, no quality in body."""

import json
from pathlib import Path
import resource
import sys
import time
import subprocess
import fitz
from ..document_sample import paragraphs, structure_ocr, validate_pair, write_docx, document_paragraphs
from ..document_templates import load_template
from ..document_entry import FONT_PATH
from ..document_layout_checks import check_layout
from .content_structure import parse_markdown, items as markdown_items
from .preview_worker import export_docx
from .word_styles import apply_styles
from .source_pagination import options, generate_source_pages


def generate(request):
    output = Path(request["output"])
    template = request.get("template_data") or load_template(
        request["template"]["id"], request["template"]["version"]
    )
    font_path = Path(template.get("font", {}).get("path", FONT_PATH))
    policy = options(request.get("pagination"))
    items = [] if policy["mode"] == "source-pages" else [("Title", request["title"])]
    grouped = []
    mappings = []
    structures = []
    for page in request["pages"]:
        begin = len(items)
        if not page["text"]:
            grouped.append({**page, "items": []})
            continue
        n = page.get("source_pdf_physical_page") or page["physical_page"]
        location = {
            "source_locator": page.get("source_locator"),
            "source_pdf_physical_page": page.get("source_pdf_physical_page"),
            "input_position": page["physical_page"],
        }
        try:
            model = structure_ocr(f"## 第 {n} 页\n" + page["text"], (n, n))
        except ValueError:
            model = {"issues": ["unsupported"], "removed_headers_footers": []}
        if (
            not model["issues"]
            and not model["removed_headers_footers"]
            and any(b.get("kind") == "question" for b in model.get("blocks", []))
        ):
            blockitems = paragraphs(model, request["title"], template["parameters"])[1:]
            for style, text in blockitems:
                if style != "Source":
                    parsed = parse_markdown(str(text))
                    for _, rich in markdown_items(parsed):
                        items.append((style, rich))
            structures.append({"schema": "known-question-structure", **location, "model": model})
            mappings.append({**location, "mode": "single-choice-parser-no-issues"})
        else:
            structure = parse_markdown(
                page["text"],
                {
                    **location,
                    "artifact_id": request.get("source_artifact_id"),
                    "sha256": request.get("source_sha256"),
                },
            )
            structures.append(structure)
            items.extend(markdown_items(structure))
            mappings.append(
                {
                    **location,
                    "mode": "markdown-basic; question ownership not inferred",
                    "diagnostics": structure["diagnostics"],
                }
            )
        grouped.append({**page, "items": items[begin:]})
    font = fitz.Font(fontfile=str(font_path))
    missing = sorted({c for _, text in items for c in text if not c.isspace() and not font.has_glyph(ord(c))})
    if missing:
        raise ValueError("FONT_MISSING_GLYPHS: " + "".join(missing))
    pagination_report = None
    if policy["mode"] == "source-pages":
        pagination_report = generate_source_pages(output, grouped, template, font_path, policy)
    else:
        write_docx(output / "document.docx", items, font_path, template["parameters"])
        apply_styles(output / "document.docx", template.get("word_styles"))
        export_docx(output / "document.docx", output, timeout=40)
    pdf_renderer = subprocess.check_output(["libreoffice", "--version"], text=True, timeout=10).strip()

    with fitz.open(output / "document.pdf") as pdf:
        if not 0 < len(pdf) <= template["parameters"]["max_pages"]:
            raise ValueError("TEMPLATE_PDF_PAGE_LIMIT")
    if pagination_report or template.get("word_styles"):
        from docx import Document
        import re
        from .source_pagination import body_text

        def canonical(text):
            return re.sub(r"\s", "", text)

        actual_paragraphs = [
            p.text for p in document_paragraphs(Document(output / "document.docx")) if p.text.strip()
        ]
        if canonical("".join(actual_paragraphs)) != canonical("".join(text for _, text in items)):
            raise ValueError("DOCX_CONTENT_MISMATCH")
        with fitz.open(output / "document.pdf") as pdf:
            actual = "".join(body_text(p, template["parameters"].get("page_numbers", True)) for p in pdf)
            geometry = [{"page": i + 1, "words": len(p.get_text("words"))} for i, p in enumerate(pdf)]
        if canonical(actual) != canonical("".join(text for _, text in items)):
            raise ValueError("PDF_CONTENT_OR_ORDER_MISMATCH")
        checks = {
            "content_equal": True,
            "pdf_pages": geometry,
            "docx_paragraphs": len(actual_paragraphs),
            "visual_review": "required",
            "word_render": "actual LibreOffice conversion; desktop Word unverified",
        }
    else:
        checks = validate_pair(
            output / "document.docx", output / "document.pdf", items, template["parameters"]
        )
    # Imported geometry is checked against the actual rendered document, not
    # Story's separate template approximation.
    if template.get("word_styles") or pagination_report:
        with fitz.open(output / "document.pdf") as rendered:
            missing_glyphs = [
                i + 1
                for i, p in enumerate(rendered)
                if any(
                    code == 0xFFFD or (glyph == 0 and not chr(code).isspace())
                    for span in p.get_texttrace()
                    for code, glyph, origin, bbox in span["chars"]
                )
            ]
            if missing_glyphs:
                raise ValueError("PDF_MISSING_GLYPH")
            outside = [
                {"page": i + 1, "bbox": list(b[:4])}
                for i, p in enumerate(rendered)
                for b in p.get_text("blocks")
                if b[0] < -1 or b[1] < -1 or b[2] > p.rect.width + 1 or b[3] > p.rect.height + 1
            ]
        boundaries = {
            "passed": not outside,
            "outside_page": outside,
            "scope": "actual page geometry; visual review still required",
        }
    else:
        boundaries = check_layout(output / "document.pdf", items, font_path, template["parameters"])
    (output / "content-structure.json").write_text(
        json.dumps(
            {
                "schema": "derived-content-v1",
                "source_pdf_sha256": request.get("source_pdf_sha256"),
                "existing_structure_sha256": request.get("existing_structure_sha256"),
                "source_artifact_id": request.get("source_artifact_id"),
                "source_sha256": request.get("source_sha256"),
                "pages": structures,
                "mapping": mappings,
                "source_output_mapping": pagination_report["groups"] if pagination_report else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not boundaries["passed"]:
        raise ValueError("PDF_LAYOUT_BOUNDARY_FAILED")
    (output / "layout-validation.json").write_text(
        json.dumps(
            {
                **checks,
                "mapping": mappings,
                "source_output_mapping": pagination_report["groups"] if pagination_report else None,
                "native_layout_boundaries": boundaries,
                "template": template["record"],
                "presentation_rule": "source labels omitted from body; original locations retained in structure.json",
                "visual_acceptance": "not performed; native checks insufficient",
                "quality_and_comments_in_body": False,
                "pdf_renderer": pdf_renderer,
                "formatter_version": "standalone-format-v2-markdown-office",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    start = time.monotonic()
    try:
        generate(request)
        result = {"status": "SUCCEEDED"}
    except Exception as exc:
        result = {
            "status": "FAILED",
            "error": {
                "category": "local",
                "stage": "generation",
                "code": type(exc).__name__,
                "message": str(exc)[:300],
            },
        }
    result.update(
        elapsed_seconds=time.monotonic() - start,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
