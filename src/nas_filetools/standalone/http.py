"""Loopback-only development HTTP/UI boundary. No OpenClaw/session dependencies."""

import argparse
import json
import mimetypes
import os
from pathlib import Path
import shutil
import signal
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
import uuid
import zipfile

from ..artifact_project import emit_viewer, import_feedback, relative, validate_feedback
from .config import load
from .text_revisions import RevisionConflict
from .tasks import ACTIVE, Projects, filename
from .export_policy import exportable, windows_safe, portable_manifest
from .naming import decorate, project_title


class BodyTooLarge(ValueError):
    def __init__(self, limit):
        self.limit = limit
        super().__init__(f"单文件上传超过 {limit / (1024 * 1024):g} MiB 上限")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # no URLs/body/credentials in access logs

    @property
    def manager(self):
        return self.server.manager

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def guard(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        if host not in allowed:
            raise PermissionError("invalid host")
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in allowed}:
            raise PermissionError("cross-origin request refused")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("cross-site refused")
        self.connection.settimeout(30)

    def json_body(self):
        length = self.length(1024 * 1024)
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError("incomplete JSON")
        return json.loads(data)

    def length(self, limit, *, upload=False):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length") or []) != 1:
            raise ValueError("single Content-Length required")
        n = int(self.headers["Content-Length"])
        if n > limit:
            if upload:
                raise BodyTooLarge(limit)
            raise ValueError("body size limit")
        if n <= 0:
            raise ValueError("positive Content-Length required")
        return n

    def stream(self, path, download=None):
        path = Path(path)
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        value = self.headers.get("Range")
        if value:
            import re

            match = re.fullmatch(r"bytes=(\d+)-(\d*)", value)
            if not match:
                raise ValueError("unsupported range")
            start = int(match[1])
            end = min(int(match[2]) if match[2] else end, end)
            if start > end:
                raise ValueError("range outside file")
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            from urllib.parse import quote

            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(download))
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def dispatch(self, method):
        self.guard()
        url = urlsplit(self.path)
        parts = [unquote(x) for x in url.path.split("/") if x]
        m = self.manager
        if method == "GET" and not parts:
            return self.stream(Path(__file__).parent / "assets/index.html")
        if method == "GET" and len(parts) == 2 and parts[0] == "projects":
            m.get(parts[1])
            return self.stream(Path(__file__).parent / "assets/index.html")
        if (
            method == "GET"
            and parts[0] == "assets"
            and len(parts) == 2
            and parts[1] in {"app.js", "management.js", "app.css", "templates.js", "engines.js"}
        ):
            return self.stream(Path(__file__).parent / "assets" / parts[1])
        if method == "GET" and parts == ["engines"]:
            return self.stream(Path(__file__).parent / "assets/engines.html")
        if method == "GET" and parts == ["templates"]:
            return self.stream(Path(__file__).parent / "assets/templates.html")
        if method == "GET" and parts == ["api", "limits"]:
            return self.send_json(
                {
                    "upload_bytes": m.config["service"]["upload_bytes"],
                    "max_pdf_pages": m.config["service"]["max_pages"],
                    "max_selected_pages": m.config["conversion"]["max_selected_pages"],
                }
            )
        if method == "GET" and parts == ["api", "templates"]:
            return self.send_json(
                {
                    "catalog": m.library.catalog(),
                    "fonts": [{"name": f["name"], "sha256": f["sha256"]} for f in m.library.fonts.values()],
                }
            )
        if method == "POST" and parts == ["api", "templates"]:
            with m.lock:
                result = m.library.save(self.json_body())
            return self.send_json(result, 201)
        if len(parts) >= 4 and parts[:2] == ["api", "templates"]:
            tid, version = parts[2:4]
            if len(parts) == 4 and method == "GET":
                return self.send_json(m.library.load(tid, version, True)["document"])
            if len(parts) == 5 and method == "POST":
                self.json_body()
                if parts[4] == "preview":
                    return self.send_json(m.template_preview(tid, version), 202)
                if parts[4] == "publish":
                    with m.lock:
                        entry = m.library.load(tid, version, True)["record"]
                        if not entry.get("preview_project_id"):
                            raise ValueError("preview: generate first")
                        return self.send_json(
                            m.library.publish(tid, version, m.get(entry["preview_project_id"]))
                        )
        if method == "GET" and parts == ["api", "engines"]:
            with m.lock:
                return self.send_json(m.settings.public())
        if len(parts) >= 3 and parts[:2] == ["api", "engines"]:
            if len(parts) == 3 and method == "POST":
                data = self.json_body()
                with m.lock:
                    return self.send_json(m.settings.update(parts[2], data))
            if len(parts) == 4 and parts[3] == "test" and method == "POST":
                self.json_body()
                return self.send_json(m.settings.test(parts[2]))
        if method == "GET" and parts == ["api", "trash"]:
            return self.send_json(m.list(trashed=True))
        if method == "POST" and len(parts) == 4 and parts[:2] == ["api", "trash"] and parts[3] == "restore":
            self.json_body()
            m.restore(parts[2])
            return self.send_json({"status": "restored"})
        if method == "GET" and parts == ["api", "projects"]:
            return self.send_json(m.list())
        if method == "POST" and parts == ["api", "uploads"]:
            query = parse_qs(url.query)
            name = filename(query.get("filename", [""])[0])
            project_name = query.get("project_name", [None])[0] or None
            length = self.length(m.config["service"]["upload_bytes"], upload=True)
            if shutil.disk_usage(m.root).free < length + 512 * 1024 * 1024:
                raise ValueError("insufficient disk reserve")
            path = m.root / "uploads" / (uuid.uuid4().hex + Path(name).suffix.lower())
            try:
                with path.open("xb") as stream:
                    remaining = length
                    while remaining:
                        block = self.rfile.read(min(65536, remaining))
                        if not block:
                            raise ValueError("incomplete upload")
                        stream.write(block)
                        remaining -= len(block)
                    stream.flush()
                    os.fsync(stream.fileno())
                return self.send_json(m.upload(path, name, project_name), 202)
            finally:
                if path.exists():
                    path.unlink()
        if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
            pid = parts[2]
            project = m.get(pid)
            root = m.path(pid)
            if len(parts) == 5 and parts[3] == "source-preview" and method == "POST":
                data = self.json_body()
                return self.send_json(m.source_preview(pid, int(parts[4]), retry=data.get("retry", False)))
            if len(parts) == 4 and parts[3] == "analysis" and method == "POST":
                self.json_body()
                return self.send_json(m.analyze(pid), 202)
            if len(parts) == 3:
                if method == "GET":
                    return self.send_json(project)
                if method == "PATCH":
                    m.rename(pid, self.json_body()["name"])
                    return self.send_json(m.get(pid))
                if method == "DELETE":
                    m.trash(pid)
                    return self.send_json({"status": "trashed"})
            if len(parts) == 5 and parts[3] == "text" and method == "GET":
                data = m.text_artifact(pid, parts[4])
                query = parse_qs(url.query)
                if "locator" in query:
                    locator = json.loads(query["locator"][0])
                    data["pages"] = [page for page in data["pages"] if page["locator"] == locator]
                    if not data["pages"]:
                        raise ValueError("未知稳定位置")
                return self.send_json(data)
            if len(parts) == 4 and parts[3] == "text-revisions" and method == "POST":
                return self.send_json(m.save_text_revision(pid, self.json_body()))
            if len(parts) == 5 and parts[3] == "text-diff" and method == "GET":
                return self.send_json(m.text_diff(pid, parts[4], parse_qs(url.query)["against"][0]))
            if len(parts) == 4 and parts[3] == "format" and method == "POST":
                data = self.json_body()
                return self.send_json(
                    m.format_artifact(pid, data["source_artifact_id"], data["template"]), 202
                )
            if len(parts) == 4 and parts[3] == "template" and method == "POST":
                data = self.json_body()
                m.library.load(data["id"], data["version"])
                with m.lock:
                    latest = m.get(pid)
                    latest["selected_template"] = {"id": data["id"], "version": data["version"]}
                    m.save(root, latest)
                return self.send_json(m.get(pid))
            if len(parts) == 5 and parts[3] == "artifacts" and method == "PATCH":
                return self.send_json(m.edit_artifact(pid, parts[4], self.json_body()))
            if len(parts) == 4 and parts[3] == "tasks" and method == "POST":
                data = self.json_body()
                return self.send_json(m.enqueue(pid, data["engine"], data["pages"]), 202)
            if len(parts) == 6 and parts[3] == "tasks" and method == "POST":
                if parts[5] == "archive":
                    return self.send_json(m.archive_task(pid, parts[4], self.json_body().get("archived")))
                if parts[5] == "cancel":
                    self.json_body()
                    m.cancel(pid, parts[4])
                    return self.send_json({"status": "cancelling"})
                if parts[5] == "format":
                    self.json_body()
                    return self.send_json(m.reformat(pid, parts[4]), 202)
                if parts[5] == "retry":
                    self.json_body()
                    return self.send_json(m.retry(pid, parts[4]), 202)
            if len(parts) == 5 and parts[3] == "previews" and method == "POST":
                data = self.json_body()
                return self.send_json(m.preview(pid, parts[4], retry=data.get("retry", False)), 202)
            if len(parts) == 4 and parts[3] == "feedback":
                feedback = root / "review/feedback.json"
                if method == "GET":
                    return self.send_json(json.loads(feedback.read_text()))
                if method == "POST":
                    receipt = self.json_body()
                    with m.lock:
                        # Legacy validation + append-only import; comments never become content.
                        validate_feedback(m.get(pid), receipt)
                        import_feedback(root, receipt)
                    return self.send_json(json.loads(feedback.read_text()))
            if len(parts) == 5 and parts[3] == "download" and method == "GET":
                art = next((a for a in project["artifacts"] if a["artifact_id"] == parts[4]), None)
                if not art or not art["path"]:
                    raise FileNotFoundError("artifact is external reference, not downloadable")
                return self.stream(
                    relative(root, art["path"]),
                    decorate(project)["artifacts"][project["artifacts"].index(art)]["download_name"],
                )
            if len(parts) == 4 and parts[3] == "export" and method == "GET":
                if (
                    pid in m.active_source_previews
                    or project.get("analysis", {}).get("status") in ACTIVE
                    or any(t["status"] in ACTIVE for t in project.get("tasks", []))
                    or any(a.get("preview_render", {}).get("status") in ACTIVE for a in project["artifacts"])
                ):
                    raise ValueError("export requires terminal tasks")
                with tempfile.TemporaryDirectory(dir=m.root) as temp:
                    package = Path(temp) / "project.zip"
                    with m.lock:
                        latest = m.get(pid)
                        if (
                            pid in m.active_source_previews
                            or latest.get("analysis", {}).get("status") in ACTIVE
                            or any(t["status"] in ACTIVE for t in latest.get("tasks", []))
                            or any(
                                a.get("preview_render", {}).get("status") in ACTIVE
                                for a in latest["artifacts"]
                            )
                        ):
                            raise ValueError("export requires terminal tasks")
                        emit_viewer(root, latest)
                        portable, aliases = portable_manifest(latest)
                        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                            for file in root.rglob("*"):
                                if (
                                    file.is_file()
                                    and not file.is_symlink()
                                    and exportable(file.relative_to(root))
                                ):
                                    if not windows_safe(file.relative_to(root)):
                                        raise ValueError(
                                            "export path not Windows portable: " + str(file.relative_to(root))
                                        )
                                    if file.relative_to(root).as_posix() not in {
                                        "project.json",
                                        "review/project.js",
                                    }:
                                        archive.write(file, file.relative_to(root))
                            archive.writestr(
                                "project.json", json.dumps(portable, ensure_ascii=False, indent=2)
                            )
                            archive.writestr(
                                "review/project.js",
                                "window.PROJECT="
                                + json.dumps(portable, ensure_ascii=True).replace("<", "\\u003c")
                                + ";",
                            )
                            for original, alias in aliases:
                                archive.write(relative(root, original), alias)
                    return self.stream(package, project_title(project["name"]) + "_离线项目.zip")
        if method == "GET" and len(parts) >= 3 and parts[0] == "p":
            root = m.path(parts[1])
            path = relative(root, "/".join(parts[2:]))
            if (
                len(parts) == 4
                and parts[2] == "review"
                and parts[3] in {"index.html", "viewer.js", "viewer.css", "editor.js"}
            ):
                path = Path(__file__).parent.parent / "project_assets" / parts[3]
            if not path.is_file():
                raise FileNotFoundError("resource unavailable")
            if parts[2:] == ["review", "project.js"]:
                with m.lock:
                    emit_viewer(root, m.get(parts[1]))
            return self.stream(path)
        raise FileNotFoundError("endpoint missing")

    def handle_method(self):
        try:
            self.dispatch(self.command)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except BodyTooLarge as exc:
            self.close_connection = True
            self.send_json({"error": "UPLOAD_TOO_LARGE", "reason": str(exc), "limit_bytes": exc.limit}, 413)
        except RevisionConflict as exc:
            self.close_connection = True
            self.send_json({"error": "REVISION_CONFLICT", "reason": str(exc)}, 409)
        except PermissionError:
            self.close_connection = True
            self.send_json({"error": "REQUEST_FORBIDDEN"}, 403)
        except FileNotFoundError:
            self.close_connection = True
            self.send_json({"error": "NOT_FOUND"}, 404)
        except (ValueError, KeyError, StopIteration, TypeError) as exc:
            self.close_connection = True
            self.send_json({"error": "INVALID_REQUEST", "reason": str(exc)[:160]}, 400)
        except Exception as exc:
            self.close_connection = True
            self.send_json({"error": "LOCAL_SERVER_ERROR", "type": type(exc).__name__}, 500)

    do_GET = do_POST = do_PATCH = do_DELETE = handle_method


def serve(root, config, testing=False):
    import fcntl

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    # A second service cannot recover/modify the same running store.
    with (root / ".service-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        server = ThreadingHTTPServer((config["service"]["bind"], config["service"]["port"]), Handler)
        manager = Projects(root, config)
        server.daemon_threads = True
        server.manager = manager

        def stop(*_):
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            server.server_close()
            manager.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--testing", action="store_true")
    p.add_argument(
        "--credential-stdin", help="one configured credential ENV name; value read from private pipe"
    )
    a = p.parse_args()
    config = load(a.config, a.testing)
    if a.credential_stdin:
        if a.credential_stdin not in {e["credential_env"] for e in config["engines"].values()}:
            raise ValueError("unknown credential reference")
        value = sys.stdin.readline(8193).rstrip("\r\n")
        if not value or len(value) > 8192:
            raise ValueError("credential pipe missing/invalid")
        os.environ[a.credential_stdin] = value
    serve(a.root, config, a.testing)


if __name__ == "__main__":
    main()
