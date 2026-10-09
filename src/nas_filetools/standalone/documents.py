"""Bounded document formatter worker; known exam styles, no quality in body."""

import json
from pathlib import Path
import resource
import sys
import time
import subprocess
import fitz
from ..document_sample import paragraphs, structure_ocr, validate_pair, write_docx, write_pdf
from ..document_templates import load_template
from ..document_entry import FONT_PATH
from ..document_layout_checks import check_layout
from .content_structure import parse_markdown, items as markdown_items
from .preview_worker import export_docx


def generate(request):
    output = Path(request["output"])
    template = request.get("template_data") or load_template(
        request["template"]["id"], request["template"]["version"]
    )
    font_path = Path(template.get("font", {}).get("path", FONT_PATH))
    items = [("Title", request["title"])]
    mappings = []
    structures = []
    for page in request["pages"]:
        if not page["text"]:
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
    font = fitz.Font(fontfile=str(font_path))
    missing = sorted({c for _, text in items for c in text if not c.isspace() and not font.has_glyph(ord(c))})
    if missing:
        raise ValueError("FONT_MISSING_GLYPHS: " + "".join(missing))
    write_docx(output / "document.docx", items, font_path, template["parameters"])
    # Story with a regular-only Chinese font does not synthesize emphasis. Reuse
    # the installed office renderer for derived Markdown instead of claiming it does.
    if any(m["mode"].startswith("markdown-basic") for m in mappings) or any(
        r.get("bold") or r.get("italic") for _, text in items for r in getattr(text, "runs", [])
    ):
        export_docx(output / "document.docx", output, timeout=40)
        pdf_renderer = subprocess.check_output(["libreoffice", "--version"], text=True, timeout=10).strip()
    else:
        write_pdf(output / "document.pdf", items, font_path, template["parameters"])
        pdf_renderer = "PyMuPDF native Story"

    with fitz.open(output / "document.pdf") as pdf:
        if not 0 < len(pdf) <= template["parameters"]["max_pages"]:
            raise ValueError("TEMPLATE_PDF_PAGE_LIMIT")
    checks = validate_pair(output / "document.docx", output / "document.pdf", items, template["parameters"])
    boundaries = check_layout(output / "document.pdf", items, font_path, template["parameters"])
    (output / "content-structure.json").write_text(
        json.dumps(
            {
                "schema": "derived-content-v1",
                "source_artifact_id": request.get("source_artifact_id"),
                "source_sha256": request.get("source_sha256"),
                "pages": structures,
                "mapping": mappings,
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
