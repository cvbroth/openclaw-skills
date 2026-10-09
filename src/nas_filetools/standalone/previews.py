"""Preview jobs share the bounded execution queue; content publishing is independent."""

import hashlib
import json
import shutil
import subprocess
import threading
import fitz
from ..artifact_project import digest, relative, emit_viewer


def signature():
    lo = "unavailable"
    if shutil.which("libreoffice"):
        lo = subprocess.check_output(["libreoffice", "--version"], text=True, timeout=10).strip()
    return {"schema": "preview-raster-v1", "pymupdf": fitz.version, "libreoffice": lo, "dpi": 120}


class PreviewJobs:
    def preview(self, pid, aid, retry=False):
        with self.lock:
            project = self.get(pid)
            artifact = next((a for a in project["artifacts"] if a["artifact_id"] == aid), None)
            if not artifact or artifact["format"] not in {"pdf", "docx"} or not artifact["path"]:
                raise ValueError("preview requires registered local DOCX/PDF")
            if aid == project.get("source_artifact_id"):
                raise ValueError("原件仅预览显式处理的物理页；不触发整份原件渲染")
            key = hashlib.sha256(
                json.dumps(
                    [artifact["sha256"], artifact["format"], self.preview_signature], sort_keys=True
                ).encode()
            ).hexdigest()
            prior = artifact.get("preview_render", {})
            if prior.get("key") == key and prior.get("status") in {"QUEUED", "RUNNING"}:
                return prior
            artifact["preview_render"] = {
                "key": key,
                "status": "QUEUED",
                "renderer": self.preview_signature,
                "source_sha256": artifact["sha256"],
                "retry": bool(retry),
            }
            self.save(self.path(pid), project)
            self.queue.put((pid, "preview:" + aid))
            return artifact["preview_render"]

    def execute_preview(self, pid, aid):
        root = self.path(pid)
        with self.lock:
            project = self.get(pid)
            artifact = next(a for a in project["artifacts"] if a["artifact_id"] == aid)
            state = artifact["preview_render"]
            state["status"] = "RUNNING"
            self.save(root, project)
        cache = root / "previews" / state["key"]
        cache.mkdir(parents=True, exist_ok=True)
        result_path = cache / "cache.json"
        result = json.loads(result_path.read_text()) if result_path.is_file() else None
        cached = (
            result
            and result.get("status") == "SUCCEEDED"
            and all(
                relative(root, p["image"]).is_file()
                and digest(relative(root, p["image"])) == p["image_sha256"]
                for p in result["views"]
            )
        )
        if not cached:
            attempt = len(list(cache.glob("attempt-*"))) + 1
            output = cache / f"attempt-{attempt}"
            output.mkdir()
            result = self.run_child(
                {
                    "source": str(relative(root, artifact["path"])),
                    "sha256": artifact["sha256"],
                    "format": artifact["format"],
                    "output": str(output),
                    "engine": {"cpu_threads": 2},
                },
                output / "result.json",
                180,
                threading.Event(),
                module="nas_filetools.standalone.preview_worker",
            )
            result["diagnostics"] = str(output.relative_to(root))
            if result["status"] == "SUCCEEDED":
                result["views"] = [
                    {
                        "label": f"{'Word' if artifact['format'] == 'docx' else 'PDF'}输出第{p['output_page']}页",
                        "locator": {
                            "kind": "output_page",
                            "page": p["output_page"],
                            "render_key": state["key"],
                        },
                        "output_page": p["output_page"],
                        "image": str((output / p["file"]).relative_to(root)),
                        "image_sha256": p["sha256"],
                    }
                    for p in result["pages"]
                ]
            from .tasks import atomic

            atomic(result_path, result)
        with self.lock:
            project = self.get(pid)
            artifact = next(a for a in project["artifacts"] if a["artifact_id"] == aid)
            artifact["preview_render"].update(
                status=result["status"],
                cache_hit=bool(cached),
                error=result.get("error"),
                diagnostics=result.get("diagnostics"),
                elapsed_seconds=result.get("elapsed_seconds"),
                page_count=len(result.get("views", [])),
            )
            if result["status"] == "SUCCEEDED":
                artifact.setdefault("legacy_pages", artifact["pages"])
                artifact["pages"] = result["views"]
                artifact["preview"] = {
                    "label": "DOCX经LibreOffice实际渲染（不是独立生成PDF）"
                    if artifact["format"] == "docx"
                    else "PDF经PyMuPDF逐页栅格预览",
                    "artifact_sha256": artifact["sha256"],
                    "renderer": result["renderer"],
                    "render_key": state["key"],
                }
            emit_viewer(root, project)
            self.save(root, project)
