"""Isolated 184-page synthetic source; no recognition or paid engines."""

from pathlib import Path
import copy
import json
import time
import fitz
from nas_filetools.artifact_project import page_data, register_artifact, emit_viewer
from nas_filetools.standalone.tasks import Projects
from nas_filetools.standalone.config import validate

root = Path("/evidence/store")
config = validate(json.loads(Path("/evidence/fixture-config.json").read_text()), testing=True)
config["engines"] = {}
m = Projects(root, config)
try:
    source = Path("/evidence/synthetic.pdf")
    with fitz.open() as pdf:
        for n in range(1, 185):
            page = pdf.new_page()
            page.insert_text((60, 80), f"Synthetic physical page {n}")
        pdf.save(source)
    pid = m.upload(source, source.name, project_name="合成 · 缺页与范围验收")["project_id"]
    while m.get(pid).get("analysis", {}).get("status") in {"QUEUED", "RUNNING"}:
        time.sleep(0.1)
    p = m.get(pid)
    folder = m.path(pid)
    views = []
    texts = []
    for n in range(6, 184):
        content = f"# 合成来源 {n}\n\n正文第{n}页，独立来源不能前移。①②③ ⸺ 📖。"
        if n == 8:
            content = "#### 四级标题\n\n##### 五级标题\n\n###### 六级标题\n\n> 引用 **加粗** 与 *斜体*。\n\n---\n\n```text\n代码 **原符号** | 管道\n  <标签>原样</标签>\n```\n\n普通 `代码文字` ①②③。"
        if n == 61:
            content = "过长的正文。" * 5000
        if n == 62:
            content = "| A | B |\n| -- | -- |\n| C | D |"
        if n == 145:
            content = ""
        parts = [content, "同一来源页的第二片段，全部保留。"] if n == 6 else [content]
        for j, text in enumerate(parts):
            name = f"content/synthetic-{n}-{j}.js"
            page_data(folder, name, {"text": text})
            texts.append(text)
            views.append(
                {
                    "source_page": n,
                    "locator": {"kind": "block", "id": f"fragment-{n}-{j}"},
                    "data": name,
                    "error": n == 145,
                }
            )
    (folder / "content/selected.md").write_text("\n\n".join(texts))
    a = register_artifact(
        folder,
        p,
        name="合成第2版",
        format="markdown",
        path="content/selected.md",
        version="2",
        pages=views,
        parents=[p["source_artifact_id"]],
    )
    broken = copy.deepcopy(views)
    broken[58]["data"] = "content/does-not-exist.js"
    broken[58]["data_sha256"] = "0" * 64
    b = register_artifact(
        folder,
        p,
        name="合成资源损坏版",
        format="markdown",
        path="content/selected.md",
        version="3",
        pages=broken,
        parents=[a["artifact_id"]],
    )
    emit_viewer(folder, p)
    m.save(folder, p)
    Path("/evidence/fixture.json").write_text(
        json.dumps(
            {
                "project_id": pid,
                "artifact_id": a["artifact_id"],
                "broken_artifact_id": b["artifact_id"],
                "OCR_calls": 0,
                "paid_model_calls": 0,
            },
            indent=2,
        )
    )
finally:
    m.close()
