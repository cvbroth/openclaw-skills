"""Immutable, cancellable Pandoc -> DOCX -> LibreOffice PDF jobs."""

import json
import threading
import uuid
from ..artifact_project import create_project, register_artifact, emit_viewer, digest, page_data
from ..publication import publish
from .text_revisions import export_rows
from .content_marks import read_marks, clean_rows
from .document_exports import export_options

SYNTHETIC = "# 合成模板预览\n\n普通 **加粗** 与 *斜体*。\n\n- 真正列表\n- 第二项\n\n> 引用\n\n|列一|列二|\n|---|---|\n|1|2|\n"


class FormatJobs:
    def export_documents(self, pid, data, allow_draft=False):
        from .tasks import now, atomic, ACTIVE
        from .pandoc_export import reference_path, reference_snapshot

        with self.lock:
            p = self.get(pid)
            root = self.path(pid)
            if any(t["status"] in ACTIVE for t in p.get("tasks", [])):
                raise ValueError("project has active task")
            a = next(a for a in p["artifacts"] if a["artifact_id"] == data["source_artifact_id"])
            settings = export_options(data, p, a)
            rows = export_rows(root, a)
            selected = settings["source_pages"]
            if selected is not None:
                if any(
                    type(r["view"].get("source_page")) is not int
                    or set(r["view"].get("source_pages", [r["view"]["source_page"]]))
                    != {r["view"]["source_page"]}
                    for r in rows
                ):
                    raise ValueError("来源映射不足或跨页范围不明确，不能按来源页选择；可导出全部已有文字")
                available = {r["view"]["source_page"] for r in rows}
                missing = sorted(set(selected) - available)
                if missing:
                    raise ValueError(
                        "没有文字记录的来源页："
                        + ",".join(map(str, missing))
                        + "；连续分页不会自动占位或静默跳页，请明确调整范围"
                    )
                rows = [r for r in rows if r["view"]["source_page"] in selected]
            # State validation is content evidence, not a pagination precheck.
            from .direct_source import content_state

            cache = {}
            issues = []
            for row in rows:
                valid, reason = (
                    (bool(row["text"].strip()) and not a.get("error"), "历史整稿缺少正文或有错误状态")
                    if row["view"].get("mapping_unavailable")
                    else content_state(root, p, a, row, cache)
                )
                if not valid:
                    issues.append(f"来源{row['view'].get('source_page', '未知')}：{reason}")
            if issues:
                raise ValueError(
                    "所选内容不完整：" + "；".join(issues) + "。请修订正文或明确缩小范围；不会自动插入空白页"
                )
            marks = read_marks(root, a)
            cleaned, summary = clean_rows(rows, marks, settings)
            if not any(r["text"].strip() for r in cleaned):
                raise ValueError("清理后没有正文，请调整范围或清理选项")
            template = None
            if settings.get("template"):
                choice = settings["template"]
                template = self.library.load(choice["id"], choice["version"], allow_draft)
            tid = str(uuid.uuid4())
            directory = root / "diagnostics/format" / tid
            directory.mkdir(parents=True)
            import shutil

            shutil.copyfile(reference_path(), directory / "reference.docx")
            style = reference_snapshot(directory / "reference.docx")
            task = {
                "task_id": tid,
                "engine_id": "format",
                "operation": "format-artifact",
                "engine": {"model": "none"},
                "source_artifact_id": a["artifact_id"],
                "parameters": {},
                "pages": {},
                "result_versions": [],
                "status": "QUEUED",
                "phase": "queued",
                "created_at": now(),
                "document_export": {
                    **settings,
                    "source_artifact_id": a["artifact_id"],
                    "source_sha256": a["sha256"],
                    "source_version": a["version"],
                    "included_source_pages": sorted(
                        {r["view"]["source_page"] for r in rows if type(r["view"].get("source_page")) is int}
                    ),
                    "source_page_mapping_complete": all(
                        type(r["view"].get("source_page")) is int for r in rows
                    ),
                    "cleaning_summary": summary,
                    "marks_revision": marks["revision"],
                },
                "reference_snapshot": str((directory / "reference.docx").relative_to(root)),
                "reference_sha256": style["sha256"],
                "template": {"id": "pandoc-reference", "version": style["version"]},
                "template_data": template,
                "pagination": {"mode": "continuous"},
            }
            atomic(
                directory / "source-snapshot.json",
                {
                    "rows": cleaned,
                    "original_rows": rows,
                    "marks": marks,
                    "style": style,
                    "settings": settings,
                    "document_metadata": p.get("document_metadata", {}),
                },
            )
            p.setdefault("tasks", []).append(task)
            self.cancels[tid] = threading.Event()
            self.save(root, p)
            self.queue.put((pid, tid))
            return {"project_id": pid, "task_id": tid, "engine_calls": 0, "cleaning_summary": summary}

    def format_artifact(self, pid, aid, choice, allow_draft=False, pagination=None, export=None):
        if pagination and pagination.get("mode") != "continuous":
            raise ValueError("来源强制分页已移除；请选择连续自然分页")
        return self.export_documents(pid, {"source_artifact_id": aid, "template": choice}, allow_draft)

    def template_preview(self, tid, version):
        from .tasks import atomic

        loaded = self.library.load(tid, version, True)
        folder = self.root / "uploads" / ("template-" + uuid.uuid4().hex)
        p = create_project(folder, "Pandoc合成预览 · " + loaded["record"]["name"], "fixed-template-preview")
        target = self.root / "projects" / p["project_id"]
        folder.rename(target)
        p.update(project_kind="template-preview", tasks=[])
        (target / "content/content.md").write_text(SYNTHETIC)
        page_data(target, "content/sample.js", {"text": SYNTHETIC})
        a = register_artifact(
            target,
            p,
            name="合成文字",
            format="markdown",
            path="content/content.md",
            pages=[
                {
                    "label": "合成",
                    "locator": {"kind": "block", "id": "synthetic"},
                    "data": "content/sample.js",
                }
            ],
        )
        p["source_artifact_id"] = a["artifact_id"]
        emit_viewer(target, p)
        atomic(target / "project.json", p)
        return self.format_artifact(p["project_id"], a["artifact_id"], {"id": tid, "version": version}, True)

    def execute_format(self, pid, tid):
        from .tasks import now

        root = self.path(pid)
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if t["status"] == "CANCELLED" or self.cancels[tid].is_set():
                return
            t.update(status="RUNNING", phase="prepare")
            self.save(root, p)
        directory = root / "diagnostics/format" / tid
        work = directory / "work"
        work.mkdir(exist_ok=True)
        a = next(a for a in p["artifacts"] if a["artifact_id"] == t["source_artifact_id"])
        if digest(root / a["path"]) != t["document_export"]["source_sha256"]:
            raise ValueError("所选文字版本哈希变化")
        export_rows(root, a)  # Recheck registered resources; snapshots are not a bypass for corruption.
        snapshot = json.loads((directory / "source-snapshot.json").read_text())
        pages = [
            {
                "text": r["text"],
                "source_locator": r["view"]["locator"],
                "source_pdf_physical_page": r["view"].get("source_page"),
            }
            for r in snapshot["rows"]
        ]
        result = self.run_child(
            {
                "engine": {"cpu_threads": 2},
                "export_mode": "pandoc",
                "pages": pages,
                "title": p["name"],
                "output": str(work),
                "project_root": str(root),
                "source_path": a["path"],
                "resource_base": a.get(
                    "resource_base",
                    str(
                        (
                            root
                            / next(
                                (
                                    x["path"]
                                    for x in p["artifacts"]
                                    if x["artifact_id"] == a.get("text_revision", {}).get("root_artifact_id")
                                ),
                                a["path"],
                            )
                        ).parent.relative_to(root)
                    ),
                ),
                "source_artifact_id": a["artifact_id"],
                "source_sha256": a["sha256"],
                "reference": str(root / t["reference_snapshot"]),
                "reference_sha256": t["reference_sha256"],
                "settings": t["document_export"],
                "template_data": t.get("template_data"),
                "metadata": snapshot["document_metadata"],
            },
            work / "generation-result.json",
            min(86400, max(600, 120 + len(pages) * 30)),
            self.cancels[tid],
            module="nas_filetools.standalone.documents",
        )
        created = []
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if self.cancels[tid].is_set() or self.stopping.is_set():
                result = {"status": "CANCELLED"}
            if (work / "progress.json").is_file():
                t["export_progress"] = json.loads((work / "progress.json").read_text())
            if result["status"] == "SUCCEEDED":
                files = ["document." + f for f in t["document_export"]["formats"]] + [
                    "content-structure.json",
                    "layout-validation.json",
                    "font-resolution.json",
                ]
                published = publish(
                    work,
                    directory,
                    [{"artifact_id": str(uuid.uuid4()), "kind": "output", "file": f} for f in files],
                )
                version = str(
                    1
                    + max(
                        [
                            int(x["version"])
                            for x in p["artifacts"]
                            if x["format"] in {"docx", "pdf"} and str(x["version"]).isdigit()
                        ]
                        + [0]
                    )
                )
                validation = json.loads((work / "layout-validation.json").read_text())
                t["export_validation"] = validation
                for file in files:
                    fmt = PathSuffix(file)
                    path = directory / next(x["file"] for x in published if x["file"].endswith("/" + file))
                    item = register_artifact(
                        root,
                        p,
                        name=file,
                        format=fmt,
                        path=str(path.relative_to(root)),
                        version=version,
                        parents=[a["artifact_id"]],
                    )
                    item.update(
                        task_id=tid,
                        role="export" if fmt in {"docx", "pdf"} else "diagnostic",
                        template_label="pandoc-reference/1.0.0",
                    )
                    if item["role"] == "export":
                        item["export_source"] = {
                            **t["document_export"],
                            "artifact_id": a["artifact_id"],
                            "sha256": a["sha256"],
                            "version": a["version"],
                            "reference_sha256": t["reference_sha256"],
                            "reference_snapshot": t["reference_snapshot"],
                            "renderer": validation["renderer"],
                        }
                        item["source_output_mapping"] = validation["source_mapping"]
                    created.append(item["artifact_id"])
                t["result_versions"].append({"version": version, "artifacts": created, "created_at": now()})
            t.update(
                status=result["status"],
                phase="finished"
                if result["status"] == "SUCCEEDED"
                else result.get("error", {}).get("stage", "cancelled"),
                finished_at=now(),
                metrics={k: result.get(k) for k in ["elapsed_seconds", "peak_rss_kib"]},
            )
            if result["status"] == "CANCELLED":
                import shutil

                shutil.rmtree(work / "resources", ignore_errors=True)
                for file in ["document.docx", "document.pdf", "reference-used.docx", "pandoc.json"]:
                    (work / file).unlink(missing_ok=True)
            if result.get("error"):
                t["error"] = result["error"]
            emit_viewer(root, p)
            self.save(root, p)
        for item in p["artifacts"]:
            if item["artifact_id"] in created and item["role"] == "export":
                self.preview(pid, item["artifact_id"])


def PathSuffix(name):
    return {"docx": "docx", "pdf": "pdf", "json": "json"}[name.rsplit(".", 1)[1]]
