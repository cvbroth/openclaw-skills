"""Pure derived formatting jobs; no recognition adapter or network access."""

import json
import threading
import uuid
from ..publication import publish
from ..artifact_project import (
    create_project,
    register_artifact,
    emit_viewer,
    digest,
    page_data,
    snapshot_template,
)
from .content_structure import parse_markdown, reading_html

SYNTHETIC = """# 模板合成预览

## 基础结构

普通段落包含 **加粗**、*斜体* 和有意保留的 \\*文字星号\\*。
同一段落的下一行。

- 无序列表第一项
- 第二项 **强调文字**

3. 有序列表原序号三
7. 有序列表原序号七（不自动纠正编号）

### 明确的题干与选项示例

1. 以下哪项符合保留原件的原则？

A. 原件不变。

B. 独立保存派生产物。

C. 保留来源。

D. 不编造答案。

""" + "\n\n".join(
    "普通长段落 " + str(i + 1) + "：这是固定合成内容，用于检查版式、页面与文字完整性。" * 8 for i in range(12)
)


class FormatJobs:
    def format_artifact(self, pid, aid, choice, allow_draft=False):
        from .tasks import ACTIVE, now

        with self.lock:
            project = self.get(pid)
            if any(t["status"] in ACTIVE for t in project.get("tasks", [])):
                raise ValueError("project has active task")
            artifact = next(a for a in project["artifacts"] if a["artifact_id"] == aid)
            if artifact["format"] != "markdown" or not artifact["path"]:
                raise ValueError("source_artifact_id: registered Markdown required")
            template = self.library.load(choice["id"], choice["version"], allow_draft)
            tid = str(uuid.uuid4())
            task = {
                "task_id": tid,
                "engine_id": "format",
                "operation": "format-artifact",
                "source_artifact_id": aid,
                "engine": {"model": "none"},
                "parameters": {},
                "pages": {},
                "result_versions": [],
                "template": choice,
                "template_sha256": template["record"]["sha256"],
                "template_data": template,
                "status": "QUEUED",
                "created_at": now(),
            }
            if not allow_draft:
                project["selected_template"] = dict(choice)
            project.setdefault("tasks", []).append(task)
            self.cancels[tid] = threading.Event()
            self.save(self.path(pid), project)
            self.queue.put((pid, tid))
            return {"project_id": pid, "task_id": tid, "engine_calls": 0}

    def template_preview(self, tid, version):
        from .tasks import atomic

        loaded = self.library.load(tid, version, True)
        root = self.root / "uploads" / ("template-" + uuid.uuid4().hex)
        p = create_project(root, "模板预览 · " + loaded["record"]["name"], "fixed-template-preview")
        target = self.root / "projects" / p["project_id"]
        root.rename(target)
        root = target
        p["project_kind"] = "template-preview"
        p["tasks"] = []
        # Explicit synthetic source, not a business attachment or a pretend model response.
        (root / "content/content.md").write_text(SYNTHETIC)
        a = register_artifact(
            root,
            p,
            name="固定合成Markdown",
            format="markdown",
            path="content/content.md",
            pages=[
                {
                    "label": "合成内容",
                    "locator": {"kind": "block", "id": "synthetic-template"},
                    "data": "content/synthetic-template.js",
                }
            ],
        )
        page_data(
            root,
            "content/synthetic-template.js",
            {"text": SYNTHETIC, "reading_html": reading_html(parse_markdown(SYNTHETIC))},
        )
        p["source_artifact_id"] = a["artifact_id"]
        emit_viewer(root, p)
        atomic(root / "project.json", p)
        result = self.format_artifact(
            p["project_id"], a["artifact_id"], {"id": tid, "version": version}, True
        )
        with self.lock:
            catalog = self.library.catalog()
            for e in catalog["templates"]:
                if e["id"] == tid and e["version"] == version:
                    e["preview_project_id"] = p["project_id"]
            self.library.write_catalog(catalog)
        return result

    def execute_format(self, pid, tid):
        from .tasks import now

        root = self.path(pid)
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            t["status"] = "RUNNING"
            self.save(root, p)
        a = next(a for a in p["artifacts"] if a["artifact_id"] == t["source_artifact_id"])
        if digest(root / a["path"]) != a["sha256"]:
            raise ValueError("SOURCE_ARTIFACT_HASH_CHANGED")
        registered_text = (root / a["path"]).read_text()
        pages = []
        source = next(x for x in p["artifacts"] if x["artifact_id"] == p["source_artifact_id"])
        provenance = root / "sources/pdf-provenance.json"
        proven = json.loads(provenance.read_text()) if provenance.is_file() else {}
        for view in a["pages"]:
            if view.get("data"):
                if view.get("data_sha256") and digest(root / view["data"]) != view["data_sha256"]:
                    raise ValueError("SOURCE_VIEW_HASH_CHANGED")
                raw = (root / view["data"]).read_text()
                payload = json.loads(raw.split("=", 1)[1].rstrip(";\n"))
                if payload.get("text") and payload["text"] not in registered_text:
                    raise ValueError("SOURCE_VIEW_TEXT_NOT_IN_REGISTERED_MARKDOWN")
                pages.append(
                    {
                        "physical_page": view.get("source_page")
                        or view["locator"].get("page")
                        or len(pages) + 1,
                        "text": payload.get("text", ""),
                        "source_locator": view["locator"],
                        "source_pdf_physical_page": (
                            proven.get("source_pdf_physical_page")
                            if proven.get("image_sha256") == source.get("sha256")
                            else None
                        )
                        if p.get("source_info", {}).get("kind") == "image"
                        else view.get("source_page"),
                    }
                )
        if not pages:
            pages = [{"physical_page": 1, "text": (root / a["path"]).read_text()}]
        directory = root / "diagnostics/format" / tid
        work = directory / "work"
        work.mkdir(parents=True)
        result = self.run_child(
            {
                "pages": pages,
                "title": p["name"],
                "template": t["template"],
                "template_data": t["template_data"],
                "source_artifact_id": a["artifact_id"],
                "source_sha256": a["sha256"],
                "output": str(work),
                "engine": {"cpu_threads": 2},
            },
            work / "generation-result.json",
            60,
            self.cancels[tid],
            module="nas_filetools.standalone.documents",
        )
        created = []
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if result["status"] == "SUCCEEDED":
                published = publish(
                    work,
                    directory,
                    [
                        {"artifact_id": str(uuid.uuid4()), "kind": "output", "file": f}
                        for f in [
                            "document.docx",
                            "document.pdf",
                            "content-structure.json",
                            "layout-validation.json",
                        ]
                    ],
                )
                # A new immutable version derives from this exact source/template pair.
                version = 1 + max(
                    [
                        int(x["version"])
                        for x in p["artifacts"]
                        if x["format"] in {"docx", "pdf"} and str(x["version"]).isdigit()
                    ]
                    + [0]
                )
                for file, fmt in [
                    ("document.docx", "docx"),
                    ("document.pdf", "pdf"),
                    ("content-structure.json", "json"),
                    ("layout-validation.json", "json"),
                ]:
                    item = register_artifact(
                        root,
                        p,
                        name=file,
                        format=fmt,
                        path=str(
                            (
                                directory
                                / next(x["file"] for x in published if x["file"].endswith("/" + file))
                            ).relative_to(root)
                        ),
                        version=str(version),
                        parents=[a["artifact_id"]],
                    )
                    item.update(
                        task_id=tid,
                        recognition_engine=a.get("recognition_engine")
                        or next(
                            (x["engine_id"] for x in p["tasks"] if x["task_id"] == a.get("task_id")),
                            "历史结果",
                        ),
                        content_nature="markdown-basic",
                        template_label=t["template"]["id"] + "/" + t["template"]["version"],
                        role="result" if fmt in {"docx", "pdf"} else "diagnostic",
                    )
                    created.append(item["artifact_id"])
                choice = t["template"]
                entry = t["template_data"]["record"]
                if not any(
                    x["id"] == choice["id"] and x["version"] == choice["version"] for x in p["templates"]
                ):
                    snapshot_template(
                        root, p, self.library.path(entry), template_id=choice["id"], version=choice["version"]
                    )
                t["result_versions"].append({"version": version, "artifacts": created, "created_at": now()})
            t.update(
                status=result["status"],
                finished_at=now(),
                metrics={k: result.get(k) for k in ["elapsed_seconds", "peak_rss_kib"]},
            )
            if result.get("error"):
                t["error"] = result["error"]
            emit_viewer(root, p)
            self.save(root, p)
        for item in p["artifacts"]:
            if item["artifact_id"] in created and item["format"] in {"docx", "pdf"}:
                self.preview(pid, item["artifact_id"])
