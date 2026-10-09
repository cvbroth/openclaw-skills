"""On-demand original-page previews, independent of the conversion queue."""

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import fitz

from ..artifact_project import digest, relative

RENDERER = {
    "schema": "source-page-v1",
    "pymupdf": fitz.VersionBind,
    "dpi": 120,
    "alpha": False,
    "max_pixels": 20_000_000,
}


def index_source(root, project):
    """Metadata-only migration. Keep old locators/views and never infer output mapping."""
    source = next(
        (a for a in project["artifacts"] if a["artifact_id"] == project.get("source_artifact_id")), None
    )
    if not source or (
        source.get("format") != "pdf" and Path(source.get("path") or "").suffix.lower() != ".pdf"
    ):
        return False
    info = project.setdefault("source_info", {})
    if info.get("kind") not in {None, "pdf"}:
        return False
    total = info.get("units")
    if not isinstance(total, int) or not 1 <= total <= 1000:
        if not source.get("path") or not relative(root, source["path"]).is_file():
            return False
        try:
            with fitz.open(relative(root, source["path"])) as doc:
                if doc.needs_pass or not doc.is_pdf or not 1 <= len(doc) <= 1000:
                    return False
                total = len(doc)
        except (OSError, RuntimeError, ValueError):
            return False
        info.update(kind="pdf", units=total)
    if (
        source.get("physical_index", {}).get("count") == total
        and len(source.get("pages", [])) == total
        and all(p.get("physical_page") == i for i, p in enumerate(source["pages"], 1))
    ):
        return False
    old = source.get("pages", [])
    legacy = source.setdefault("legacy_pages", [])
    for p in old:
        if p not in legacy and p.get("image"):
            legacy.append(p.copy())
    views = {}
    for p in old:
        n = p.get("physical_page") or (
            p.get("locator", {}).get("page") if p.get("locator", {}).get("kind") == "physical_page" else None
        )
        if isinstance(n, int):
            views[n] = p
    source["pages"] = [
        {
            **views.get(n, {}),
            "label": f"第{n}页 / 共{total}页",
            "physical_page": n,
            "locator": {"kind": "physical_page", "page": n},
        }
        for n in range(1, total + 1)
    ]
    source["physical_index"] = {
        "schema": "source-physical-index-v1",
        "count": total,
        "source_sha256": source["sha256"],
    }
    return True


class SourcePreviewJobs:
    def source_preview(self, pid, page, retry=False):
        if isinstance(page, bool) or not isinstance(page, int):
            raise ValueError("原件物理页必须是整数")
        if not self.source_preview_slot.acquire(blocking=False):
            return {"status": "BUSY", "message": "原件单页预览忙，请稍后重试"}
        with self.lock:
            self.active_source_previews.add(pid)
        try:
            return self._source_preview(pid, page, retry)
        finally:
            with self.lock:
                self.active_source_previews.discard(pid)
            self.source_preview_slot.release()

    def _source_preview(self, pid, page, retry):
        from .tasks import atomic

        root = self.path(pid)
        with self.lock:
            project = self.get(pid)
            source = next(
                a for a in project["artifacts"] if a["artifact_id"] == project["source_artifact_id"]
            )
            total = source.get("physical_index", {}).get("count", 0)
            if not 1 <= page <= total:
                raise ValueError(f"原件物理页越界，共{total}页")
            if not source.get("path"):
                return {
                    "status": "FAILED",
                    "error": {"code": "SOURCE_UNAVAILABLE", "message": "外部原件不可访问，仅可查看已有缓存"},
                }
            path = relative(root, source["path"])
            sha = source["sha256"]
        # Hash outside metadata lock; changed originals must never re-use a stale cache.
        if not path.is_file() or digest(path) != sha:
            return {
                "status": "FAILED",
                "error": {
                    "code": "SOURCE_CHANGED_OR_MISSING",
                    "message": "原件不存在或哈希改变；未替换登记原件、缓存及评论",
                },
            }
        key = hashlib.sha256(json.dumps([sha, page, RENDERER], sort_keys=True).encode()).hexdigest()
        cache = root / "previews" / "source" / key
        cache.mkdir(parents=True, exist_ok=True)
        result_file = cache / "result.json"
        prior = json.loads(result_file.read_text()) if result_file.is_file() else {}
        hit = (
            prior.get("status") == "SUCCEEDED"
            and (cache / "page.png").is_file()
            and digest(cache / "page.png") == prior.get("image_sha256")
        )
        if hit:
            result = {**prior, "cache_hit": True}
        elif prior.get("status") == "FAILED" and not retry:
            result = prior
        else:
            request = {
                "source": str(path),
                "sha256": sha,
                "format": "pdf",
                "output": str(cache),
                "physical_page": page,
                "dpi": RENDERER["dpi"],
            }
            atomic(cache / "request.json", request)
            try:
                with (cache / "stdout.log").open("wb") as out, (cache / "stderr.log").open("wb") as err:
                    proc = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "nas_filetools.standalone.preview_worker",
                            str(cache / "request.json"),
                            str(cache / "worker-result.json"),
                        ],
                        stdout=out,
                        stderr=err,
                        timeout=30,
                        check=False,
                        env={
                            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                            "PYTHONDONTWRITEBYTECODE": "1",
                            "OMP_NUM_THREADS": "1",
                            "OPENBLAS_NUM_THREADS": "1",
                        },
                    )
                result = (
                    json.loads((cache / "worker-result.json").read_text())
                    if proc.returncode == 0
                    else {
                        "status": "FAILED",
                        "error": {"code": "RENDER_EXIT", "message": f"预览子进程退出{proc.returncode}"},
                    }
                )
            except subprocess.TimeoutExpired:
                result = {"status": "FAILED", "error": {"code": "TIMEOUT", "message": "原件单页预览超过30秒"}}
            if result["status"] == "SUCCEEDED":
                rendered = result["pages"][0]
                result.update(
                    image=str((cache / rendered["file"]).relative_to(root)), image_sha256=rendered["sha256"]
                )
            result.update(
                cache_hit=False, render_key=key, source_sha256=sha, physical_page=page, renderer=RENDERER
            )
            atomic(result_file, result)
        with self.lock:
            latest = self.get(pid)
            a = next(a for a in latest["artifacts"] if a["artifact_id"] == latest["source_artifact_id"])
            p = a["pages"][page - 1]
            p["source_preview"] = {
                k: v for k, v in result.items() if k not in {"pages", "image", "image_sha256"}
            }
            if result["status"] == "SUCCEEDED":
                if p.get("image") and p["image"] != result["image"]:
                    a.setdefault("legacy_pages", []).append(p.copy())
                    p["recognition_image_sha256"] = p.get("image_sha256")
                p.update(image=result["image"], image_sha256=result["image_sha256"])
            self.save(root, latest)
        return result


def preview_slot():
    return threading.BoundedSemaphore(1)
