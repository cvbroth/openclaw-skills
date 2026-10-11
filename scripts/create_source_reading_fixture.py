#!/usr/bin/env python3
"""Create evidence-only mapped fragments, without running OCR or inference.

Usage: ROOT CONFIG OUTPUT_MANIFEST. ROOT must be an isolated synthetic store.
"""

import json
from pathlib import Path
import sys
import time
import fitz
from nas_filetools.artifact_project import register_artifact, page_data, emit_viewer
from nas_filetools.standalone.config import validate
from nas_filetools.standalone.tasks import Projects
from nas_filetools.standalone.content_structure import parse_markdown, reading_html
from nas_filetools.document_entry import FONT_PATH

root, config_path, manifest_path = map(Path, sys.argv[1:])
assert "source-page-reading" in str(root) or root == Path("/evidence/store"), (
    "Only isolated source-page-reading fixture stores are allowed"
)
config = validate(json.loads(config_path.read_text()), testing=True)
config["engines"] = {}
manager = Projects(root, config)
try:
    pdf = root.parent / "synthetic-source-30.pdf"
    with fitz.open() as document:
        for n in range(1, 31):
            page = document.new_page()
            page.insert_font(fontname="Chinese", fontfile=str(FONT_PATH))
            page.insert_text((60, 70), f"合成原件物理第{n}页", fontname="Chinese", fontsize=18)
            if n == 22:
                page.insert_text((60, 120), "ONE_P22 · 一页一个片段", fontname="Chinese", fontsize=14)
            if n == 24:
                page.insert_text((60, 120), "第24页部分；跨页片段完整保留。", fontname="Chinese", fontsize=14)
            if n == 23:
                page.insert_text((60, 120), "FIRST_P23 · 第一片段完整正文。", fontname="Chinese", fontsize=14)
                page.insert_text(
                    (60, 170), "SECOND_P23 · 第二片段等待独立编辑。", fontname="Chinese", fontsize=14
                )
                page.insert_text((60, 220), "CROSS_23_24 · 第23页部分。", fontname="Chinese", fontsize=14)
        document.save(pdf)
    p = manager.upload(pdf, "synthetic-source-30.pdf", project_name="合成 · 来源页连续阅读验收")
    pid = p["project_id"]
    for _ in range(200):
        if manager.get(pid).get("analysis", {}).get("status") not in {"RUNNING", "QUEUED"}:
            break
        time.sleep(0.05)
    with manager.lock:
        p = manager.get(pid)
        project = manager.path(pid)
        definitions = [
            (22, "ONE_P22 · 一页一个片段", {"source_page": 22}),
            (23, "FIRST_P23 · 第一片段完整正文。", {"source_page": 23}),
            (23, "SECOND_P23 · 第二片段等待独立编辑。", {"source_page": 23}),
            (23, "CROSS_23_24 · 第23页部分。\n第24页部分；跨页片段完整保留。", {"source_pages": [23, 24]}),
            (25, "", {"source_page": 25, "error": {"code": "SYNTHETIC_FAILURE"}, "error_category": "local"}),
            (0, "UNMAPPED_FRAGMENT · 来源未知，仍可独立编辑。", {}),
        ]
        texts = []
        views = []
        for i, (n, text, mapping) in enumerate(definitions):
            data = f"content/fixture-{i}.js"
            texts.append(text)
            page_data(project, data, {"text": text, "reading_html": reading_html(parse_markdown(text, {}))})
            views.append(
                {
                    "label": f"登记文字片段{i + 1}",
                    "locator": {"kind": "block", "id": f"stable-fragment-{i}"},
                    "data": data,
                    **mapping,
                }
            )
        path = project / "content/fixture.md"
        path.write_text("\n\n".join(texts))
        a = register_artifact(
            project,
            p,
            name="合成映射文字",
            format="markdown",
            path="content/fixture.md",
            parents=[p["source_artifact_id"]],
            pages=views,
        )
        unknown = register_artifact(
            project,
            p,
            name="合成历史无来源映射",
            format="markdown",
            path="content/fixture.md",
            parents=[p["source_artifact_id"]],
            pages=[
                {k: v for k, v in view.items() if k not in {"source_page", "source_pages"}} for view in views
            ],
        )
        page_data(project, "content/whole-document.js", {"text": "\n\n".join(texts)})
        whole = register_artifact(
            project,
            p,
            name="合成历史整份文字",
            format="markdown",
            path="content/fixture.md",
            parents=[p["source_artifact_id"]],
            pages=[
                {
                    "label": "整份文字 · 来源未知",
                    "locator": {"kind": "document"},
                    "data": "content/whole-document.js",
                }
            ],
        )
        manager.save(project, p)
        emit_viewer(project, p)
    Path(manifest_path).write_text(
        json.dumps(
            {
                "project_id": pid,
                "artifact_id": a["artifact_id"],
                "unmapped_id": unknown["artifact_id"],
                "whole_id": whole["artifact_id"],
            },
            indent=2,
        )
    )
finally:
    manager.close()
