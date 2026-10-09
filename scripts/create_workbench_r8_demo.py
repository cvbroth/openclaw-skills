"""Explicit 169-page synthetic workbench fixture; no model or OCR calls."""

import argparse
import json
from pathlib import Path
import uuid
import fitz
from nas_filetools.artifact_project import create_project, register_artifact, page_data, emit_viewer, digest
from nas_filetools.standalone.source_preview import index_source
from nas_filetools.standalone.content_structure import parse_markdown, reading_html
from nas_filetools.standalone.naming import decorate


def create(store):
    pid = str(uuid.uuid4())
    root = store / "projects" / pid
    p = create_project(root, "R8 对照与模板演示（合成169页，非真实试题册）", "synthetic-r8")
    p.update(
        project_id=pid,
        tasks=[],
        source_info={"kind": "pdf", "units": 169, "actual_type": "PDF", "validation_status": "SUCCEEDED"},
        selected_template={"id": "questions-zh-cn", "version": "1.0.0"},
    )
    d = fitz.open()
    for n in range(1, 170):
        page = d.new_page()
        page.insert_text((50, 70), f"R8 SYNTHETIC PHYSICAL PAGE {n:03d} / 169", fontsize=18)
        page.insert_text((50, 130), f"合成物理第{n}页，不是用户试题册。", fontname="china-s", fontsize=14)
    d.save(root / "sources/original.pdf")
    d.close()
    a = register_artifact(root, p, name="合成原件.pdf", format="pdf", path="sources/original.pdf")
    p["source_artifact_id"] = a["artifact_id"]
    p["source_info"]["bytes"] = (root / a["path"]).stat().st_size
    result = {"project_id": pid, "source_artifact_id": a["artifact_id"]}
    sets = [("main", list(range(1, 18)) + [23, 24]), ("multiple", [23, 23, 24]), ("unmapped", [None])]
    for label, positions in sets:
        views = []
        texts = []
        for i, n in enumerate(positions, 1):
            text = f"## 合成片段{i}\n\n来源映射演示，原件物理页{n}。\n\n1. 合成错宇修补及完整文字保留。\n\nA. 独立定位。\n\nB. 保留原件。\n\nC. 不调用识别。\n\nD. 不伪造来源。"
            path = f"content/{label}-{i}.js"
            texts.append(text)
            page_data(root, path, {"text": text, "reading_html": reading_html(parse_markdown(text))})
            view = {
                "label": f"合成片段{i}",
                "locator": {"kind": "block", "id": f"{label}-{i}"},
                "data": path,
                "data_sha256": digest(root / path),
            }
            if n is not None:
                view["source_page"] = n
            views.append(view)
        path = f"content/{label}.md"
        (root / path).write_text("\n\n".join(texts))
        a = register_artifact(
            root,
            p,
            name="提取文字 · " + label,
            format="markdown",
            path=path,
            pages=views,
            parents=[p["source_artifact_id"]],
        )
        a.update(
            role="result",
            recognition_engine="合成夹具（未运行OCR）",
            display_name_override={
                "main": "文字稿 · 来源定位示例",
                "multiple": "文字稿 · 一对多示例",
                "unmapped": "文字稿 · 无映射示例",
            }[label],
        )
        result[label + "_artifact_id"] = a["artifact_id"]
    p["source_evaluations"] = [
        {
            "evaluation_id": "synthetic-quality-23",
            "source_artifact_id": p["source_artifact_id"],
            "source_sha256": next(
                a["sha256"] for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"]
            ),
            "source_locator": {"kind": "physical_page", "page": 23},
            "model": "合成筛选夹具（未调用模型）",
            "assessed_at": "2026-10-10T00:00:00Z",
            "quality": {
                "overall_quality": "poor",
                "evidence": ["仅用于筛选交互测试，不评价真实图像。"],
                "uncertainty_note": "明确合成测试记录",
            },
        }
    ]
    index_source(root, p)
    decorate(p)
    emit_viewer(root, p)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    print(json.dumps(create(parser.parse_args().store)))
