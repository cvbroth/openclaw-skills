"""Synthetic task/artifact isolation and append-only comment receipt checks."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from nas_filetools.artifact_project import (
    create_project,
    digest,
    emit_viewer,
    import_feedback,
    register_artifact,
    relative,
    snapshot_template,
    validate_feedback,
)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.p = create_project(self.root, "Synthetic", "task1")
        (self.root / "content/content.md").write_text("<script>alert(1)</script>")
        self.a = register_artifact(
            self.root,
            self.p,
            name="text",
            format="markdown",
            path="content/content.md",
            pages=[{"label": "p1", "locator": {"kind": "source_page", "page": 1}}],
        )
        emit_viewer(self.root, self.p)
        self.r = {
            "schema": "filetools-artifact-feedback-v1",
            "project_id": self.p["project_id"],
            "project_revision": 1,
            "reviewer_type": "developer-agent",
            "comments": [
                {
                    "project_id": self.p["project_id"],
                    "artifact_id": self.a["artifact_id"],
                    "artifact_sha256": self.a["sha256"],
                    "locator": {"kind": "source_page", "page": 1},
                    "text": "Synthetic comment",
                    "updated_at": "2026-10-08T12:00:00+00:00",
                }
            ],
        }

    def test_new_task_same_source_is_independent(self):
        other = create_project(Path(self.temp.name) / "second", "Other", "task2")
        self.assertNotEqual(self.p["project_id"], other["project_id"])
        with self.assertRaises(ValueError):
            validate_feedback(other, self.r)

    def test_add_outputs_same_project_and_distinct_ids(self):
        before = self.p["project_id"]
        a = register_artifact(
            self.root,
            self.p,
            name="new version",
            format="markdown",
            path="content/content.md",
            version="2",
            parents=[self.a["artifact_id"]],
        )
        self.assertEqual(before, self.p["project_id"])
        self.assertNotEqual(a["artifact_id"], self.a["artifact_id"])
        self.assertEqual(a["parents"], [self.a["artifact_id"]])

    def test_receipt_history_and_no_original_change(self):
        before = digest(self.root / "content/content.md")
        first = import_feedback(self.root, self.r)
        with self.assertRaises(ValueError):
            import_feedback(self.root, self.r)
        r = copy.deepcopy(self.r)
        r["base_feedback_revision"] = 1
        r["comments"][0]["text"] = "Changed comment"
        second = import_feedback(self.root, r)
        self.assertTrue(first.is_file())
        self.assertNotEqual(first, second)
        self.assertEqual(before, digest(self.root / "content/content.md"))
        self.assertEqual(json.loads((self.root / "review/feedback.json").read_text())["revision"], 2)

    def test_invalid_receipts(self):
        for field, value in [
            ("artifact_id", "unknown"),
            ("artifact_sha256", "bad"),
            ("locator", {"kind": "source_page", "page": 2}),
            ("updated_at", "bad"),
            ("text", None),
        ]:
            r = copy.deepcopy(self.r)
            r["comments"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_feedback(self.p, r)
        r = copy.deepcopy(self.r)
        r["project_revision"] = 9
        with self.assertRaises(ValueError):
            validate_feedback(self.p, r)
        r = copy.deepcopy(self.r)
        r["comments"] *= 2
        with self.assertRaises(ValueError):
            validate_feedback(self.p, r)

    def test_reference_hash_and_independent_positions(self):
        a = register_artifact(
            self.root,
            self.p,
            name="output PDF",
            format="pdf",
            path="content/content.md",
            pages=[{"label": "output1", "locator": {"kind": "physical_page", "page": 1}}],
        )
        r = copy.deepcopy(self.r)
        r["comments"][0].update(
            reference_artifact_id=a["artifact_id"],
            reference_sha256=a["sha256"],
            reference_locator={"kind": "physical_page", "page": 1},
        )
        validate_feedback(self.p, r)
        r["comments"][0]["reference_sha256"] = "stale"
        with self.assertRaises(ValueError):
            validate_feedback(self.p, r)

    def test_paths_and_external_reference_never_followed(self):
        for path in ["../escape", "/tmp/escape", "a\\b"]:
            with self.assertRaises(ValueError):
                relative(self.root, path)
        a = register_artifact(
            self.root,
            self.p,
            name="missing original",
            format="reference",
            external_reference={"path": "/not-mounted/original.pdf", "sha256": "a" * 64},
        )
        self.assertIsNone(a["path"])

    def test_template_snapshot_and_move(self):
        original = Path(self.temp.name) / "template.json"
        original.write_text('{"body":11}')
        snapshot_template(self.root, self.p, original, template_id="synthetic", version="1")
        sha = self.p["templates"][0]["sha256"]
        original.write_text('{"body":12}')
        self.assertEqual(digest(self.root / self.p["templates"][0]["path"]), sha)
        emit_viewer(self.root, self.p)
        moved = self.root.with_name("moved")
        self.root.rename(moved)
        self.assertTrue((moved / "review/index.html").is_file())
        self.assertTrue(relative(moved, self.a["path"]).is_file())

    def test_changed_bytes_refused(self):
        (self.root / "content/content.md").write_text("altered")
        with self.assertRaises(ValueError):
            import_feedback(self.root, self.r)
        self.assertFalse((self.root / "review/feedback-history").exists())

    def test_unsafe_preview_and_script_safe_metadata(self):
        self.p["name"] = "</script><img src=x onerror=alert(1)>"
        emit_viewer(self.root, self.p)
        self.assertNotIn("</script>", (self.root / "review/project.js").read_text())
        self.a["pages"][0]["image"] = "../escape.png"
        with self.assertRaises(ValueError):
            emit_viewer(self.root, self.p)


if __name__ == "__main__":
    unittest.main()
