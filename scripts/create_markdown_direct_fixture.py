#!/usr/bin/env python3
"""Synthetic-only mapped Markdown and immutable revision; no OCR or network."""

import json
from pathlib import Path
import sys
import time
import uuid
import fitz
from nas_filetools.artifact_project import page_data, register_artifact, emit_viewer
from nas_filetools.standalone.config import validate
from nas_filetools.standalone.tasks import Projects

root = Path(sys.argv[1])
assert root == Path("/evidence/store"), "Isolated evidence store required"
config = validate(json.loads(Path("/evidence/fixture-config.json").read_text()), testing=True)
config["engines"] = {}
m = Projects(root, config)


def settled(pid):
    until = time.monotonic() + 180
    while time.monotonic() < until:
        p = m.get(pid)
        if (
            p.get("analysis", {}).get("status") not in {"QUEUED", "RUNNING"}
            and not any(t["status"] in {"QUEUED", "RUNNING", "CANCELLING"} for t in p["tasks"])
            and not any(
                a.get("preview_render", {}).get("status") in {"QUEUED", "RUNNING"} for a in p["artifacts"]
            )
        ):
            return p
        time.sleep(0.1)
    raise RuntimeError("Evidence timeout")


try:
    source = root.parent / "synthetic.pdf"
    with fitz.open() as pdf:
        for n in range(1, 13):
            page = pdf.new_page()
            page.insert_text((60, 80), f"Synthetic physical page {n}", fontsize=16)
        pdf.save(source)
    pid = m.upload(source, "synthetic.pdf", project_name="合成 · Markdown原文直出验收")["project_id"]
    settled(pid)
    fragments = [
        (
            6,
            "# 阅读标题\n\n正文 **加粗** 和 *斜体*。①②③ ⸺ 📖。\n同段换行，普通 Page 99 不分页。\n\n- 第一项\n- 第二项\n\n3. 原序号三\n7. 原序号七",
        ),
        (
            6,
            "## 同页第二片段\n\n第二片段独立保存，保持原顺序。\n\nA. 普通正文选项\nB. 不自动组合\nC. 不猜测归属\nD. 保留四行",
        ),
        (7, "# 稀疏页\n\n本页只有少量内容。"),
        (8, "## 正常密度与长段落\n\n" + "这是一段已有文字，检查长段落自然换行和完整保存。" * 28),
        (9, "### 第九来源页\n\n正常正文保持单页。"),
        (10, "## 第十来源页\n\n最后一页正文。"),
    ]
    with m.lock:
        p = m.get(pid)
        folder = m.path(pid)
        views = []
        for i, (n, text) in enumerate(fragments):
            path = f"content/direct-{i}.js"
            page_data(folder, path, {"text": text})
            views.append(
                {
                    "label": f"来源第{n}页 · 片段{i + 1}",
                    "source_page": n,
                    "locator": {"kind": "block", "id": f"fragment-{i}"},
                    "data": path,
                }
            )
        (folder / "content/direct.md").write_text("\n\n".join(t for _, t in fragments))
        a = register_artifact(
            folder,
            p,
            name="合成Markdown原文",
            format="markdown",
            path="content/direct.md",
            pages=views,
            parents=[p["source_artifact_id"]],
        )
        emit_viewer(folder, p)
        m.save(folder, p)
        aid = a["artifact_id"]
    info = m.text_artifact(pid, aid)
    revised = m.save_text_revision(
        pid,
        {
            "request_id": str(uuid.uuid4()),
            "parent_artifact_id": aid,
            "parent_sha256": info["sha256"],
            "head_id": info["head_id"],
            "head_sha256": info["head_sha256"],
            "locator": info["pages"][0]["locator"],
            "text": fragments[0][1].replace("阅读标题", "人工修订版 · 阅读标题"),
        },
    )["artifact_id"]
    exports = []
    for formats, pages, version in [
        (["docx", "pdf"], "6-10", revised),
        (["docx"], "7", aid),
        (["pdf"], "8", revised),
    ]:
        task = m.export_documents(pid, {"source_artifact_id": version, "pages": pages, "formats": formats})
        p = settled(pid)
        t = m.task(p, task["task_id"])
        assert t["status"] == "SUCCEEDED", t
        exports.append({"task_id": t["task_id"], "formats": formats, "pages": pages, "source": version})
    manifest = {
        "project_id": pid,
        "original_artifact_id": aid,
        "revised_artifact_id": revised,
        "exports": exports,
        "OCR_calls": 0,
        "paid_model_calls": 0,
    }
    Path("/evidence/fixture.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False))
finally:
    m.close()
