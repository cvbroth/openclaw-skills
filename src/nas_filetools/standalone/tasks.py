"""Persistent serial executor independent of HTTP and OpenClaw identities."""

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
import uuid

from ..artifact_project import (
    create_project,
    digest,
    emit_viewer,
    page_data,
    register_artifact,
    relative,
    snapshot_template,
)
from ..document_templates import TEMPLATE_ROOT
from ..process_tree import ManagedChild
from ..publication import publish
from .config import snapshot
from .previews import PreviewJobs, signature
from .format_jobs import FormatJobs
from .template_library import TemplateLibrary
from .naming import decorate
from .content_structure import parse_markdown, reading_html
from .source_quality import migrate

ACTIVE = {"QUEUED", "RUNNING", "CANCELLING"}


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    path = Path(path)
    temp = path.with_name(path.name + ".next")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def filename(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 180
        or any(c in value for c in "/\\\0\r\n")
        or value in {".", ".."}
        or len(value.encode("utf-8")) > 240
        or any(ord(c) < 32 or c in '<>:"|?*' for c in value)
    ):
        raise ValueError("invalid filename")
    if Path(value).suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("only PDF, PNG, JPEG and WebP supported")
    return value


def inspect_file(path, config):
    from PIL import Image
    from ..engines import probe
    from ..contracts import Limits

    if Path(path).suffix.lower() == ".pdf":
        import fitz
        from ..contracts import Fault

        with fitz.open(path) as doc:
            if not doc.is_pdf or doc.needs_pass or len(doc) < 1:
                raise Fault("INVALID_OR_ENCRYPTED_PDF")
            pages = len(doc)
            maximum = config["service"]["max_pages"]
            if pages > maximum:
                raise Fault("PAGE_LIMIT", f"PDF共{pages}页，最多允许{maximum}页（包含{maximum}页）")
        # Upload validation never loads, extracts or rasterizes any PDF page.
        return {"kind": "pdf", "units": pages, "warnings": [], "preview": [], "preview_coverage": []}
    limits = Limits(
        max_pages=config["service"]["max_pages"], max_image_pixels=config["service"]["max_pixels"]
    )
    info = probe(path, limits)
    if info["kind"] not in {"pdf", "image"}:
        raise ValueError("unsupported upload type")
    if info["kind"] == "image":
        if info["units"] != 1:
            raise ValueError("animated/multiframe images are not supported")
        with Image.open(path) as im:
            im.verify()
            if im.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("file signature unsupported")
            suffix = Path(path).suffix.lower()
            if im.format != {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}[suffix]:
                raise ValueError("extension/signature mismatch")
    return info


class Projects(PreviewJobs, FormatJobs):
    def __init__(self, root, config, *, start_worker=True):
        self.root = Path(root).resolve()
        self.config = config
        self.lock = threading.RLock()
        for name in ["projects", "trash", "uploads"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.library = TemplateLibrary(self.root / "template-library")
        self.queue = queue.Queue()
        self.stopping = threading.Event()
        self.cancels = {}
        self.child = None
        self.preview_signature = signature()
        self.recover()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        if start_worker:
            self.thread.start()

    def path(self, pid):
        try:
            uuid.UUID(pid)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("invalid project ID") from None
        path = self.root / "projects" / pid
        if not path.is_dir():
            raise FileNotFoundError("project missing or in trash")
        return path

    def get(self, pid):
        with self.lock:
            return json.loads((self.path(pid) / "project.json").read_text())

    def list(self, trashed=False):
        with self.lock:
            return sorted(
                (
                    json.loads(p.read_text())
                    for p in (self.root / ("trash" if trashed else "projects")).glob("*/project.json")
                ),
                key=lambda project: project["created_at"],
                reverse=True,
            )

    def save(self, root, project):
        if project.get("source_info", {}).get("kind") == "image":
            for artifact in project["artifacts"]:
                if artifact["artifact_id"] == project["source_artifact_id"]:
                    for page in artifact["pages"]:
                        page["label"] = "上传图片（位置1；非原PDF页码）"
        decorate(project)
        atomic(root / "project.json", project)
        if "source_quality_schema" in project:
            atomic(
                root / "review/source-assessments.json",
                {
                    "schema": project["source_quality_schema"],
                    "project_id": project["project_id"],
                    "source_artifact_id": project.get("source_artifact_id"),
                    "evaluations": project.get("source_evaluations", []),
                    "unbound_legacy_records": project.get("legacy_quality_records", []),
                },
            )
        # Same data backs HTTP and portable review; safe text inserted in generated local JS.
        (root / "review/project.js").write_text(
            "window.PROJECT=" + json.dumps(project, ensure_ascii=True).replace("<", "\\u003c") + ";",
            encoding="utf-8",
        )

    def recover(self):
        for file in (self.root / "projects").glob("*/project.json"):
            project = json.loads(file.read_text())
            changed = False
            project.setdefault("project_kind", "historical-validation")
            if "source_quality_schema" not in project:
                backup = file.parent / "diagnostics/migrations/source-quality-v1"
                backup.mkdir(parents=True, exist_ok=True)
                if not (backup / "project-before.json").exists():
                    shutil.copyfile(file, backup / "project-before.json")
            migrate(file.parent, project)
            for artifact in project["artifacts"]:
                state = artifact.get("preview_render", {})
                if state.get("status") in {"QUEUED", "RUNNING"}:
                    state.update(
                        status="INTERRUPTED",
                        error={
                            "stage": "preview",
                            "code": "SERVICE_RESTART",
                            "message": "Preview interrupted; explicit retry required.",
                        },
                    )
            for artifact in project["artifacts"]:
                if artifact["format"] == "markdown":
                    for view in artifact["pages"]:
                        if view.get("data") and (file.parent / view["data"]).is_file():
                            raw = (file.parent / view["data"]).read_text()
                            payload = json.loads(raw.split("=", 1)[1].rstrip(";\n"))
                            payload["reading_html"] = reading_html(parse_markdown(payload.get("text", "")))
                            page_data(file.parent, view["data"], payload)
            decorate(project)
            emit_viewer(file.parent, project)
            changed = True
            for task in project.get("tasks", []):
                if task["status"] in ACTIVE:
                    task.update(
                        status="INTERRUPTED",
                        finished_at=now(),
                        error={
                            "stage": "recovery",
                            "category": "local",
                            "code": "SERVICE_RESTART",
                            "message": "Interrupted at service restart; explicit retry required.",
                        },
                    )
                    for page in task["pages"].values():
                        if page["status"] in ACTIVE:
                            page["status"] = "INTERRUPTED"
                        for attempt in page["attempts"]:
                            if attempt["status"] in ACTIVE:
                                attempt["status"] = "INTERRUPTED"
                                attempt["error"] = {
                                    "category": "local",
                                    "stage": "recovery",
                                    "code": "SERVICE_RESTART",
                                    "message": "Interrupted attempt retained; not assumed unbilled or completed.",
                                }
                    changed = True
            if changed:
                self.save(file.parent, project)

    def upload(self, temp, name, engine, pages, options=None):
        name = filename(name)
        if engine not in self.config["engines"]:
            raise ValueError("unknown engine")
        try:
            info = inspect_file(temp, self.config)
        except Exception as exc:
            from ..contracts import Fault

            code = exc.code if isinstance(exc, Fault) else type(exc).__name__
            detail = (
                (": " + exc.message)
                if isinstance(exc, Fault) and code == "PAGE_LIMIT" and Path(temp).suffix.lower() == ".pdf"
                else ""
            )
            raise ValueError("UPLOAD_VALIDATION: " + code + detail) from None
        params = {**self.config["conversion"], **(options or {})}
        if set(params) != set(self.config["conversion"]):
            raise ValueError("conversion keys")
        from .config import integer

        integer(params["dpi"], 100, 300)
        if params["language"] not in {"zh", "en"} or any(
            type(params[k]) is not bool for k in ["quality", "generate_documents"]
        ):
            raise ValueError("invalid conversion parameters")
        params["max_selected_pages"] = self.config["conversion"]["max_selected_pages"]
        if (
            not isinstance(pages, list)
            or not pages
            or len(pages) > params["max_selected_pages"]
            or pages != sorted(set(pages))
            or any(type(n) is not int or not 1 <= n <= info["units"] for n in pages)
        ):
            raise ValueError("explicit sorted unique page selection required")
        pid = str(uuid.uuid4())
        root = self.root / "projects" / pid
        project = create_project(root, name, "upload-" + pid)
        # Adopt chosen ID, independent of content SHA. Upload never reads all bytes into RAM.
        project["project_id"] = pid
        project["tasks"] = []
        project["project_kind"] = "user"
        source = root / "sources" / name
        shutil.move(temp, source)
        artifact = register_artifact(
            root,
            project,
            name=name,
            format="pdf" if info["kind"] == "pdf" else "image",
            path="sources/" + name,
        )
        project["source_artifact_id"] = artifact["artifact_id"]
        project["source_info"] = {k: info[k] for k in ["kind", "units"]}
        emit_viewer(root, project)
        with self.lock:
            self.save(root, project)
            return self.enqueue(pid, engine, pages, params)

    def enqueue(self, pid, engine, pages, parameters=None):
        with self.lock:
            project = self.get(pid)
            root = self.path(pid)
            if engine not in self.config["engines"]:
                raise ValueError("unknown engine")
            if "source_info" not in project:
                raise ValueError(
                    "legacy reference project: review/download supported; upload accessible original for a new conversion"
                )
            if any(t["status"] in ACTIVE for t in project.get("tasks", [])):
                raise ValueError("project has active task")
            if (
                not isinstance(pages, list)
                or not pages
                or len(pages) > self.config["conversion"]["max_selected_pages"]
                or pages != sorted(set(pages))
                or any(type(n) is not int or not 1 <= n <= project["source_info"]["units"] for n in pages)
            ):
                raise ValueError("invalid pages")
            tid = str(uuid.uuid4())
            task = {
                "task_id": tid,
                "engine_id": engine,
                "engine": snapshot(self.config["engines"][engine]),
                "parameters": parameters or copy.deepcopy(self.config["conversion"]),
                "template": self.config["template"],
                "status": "QUEUED",
                "created_at": now(),
                "pages": {str(n): {"status": "QUEUED", "attempts": []} for n in pages},
                "result_versions": [],
            }
            project.setdefault("tasks", []).append(task)
            self.save(root, project)
            self.cancels[tid] = threading.Event()
            self.queue.put((pid, tid))
            return {"project_id": pid, "task_id": tid}

    def task(self, project, tid):
        for task in project.get("tasks", []):
            if task["task_id"] == tid:
                return task
        raise ValueError("unknown task")

    def cancel(self, pid, tid):
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if t["status"] not in ACTIVE:
                raise ValueError("task not active")
            self.cancels[tid].set()
            t["status"] = "CANCELLING"
            self.save(self.path(pid), p)

    def retry(self, pid, tid):
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if any(x["status"] in ACTIVE for x in p["tasks"]):
                raise ValueError("active task")
            pending = [n for n, row in t["pages"].items() if row["status"] != "SUCCEEDED"]
            if not pending:
                raise ValueError("no failed/interrupted pages")
            # Never silently switch changed server engine config for an existing task.
            if t["engine"] != snapshot(self.config["engines"][t["engine_id"]]):
                raise ValueError("engine config changed; create new task")
            for n in pending:
                t["pages"][n]["status"] = "QUEUED"
            t["status"] = "QUEUED"
            t.pop("error", None)
            self.cancels[tid] = threading.Event()
            self.save(self.path(pid), p)
            self.queue.put((pid, tid))
            return {"project_id": pid, "task_id": tid, "retry_pages": pending}

    def reformat(self, pid, tid):
        """Re-publish existing recognition with new documents, without engine calls."""
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if any(x["status"] in ACTIVE for x in p["tasks"]):
                raise ValueError("active task")
            if not any(row.get("latest") for row in t["pages"].values()):
                raise ValueError("no saved recognition results")
            t.update(status="QUEUED", format_only=True)
            t.pop("error", None)
            self.cancels[tid] = threading.Event()
            self.save(self.path(pid), p)
            self.queue.put((pid, tid))
            return {"project_id": pid, "task_id": tid, "engine_calls": 0}

    def rename(self, pid, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("invalid project name")
        with self.lock:
            p = self.get(pid)
            p["name"] = name.strip()
            decorate(p)
            emit_viewer(self.path(pid), p)
            self.save(self.path(pid), p)

    def trash(self, pid):
        with self.lock:
            p = self.get(pid)
            if any(t["status"] in ACTIVE for t in p.get("tasks", [])) or any(
                a.get("preview_render", {}).get("status") in ACTIVE for a in p["artifacts"]
            ):
                raise ValueError("wait for active conversion/preview before trash")
            os.replace(self.path(pid), self.root / "trash" / pid)

    def restore(self, pid):
        uuid.UUID(pid)
        with self.lock:
            source = self.root / "trash" / pid
            target = self.root / "projects" / pid
            if not source.is_dir() or target.exists():
                raise ValueError("trash project missing or project ID conflict")
            os.replace(source, target)

    def loop(self):
        while not self.stopping.is_set():
            try:
                pid, tid = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if tid.startswith("preview:"):
                    self.execute_preview(pid, tid.split(":", 1)[1])
                elif self.task(self.get(pid), tid).get("operation") == "format-artifact":
                    self.execute_format(pid, tid)
                else:
                    self.execute(pid, tid)
            except Exception as exc:
                if tid.startswith("preview:"):
                    with self.lock:
                        p = self.get(pid)
                        a = next(a for a in p["artifacts"] if a["artifact_id"] == tid.split(":", 1)[1])
                        a["preview_render"].update(
                            status="FAILED",
                            error={"stage": "preview", "code": type(exc).__name__, "message": str(exc)[:300]},
                        )
                        self.save(self.path(pid), p)
                    continue
                with self.lock:
                    p = self.get(pid)
                    t = self.task(p, tid)
                    t.update(
                        status="FAILED",
                        finished_at=now(),
                        error={
                            "category": "local",
                            "stage": "executor",
                            "code": type(exc).__name__,
                            "message": str(exc)[:300]
                            if t.get("operation") == "format-artifact"
                            else "Executor failure; see persisted page diagnostics.",
                        },
                    )
                    for page in t["pages"].values():
                        if page["status"] in ACTIVE:
                            page["status"] = "INTERRUPTED"
                    self.save(self.path(pid), p)
            finally:
                self.queue.task_done()

    def update(self, pid, tid, callback):
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            callback(p, t)
            self.save(self.path(pid), p)

    def run_child(self, request, result, timeout, cancel, module="nas_filetools.standalone.engine_worker"):
        engine = request["engine"]
        req = result.with_name("request.json")
        atomic(req, request)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": str(engine["cpu_threads"]),
            "OPENBLAS_NUM_THREADS": str(engine["cpu_threads"]),
        }
        key = engine.get("credential_env")
        if key and key in os.environ:
            env[key] = os.environ[key]
        started = time.monotonic()
        with (
            result.with_name("stdout.log").open("wb") as out,
            result.with_name("stderr.log").open("wb") as err,
        ):
            child = ManagedChild(
                [sys.executable, "-m", module, str(req), str(result)],
                env=env,
                stdout=out,
                stderr=err,
            )
            self.child = child
            try:
                while child.process.poll() is None:
                    if cancel.is_set() or self.stopping.is_set():
                        return {
                            "status": "CANCELLED",
                            "text": "",
                            "blocks": [],
                            "quality": None,
                            "error": {
                                "category": "local",
                                "stage": "execution",
                                "code": "CANCELLED",
                                "message": "Cancelled by request.",
                            },
                        }
                    if time.monotonic() - started > timeout:
                        return {
                            "status": "FAILED",
                            "text": "",
                            "blocks": [],
                            "quality": None,
                            "error": {
                                "category": "local",
                                "stage": "execution",
                                "code": "TIMEOUT",
                                "message": "Configured page deadline reached.",
                            },
                        }
                    time.sleep(0.05)
                if not result.is_file():
                    return {
                        "status": "FAILED",
                        "text": "",
                        "blocks": [],
                        "quality": None,
                        "error": {
                            "category": "local",
                            "stage": "execution",
                            "code": "CHILD_EXIT",
                            "message": "No engine result; exit " + str(child.process.returncode),
                        },
                    }
                return json.loads(result.read_text())
            finally:
                child.close()
                self.child = None

    def render(self, root, p, tid, n, params):
        source = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
        path = relative(root, source["path"])
        target = root / f"sources/previews/{tid}/page-{n}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        if p["source_info"]["kind"] == "pdf":
            import fitz

            with fitz.open(path) as pdf:
                page = pdf[n - 1]
                rect = page.rect
                if (
                    rect.width * rect.height * (params["dpi"] / 72) ** 2
                    > self.config["service"]["max_pixels"]
                ):
                    raise ValueError("render pixel limit")
                page.get_pixmap(
                    matrix=fitz.Matrix(params["dpi"] / 72, params["dpi"] / 72), alpha=False, annots=False
                ).save(target)
        else:
            # Preserve uploaded file bytes and MIME, no lossy conversion or resize.
            target = target.with_suffix(path.suffix)
            shutil.copyfile(path, target)
        return target

    def execute(self, pid, tid):
        p = self.get(pid)
        t = self.task(p, tid)
        root = self.path(pid)
        cancel = self.cancels[tid]
        self.update(pid, tid, lambda p, t: t.update(status="RUNNING", started_at=now()))
        for key, old in t["pages"].items():
            if t.get("format_only"):
                break
            if old["status"] == "SUCCEEDED":
                continue
            if cancel.is_set() or self.stopping.is_set():
                break
            n = int(key)
            start = time.monotonic()
            self.update(pid, tid, lambda p, t: t["pages"][key].update(status="RUNNING"))
            parent = root / f"diagnostics/tasks/{tid}/page-{n}"
            prior = [
                int(path.name.split("-")[-1])
                for path in parent.glob("attempt-*")
                if path.name.split("-")[-1].isdigit()
            ]
            attempt = max([len(old["attempts"]), *prior]) + 1
            directory = parent / f"attempt-{attempt}"
            directory.mkdir(parents=True, exist_ok=False)

            def started(project, task):
                task["pages"][key]["attempts"].append(
                    {
                        "attempt": attempt,
                        "status": "RUNNING",
                        "started_at": now(),
                        "directory": str(directory.relative_to(root)),
                    }
                )

            self.update(pid, tid, started)
            try:
                image = self.render(root, p, tid, n, t["parameters"])
                result = self.run_child(
                    {
                        "image": str(image),
                        "engine": self.config["engines"][t["engine_id"]],
                        "parameters": t["parameters"],
                    },
                    directory / "result.json",
                    t["engine"]["timeout"],
                    cancel,
                )
            except Exception as exc:
                result = {
                    "status": "FAILED",
                    "text": "",
                    "blocks": [],
                    "quality": None,
                    "error": {
                        "category": "local",
                        "stage": "render",
                        "code": type(exc).__name__,
                        "message": "Input rendering or request preparation failed.",
                    },
                }
                image = None
            result["wall_seconds"] = time.monotonic() - start
            # Request config contains only an ENV NAME, never key value; remove it from project diagnostics.
            req = directory / "request.json"
            if req.exists():
                data = json.loads(req.read_text())
                data["engine"] = snapshot(data["engine"])
                atomic(req, data)
            atomic(directory / "result.json", result)
            (directory / "raw.md").write_text(result.get("text", ""), encoding="utf-8")
            if result.get("raw_response") is not None:
                (directory / "response.raw.json").write_text(result["raw_response"], encoding="utf-8")
            record = {
                "attempt": attempt,
                "status": result["status"],
                "result": str((directory / "result.json").relative_to(root)),
                "image": str(image.relative_to(root)) if image else None,
                "wall_seconds": result["wall_seconds"],
                "finished_at": now(),
                "error": result.get("error"),
                "peak_rss_kib": result.get("peak_rss_kib"),
            }

            def finish(project, task):
                page = task["pages"][key]
                page["attempts"][-1] = record
                page.update(status=record["status"], latest=record)
                source = next(
                    a for a in project["artifacts"] if a["artifact_id"] == project["source_artifact_id"]
                )
                if image and not any(
                    x.get("physical_page") == n and x.get("image_sha256") == digest(image)
                    for x in source["pages"]
                ):
                    source["pages"].append(
                        {
                            "label": f"输入物理第{n}页"
                            if project["source_info"]["kind"] == "pdf"
                            else "上传图片",
                            "locator": {"kind": "physical_page", "page": n},
                            "physical_page": n,
                            "task_id": tid,
                            "image": record["image"],
                            "image_sha256": digest(image),
                        }
                    )

            self.update(pid, tid, finish)
        if cancel.is_set() or self.stopping.is_set():

            def mark_cancelled(project, task):
                for page in task["pages"].values():
                    if page["status"] in ACTIVE:
                        page["status"] = "CANCELLED"

            self.update(pid, tid, mark_cancelled)
        self.publish_results(pid, tid)

        def final(project, task):
            statuses = [page["status"] for page in task["pages"].values()]
            task["status"] = (
                "CANCELLED"
                if cancel.is_set() or self.stopping.is_set()
                else (
                    "SUCCEEDED"
                    if all(s == "SUCCEEDED" for s in statuses) and not task.get("error")
                    else ("PARTIAL" if any(s in {"SUCCEEDED", "PARTIAL"} for s in statuses) else "FAILED")
                )
            )
            for page in task["pages"].values():
                if page["status"] in ACTIVE:
                    page["status"] = "CANCELLED"
            task["finished_at"] = now()
            task.pop("format_only", None)

        self.update(pid, tid, final)

    def publish_results(self, pid, tid):
        p = self.get(pid)
        t = self.task(p, tid)
        root = self.path(pid)
        version = len(t["result_versions"]) + 1
        run = root / f"diagnostics/tasks/{tid}/generation-{version}"
        work = run / "work"
        work.mkdir(parents=True)
        pages = []
        md = []
        quality = []
        for key, row in t["pages"].items():
            result = json.loads((root / row["latest"]["result"]).read_text()) if row.get("latest") else {}
            text = result.get("text", "")
            n = int(key)
            blocks = result.get("blocks") or (
                [
                    {
                        "id": f"p{n}-b0001",
                        "type": "unsegmented-transcription",
                        "text": text,
                        "reading_order": 0,
                        "coordinates": None,
                        "coordinate_system": None,
                    }
                ]
                if text
                else []
            )
            pages.append(
                {
                    "physical_page": n,
                    "status": row["status"],
                    "text": text,
                    "blocks": blocks,
                    "input": result.get("input"),
                    "error": result.get("error"),
                    "diagnostic": row.get("latest", {}).get("result"),
                }
            )
            md.append(f"<!-- source physical page {n}; task {tid} -->\n" + text)
            quality.append(
                {"physical_page": n, "quality": result.get("quality"), "error": result.get("error")}
            )
        content = "\n\n".join(md)
        (work / "content.md").write_text(content, encoding="utf-8")
        atomic(
            work / "structure.json",
            {
                "schema": "standalone-structure-v1",
                "project_id": pid,
                "source_sha256": p["artifacts"][0]["sha256"],
                "task_id": tid,
                "pages": pages,
            },
        )
        atomic(work / "quality.json", quality)
        files = ["content.md", "structure.json", "quality.json"]
        format_error = None
        if t["parameters"]["generate_documents"] and any(page["text"] for page in pages):
            try:
                result = self.run_child(
                    {
                        "operation": "documents",
                        "pages": pages,
                        "title": p["name"],
                        "template": t["template"],
                        "template_data": self.library.load(t["template"]["id"], t["template"]["version"]),
                        "output": str(work),
                        "engine": {"cpu_threads": 2},
                    },
                    work / "generation-result.json",
                    60,
                    self.cancels[tid],
                    module="nas_filetools.standalone.documents",
                )
                if result["status"] != "SUCCEEDED":
                    raise ValueError("DOCUMENT_GENERATION_FAILED")
                files += [
                    "document.docx",
                    "document.pdf",
                    "content-structure.json",
                    "layout-validation.json",
                    "generation-result.json",
                ]
                choice = t["template"]
                if not any(
                    x["id"] == choice["id"] and x["version"] == choice["version"] for x in p["templates"]
                ):
                    snapshot_template(
                        root,
                        p,
                        TEMPLATE_ROOT / "published" / choice["id"] / (choice["version"] + ".json"),
                        template_id=choice["id"],
                        version=choice["version"],
                    )
            except Exception as exc:
                format_error = {
                    "category": "local",
                    "stage": "generation",
                    "code": type(exc).__name__,
                    "message": "Word/PDF not available; raw Markdown and source mapping retained.",
                }
        artifacts = publish(
            work, run, [{"artifact_id": str(uuid.uuid4()), "kind": "output", "file": file} for file in files]
        )
        source_id = p["source_artifact_id"]
        created = []
        content_parents = []
        for artifact in artifacts:
            path = str((run / artifact["file"]).relative_to(root))
            file = Path(path).name
            fmt = {".md": "markdown", ".json": "json", ".docx": "docx", ".pdf": "pdf"}[Path(path).suffix]
            views = []
            if file == "content.md":
                for page in pages:
                    n = page["physical_page"]
                    data_path = f"content/{tid}/v{version}/page-{n}.js"
                    q = next(x["quality"] for x in quality if x["physical_page"] == n)
                    page_data(
                        root,
                        data_path,
                        {
                            "text": page["text"],
                            "reading_html": reading_html(parse_markdown(page["text"])),
                            "quality": q,
                            "raw_path": page["diagnostic"],
                        },
                    )
                    views.append(
                        {
                            "label": f"来源物理第{n}页 · {page['status']}",
                            "locator": {"kind": "block", "id": f"p{n}-transcription"},
                            "source_page": n,
                            "data": data_path,
                            "quality": (q or {}).get("overall_quality"),
                            "error": bool(page["error"]),
                            "error_category": (page["error"] or {}).get("category"),
                        }
                    )
            item = register_artifact(
                root,
                p,
                name=file + " · " + t["engine_id"],
                format=fmt,
                path=path,
                version=str(version),
                parents=content_parents if fmt in {"docx", "pdf"} else [source_id],
                pages=views,
            )
            # Publication and project registry refer to the SAME artifact ID.
            item["artifact_id"] = artifact["artifact_id"]
            if file in {"content.md", "structure.json"}:
                content_parents.append(item["artifact_id"])
            item["task_id"] = tid
            item["role"] = (
                "quality"
                if file == "quality.json"
                else ("diagnostic" if file == "layout-validation.json" else "result")
            )
            created.append(item["artifact_id"])
        task = self.task(p, tid)
        task["result_versions"].append({"version": version, "artifacts": created, "created_at": now()})
        if format_error:
            task["error"] = format_error
        with self.lock:
            # Merge into latest metadata so concurrent rename/cancel cannot be lost.
            latest = self.get(pid)
            ids = {a["artifact_id"] for a in latest["artifacts"]}
            latest["artifacts"].extend(a for a in p["artifacts"] if a["artifact_id"] not in ids)
            versions = {(x["id"], x["version"]) for x in latest["templates"]}
            latest["templates"].extend(x for x in p["templates"] if (x["id"], x["version"]) not in versions)
            current_task = self.task(latest, tid)
            current_task["result_versions"] = task["result_versions"]
            current_task["generation_title"] = p["name"]
            if format_error:
                current_task["error"] = format_error
            # Comments live independently; no imported feedback is replaced.
            migrate(root, latest)
            emit_viewer(root, latest)
            self.save(root, latest)
        for artifact in latest["artifacts"]:
            if artifact["artifact_id"] in created and artifact["format"] in {"docx", "pdf"}:
                self.preview(pid, artifact["artifact_id"])

    def close(self):
        self.stopping.set()
        for event in self.cancels.values():
            event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=10)
