"""Bounded document formatter worker; known exam styles, no quality in body."""

import json
from pathlib import Path
import resource
import sys
import time
from ..document_sample import paragraphs, structure_ocr, validate_pair, write_docx, write_pdf
from ..document_templates import load_template
from ..document_entry import FONT_PATH
from ..document_layout_checks import check_layout


def generate(request):
    output = Path(request["output"])
    template = load_template(request["template"]["id"], request["template"]["version"])
    items = [("Title", request["title"])]
    mappings = []
    for page in request["pages"]:
        if not page["text"]:
            continue
        n = page["physical_page"]
        try:
            model = structure_ocr(f"## 第 {n} 页\n" + page["text"], (n, n))
        except ValueError:
            model = {"issues": ["unsupported"], "removed_headers_footers": []}
        if not model["issues"] and not model["removed_headers_footers"]:
            blockitems = paragraphs(model, request["title"], template["parameters"])[1:]
            items.extend((style, text) for style, text in blockitems if style != "Source")
            mappings.append({"physical_page": n, "mode": "single-choice-parser-no-issues"})
        else:
            # Retain unsupported material as one verbatim block, preserving line breaks.
            items.extend([("Heading 3", "待核对片段"), ("Normal", page["text"])])
            mappings.append(
                {"physical_page": n, "mode": "verbatim-unsegmented; no guessed question ownership"}
            )
    write_docx(output / "document.docx", items, FONT_PATH, template["parameters"])
    write_pdf(output / "document.pdf", items, FONT_PATH, template["parameters"])
    checks = validate_pair(output / "document.docx", output / "document.pdf", items, template["parameters"])
    boundaries = check_layout(output / "document.pdf", items, FONT_PATH, template["parameters"])
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
                "message": "Document formatting failed; raw content retained.",
            },
        }
    result.update(
        elapsed_seconds=time.monotonic() - start,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
