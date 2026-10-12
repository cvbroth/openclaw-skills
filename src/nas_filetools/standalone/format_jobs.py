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
    def direct_source_summary(self, pid, data):
        from .document_exports import export_options
        from .direct_source import collect

        with self.lock:
            project = self.get(pid)
            artifact = next(a for a in project["artifacts"] if a["artifact_id"] == data["source_artifact_id"])
            options = export_options(
                {**data, "mode": "markdown-direct", "purpose": "check", "blank_missing": False},
                project,
                artifact,
            )
            source = collect(self.path(pid), project, artifact, options["source_pages"])
            return {
                k: source.get(k, []) for k in ("requested_source_pages", "placeholder_candidates", "issues")
            } | {
                "expected_output_pages": len(source["requested_source_pages"]),
                "source_artifact_id": artifact["artifact_id"],
                "source_sha256": artifact["sha256"],
            }

    def export_documents(self, pid, data):
        from .document_exports import export_options

        with self.lock:
            project = self.get(pid)
            if not isinstance(data, dict):
                raise ValueError("导出设置必须是对象")
            if "mode" not in data and not data.get("template"):
                data = {**data, "mode": "markdown-direct"}
            artifact = next(a for a in project["artifacts"] if a["artifact_id"] == data["source_artifact_id"])
            options = export_options(data, project, artifact)
            if options["mode"] == "markdown-direct":
                from .direct_source import collect

                source = collect(
                    self.path(pid), project, artifact, options["source_pages"], options["blank_missing"]
                )
                if options["purpose"] == "preview" and len(source["requested_source_pages"]) != 1:
                    raise ValueError("纸张预览请选择一个来源物理页")
                if options["purpose"] == "export" and source["issues"]:
                    raise ValueError(
                        "导出前检查阻塞："
                        + "；".join(f"来源第{i['source_page']}页：{i['reason']}" for i in source["issues"])
                        + "。请先完整预检查；不会自动跳页，可明确修改来源范围后重试。"
                    )
            return self.format_artifact(
                pid,
                artifact["artifact_id"],
                data.get("template"),
                pagination={"mode": "source-pages"}
                if options["mode"] == "markdown-direct"
                else data.get("pagination"),
                export=options,
            )

    def format_artifact(self, pid, aid, choice, allow_draft=False, pagination=None, export=None):
        from .tasks import ACTIVE, now

        from .source_pagination import options

        policy = options(pagination)
        with self.lock:
            project = self.get(pid)
            if any(t["status"] in ACTIVE for t in project.get("tasks", [])):
                raise ValueError("project has active task")
            artifact = next(a for a in project["artifacts"] if a["artifact_id"] == aid)
            if artifact.get("recycled") or artifact["format"] != "markdown" or not artifact["path"]:
                raise ValueError("source_artifact_id: registered Markdown required")
            if policy["mode"] == "source-pages" and not (
                export
                and (export.get("mode") == "markdown-direct" or export.get("purpose") in {"check", "preview"})
            ):
                from .text_revisions import mapped_text

                mapped_text(self.path(pid), artifact)
                if not artifact.get("pages") or any(
                    type(v.get("source_page")) is not int
                    or not 1 <= v["source_page"] <= project.get("source_info", {}).get("units", 0)
                    for v in artifact["pages"]
                ):
                    raise ValueError("SOURCE_PAGE_MAPPING_REQUIRED: 保留原件分页需要每个片段的明确来源页")
            direct = export is not None and export.get("mode") == "markdown-direct"
            if direct:
                from .markdown_direct import direct_template

                template = direct_template()
                choice = {"id": "markdown-direct", "version": template["record"]["version"]}
            else:
                template = self.library.load(choice["id"], choice["version"], allow_draft)
            tid = str(uuid.uuid4())
            task = {
                "task_id": tid,
                "engine_id": "format",
                "operation": "format-artifact",
                "source_artifact_id": aid,
                "engine": {"model": "none"},
                "parameters": {},
                "pagination": policy,
                "pages": {},
                "result_versions": [],
                "template": choice,
                "template_sha256": template["record"]["sha256"],
                "template_data": template,
                "status": "QUEUED",
                "phase": "generation",
                "created_at": now(),
            }
            snapshot = self.path(pid) / "diagnostics/format" / tid / "template.json"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            raw = (
                json.dumps(template["reading_style"], ensure_ascii=False, sort_keys=True).encode()
                if direct
                else self.library.path(template["record"]).read_bytes()
            )
            import hashlib

            if hashlib.sha256(raw).hexdigest() != task["template_sha256"]:
                raise ValueError("TEMPLATE_HASH_CHANGED")
            snapshot.write_bytes(raw)
            task["template_snapshot"] = str(snapshot.relative_to(self.path(pid)))
            if export is not None:
                # Validate full assembly now, before accepting a range that could omit fragments.
                from .text_revisions import mapped_text

                if (
                    not direct
                    and export.get("purpose") not in {"check", "preview"}
                    and (
                        export["source_pages"] is not None
                        or any(v.get("data") for v in artifact.get("pages", []))
                    )
                ):
                    mapped_text(self.path(pid), artifact)
                task["document_export"] = {
                    **export,
                    "source_artifact_id": aid,
                    "source_sha256": artifact["sha256"],
                    "source_version": artifact["version"],
                    "excluded_source_pages": sorted(
                        {
                            v["source_page"]
                            for v in artifact.get("pages", [])
                            if type(v.get("source_page")) is int
                            and export["source_pages"] is not None
                            and v["source_page"] not in export["source_pages"]
                        }
                    ),
                    "source_page_mapping_complete": bool(artifact.get("pages"))
                    and all(type(v.get("source_page")) is int for v in artifact["pages"]),
                    "included_source_pages": sorted(
                        {
                            v["source_page"]
                            for v in artifact.get("pages", [])
                            if type(v.get("source_page")) is int
                            and (export["source_pages"] is None or v["source_page"] in export["source_pages"])
                        }
                    )
                    if artifact.get("pages")
                    and all(type(v.get("source_page")) is int for v in artifact["pages"])
                    else None,
                }
                if direct:
                    from .direct_source import collect

                    resolved = collect(
                        self.path(pid),
                        project,
                        artifact,
                        export["source_pages"],
                        export.get("blank_missing", False),
                    )
                    task["document_export"]["included_source_pages"] = resolved["requested_source_pages"]
                    task["document_export"]["placeholders"] = resolved.get("placeholders", [])
            if not allow_draft and not direct:
                project["selected_template"] = dict(choice)
                project["selected_pagination"] = policy
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
            if t["status"] == "CANCELLED" or self.cancels[tid].is_set():
                return
            t["status"] = "RUNNING"
            self.save(root, p)
        a = next(a for a in p["artifacts"] if a["artifact_id"] == t["source_artifact_id"])
        if t.get("document_export", {}).get("source_sha256", a["sha256"]) != a["sha256"]:
            raise ValueError("SOURCE_ARTIFACT_HASH_CHANGED")
        if digest(root / a["path"]) != a["sha256"]:
            raise ValueError("SOURCE_ARTIFACT_HASH_CHANGED")
        registered_text = (root / a["path"]).read_text()
        direct = t.get("document_export", {}).get("mode") == "markdown-direct"
        if (
            not direct
            and t.get("document_export")
            and (
                t["document_export"]["source_pages"] is not None
                or any(v.get("data") for v in a.get("pages", []))
            )
        ):
            from .text_revisions import mapped_text

            mapped_text(root, a)
        pages = []
        source = next(x for x in p["artifacts"] if x["artifact_id"] == p["source_artifact_id"])
        provenance = root / "sources/pdf-provenance.json"
        proven = json.loads(provenance.read_text()) if provenance.is_file() else {}
        source_check = None
        if direct:
            from .direct_source import collect

            source_check = collect(
                root,
                p,
                a,
                t["document_export"]["source_pages"],
                t["document_export"].get("blank_missing", False),
            )
            pages = source_check["pages"]
        for view in [] if direct else a["pages"]:
            selected = t.get("document_export", {}).get("source_pages")
            if selected is not None and view.get("source_page") not in selected:
                continue
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
                        "source_pdf_physical_page": view.get("source_page")
                        if t.get("document_export", {}).get("mode") == "markdown-direct"
                        else (
                            proven.get("source_pdf_physical_page")
                            if proven.get("image_sha256") == source.get("sha256")
                            else None
                        )
                        if p.get("source_info", {}).get("kind") == "image"
                        else view.get("source_page"),
                    }
                )
        if not direct and not pages and t.get("document_export", {}).get("source_pages") is not None:
            raise ValueError("所选原件页没有可导出的文字内容")
        if not direct and not pages:
            pages = [{"physical_page": 1, "text": (root / a["path"]).read_text()}]
        directory = root / "diagnostics/format" / tid
        work = directory / "work"
        work.mkdir(parents=True)
        result = self.run_child(
            {
                "pages": pages,
                "pagination": t.get("pagination"),
                "export_mode": t.get("document_export", {}).get("mode", "template"),
                "direct_compact": t.get("document_export", {}).get("compact"),
                "direct_purpose": t.get("document_export", {}).get("purpose", "export"),
                "formats": t.get("document_export", {}).get("formats", ["docx", "pdf"]),
                "source_issues": source_check["issues"] if source_check else [],
                "placeholder_candidates": source_check.get("placeholder_candidates", [])
                if source_check
                else [],
                "placeholders": source_check.get("placeholders", []) if source_check else [],
                "blank_missing": t.get("document_export", {}).get("blank_missing", False),
                "content_states": source_check["content_states"] if source_check else [],
                "requested_source_pages": source_check["requested_source_pages"] if source_check else None,
                "excluded_source_pages": t.get("document_export", {}).get("excluded_source_pages", []),
                "title": p["name"],
                "template": t["template"],
                "template_data": t["template_data"],
                "source_artifact_id": a["artifact_id"],
                "source_sha256": a["sha256"],
                "output": str(work),
                "engine": {"cpu_threads": 2},
            },
            work / "generation-result.json",
            min(
                86400,
                120
                + 120 * max(len(pages), len(source_check["requested_source_pages"]) if source_check else 0),
            )
            if direct
            else min(1800, 60 + 12 * len(pages))
            if t.get("pagination", {}).get("mode") == "source-pages"
            else 60,
            self.cancels[tid],
            module="nas_filetools.standalone.documents",
        )
        created = []
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if self.cancels[tid].is_set() or self.stopping.is_set():
                result = {"status": "CANCELLED"}
            purpose = t.get("document_export", {}).get("purpose", "export")
            report_path = work / "pagination-report.json"
            if direct and report_path.is_file():
                report = json.loads(report_path.read_text())
                t["direct_report"] = report
                t["pagination_report"] = str(report_path.relative_to(root))
                if (work / "progress.json").is_file():
                    t["direct_progress"] = json.loads((work / "progress.json").read_text())
            if result["status"] == "SUCCEEDED" and purpose == "export":
                required_formats = t["document_export"]["formats"] if direct else ["docx", "pdf"]
                output_files = [f"document.{fmt}" for fmt in required_formats] + [
                    "content-structure.json",
                    "layout-validation.json",
                ]
                if direct:
                    output_files.append("font-resolution.json")
                if (work / "pagination-report.json").is_file():
                    output_files.append("pagination-report.json")
                published = publish(
                    work,
                    directory,
                    [{"artifact_id": str(uuid.uuid4()), "kind": "output", "file": f} for f in output_files],
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
                ] + ([("font-resolution.json", "json")] if direct else []):
                    if not (work / file).is_file():
                        continue
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
                    if fmt in {"docx", "pdf"}:
                        item["role"] = "export"
                        item["export_source"] = {
                            "artifact_id": a["artifact_id"],
                            "sha256": a["sha256"],
                            "version": a["version"],
                            "template": t["template"],
                            "template_sha256": t["template_sha256"],
                            "source_pages": t.get("document_export", {}).get("included_source_pages"),
                            "requested_source_pages": t.get("document_export", {}).get("source_pages"),
                            "excluded_source_pages": t.get("document_export", {}).get(
                                "excluded_source_pages", []
                            ),
                            "source_page_mapping_complete": t.get("document_export", {}).get(
                                "source_page_mapping_complete", False
                            ),
                            "template_snapshot": t.get("template_snapshot"),
                            "pagination": t.get("pagination"),
                            "mode": t.get("document_export", {}).get("mode", "template"),
                            "blank_missing": t.get("document_export", {}).get("blank_missing", False),
                            "placeholders": t.get("document_export", {}).get("placeholders", []),
                            "compact": t.get("document_export", {}).get("compact"),
                            "reading_style": t.get("template_data", {}).get("reading_style"),
                            "renderer": t.get("direct_report", {}).get("renderer"),
                        }
                        if fmt not in t.get("document_export", {}).get("formats", ["docx", "pdf"]):
                            # Both formats are rendered for validation; expose only the requested files.
                            item["role"] = "diagnostic"
                    created.append(item["artifact_id"])
                if (work / "pagination-report.json").is_file():
                    paging = json.loads((work / "pagination-report.json").read_text())
                    for item in p["artifacts"]:
                        if item["artifact_id"] in created and item["format"] in {"docx", "pdf"}:
                            item["source_output_mapping"] = paging["groups"]
                    register_artifact(
                        root,
                        p,
                        name="分页适配记录",
                        format="json",
                        path=str((directory / "published/pagination-report.json").relative_to(root)),
                        parents=[a["artifact_id"]],
                    )
                choice = t["template"]
                if not any(
                    x["id"] == choice["id"] and x["version"] == choice["version"] for x in p["templates"]
                ):
                    snapshot_template(
                        root,
                        p,
                        root / t["template_snapshot"],
                        template_id=choice["id"],
                        version=choice["version"],
                    )
                imported = t["template_data"].get("document", {}).get("import_source")
                if imported:
                    import shutil

                    origin = self.library.root / "imports" / imported["import_id"]
                    dest = root / "templates" / ("import-" + imported["import_id"])
                    if not dest.exists():
                        shutil.copytree(origin, dest)
                t["result_versions"].append({"version": version, "artifacts": created, "created_at": now()})
            t.update(
                status=result["status"],
                finished_at=now(),
                metrics={k: result.get(k) for k in ["elapsed_seconds", "peak_rss_kib"]},
            )
            if result.get("error"):
                t["error"] = result["error"]
                if (work / "pagination-report.json").is_file():
                    t["pagination_report"] = str((work / "pagination-report.json").relative_to(root))
            emit_viewer(root, p)
            self.save(root, p)
        for item in p["artifacts"]:
            if (
                item["artifact_id"] in created
                and item["format"] in {"docx", "pdf"}
                and item.get("role") != "diagnostic"
            ):
                self.preview(pid, item["artifact_id"])
