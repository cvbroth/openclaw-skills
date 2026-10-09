"""Real loopback HTTP/subprocess behavior with synthetic engines and fake providers."""

import base64
import copy
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

from nas_filetools.standalone.adapters import recognize, separate
from nas_filetools.standalone.config import validate
from nas_filetools.standalone.http import Handler
from nas_filetools.standalone.tasks import Projects
from nas_filetools.process_tree import terminate_descendants

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    data = json.loads((ROOT / "deploy/standalone-http.example.json").read_text())
    engine = copy.deepcopy(data["engines"]["local"])
    engine.update(type="fixture", model="success", timeout=5)
    data["engines"] = {
        "fixture": engine,
        "delay": {**engine, "model": "delay"},
        "failure": {**engine, "model": "failure"},
    }
    data["conversion"]["generate_documents"] = False
    return validate(data, testing=True)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = configuration()
        self.m = Projects(self.root / "data", self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.manager = self.m
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        from PIL import Image

        self.image = self.root / "synthetic.png"
        Image.new("RGB", (400, 500), "white").save(self.image)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.m.close()

    def request(self, path, method="GET", data=None, headers=None):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        req = urllib.request.Request(self.base + path, data, headers or {}, method=method)
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if response.headers["Content-Type"].startswith("application/json") else raw

    def upload(self, engine="fixture"):
        return self.request(
            "/api/uploads?filename=synthetic.png&engine=" + engine + "&pages=1",
            "POST",
            self.image.read_bytes(),
        )

    def terminal(self, item):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            p = self.request("/api/projects/" + item["project_id"])
            t = next(t for t in p["tasks"] if t["task_id"] == item["task_id"])
            if t["status"] not in {"QUEUED", "RUNNING", "CANCELLING"}:
                return p, t
            time.sleep(0.03)
        self.fail("task did not reach terminal status")

    def test_reformat_reuses_engine_attempts_and_keeps_artifacts(self):
        item = self.upload()
        p, t = self.terminal(item)
        old_ids = {a["artifact_id"] for a in p["artifacts"]}
        before = t["pages"]["1"]["attempts"]
        self.request(f"/api/projects/{item['project_id']}/tasks/{item['task_id']}/format", "POST", {})
        p, t = self.terminal(item)
        self.assertEqual(t["status"], "SUCCEEDED")
        self.assertEqual(before, t["pages"]["1"]["attempts"])
        self.assertEqual(len(t["result_versions"]), 2)
        self.assertTrue(old_ids <= {a["artifact_id"] for a in p["artifacts"]})

    def test_upload_convert_download_and_versions(self):
        item = self.upload()
        p, t = self.terminal(item)
        self.assertEqual(t["status"], "SUCCEEDED")
        a = next(a for a in p["artifacts"] if a["format"] == "markdown")
        body = self.request("/api/projects/" + p["project_id"] + "/download/" + a["artifact_id"])
        self.assertIn("合成测试", body.decode())
        self.assertNotIn("overall_quality", body.decode())
        newer = self.request(
            "/api/projects/" + p["project_id"] + "/tasks", "POST", {"engine": "fixture", "pages": [1]}
        )
        p, t = self.terminal(newer)
        self.assertEqual(len(p["tasks"]), 2)
        self.assertEqual(len({a["artifact_id"] for a in p["artifacts"]}), len(p["artifacts"]))
        self.assertTrue((self.m.path(p["project_id"]) / a["path"]).is_file())

    def test_cancel_and_retry_no_success_rerun(self):
        item = self.upload("delay")
        time.sleep(0.2)
        self.request(
            "/api/projects/" + item["project_id"] + "/tasks/" + item["task_id"] + "/cancel", "POST", {}
        )
        p, t = self.terminal(item)
        self.assertEqual(t["status"], "CANCELLED")
        successful = self.upload()
        p, t = self.terminal(successful)
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/projects/" + p["project_id"] + "/tasks/" + t["task_id"] + "/retry", "POST", {})

    def test_failure_retry_history(self):
        item = self.upload("failure")
        p, t = self.terminal(item)
        self.assertEqual(t["status"], "FAILED")
        self.request("/api/projects/" + p["project_id"] + "/tasks/" + t["task_id"] + "/retry", "POST", {})
        p, t = self.terminal(item)
        self.assertEqual(len(t["pages"]["1"]["attempts"]), 2)
        self.assertEqual(len(t["result_versions"]), 2)

    def test_mixed_failure_retry_reuses_success(self):
        self.config["engines"]["fixture"]["model"] = "page2-failure"
        import fitz

        pdf = fitz.open()
        pdf.new_page()
        pdf.new_page()
        item = self.request("/api/uploads?filename=mixed.pdf&engine=fixture&pages=1,2", "POST", pdf.tobytes())
        pdf.close()
        p, t = self.terminal(item)
        self.assertEqual(t["status"], "PARTIAL")
        first_result = t["pages"]["1"]["latest"]["result"]
        self.request("/api/projects/" + p["project_id"] + "/tasks/" + t["task_id"] + "/retry", "POST", {})
        p, t = self.terminal(item)
        self.assertEqual(len(t["pages"]["1"]["attempts"]), 1)
        self.assertEqual(t["pages"]["1"]["latest"]["result"], first_result)
        self.assertEqual(len(t["pages"]["2"]["attempts"]), 2)

    def test_page_deadline(self):
        self.config["engines"]["delay"]["timeout"] = 1
        p, t = self.terminal(self.upload("delay"))
        self.assertEqual(t["pages"]["1"]["latest"]["error"]["code"], "TIMEOUT")

    def test_actual_service_crash_recovers_interrupted(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = configuration()
        config["service"]["port"] = port
        path = self.root / "crash-config.json"
        path.write_text(json.dumps(config))
        store = self.root / "crash-store"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nas_filetools.standalone.http",
                "--root",
                str(store),
                "--config",
                str(path),
                "--testing",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = "http://127.0.0.1:" + str(port)
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + "/api/projects", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.05)
            req = urllib.request.Request(
                base + "/api/uploads?filename=crash.png&engine=delay&pages=1",
                self.image.read_bytes(),
                method="POST",
            )
            with urllib.request.urlopen(req) as r:
                item = json.load(r)
            project_file = store / "projects" / item["project_id"] / "project.json"
            for _ in range(100):
                saved = json.loads(project_file.read_text())
                if saved["tasks"][0]["pages"]["1"]["status"] == "RUNNING":
                    break
                time.sleep(0.02)
            # Controlled crash only this synthetic child service and its descendants.
            os.kill(process.pid, signal.SIGSTOP)
            children = terminate_descendants(process.pid)
            process.kill()
            process.wait(timeout=5)
            for pid in children:
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass
            recovered = Projects(store, config, start_worker=False)
            self.assertEqual(recovered.get(item["project_id"])["tasks"][0]["status"], "INTERRUPTED")
            self.assertEqual(
                recovered.get(item["project_id"])["tasks"][0]["pages"]["1"]["status"], "INTERRUPTED"
            )
            engine = recovered.config["engines"]["delay"]
            engine["timeout"] = 1
            # Existing task config must match on retry; only this synthetic test record is changed.
            saved = recovered.get(item["project_id"])
            saved["tasks"][0]["engine"]["timeout"] = 1
            from nas_filetools.standalone.tasks import atomic

            atomic(project_file, saved)
            recovered.retry(item["project_id"], item["task_id"])
            recovered.execute(item["project_id"], item["task_id"])
            after = recovered.get(item["project_id"])["tasks"][0]
            self.assertEqual(after["pages"]["1"]["latest"]["error"]["code"], "TIMEOUT")
        finally:
            if process.poll() is None:
                terminate_descendants(process.pid)
                process.kill()
                process.wait(timeout=5)

    def test_recovery_rename_and_trash_reference_not_deleted(self):
        item = self.upload()
        p, t = self.terminal(item)
        p["tasks"][0]["status"] = "RUNNING"
        from nas_filetools.standalone.tasks import atomic

        atomic(self.m.path(p["project_id"]) / "project.json", p)
        recovered = Projects(self.root / "data", self.config, start_worker=False)
        self.assertEqual(recovered.get(p["project_id"])["tasks"][0]["status"], "INTERRUPTED")
        self.request("/api/projects/" + p["project_id"], "PATCH", {"name": "New name"})
        external = self.root / "external.pdf"
        external.write_bytes(b"original")
        p = recovered.get(p["project_id"])
        p["external_reference"] = {"path": str(external)}
        atomic(recovered.path(p["project_id"]) / "project.json", p)
        self.request("/api/projects/" + p["project_id"], "DELETE")
        self.assertTrue(external.exists())
        self.assertEqual(self.request("/api/projects"), [])
        self.assertEqual(len(self.request("/api/trash")), 1)
        self.request("/api/trash/" + p["project_id"] + "/restore", "POST", {})
        self.assertEqual(len(self.request("/api/projects")), 1)

    def test_feedback_clear_stale_and_cross_project(self):
        item = self.upload()
        p, t = self.terminal(item)
        a = next(a for a in p["artifacts"] if a["format"] == "markdown")
        receipt = {
            "schema": "filetools-artifact-feedback-v1",
            "project_id": p["project_id"],
            "project_revision": 1,
            "reviewer_type": "developer-agent",
            "base_feedback_revision": 0,
            "comments": [
                {
                    "project_id": p["project_id"],
                    "artifact_id": a["artifact_id"],
                    "artifact_sha256": a["sha256"],
                    "locator": a["pages"][0]["locator"],
                    "text": "synthetic comment",
                    "updated_at": "2026-10-08T12:00:00Z",
                }
            ],
        }
        endpoint = "/api/projects/" + p["project_id"] + "/feedback"
        r = self.request(endpoint, "POST", receipt)
        self.assertEqual(r["revision"], 1)
        with self.assertRaises(urllib.error.HTTPError):
            self.request(endpoint, "POST", receipt)
        receipt["base_feedback_revision"] = 1
        receipt["comments"][0]["text"] = ""
        self.assertEqual(self.request(endpoint, "POST", receipt)["receipt"]["comments"][0]["text"], "")
        other = self.upload()
        self.terminal(other)
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/projects/" + other["project_id"] + "/feedback", "POST", receipt)

    def test_upload_limits_signature_paths_and_origin(self):
        for path, data in [
            ("/api/uploads?filename=evil.png&engine=fixture&pages=1", b"%PDF-fake"),
            ("/api/uploads?filename=..%2Fevil.png&engine=fixture&pages=1", self.image.read_bytes()),
        ]:
            with self.assertRaises(urllib.error.HTTPError):
                self.request(path, "POST", data)
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/projects", headers={"Origin": "https://evil.invalid"})
        self.config["service"]["upload_bytes"] = 10
        with self.assertRaises(urllib.error.HTTPError):
            self.upload()
        self.assertFalse(list((self.root / "data/uploads").iterdir()))

    def test_upload_limits_boundary_and_incomplete_cleanup(self):
        import http.client

        limits = self.request("/api/limits")
        self.assertEqual(limits, {"upload_bytes": 536870912, "max_pdf_pages": 1000, "max_selected_pages": 5})
        raw = self.image.read_bytes()
        self.config["service"]["upload_bytes"] = len(raw)
        accepted = self.upload()
        self.assertIn("project_id", accepted)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/uploads?filename=synthetic.png&engine=fixture&pages=1", "POST", raw + b"x")
        self.assertEqual(raised.exception.code, 413)
        result = json.loads(raised.exception.read())
        self.assertEqual(result["error"], "UPLOAD_TOO_LARGE")
        self.assertEqual(result["limit_bytes"], len(raw))
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.putrequest("POST", "/api/uploads?filename=incomplete.png&engine=fixture&pages=1")
        connection.putheader("Content-Length", len(raw))
        connection.endheaders()
        connection.send(raw[:20])
        connection.sock.shutdown(socket.SHUT_WR)
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        self.assertIn("incomplete upload", response.read().decode())
        connection.close()
        self.assertEqual(list((self.root / "data/uploads").iterdir()), [])
        # Keep PDF/selection checks even when byte size is allowed.
        import fitz

        self.config["service"]["upload_bytes"] = 536870912
        doc = fitz.open()
        for _ in range(6):
            doc.new_page()
        with self.assertRaises(urllib.error.HTTPError):
            self.request(
                "/api/uploads?filename=too-many-selected.pdf&engine=fixture&pages=1,2,3,4,5,6",
                "POST",
                doc.tobytes(),
            )
        self.config["service"]["max_pages"] = 5
        with self.assertRaises(urllib.error.HTTPError):
            self.request(
                "/api/uploads?filename=too-many-pages.pdf&engine=fixture&pages=1", "POST", doc.tobytes()
            )
        self.assertEqual(list((self.root / "data/uploads").iterdir()), [])
        doc.close()

    def test_pdf_total_page_boundary_without_upload_render(self):
        import fitz
        from unittest.mock import patch

        fixtures = {}
        for pages in [1, 999, 1000, 1001]:
            doc = fitz.open()
            for _ in range(pages):
                doc.new_page()
            fixtures[pages] = doc.tobytes()
            doc.close()
        with (
            patch.object(
                self.m,
                "enqueue",
                side_effect=lambda pid, *a, **k: {"project_id": pid, "task_id": "upload-only"},
            ),
            patch.object(fitz.Document, "load_page", side_effect=AssertionError("upload loaded PDF page")),
            patch.object(fitz.Page, "get_text", side_effect=AssertionError("upload extracted text")),
            patch.object(fitz.Page, "get_pixmap", side_effect=AssertionError("upload rendered page")),
        ):
            for pages in [1, 999, 1000]:
                result = self.request(
                    "/api/uploads?filename=boundary.pdf&engine=fixture&pages=1", "POST", fixtures[pages]
                )
                self.assertEqual(self.m.get(result["project_id"])["source_info"]["units"], pages)
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                self.request(
                    "/api/uploads?filename=over-limit.pdf&engine=fixture&pages=1", "POST", fixtures[1001]
                )
            self.assertEqual(rejected.exception.code, 400)
            reason = json.loads(rejected.exception.read())["reason"]
            self.assertIn("PAGE_LIMIT", reason)
            self.assertIn("1001", reason)
            self.assertIn("1000", reason)
            self.assertEqual(list((self.root / "data/uploads").iterdir()), [])

    def test_restore_body_consumed_on_keepalive_connection(self):
        import http.client

        item = self.upload()
        p, t = self.terminal(item)
        self.request("/api/projects/" + p["project_id"], "DELETE")
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            conn.request(
                "POST",
                "/api/trash/" + p["project_id"] + "/restore",
                b"{}",
                {"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.request("GET", "/api/projects")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
        finally:
            conn.close()

    def test_pdf_upload_rendered_only_selected_page(self):
        import fitz

        doc = fitz.open()
        doc.new_page().insert_text((30, 30), "Page one")
        doc.new_page().insert_text((30, 30), "Page two")
        item = self.request(
            "/api/uploads?filename=synthetic.pdf&engine=fixture&pages=2", "POST", doc.tobytes()
        )
        doc.close()
        p, t = self.terminal(item)
        self.assertEqual(list(t["pages"]), ["2"])
        self.assertEqual(len(list(self.m.path(p["project_id"]).glob("sources/previews/*/*.png"))), 1)


class AdapterTests(unittest.TestCase):
    def test_formatter_verbatim_preservation_and_native_boundaries(self):
        from nas_filetools.standalone import documents
        from unittest.mock import patch
        import fitz

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            font = root / "font.ttf"
            font.write_bytes(fitz.Font("cjk").buffer)
            text = "\n".join("未确认结构的长正文，保留换行与原文。" for _ in range(90))
            with patch.object(documents, "FONT_PATH", font):
                documents.generate(
                    {
                        "output": str(root),
                        "template": {"id": "questions-zh-cn", "version": "1.0.0"},
                        "title": "合成格式验收",
                        "pages": [{"physical_page": 1, "text": text}],
                    }
                )
            check = json.loads((root / "layout-validation.json").read_text())
            self.assertTrue(check["content_equal"])
            self.assertTrue(check["native_layout_boundaries"]["passed"])
            self.assertFalse(check["quality_and_comments_in_body"])

    def test_config_errors(self):
        data = configuration()
        for change in [
            lambda x: x["service"].update(bind="0.0.0.0"),
            lambda x: x["engines"]["fixture"].update(retries=2),
            lambda x: x["conversion"].update(dpi=True),
        ]:
            x = copy.deepcopy(data)
            change(x)
            with self.assertRaises(ValueError):
                validate(x, testing=True)
        with self.assertRaises(ValueError):
            validate(data)

    def test_separation_and_unknown_quality(self):
        text = "<transcription_markdown>raw\n</transcription_markdown><quality_json>broken</quality_json>"
        body, quality, error = separate(text, True)
        self.assertEqual(body, "raw\n")
        self.assertIsNone(quality)
        self.assertEqual(error["stage"], "response_parse")
        self.assertEqual(separate("unstructured response quality data", True)[0], "")

    def test_remote_redirect_is_not_followed(self):
        calls = []

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                calls.append(self.path)
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(307)
                self.send_header("Location", "/must-not-follow")
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                from PIL import Image

                image = Path(folder) / "test.png"
                Image.new("RGB", (100, 100), "white").save(image)
                os.environ["FILETOOLS_TEST_KEY"] = "SYNTHETIC_PRIVATE_KEY"
                try:
                    result = recognize(
                        image,
                        {
                            "type": "openai-vision",
                            "model": "mock",
                            "endpoint": f"http://127.0.0.1:{server.server_port}/start",
                            "credential_env": "FILETOOLS_TEST_KEY",
                            "timeout": 5,
                        },
                        {"language": "zh", "quality": False},
                    )
                finally:
                    os.environ.pop("FILETOOLS_TEST_KEY")
                self.assertEqual(result["error"]["code"], 307)
                self.assertEqual(calls, ["/start"])
        finally:
            server.shutdown()
            server.server_close()

    def test_openai_protocol_real_mock_and_secret_echo(self):
        captured = {}

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured.update(payload)
                text = '<transcription_markdown>untouched original</transcription_markdown><quality_json>{"overall_quality":"good","suggested_action":"keep","evidence":[],"uncertainty_note":"mock only"}</quality_json>'
                response = json.dumps(
                    {
                        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                        "echo": "SYNTHETIC_PRIVATE_KEY",
                    }
                )
                self.send_response(200)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response.encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                from PIL import Image

                image = Path(folder) / "test.png"
                Image.new("RGB", (100, 100), "white").save(image)
                engine = {
                    "type": "openai-vision",
                    "model": "mock-vision",
                    "endpoint": "http://127.0.0.1:" + str(server.server_port),
                    "credential_env": "FILETOOLS_TEST_KEY",
                    "timeout": 5,
                }
                os.environ["FILETOOLS_TEST_KEY"] = "SYNTHETIC_PRIVATE_KEY"
                try:
                    result = recognize(image, engine, {"language": "zh", "quality": True})
                finally:
                    os.environ.pop("FILETOOLS_TEST_KEY")
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertNotIn("SYNTHETIC_PRIVATE_KEY", json.dumps(result))
                uploaded = captured["messages"][0]["content"][1]["image_url"]["url"].split(",")[1]
                self.assertEqual(base64.b64decode(uploaded), image.read_bytes())
                result = recognize(image, engine, {"language": "zh", "quality": True})
                self.assertEqual(result["error"]["code"], "CREDENTIAL_UNAVAILABLE")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
