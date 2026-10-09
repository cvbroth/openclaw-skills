"""Explicit synthetic revision demo. New directory only; no OCR or providers."""

import argparse
import json
from pathlib import Path
import uuid
import fitz
from nas_filetools.artifact_project import create_project, register_artifact, page_data, emit_viewer, digest
from nas_filetools.standalone.content_structure import parse_markdown, reading_html
from nas_filetools.standalone.source_preview import index_source
from nas_filetools.standalone.naming import decorate


def create(store):
    pid = str(uuid.uuid4())
    root = store / "projects" / pid
    p = create_project(root, "R7 人工文字修补演示（合成）", "synthetic-r7")
    p.update(
        project_id=pid,
        tasks=[],
        source_info={"kind": "pdf", "units": 24, "actual_type": "PDF", "validation_status": "SUCCEEDED"},
        selected_template={"id": "questions-zh-cn", "version": "1.0.0"},
    )
    doc = fitz.open()
    for n in range(1, 25):
        page = doc.new_page()
        page.insert_text((50, 70), f"R7 SYNTHETIC PHYSICAL PAGE {n:02d} / 24", fontsize=18)
        if n in [22, 23, 24]:
            page.insert_font(fontname="china-s")
            page.insert_text(
                (50, 130),
                f"合成第{n}页：人工修补错字。保留原件，保存新版本。",
                fontname="china-s",
                fontsize=14,
            )
    doc.save(root / "sources/original.pdf")
    doc.close()
    source = register_artifact(root, p, name="合成原件.pdf", format="pdf", path="sources/original.pdf")
    p["source_artifact_id"] = source["artifact_id"]
    p["source_info"]["bytes"] = (root / source["path"]).stat().st_size
    texts = [
        "# 合成文字修补测试\n\n第22页保持不变。",
        "## 第23页合成题\n\n1. 人工修补错宇后如何保存？\n\nA. 保留原件。\n\nB. 保存独立修订版。\n\nC. 不调用识别。\n\nD. 保留来源。",
        "## 第24页\n\n此页保持不变。",
    ]
    views = []
    for n, text in zip([22, 23, 24], texts):
        path = f"content/original-page-{n}.js"
        page_data(root, path, {"text": text, "reading_html": reading_html(parse_markdown(text))})
        views.append(
            {
                "label": f"来源物理第{n}页（合成）",
                "source_page": n,
                "locator": {"kind": "block", "id": f"p{n}-text"},
                "data": path,
                "data_sha256": digest(root / path),
            }
        )
    (root / "content/original.md").write_text("\n\n".join(texts), encoding="utf-8")
    md = register_artifact(
        root,
        p,
        name="合成文字稿",
        format="markdown",
        path="content/original.md",
        pages=views,
        parents=[source["artifact_id"]],
    )
    md.update(role="result", recognition_engine="合成夹具（未运行OCR）")
    index_source(root, p)
    decorate(p)
    emit_viewer(root, p)
    return {
        "project_id": pid,
        "source_artifact_id": source["artifact_id"],
        "markdown_artifact_id": md["artifact_id"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    print(json.dumps(create(parser.parse_args().store)))
