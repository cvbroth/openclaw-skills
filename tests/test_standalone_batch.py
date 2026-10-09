"""Ranges, reversible metadata and full fake-provider credential chain. No cloud."""

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error

import pytest
import test_standalone_http as scenarios
from nas_filetools.standalone.page_ranges import parse_pages
from nas_filetools.standalone.config import validate


@pytest.mark.parametrize(
    "value,expected",
    [
        ("5-150", list(range(5, 151))),
        ("1，3,8-10 9", [1, 3, 8, 9, 10]),
        ("1, 3, 8 - 10", [1, 3, 8, 9, 10]),
        ("全部", list(range(1, 1001))),
        ([3, 1, 1], [1, 3]),
    ],
)
def test_ranges(value, expected):
    assert parse_pages(value, 1000) == expected


@pytest.mark.parametrize(
    "value", ["", " ", "3-1", "1.5", "-2", "1,,2", "0", "1001", [True], "1-1001", "1-", "1e2"]
)
def test_invalid_ranges(value):
    with pytest.raises(ValueError):
        parse_pages(value, 1000)


def test_config_selection_boundary():
    c = scenarios.configuration()
    c["conversion"]["max_selected_pages"] = 1000
    validate(c, testing=True)
    c["conversion"]["max_selected_pages"] = 1001
    with pytest.raises(ValueError):
        validate(c, testing=True)
    with pytest.raises(ValueError):
        parse_pages("全部", 6, 5)


class ManagementTests(scenarios.HTTPTests):
    def test_artifact_rename_recycle_restore_retains_comments_bytes(self):
        p, t = self.terminal(self.upload())
        a = next(a for a in p["artifacts"] if a["format"] == "markdown")
        original = (self.m.path(p["project_id"]) / a["path"]).read_bytes()
        receipt = {
            "schema": "filetools-artifact-feedback-v1",
            "project_id": p["project_id"],
            "project_revision": p["revision"],
            "reviewer_type": "developer-agent",
            "base_feedback_revision": 0,
            "comments": [
                {
                    "project_id": p["project_id"],
                    "artifact_id": a["artifact_id"],
                    "artifact_sha256": a["sha256"],
                    "locator": {"kind": "document"},
                    "text": "Synthetic retained comment",
                    "updated_at": "2026-10-09T00:00:00Z",
                }
            ],
        }
        self.request("/api/projects/" + p["project_id"] + "/feedback", "POST", receipt)
        route = "/api/projects/" + p["project_id"] + "/artifacts/" + a["artifact_id"]
        changed = self.request(route, "PATCH", {"name": "我的提取文字", "recycled": True})
        self.assertEqual(changed["display_name"], "我的提取文字")
        self.assertEqual(changed["sha256"], a["sha256"])
        self.assertEqual(changed["parents"], a["parents"])
        self.assertTrue(changed["recycled"])
        self.assertIn("我的提取文字", changed["download_name"])
        self.assertFalse(self.request(route, "PATCH", {"recycled": False})["recycled"])
        self.assertEqual((self.m.path(p["project_id"]) / a["path"]).read_bytes(), original)
        feedback = self.request("/api/projects/" + p["project_id"] + "/feedback")
        self.assertEqual(feedback["receipt"]["comments"][0]["text"], "Synthetic retained comment")
        with self.assertRaises(urllib.error.HTTPError):
            self.request(
                "/api/projects/" + p["project_id"] + "/artifacts/" + p["source_artifact_id"],
                "PATCH",
                {"recycled": True},
            )
        result = self.request(
            "/api/projects/" + p["project_id"] + "/tasks/" + t["task_id"] + "/archive",
            "POST",
            {"archived": True},
        )
        self.assertTrue(result["archived"])
        after = self.request("/api/projects/" + p["project_id"])
        self.assertEqual(len(after["artifacts"]), len(p["artifacts"]))
        self.assertFalse(
            self.request(
                "/api/projects/" + p["project_id"] + "/tasks/" + t["task_id"] + "/archive",
                "POST",
                {"archived": False},
            )["archived"]
        )

    def test_active_task_cannot_archive_or_recycle(self):
        p, t = self.terminal(self.upload())
        a = next(a for a in p["artifacts"] if a["format"] == "markdown")
        item = self.request(
            "/api/projects/" + p["project_id"] + "/tasks", "POST", {"engine": "delay", "pages": "1"}
        )
        for route, method, data in [
            ("/tasks/" + item["task_id"] + "/archive", "POST", {"archived": True}),
            ("/artifacts/" + a["artifact_id"], "PATCH", {"recycled": True}),
        ]:
            with self.assertRaises(urllib.error.HTTPError):
                self.request("/api/projects/" + p["project_id"] + route, method, data)
        self.request("/api/projects/" + p["project_id"] + "/tasks/" + item["task_id"] + "/cancel", "POST", {})
        self.terminal(item)

    def test_legacy_source_size_is_read_from_registered_file(self):
        p, t = self.terminal(self.upload())
        root = self.m.path(p["project_id"])
        p["source_info"].pop("bytes", None)
        self.m.save(root, p)
        self.assertEqual(
            self.request("/api/projects/" + p["project_id"])["source_info"]["bytes"],
            self.image.stat().st_size,
        )

    def test_private_key_reaches_real_child_and_fake_provider(self):
        key = "synthetic-private-key-not-real"
        checks = []

        class Provider(BaseHTTPRequestHandler):
            def do_POST(inner):
                body = json.loads(inner.rfile.read(int(inner.headers["Content-Length"])))
                contents = body["messages"][0]["content"]
                received = (
                    bool(contents[0]["source"]["data"])
                    if contents[0]["type"] == "image"
                    else contents[1]["image_url"]["url"].startswith("data:image/png;base64,")
                )
                checks.append(
                    {
                        "authorization_matches": inner.headers.get("Authorization") == "Bearer " + key,
                        "image_received": received,
                        "model": body["model"],
                    }
                )
                data = json.dumps(
                    {
                        "model": "synthetic-v1",
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "Synthetic provider response"}],
                        "choices": [
                            {"message": {"content": "Synthetic provider response"}, "finish_reason": "stop"}
                        ],
                    }
                ).encode()
                inner.send_response(200)
                inner.send_header("Content-Length", str(len(data)))
                inner.end_headers()
                inner.wfile.write(data)

            def log_message(inner, *args):
                pass

        provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        try:
            for engine_id, kind in [
                ("remote-compatible", "openai-vision"),
                ("remote-native", "minimax-messages"),
            ]:
                self.config["engines"][engine_id] = {
                    **copy.deepcopy(self.config["engines"]["fixture"]),
                    "type": kind,
                    "model": "synthetic-v1",
                    "credential_env": "SYNTHETIC_REMOTE_REF",
                    "endpoint": f"http://127.0.0.1:{provider.server_port}/v1/chat/completions",
                }
                self.config["conversion"]["quality"] = False
                self.request("/api/engines/" + engine_id, "POST", {"key_action": "replace", "api_key": key})
                item = self.request("/api/uploads?filename=synthetic.png", "POST", self.image.read_bytes())
                item = self.request(
                    "/api/projects/" + item["project_id"] + "/tasks",
                    "POST",
                    {"engine": engine_id, "pages": "全部"},
                )
                p, t = self.terminal(item)
                self.assertEqual(t["status"], "SUCCEEDED")
                self.assertEqual(
                    checks[-1],
                    {"authorization_matches": True, "image_received": True, "model": "synthetic-v1"},
                )
                for f in self.m.path(p["project_id"]).rglob("*"):
                    if f.is_file():
                        self.assertNotIn(key.encode(), f.read_bytes())
                self.request("/api/engines/" + engine_id, "POST", {"key_action": "clear"})
                with self.assertRaises(urllib.error.HTTPError):
                    self.request(
                        "/api/projects/" + p["project_id"] + "/tasks",
                        "POST",
                        {"engine": engine_id, "pages": [1]},
                    )
            self.assertEqual(len(checks), 2)
        finally:
            provider.shutdown()
            provider.server_close()


for name in dir(scenarios.HTTPTests):
    if name.startswith("test_") and name not in ManagementTests.__dict__:
        setattr(ManagementTests, name, None)
