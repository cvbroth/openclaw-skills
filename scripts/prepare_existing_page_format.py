"""Scoped reuse of an existing reviewed structure; does not OCR or repair text."""

import argparse
from copy import deepcopy
import json
import hashlib
import re
from pathlib import Path
from nas_filetools.document_sample import paragraphs
from nas_filetools.standalone.template_library import TemplateLibrary


def prepare(args):
    if not re.fullmatch(r"[0-9a-f]{64}", args.source_sha):
        raise ValueError("source-sha必须为已核对原件SHA-256")
    original = json.loads(args.structure.read_text())
    selected = []
    for block in original["blocks"]:
        pages = {f["page"] for f in block.get("fragments", [])}
        if pages == {args.page}:
            selected.append(deepcopy(block))
        elif args.page in pages:
            raise ValueError("跨页块不能隐式截取，请显式准备完整映射")
    if not selected:
        raise ValueError("所选物理页无完整已有块")
    model = {**original, "blocks": selected}
    template = TemplateLibrary(args.library).load("questions-zh-cn", "1.0.0")
    items = paragraphs(model, "", template["parameters"])[1:]
    text = "\n\n".join(
        (
            "# "
            if style == "Heading 1"
            else "## "
            if style in {"Subject", "Heading 2"}
            else "### "
            if style == "Heading 3"
            else ""
        )
        + str(value)
        for style, value in items
        if style != "Source"
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "input.md").write_text(text)
    request = {
        "output": str(args.output),
        "title": "真实已授权页排版验证",
        "template": {"id": "questions-zh-cn", "version": "1.0.0"},
        "template_data": template,
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_pdf_sha256": args.source_sha,
        "existing_structure_sha256": hashlib.sha256(args.structure.read_bytes()).hexdigest(),
        "pagination": {
            "mode": "source-pages",
            "font_fit": True,
            "minimum_font_pt": 9,
            "allow_continuation": False,
        },
        "pages": [{"physical_page": 1, "source_pdf_physical_page": args.page, "text": text}],
    }
    (args.output / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "physical_page": args.page,
                "blocks": len(selected),
                "characters": len(text),
                "origin": "existing reviewed structure; no new OCR or text repair",
            }
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--structure", type=Path, required=True)
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--library", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    prepare(p.parse_args())
