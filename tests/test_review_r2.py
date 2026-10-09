"""Synthetic source assessment migration, preview jobs and comment scope regression."""

import json
from pathlib import Path
import tempfile
import time
import unittest
import fitz
from PIL import Image
from nas_filetools.artifact_project import (
    create_project,
    register_artifact,
    digest,
    validate_feedback,
    emit_viewer,
)
from nas_filetools.standalone.source_quality import migrate
from nas_filetools.standalone.tasks import Projects
from test_standalone_http import configuration


class QualityTests(unittest.TestCase):
    def test_proven_image_multirecord_and_local_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "p"
            p = create_project(root, "Synthetic", "task")
            image = root / "sources/test.png"
            Image.new("RGB", (120, 140), "white").save(image)
            loc = {"kind": "physical_page", "page": 1}
            src = register_artifact(
                root,
                p,
                name="source",
                format="image",
                path="sources/test.png",
                pages=[
                    {
                        "locator": loc,
                        "image": "sources/test.png",
                        "image_sha256": digest(image),
                        "label": "p1",
                        "task_id": "one",
                    },
                    {
                        "locator": loc,
                        "image": "sources/test.png",
                        "image_sha256": digest(image),
                        "label": "p1",
                        "task_id": "two",
                    },
                ],
            )
            p["source_artifact_id"] = src["artifact_id"]
            submitted = {"sha256": digest(image), "width": 120, "height": 140}
            p["tasks"] = []
            for i, quality in enumerate(
                [{"overall_quality": "good"}, {"overall_quality": "poor"}, None, {"overall_quality": "good"}]
            ):
                path = f"diagnostics/r{i}.json"
                (root / path).write_text(
                    json.dumps({"quality": quality, "submitted_input": submitted if i != 3 else None})
                )
                p["tasks"].append(
                    {
                        "task_id": str(i),
                        "engine": {"model": "synthetic"},
                        "pages": {"1": {"attempts": [{"attempt": 1, "result": path}]}},
                    }
                )
            migrate(root, p)
            self.assertEqual(len(src["pages"]), 1)
            self.assertEqual(src["pages"][0]["task_ids"], ["one", "two"])
            self.assertEqual(
                [e["quality"]["overall_quality"] for e in p["source_evaluations"]], ["good", "poor"]
            )
            self.assertEqual(len(p["legacy_quality_records"]), 1)
            migrate(root, p)
            self.assertEqual(len(p["source_evaluations"]), 2)
            self.assertEqual(len(p["legacy_quality_records"]), 1)
            # A missing local preview cannot establish a new source association.
            image.unlink()
            p["source_evaluations"] = []
            migrate(root, p)
            self.assertEqual(p["source_evaluations"], [])
            self.assertEqual(len(p["legacy_quality_records"]), 3)
            expected_image_hash = src["pages"][0]["image_sha256"]
            emit_viewer(root, p)
            self.assertEqual(src["pages"][0]["image_availability"], "missing")
            self.assertEqual(src["pages"][0]["image_sha256"], expected_image_hash)
            receipt = {
                "schema": "filetools-artifact-feedback-v1",
                "project_id": p["project_id"],
                "project_revision": 1,
                "reviewer_type": "developer-agent",
                "comments": [],
            }
            base = {
                "project_id": p["project_id"],
                "artifact_id": src["artifact_id"],
                "artifact_sha256": src["sha256"],
                "locator": loc,
                "text": "Synthetic",
                "updated_at": "2026-10-09T00:00:00Z",
            }
            receipt["comments"] = [
                {**base, "object_type": "source_page"},
                {**base, "object_type": "artifact"},
            ]
            validate_feedback(p, receipt)  # Explicitly different comment objects at the same source position.
            receipt["comments"][0]["object_type"] = "unknown"
            with self.assertRaises(ValueError):
                validate_feedback(p, receipt)


class PreviewTests(unittest.TestCase):
    def test_pdf_preview_cache_failure_and_restart_state(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "store"
            manager = Projects(store, configuration())
            try:
                image = Path(folder) / "source.png"
                Image.new("RGB", (200, 300), "white").save(image)
                created = manager.upload(image, "source.png")
                item = manager.enqueue(created["project_id"], "fixture", [1])
                pid = item["project_id"]
                deadline = time.monotonic() + 10
                while (
                    manager.task(manager.get(pid), item["task_id"])["status"] in {"RUNNING", "QUEUED"}
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                root = manager.path(pid)
                project = manager.get(pid)
                path = root / "outputs/test.pdf"
                with fitz.open() as pdf:
                    for n in range(3):
                        pdf.new_page().insert_text((60, 60), "Synthetic page " + str(n + 1))
                    pdf.save(path)
                a = register_artifact(root, project, name="test", format="pdf", path="outputs/test.pdf")
                manager.save(root, project)
                # A generic output preview request must not silently render a full source PDF.
                project["source_artifact_id"] = a["artifact_id"]
                manager.save(root, project)
                with self.assertRaisesRegex(ValueError, "原件"):
                    manager.preview(pid, a["artifact_id"])
                project["source_artifact_id"] = item.get("source_artifact_id") or next(
                    x["artifact_id"] for x in project["artifacts"] if x["format"] == "image"
                )
                manager.save(root, project)

                def wait():
                    end = time.monotonic() + 15
                    while time.monotonic() < end:
                        a = next(a for a in manager.get(pid)["artifacts"] if a["name"] == "test")
                        if a.get("preview_render", {}).get("status") not in {"RUNNING", "QUEUED"}:
                            return a
                        time.sleep(0.05)
                    self.fail("preview deadline")

                manager.preview(pid, a["artifact_id"])
                a = wait()
                self.assertEqual(a["preview_render"]["status"], "SUCCEEDED")
                self.assertEqual(len(a["pages"]), 3)
                for page in a["pages"]:
                    self.assertEqual(page["locator"]["kind"], "output_page")
                    self.assertEqual(digest(root / page["image"]), page["image_sha256"])
                before = list((root / "previews" / a["preview_render"]["key"]).glob("attempt-*"))
                manager.preview(pid, a["artifact_id"])
                a = wait()
                self.assertTrue(a["preview_render"]["cache_hit"])
                self.assertEqual(
                    before, list((root / "previews" / a["preview_render"]["key"]).glob("attempt-*"))
                )
                (root / "outputs/test.pdf").write_bytes(b"bad pdf")
                project = manager.get(pid)
                a = next(x for x in project["artifacts"] if x["artifact_id"] == a["artifact_id"])
                a["sha256"] = digest(root / "outputs/test.pdf")
                manager.save(root, project)
                manager.preview(pid, a["artifact_id"], True)
                a = wait()
                self.assertEqual(a["preview_render"]["status"], "FAILED")
                self.assertEqual(a["preview_render"]["error"]["stage"], "preview")
                # A failed preview must not delete the published source/result.
                self.assertTrue((root / "outputs/test.pdf").exists())
                self.assertEqual(manager.task(manager.get(pid), item["task_id"])["status"], "SUCCEEDED")
                project = manager.get(pid)
                a = next(x for x in project["artifacts"] if x["artifact_id"] == a["artifact_id"])
                a["preview_render"]["status"] = "RUNNING"
                manager.save(root, project)
            finally:
                manager.close()
            recovered = Projects(store, configuration(), start_worker=False)
            a = next(x for x in recovered.get(pid)["artifacts"] if x["name"] == "test")
            self.assertEqual(a["preview_render"]["status"], "INTERRUPTED")
