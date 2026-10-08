"""Adapt explicit existing deliveries into NEW task projects; no inference/conversion."""

import argparse
import html
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_filetools.artifact_project import (
    create_project,
    digest,
    emit_viewer,
    page_data,
    register_artifact,
    snapshot_template,
    write_json,
)


def copy(root, source, target):
    destination = root / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return target


def legacy_m3(source, root, original_reference):
    data = json.loads((source / "structure.json").read_text())
    project = create_project(root, "M3 50页原图转写与质量自评", "m3-quality50-20261008")
    project["adapter"] = {
        "name": "legacy-m3-quality50-v1",
        "source_structure_sha256": digest(source / "structure.json"),
        "note": "Historical results only; no new requests; original bundle unchanged.",
    }
    source_pages, md_pages = [], []
    for row in data["pages"]:
        n = row["physical_page"]
        old = row["source"]["image"]
        image = copy(root, source / old, f"sources/previews/page-{n}.png")
        if digest(root / image) != row["source"]["sha256"]:
            raise ValueError("preview source hash mismatch")
        source_pages.append(
            {"label": f"原PDF物理第{n}页", "locator": {"kind": "physical_page", "page": n}, "image": image}
        )
        page_path = f"content/pages/page-{n}.js"
        attempt = row["attempts"][-1]["path"]
        # Only existing exact files; no NAS or cache discovery.
        folder = source / attempt
        if folder.is_file():
            folder = folder.parent
        raw = folder / "response.raw.json"
        raw_path = copy(root, raw, f"diagnostics/page-{n}/response.raw.json") if raw.is_file() else None
        for filename in ("receipt.json", "parse-receipt.json", "quality.raw.txt", "transcription.md"):
            if (folder / filename).is_file():
                copy(root, folder / filename, f"diagnostics/page-{n}/{filename}")
        page_data(root, page_path, {"text": row["text"], "quality": row.get("quality"), "raw_path": raw_path})
        md_pages.append(
            {
                "label": f"来源物理第{n}页 · " + row["status"],
                "locator": (
                    {"kind": "block", "id": row["blocks"][0]["id"]}
                    if row.get("blocks")
                    else {"kind": "source_page", "page": n}
                ),
                "block_id": row.get("blocks", [{}])[0].get("id") if row.get("blocks") else None,
                "data": page_path,
                "quality": (row.get("quality") or {}).get("overall_quality"),
                "error": row["status"] != "succeeded",
                "source_page": n,
            }
        )
    ref = register_artifact(
        root,
        project,
        name="PDF原件引用＋已有原图预览",
        format="reference",
        external_reference={"path": original_reference, "sha256": data["source_pdf_sha256"]},
        pages=source_pages,
    )
    copy(root, source / "content.md", "content/content.md")
    copy(root, source / "structure.json", "content/structure.json")
    md = register_artifact(
        root,
        project,
        name="M3原始Markdown（未人工验收）",
        format="markdown",
        path="content/content.md",
        parents=[ref["artifact_id"]],
        pages=md_pages,
    )
    register_artifact(
        root,
        project,
        name="历史原生映射（未改写）",
        format="json",
        path="content/structure.json",
        parents=[md["artifact_id"]],
    )
    # No document generation template was used in this experiment.
    write_json(
        root / "templates" / "README.json",
        {"status": "not-used", "reason": "direct model transcription, not document rendering"},
    )
    emit_viewer(root, project)
    return project


def document_sample(source, previews, originals, template, root, original_reference, pdf_sha):
    project = create_project(
        root, "已存在的第6–10页文档生成小样", "production-0fe1b69318ae456ca642b728d286be64"
    )
    rows = []
    for n in range(6, 11):
        image = copy(root, originals / f"original-page-{n}.png", f"sources/previews/page-{n}.png")
        rows.append(
            {"label": f"原PDF物理第{n}页", "locator": {"kind": "physical_page", "page": n}, "image": image}
        )
    ref = register_artifact(
        root,
        project,
        name="PDF原件引用＋第6–10页预览",
        format="reference",
        external_reference={"path": original_reference, "sha256": pdf_sha},
        pages=rows,
    )
    for filename in (
        "original-ocr.md",
        "structured.json",
        "issues.md",
        "validation.json",
        "generation-metrics.json",
    ):
        copy(
            root,
            source / filename,
            ("content/" if filename in {"original-ocr.md", "structured.json"} else "diagnostics/") + filename,
        )
    copy(root, source / "original-ocr.md", "content/content.md")
    copy(root, source / "structured.json", "content/structure.json")
    text_path = "content/content.md"
    page_data(root, "content/raw-ocr.js", {"text": (source / "original-ocr.md").read_text(), "quality": None})
    raw = register_artifact(
        root,
        project,
        name="原始OCR（非生成后的整理正文）",
        format="markdown",
        path=text_path,
        parents=[ref["artifact_id"]],
        pages=[
            {
                "label": "原OCR全文；未提供段落对应",
                "locator": {"kind": "document"},
                "data": "content/raw-ocr.js",
            }
        ],
    )
    structured = register_artifact(
        root,
        project,
        name="独立整理与来源映射",
        format="json",
        path="content/structured.json",
        parents=[raw["artifact_id"]],
    )
    for fmt, prefix, count in [("pdf", "pdf", 9), ("docx", "word", 10)]:
        file = "sample." + fmt
        copy(root, source / file, "outputs/" + file)
        pages = []
        for n in range(1, count + 1):
            im = copy(root, previews / f"{prefix}-page-{n}.png", f"outputs/previews/{prefix}-{n}.png")
            # Output page is NOT original PDF physical page.
            pages.append(
                {
                    "label": f"{'PDF' if fmt == 'pdf' else 'Word历史渲染'}自身第{n}页（无原页一一映射）",
                    "locator": (
                        {"kind": "document"} if fmt == "docx" else {"kind": "physical_page", "page": n}
                    ),
                    "image": im,
                    "output_page": n,
                }
            )
        register_artifact(
            root,
            project,
            name=file,
            format=fmt,
            path="outputs/" + file,
            parents=[structured["artifact_id"]],
            pages=pages,
            preview={
                "label": "已有独立渲染图片；"
                + (
                    "Word经LibreOffice历史渲染，不是浏览器原生Word，也非用户字体环境。无稳定段落定位，评论作用于整份Word，预览页只作浏览位置。"
                    if fmt == "docx"
                    else "已有PDF渲染预览。"
                ),
                "source_pdf_sha256": digest(previews / "sample.pdf")
                if fmt == "docx"
                else digest(source / file),
            },
        )
    metrics = json.loads((source / "generation-metrics.json").read_text())
    if digest(template) != metrics["template_sha256"]:
        raise ValueError("template snapshot differs from historical generation")
    snapshot_template(
        root, project, template, template_id=metrics["template_id"], version=metrics["template_version"]
    )
    project["historical_generation_metrics_sha256"] = digest(source / "generation-metrics.json")
    project["note"] = (
        "Existing production small sample; not derived from the M3 50-page project. No new generation."
    )
    write_json(
        root / "diagnostics" / "adapter.json",
        {"source": str(source), "metrics": metrics, "preview_source": str(previews)},
    )
    emit_viewer(root, project)
    return project


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--legacy", type=Path, required=True)
    p.add_argument("--sample", type=Path, required=True)
    p.add_argument("--sample-previews", type=Path, required=True)
    p.add_argument("--original-previews", type=Path, required=True)
    p.add_argument("--template", type=Path, required=True)
    p.add_argument("--original-reference", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    original_hash = json.loads((a.legacy / "structure.json").read_text())["source_pdf_sha256"]
    projects = [
        legacy_m3(a.legacy, a.output / "m3-50", a.original_reference),
        document_sample(
            a.sample,
            a.sample_previews,
            a.original_previews,
            a.template,
            a.output / "document-sample",
            a.original_reference,
            original_hash,
        ),
    ]
    links = "".join(
        f'<li><a href="{folder}/review/index.html">{html.escape(project["name"])}</a> — 独立项目；人工评论初始为空</li>'
        for folder, project in zip(["m3-50", "document-sample"], projects)
    )
    (a.output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>FileTools 项目列表</title><h1>产物评审演示</h1><ul>'
        + links
        + "</ul><p>完整解压，离线打开。草稿仅保存在本机浏览器，请导出JSON备份；不代表人工验收。原件仅外部引用，包内包含既有预览。先选左右产物，再分别定位。Word为明确标注的历史渲染预览。</p>",
        encoding="utf-8",
    )
    (a.output / "README.md").write_text(
        "完整解压后打开 index.html。左右独立滚动；两侧位置分别选择。底部评论始终可访问。切换自动保存草稿，导出后交回开发侧。导入拒绝项目/版本不符及冲突；不能作为身份认证。更换电脑或移动目录可能无法沿用浏览器localStorage，请先导出再导入。旧包不变。本包不是FileTools正式发布回执，没有新OCR/模型/文档生成。\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "project_ids": [x["project_id"] for x in projects],
                "artifacts": [len(x["artifacts"]) for x in projects],
            }
        )
    )


if __name__ == "__main__":
    main()
