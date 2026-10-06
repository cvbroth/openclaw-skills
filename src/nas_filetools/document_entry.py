"""Preinstalled, single-input entry for reviewed single-choice OCR documents.

Called from the existing restricted Python tool, not a new registered tool.
No OCR, correction, publication, permanent saving, or subprocess rendering here.
"""
import hashlib
import json
import os
import time
from pathlib import Path

from .document_sample import generate_sample
from .document_templates import load_template

FONT_PATH = Path("/usr/share/fonts/truetype/filetools/DroidSansFallback.ttf")
FONT_SHA256 = "ee38813ea00c3e32add4268fff7fff9e39417b4913cb13be2415164a47807cc2"
OUTPUTS = ("sample.docx", "sample.pdf", "structured.json", "original-ocr.md", "issues.md",
           "validation.json", "generation-metrics.json")


def validate_request(request):
    if (not isinstance(request, dict) or set(request) - {"document", "raw_ocr", "margin_evidence",
            "reviewed_edits", "review_notes", "input_ocr_sha256"} or not isinstance(request.get("document"), dict)):
        raise ValueError("DOCUMENT_INPUT_SCHEMA_OR_EXPLICIT_SCOPE_REQUIRED")
    spec = request.get("document", {})
    pages, title = spec.get("source_pages"), spec.get("title")
    choice = spec.get("template")
    if (set(spec) != {"schema", "source_pages", "title", "template"}
            or spec.get("schema") != "reviewed-single-choice-v1" or not isinstance(pages, list)
            or len(pages) != 2 or any(type(n) is not int or n < 1 for n in pages)
            or pages[0] > pages[1] or not isinstance(title, str) or not 1 <= len(title) <= 200
            or not isinstance(request.get("raw_ocr"), str) or not isinstance(choice, dict)
            or set(choice) != {"id", "version"}):
        raise ValueError("DOCUMENT_INPUT_SCHEMA_OR_EXPLICIT_SCOPE_REQUIRED")
    load_template(choice["id"], choice["version"])
    return pages, title


def prepare_registered_ocr(document, margin_evidence=None, reviewed_edits=None, review_notes=None):
    """Package the sole registered OCR input; supplied review evidence is data.

    Does not assert that an Agent has actually compared the original page.
    Publish/select reviewed-input.json through existing FileTools tools next.
    """
    raw = Path(os.environ["FILETOOLS_INPUT"]).read_bytes()
    request = {"raw_ocr": raw.decode("utf-8"), "document": document,
               "margin_evidence": margin_evidence or [], "reviewed_edits": reviewed_edits or [],
               "review_notes": review_notes or [], "input_ocr_sha256": hashlib.sha256(raw).hexdigest()}
    pages, _ = validate_request(request)
    from .document_sample import structure_ocr
    # Verify selected markers and bound edits before publishing the new input.
    structure_ocr(request["raw_ocr"], tuple(pages), request["margin_evidence"], request["reviewed_edits"])
    Path("reviewed-input.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_registered_input():
    """Consume FILETOOLS_INPUT JSON; require explicit scope, never default to full."""
    started = time.monotonic()
    incoming = Path(os.environ["FILETOOLS_INPUT"])
    request = json.loads(incoming.read_bytes())
    pages, title = validate_request(request)
    template = load_template(request["document"]["template"]["id"], request["document"]["template"]["version"])
    if hashlib.sha256(FONT_PATH.read_bytes()).hexdigest() != FONT_SHA256:
        raise ValueError("DOCUMENT_FIXED_FONT_MISMATCH")
    result = generate_sample(incoming, Path.cwd(), FONT_PATH, title=title, pages=tuple(pages),
                             template=template["parameters"])
    result["template_record"] = template["record"]
    Path("validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    import resource  # Linux Worker only; no process spawning or filesystem access.
    metrics = {"elapsed_seconds": round(time.monotonic() - started, 6),
               "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "scope": pages, "input_sha256": hashlib.sha256(incoming.read_bytes()).hexdigest(),
               "visual_review": "required; native content/geometry checks are insufficient",
               "word_render": "not performed", "font_sha256": FONT_SHA256,
               "template_id": template["record"]["id"], "template_version": template["record"]["version"],
               "template_sha256": template["record"]["sha256"]}
    Path("generation-metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    return result
