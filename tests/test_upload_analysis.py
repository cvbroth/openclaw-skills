"""Synthetic source analysis and private engine lifecycle, no remote requests."""

import copy
import json
import time
import threading
from unittest.mock import patch
import urllib.error

import fitz
from PIL import Image
import test_standalone_http as scenarios


class SeparationTests(scenarios.HTTPTests):
    # Inherit only setup/helpers, do not duplicate unrelated inherited scenarios.
    def wait_analysis(self, pid):
        for _ in range(150):
            p = self.request("/api/projects/" + pid)
            if p.get("analysis", {}).get("status") not in ["RUNNING", "QUEUED"]:
                return p
            time.sleep(0.05)
        self.fail("analysis did not finish")

    def test_upload_never_enqueues_engine_and_retains_failed_source(self):
        with patch.object(self.m, "enqueue", side_effect=AssertionError("upload called engine")):
            item = self.request(
                "/api/uploads?filename=invalid.pdf&project_name=synthetic", "POST", b"not-pdf"
            )
            p = self.wait_analysis(item["project_id"])
            self.assertEqual(p["tasks"], [])
            self.assertEqual(p["analysis"]["status"], "FAILED")
            self.assertIsNone(p["source_info"]["units"])
            self.assertEqual(p["source_info"]["bytes"], 7)
            artifact = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
            self.assertEqual((self.m.path(p["project_id"]) / artifact["path"]).read_bytes(), b"not-pdf")
            self.request("/api/projects/" + p["project_id"] + "/analysis", "POST", {})
            self.assertEqual(self.wait_analysis(p["project_id"])["analysis"]["status"], "FAILED")
        self.assertFalse(list((self.m.root / "uploads").iterdir()))

    def test_page_analysis_and_direct_extraction_no_visual_quality(self):
        image = self.root / "scan.png"
        Image.new("RGB", (600, 800), "grey").save(image)
        pdf = fitz.open()
        pdf.new_page().insert_text((30, 50), "Extractable synthetic paragraph " * 3)
        pdf.new_page().insert_image(fitz.Rect(0, 0, 595, 842), filename=str(image))
        page = pdf.new_page()
        page.insert_image(fitz.Rect(0, 0, 595, 842), filename=str(image))
        page.insert_text((30, 50), "Synthetic OCR text layer " * 3)
        page = pdf.new_page()
        page.insert_image(fitz.Rect(300, 100, 550, 400), filename=str(image))
        page.insert_text((30, 50), "Synthetic text and small illustration " * 2)
        pdf.new_page()
        item = self.request("/api/uploads?filename=classification.pdf", "POST", pdf.tobytes())
        pdf.close()
        p = self.wait_analysis(item["project_id"])
        self.assertEqual(p["tasks"], [])
        self.assertEqual(
            [r["category"] for r in p["analysis"]["pages"]],
            ["text", "scan", "mixed", "text", "blank_or_undetermined"],
        )
        self.assertEqual(p["analysis"]["source_sha256"], p["artifacts"][0]["sha256"])
        self.assertEqual([r["physical_page"] for r in p["analysis"]["pages"]], [1, 2, 3, 4, 5])
        self.assertFalse(p["analysis"]["visual_quality_performed"])
        task = self.request(
            "/api/projects/" + p["project_id"] + "/tasks", "POST", {"engine": "pdf-text", "pages": [1, 3]}
        )
        p, t = self.terminal(task)
        self.assertEqual(t["status"], "SUCCEEDED")
        self.assertEqual(list(t["pages"]), ["1", "3"])
        structure = next(a for a in p["artifacts"] if a["name"].startswith("structure.json"))
        data = json.loads((self.m.path(p["project_id"]) / structure["path"]).read_text())
        self.assertEqual([r["physical_page"] for r in data["pages"]], [1, 3])
        self.assertTrue(data["pages"][0]["blocks"][0]["coordinates"])
        self.assertEqual(
            data["pages"][0]["blocks"][0]["coordinate_system"], "PDF points; source physical page"
        )
        self.assertFalse(list(self.m.path(p["project_id"]).glob("sources/previews/**/*.png")))
        self.assertEqual(p.get("source_evaluations", []), [])

    def test_partial_analysis_and_recovery_keep_completed_pages(self):
        from nas_filetools.standalone.source_analysis import main
        from nas_filetools.artifact_project import digest
        from nas_filetools.standalone.tasks import Projects

        source = self.root / "partial.pdf"
        with fitz.open() as doc:
            doc.new_page()
            doc.new_page()
            doc.save(source)
        output = self.root / "partial.json"
        with patch(
            "nas_filetools.standalone.source_analysis.inspect_page",
            side_effect=[{"category": "text", "status": "SUCCEEDED"}, TimeoutError("synthetic timeout")],
        ):
            main(
                {"source": str(source), "source_sha256": digest(source), "kind": "pdf", "max_pages": 1000},
                output,
            )
        data = json.loads(output.read_text())
        self.assertEqual(data["status"], "PARTIAL")
        self.assertEqual(data["completed_pages"], 2)
        self.assertEqual(data["pages"][1]["text_usability"], "unknown")
        item = self.request("/api/uploads?filename=recovery.png", "POST", self.image.read_bytes())
        p = self.wait_analysis(item["project_id"])
        self.assertEqual(p["source_info"]["dimensions"], [400, 500])
        p["analysis"]["status"] = "RUNNING"
        self.m.save(self.m.path(p["project_id"]), p)
        recovered = Projects(self.m.root, self.config, start_worker=False)
        try:
            restored = recovered.get(p["project_id"])
            self.assertEqual(restored["analysis"]["status"], "INTERRUPTED")
            self.assertEqual(restored["analysis"]["completed_pages"], 1)
            self.assertEqual(restored["tasks"], [])
        finally:
            recovered.close()

    def test_analysis_does_not_bypass_pixel_or_password_limits(self):
        self.config["service"]["max_pixels"] = 100000
        item = self.request("/api/uploads?filename=large.png", "POST", self.image.read_bytes())
        p = self.wait_analysis(item["project_id"])
        self.assertEqual(p["analysis"]["status"], "FAILED")
        self.assertEqual(p["analysis"]["error"]["code"], "PIXEL_LIMIT")
        self.assertEqual(p["source_info"]["validation_status"], "FAILED")
        with self.assertRaises(urllib.error.HTTPError):
            self.request(
                "/api/projects/" + p["project_id"] + "/tasks", "POST", {"engine": "fixture", "pages": [1]}
            )
        doc = fitz.open()
        doc.new_page()
        raw = doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="synthetic-owner", user_pw="synthetic-test"
        )
        doc.close()
        item = self.request("/api/uploads?filename=encrypted.pdf", "POST", raw)
        p = self.wait_analysis(item["project_id"])
        self.assertEqual(p["analysis"]["status"], "FAILED")
        self.assertEqual(p["analysis"]["error"]["code"], "PDF_PASSWORD_REQUIRED")
        self.assertEqual(p["tasks"], [])

    def test_actual_jpeg_type_is_not_inferred_from_extension(self):
        path = self.root / "synthetic.jpg"
        Image.new("RGB", (120, 160), "white").save(path, format="JPEG")
        item = self.request("/api/uploads?filename=synthetic.jpg", "POST", path.read_bytes())
        p = self.wait_analysis(item["project_id"])
        self.assertEqual(p["source_info"]["actual_type"], "JPEG")
        self.assertEqual(p["source_info"]["dimensions"], [120, 160])
        self.assertEqual(p["tasks"], [])

    def test_source_hash_change_blocks_processing_and_local_model_is_fixed(self):
        self.config["engines"]["local"] = {
            **copy.deepcopy(self.config["engines"]["fixture"]),
            "type": "rapidocr",
            "model": "bundled-fixed",
        }
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/engines/local", "POST", {"model": "invented-weights"})
        item = self.request("/api/uploads?filename=immutable.png", "POST", self.image.read_bytes())
        p = self.wait_analysis(item["project_id"])
        with patch.object(self.m.queue, "put"):
            task = self.request(
                "/api/projects/" + p["project_id"] + "/tasks", "POST", {"engine": "fixture", "pages": [1]}
            )
        source = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
        (self.m.path(p["project_id"]) / source["path"]).write_bytes(b"synthetic changed input")
        self.m.queue.put((p["project_id"], task["task_id"]))
        _, result = self.terminal(task)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["pages"]["1"]["latest"]["error"]["code"], "SOURCE_HASH_CHANGED")

    def test_private_key_and_frozen_task_config(self):
        self.config["engines"]["remote"] = {
            **copy.deepcopy(self.config["engines"]["fixture"]),
            "type": "openai-vision",
            "model": "synthetic-old",
            "endpoint": "https://example.invalid/v1/chat/completions",
            "credential_env": "SYNTHETIC_TEST_KEY",
        }
        item = self.request("/api/uploads?filename=source.png", "POST", self.image.read_bytes())
        p = self.wait_analysis(item["project_id"])
        route = "/api/engines/remote"
        with self.assertRaises(urllib.error.HTTPError):
            self.request(
                "/api/projects/" + p["project_id"] + "/tasks", "POST", {"engine": "remote", "pages": [1]}
            )
        key = "synthetic-credential-only-not-real"
        response = self.request(route, "POST", {"name": "合成远端", "key_action": "replace", "api_key": key})
        self.assertTrue(response["credential_configured"])
        self.assertNotIn(key, json.dumps(self.request("/api/engines")))
        with patch.object(self.m.queue, "put"):
            task = self.request(
                "/api/projects/" + p["project_id"] + "/tasks", "POST", {"engine": "remote", "pages": [1]}
            )
        self.request(
            route,
            "POST",
            {"model": "synthetic-new", "key_action": "replace", "api_key": "another-fake-value"},
        )
        self.assertEqual(self.m.runtime_engines[task["task_id"]]["model"], "synthetic-old")
        self.assertEqual(self.m.runtime_keys[task["task_id"]], key)
        entered, release = threading.Event(), threading.Event()
        captured = {}

        def fake_child(request, result, timeout, cancel, **kwargs):
            captured.update(model=request["engine"]["model"], key=kwargs.get("secret"))
            entered.set()
            assert release.wait(5)
            return {
                "status": "SUCCEEDED",
                "text": "Synthetic response",
                "blocks": [],
                "quality": None,
                "error": None,
            }

        with patch.object(self.m, "run_child", side_effect=fake_child):
            self.m.queue.put((p["project_id"], task["task_id"]))
            self.assertTrue(entered.wait(5))
            try:
                self.request(route, "POST", {"model": "changed-while-running"})
                self.assertEqual(captured["model"], "synthetic-old")
                self.assertEqual(captured["key"], key)
            finally:
                release.set()
            self.assertEqual(self.terminal(task)[1]["status"], "SUCCEEDED")
        private = self.m.root / "private/engines.json"
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        for file in self.m.path(p["project_id"]).rglob("*"):
            if file.is_file():
                self.assertNotIn(key.encode(), file.read_bytes())
        with patch(
            "urllib.request.OpenerDirector.open", side_effect=AssertionError("connection test called network")
        ):
            self.assertEqual(self.m.settings.test("remote")["requests"], 0)
        self.request(route, "POST", {"key_action": "clear"})
        self.assertFalse(self.request("/api/engines")["remote"]["credential_configured"])
        self.assertNotIn(key, private.read_text())
        self.assertEqual(
            self.m.task(self.m.get(p["project_id"]), task["task_id"])["engine"]["model"], "synthetic-old"
        )


# unittest discovers inherited tests; retain only dedicated additions in this class.
for name in dir(scenarios.HTTPTests):
    if name.startswith("test_") and name not in SeparationTests.__dict__:
        setattr(SeparationTests, name, None)
