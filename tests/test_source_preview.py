"""Synthetic original-page rendering: no OCR, no provider requests."""

import json
import urllib.error
from unittest.mock import patch

import fitz
import pytest
import test_standalone_http as scenarios
from nas_filetools.artifact_project import digest, validate_feedback
from nas_filetools.standalone.source_preview import RENDERER, index_source


class SourcePreviewTests(scenarios.HTTPTests):
    def pdf_project(self):
        pdf = fitz.open()
        for n in range(1, 170):
            page = pdf.new_page(width=320, height=440)
            page.insert_text((30, 70), f"PHYSICAL PAGE {n:03d}", fontsize=20)
            page.draw_rect((30, 100, 30 + n, 120), color=(0, 0, 0), fill=(0, 0, 0))
        data = pdf.tobytes()
        pdf.close()
        return self.request("/api/uploads?filename=synthetic169.pdf", "POST", data)

    def test_full_index_without_recognition_and_cache(self):
        p = self.pdf_project()
        pid = p["project_id"]
        p = self.request("/api/projects/" + pid)
        source = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
        assert len(source["pages"]) == 169 and p["tasks"] == []
        assert not any(x.get("image") for x in source["pages"])
        images = []
        with patch.object(self.m, "run_child", side_effect=AssertionError("no engine/queue child")):
            for n in [1, 16, 23, 169]:
                r = self.request(f"/api/projects/{pid}/source-preview/{n}", "POST", {})
                assert r["status"] == "SUCCEEDED" and r["physical_page"] == n
                assert not r["cache_hit"]
                images.append(r["image_sha256"])
                source_path = self.m.path(pid) / source["path"]
                with fitz.open(source_path) as doc:
                    expected = doc[n - 1].get_pixmap(matrix=fitz.Matrix(120 / 72, 120 / 72), alpha=False)
                    actual = fitz.Pixmap(str(self.m.path(pid) / r["image"]))
                    assert actual.samples == expected.samples
                second = self.request(f"/api/projects/{pid}/source-preview/{n}", "POST", {})
                assert second["cache_hit"] and second["image_sha256"] == r["image_sha256"]
        assert len(set(images)) == 4
        assert self.m.get(pid)["tasks"] == []
        assert RENDERER["dpi"] == 120
        for n in [0, 170]:
            with pytest.raises(urllib.error.HTTPError) as e:
                self.request(f"/api/projects/{pid}/source-preview/{n}", "POST", {})
            assert e.value.code == 400

    def test_comment_uncached_physical_page_and_reload(self):
        p = self.pdf_project()
        pid = p["project_id"]
        p = self.m.get(pid)
        a = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
        receipt = {
            "schema": "filetools-artifact-feedback-v1",
            "project_id": pid,
            "project_revision": p["revision"],
            "reviewer_type": "developer-agent",
            "base_feedback_revision": 0,
            "comments": [
                {
                    "object_type": "source_page",
                    "project_id": pid,
                    "artifact_id": a["artifact_id"],
                    "artifact_sha256": a["sha256"],
                    "locator": {"kind": "physical_page", "page": 169},
                    "text": "Synthetic uncached-page comment",
                    "updated_at": "2026-10-09T12:00:00Z",
                }
            ],
        }
        validate_feedback(p, receipt)
        self.request(f"/api/projects/{pid}/feedback", "POST", receipt)
        assert (
            self.request(f"/api/projects/{pid}/feedback")["receipt"]["comments"][0]["locator"]["page"] == 169
        )
        assert not self.m.get(pid)["artifacts"][0]["pages"][168].get("image")

    def test_failure_retry_and_changed_original(self):
        p = self.pdf_project()
        pid = p["project_id"]
        endpoint = f"/api/projects/{pid}/source-preview/16"
        import subprocess

        with patch(
            "nas_filetools.standalone.source_preview.subprocess.run",
            side_effect=subprocess.TimeoutExpired("synthetic", 30),
        ):
            result = self.request(endpoint, "POST", {})
        assert result["error"]["code"] == "TIMEOUT"
        assert self.request(endpoint, "POST", {})["status"] == "FAILED"
        assert self.request(endpoint, "POST", {"retry": True})["status"] == "SUCCEEDED"
        source = self.m.get(pid)["artifacts"][0]
        original = self.m.path(pid) / source["path"]
        before = original.read_bytes()
        original.write_bytes(before + b"\nchanged")
        result = self.request(endpoint, "POST", {})
        assert result["error"]["code"] == "SOURCE_CHANGED_OR_MISSING"
        original.write_bytes(before)
        assert digest(original) == source["sha256"]
        assert self.request(endpoint, "POST", {})["cache_hit"]

    def test_preview_independent_of_busy_queue_and_busy_slot(self):
        p = self.pdf_project()
        pid = p["project_id"]
        assert self.m.source_preview_slot.acquire(False)
        try:
            assert self.request(f"/api/projects/{pid}/source-preview/1", "POST", {})["status"] == "BUSY"
        finally:
            self.m.source_preview_slot.release()
        # A blocked conversion executor cannot hold the dedicated rendering slot.
        with patch.object(self.m.queue, "put", side_effect=AssertionError("must not enqueue preview")):
            assert self.request(f"/api/projects/{pid}/source-preview/1", "POST", {})["status"] == "SUCCEEDED"

    def test_legacy_index_and_missing_original(self):
        p = self.pdf_project()
        pid = p["project_id"]
        root = self.m.path(pid)
        p = self.m.get(pid)
        source = p["artifacts"][0]
        source.pop("physical_index")
        source["pages"] = [
            {"locator": {"kind": "physical_page", "page": 23}, "physical_page": 23, "label": "old"}
        ]
        p.pop("source_info")
        assert index_source(root, p)
        assert len(source["pages"]) == 169 and source["pages"][22]["physical_page"] == 23
        self.m.save(root, p)
        original = root / source["path"]
        original.rename(original.with_suffix(".hidden"))
        r = self.request(f"/api/projects/{pid}/source-preview/23", "POST", {})
        assert r["error"]["code"] == "SOURCE_CHANGED_OR_MISSING"
        assert (
            json.loads((root / "project.json").read_text())["artifacts"][0]["physical_index"]["count"] == 169
        )

    def test_corrupt_cache_and_renderer_version(self):
        p = self.pdf_project()
        pid = p["project_id"]
        first = self.m.source_preview(pid, 23)
        image = self.m.path(pid) / first["image"]
        image.write_bytes(b"corrupted synthetic cache")
        second = self.m.source_preview(pid, 23)
        assert not second["cache_hit"] and second["image_sha256"] == first["image_sha256"]
        with patch.dict(RENDERER, schema="source-page-synthetic-next-version"):
            third = self.m.source_preview(pid, 23)
        assert third["render_key"] != second["render_key"] and not third["cache_hit"]
        assert len(self.m.get(pid)["artifacts"][0]["pages"]) == 169
        assert any(x.get("image") == first["image"] for x in self.m.get(pid)["artifacts"][0]["legacy_pages"])

    def test_real_preview_while_conversion_child_is_blocked(self):
        import threading
        import time

        p = self.pdf_project()
        pid = p["project_id"]
        started, release = threading.Event(), threading.Event()
        original = self.m.run_child

        def blocked(*args, **kwargs):
            started.set()
            release.wait(5)
            return original(*args, **kwargs)

        with patch.object(self.m, "run_child", side_effect=blocked):
            self.m.enqueue(pid, "fixture", [1])
            assert started.wait(3)
            begin = time.monotonic()
            result = self.m.source_preview(pid, 169)
            assert result["status"] == "SUCCEEDED" and time.monotonic() - begin < 3
            assert not release.is_set()
            release.set()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and any(
                t["status"] in ["RUNNING", "QUEUED"] for t in self.m.get(pid)["tasks"]
            ):
                time.sleep(0.05)
