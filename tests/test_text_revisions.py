"""Mapped revision contract with synthetic text; no OCR or remote calls."""

import json
import uuid
import time
from unittest.mock import patch

from nas_filetools.artifact_project import digest, page_data, register_artifact, emit_viewer
from nas_filetools.standalone.text_revisions import RevisionConflict
from test_standalone_http import HTTPTests


class RevisionTests(HTTPTests):
    def fixture(self):
        p = self.m.upload(self.image, "revision-source.png")
        pid = p["project_id"]
        for _ in range(100):
            if self.m.get(pid).get("analysis", {}).get("status") not in {"QUEUED", "RUNNING"}:
                break
            time.sleep(0.05)
        with self.m.lock:
            p = self.m.get(pid)
            root = self.m.path(pid)
            texts = [
                "# 合成测试\n\n第22页保持不变。",
                "第23页：人工修补错宇。\n\nA. 保留原件。\nB. 保存新版本。",
                "第24页保持不变。",
            ]
            views = []
            for n, text in zip([22, 23, 24], texts):
                path = f"content/synthetic-{n}.js"
                page_data(root, path, {"text": text})
                views.append(
                    {
                        "label": f"合成来源第{n}页",
                        "source_page": n,
                        "locator": {"kind": "block", "id": f"p{n}-text"},
                        "data": path,
                    }
                )
            (root / "content/source.md").write_text("\n\n".join(texts))
            a = register_artifact(
                root,
                p,
                name="合成文字稿",
                format="markdown",
                path="content/source.md",
                pages=views,
                parents=[p["source_artifact_id"]],
            )
            self.m.save(root, p)
            emit_viewer(root, p)
            return pid, a["artifact_id"]

    def payload(self, pid, aid, text="第23页：人工修补错字。"):
        info = self.m.text_artifact(pid, aid)
        return {
            "request_id": str(uuid.uuid4()),
            "parent_artifact_id": aid,
            "parent_sha256": info["sha256"],
            "head_id": info["head_id"],
            "head_sha256": info["head_sha256"],
            "locator": info["pages"][1]["locator"],
            "text": text,
        }

    def test_revision_consistency_and_idempotency(self):
        pid, aid = self.fixture()
        old = self.m.text_artifact(pid, aid)
        req = self.payload(pid, aid)
        receipt = self.m.save_text_revision(pid, req)
        self.assertEqual(receipt["engine_calls"], 0)
        self.assertTrue(self.m.save_text_revision(pid, req)["replayed"])
        new = self.m.text_artifact(pid, receipt["artifact_id"])
        self.assertEqual(new["pages"][0], old["pages"][0])
        self.assertEqual(new["pages"][2], old["pages"][2])
        self.assertEqual(new["pages"][1]["text"], req["text"])
        self.assertEqual(self.m.text_artifact(pid, aid)["pages"], old["pages"])
        p = self.m.get(pid)
        a = next(a for a in p["artifacts"] if a["artifact_id"] == receipt["artifact_id"])
        structure = json.loads((self.m.path(pid) / a["path"]).with_name("structure.json").read_text())
        self.assertEqual(structure["pages"][1]["text"], req["text"])
        self.assertIsNone(structure["pages"][1]["coordinates"])
        self.assertIn("错字", self.m.text_diff(pid, new["artifact_id"], aid)["diff"])
        self.assertEqual(digest(self.m.path(pid) / a["path"]), a["sha256"])

    def test_empty_nochange_continuous_conflict_restore(self):
        pid, aid = self.fixture()
        stale = self.payload(pid, aid)
        first = self.m.save_text_revision(pid, self.payload(pid, aid, ""))
        info = self.m.text_artifact(pid, first["artifact_id"])
        self.assertEqual(info["pages"][1]["text"], "")
        self.assertTrue(
            self.m.save_text_revision(pid, self.payload(pid, first["artifact_id"], ""))["no_change"]
        )
        with self.assertRaises(RevisionConflict):
            self.m.save_text_revision(pid, stale)
        second = self.m.save_text_revision(pid, self.payload(pid, first["artifact_id"], "连续保存"))
        req = self.payload(pid, second["artifact_id"])
        req.pop("locator")
        req.pop("text")
        req["restore_artifact_id"] = aid
        restored = self.m.save_text_revision(pid, req)
        self.assertNotEqual(restored["artifact_id"], aid)
        self.assertEqual(
            self.m.text_artifact(pid, restored["artifact_id"])["pages"],
            self.m.text_artifact(pid, aid)["pages"],
        )

    def test_failure_not_registered_and_invalid_mapping(self):
        pid, aid = self.fixture()
        before = self.m.get(pid)
        from nas_filetools.standalone.tasks import atomic

        def fail_registry(path, data):
            if path.name == "project.json":
                raise OSError("synthetic disk failure")
            return atomic(path, data)

        with patch("nas_filetools.standalone.tasks.atomic", side_effect=fail_registry):
            with self.assertRaises(OSError):
                self.m.save_text_revision(pid, self.payload(pid, aid))
        self.assertEqual(self.m.get(pid)["artifacts"], before["artifacts"])
        self.assertEqual(list((self.m.path(pid) / "content/revisions").iterdir()), [])
        with self.m.lock:
            p = self.m.get(pid)
            next(a for a in p["artifacts"] if a["artifact_id"] == aid)["pages"] = []
            self.m.save(self.m.path(pid), p)
        with self.assertRaisesRegex(ValueError, "没有逐页"):
            self.m.text_artifact(pid, aid)

    def test_http_conflict_security_and_safe_preview(self):
        pid, aid = self.fixture()
        info = self.request(f"/api/projects/{pid}/text/{aid}")
        self.assertEqual(len(info["pages"]), 3)
        from urllib.parse import quote

        selected = self.request(
            f"/api/projects/{pid}/text/{aid}?locator=" + quote(json.dumps(info["pages"][1]["locator"]))
        )
        self.assertEqual(len(selected["pages"]), 1)
        req = self.payload(pid, aid, "<script>alert(1)</script>\n\n**安全文字**")
        result = self.request(f"/api/projects/{pid}/text-revisions", "POST", req)
        a = next(a for a in self.m.get(pid)["artifacts"] if a["artifact_id"] == result["artifact_id"])
        raw = (self.m.path(pid) / a["pages"][1]["data"]).read_text()
        self.assertNotIn("<script>", raw)
        import urllib.error

        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(f"/api/projects/{pid}/text-revisions", "POST", self.payload(pid, aid))
        self.assertEqual(error.exception.code, 409)
        bad_hash = self.payload(pid, result["artifact_id"])
        bad_hash["parent_sha256"] = "0" * 64
        with self.assertRaises(RevisionConflict):
            self.m.save_text_revision(pid, bad_hash)
        bad_locator = self.payload(pid, result["artifact_id"])
        bad_locator["locator"] = {"kind": "block", "id": "unknown"}
        with self.assertRaisesRegex(ValueError, "未知稳定位置"):
            self.m.save_text_revision(pid, bad_locator)
        bad = self.payload(pid, result["artifact_id"])
        bad["path"] = "/etc/passwd"
        with self.assertRaises(urllib.error.HTTPError):
            self.request(f"/api/projects/{pid}/text-revisions", "POST", bad)
