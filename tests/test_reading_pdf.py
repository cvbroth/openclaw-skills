"""Reader PDF, evidence-based content state and cancellable whole-range checks."""

import json
import subprocess
import sys
import time
import uuid
from unittest.mock import patch
import fitz
import pytest
from nas_filetools.artifact_project import digest, page_data, register_artifact
from nas_filetools.standalone.content_structure import parse_markdown
from nas_filetools.standalone.direct_source import collect
from test_template_exports import project as template_project, terminal


@pytest.fixture(name="project")
def fixture(tmp_path):
    yield from template_project.__wrapped__(tmp_path)


def historical(m, pid, aid, number=6, status="PARTIAL", code="QUALITY_FORMAT", stop="end_turn"):
    p = m.get(pid)
    a = next(a for a in p["artifacts"] if a["artifact_id"] == aid)
    v = next(v for v in a["pages"] if v["source_page"] == number)
    root = m.path(pid)
    data = json.loads((root / v["data"]).read_text().split("=", 1)[1].rstrip(";\n"))
    folder = root / f"diagnostics/synthetic-history-{number}"
    folder.mkdir(exist_ok=True)
    result = {"status": status, "text": data["text"], "error": {"code": code, "stage": "response_parse"}}
    (folder / "result.json").write_text(json.dumps(result))
    raw = {
        "stop_reason": stop,
        "content": [
            {
                "type": "text",
                "text": "<transcription_markdown>"
                + data["text"]
                + "</transcription_markdown><quality_json>{broken</quality_json>",
            }
        ],
    }
    (folder / "response.raw.json").write_text(json.dumps(raw))
    data["raw_path"] = str((folder / "result.json").relative_to(root))
    page_data(root, v["data"], data)
    v.update(error=True, data_sha256=digest(root / v["data"]))
    m.save(root, p)
    return root, a, folder


def test_quality_failure_has_independent_complete_body_and_revision(project):
    m, pid, aid = project
    root, a, folder = historical(m, pid, aid)
    before = {f: digest(f) for f in folder.glob("*.json")}
    source = collect(root, m.get(pid), a, [6])
    assert not source["issues"]
    assert "仅原图质量" in source["content_states"][0]["reason"]
    job = m.export_documents(pid, {"source_artifact_id": aid, "pages": "6", "formats": ["pdf"]})
    p, t = terminal(m, pid, job["task_id"])
    assert t["status"] == "SUCCEEDED", t.get("error")
    assert t["direct_report"]["renderer"]["pdf"]["name"] == "Chromium"
    assert not (root / "diagnostics/format" / t["task_id"] / "work/document.docx").exists()
    assert all(digest(f) == h for f, h in before.items())
    # Same nonempty body with truncated completion must stay blocked.
    raw = json.loads((folder / "response.raw.json").read_text())
    raw["stop_reason"] = "max_tokens"
    (folder / "response.raw.json").write_text(json.dumps(raw))
    assert collect(root, m.get(pid), a, [6])["issues"]
    with pytest.raises(ValueError, match="来源第6页"):
        m.export_documents(pid, {"source_artifact_id": aid, "pages": "6", "formats": ["pdf"]})
    # Authoritative manual replacement supersedes that historical error only for its own locator.
    info = m.text_artifact(pid, aid)
    revised = m.save_text_revision(
        pid,
        {
            "request_id": str(uuid.uuid4()),
            "parent_artifact_id": aid,
            "parent_sha256": info["sha256"],
            "head_id": info["head_id"],
            "head_sha256": info["head_sha256"],
            "locator": info["pages"][0]["locator"],
            "text": "# 人工修订\n\n已有正文明确修复。",
        },
    )
    p = m.get(pid)
    new = next(a for a in p["artifacts"] if a["artifact_id"] == revised["artifact_id"])
    assert not collect(root, p, new, [6])["issues"]
    assert collect(root, p, a, [6])["issues"]


@pytest.mark.parametrize("status,code", [("FAILED", "PROVIDER_ERROR"), ("PARTIAL", "TRANSCRIPTION_PARTIAL")])
def test_nonempty_failed_or_partial_body_is_not_success(project, status, code):
    m, pid, aid = project
    root, a, _ = historical(m, pid, aid, status=status, code=code)
    result = collect(root, m.get(pid), a, [6])
    assert result["issues"]
    with pytest.raises(ValueError, match="来源第6页"):
        m.export_documents(pid, {"source_artifact_id": aid, "pages": "6", "formats": ["pdf"]})


def test_ordinary_pipes_preserved_real_table_rejected(project):
    assert not parse_markdown("A | B\n\n绝对值 |x| 与普通竖线。")["diagnostics"]
    assert not parse_markdown("标题 | 原文\n---")["diagnostics"]
    assert any(
        d["code"] == "POSSIBLE_TABLE_PRESERVED_AS_TEXT"
        for d in parse_markdown("| 列1 | 列2 |\n| --- | --- |\n| A | B |")["diagnostics"]
    )
    m, pid, aid = project
    info = m.text_artifact(pid, aid)
    new = m.save_text_revision(
        pid,
        {
            "request_id": str(uuid.uuid4()),
            "parent_artifact_id": aid,
            "parent_sha256": info["sha256"],
            "head_id": info["head_id"],
            "head_sha256": info["head_sha256"],
            "locator": info["pages"][0]["locator"],
            "text": "普通 A | B 和 |x|。 **加粗** *斜体* ① 📖。",
        },
    )
    j = m.export_documents(pid, {"source_artifact_id": new["artifact_id"], "pages": "6", "formats": ["pdf"]})
    p, t = terminal(m, pid, j["task_id"])
    assert t["status"] == "SUCCEEDED", t.get("error")
    a = next(a for a in p["artifacts"] if a.get("task_id") == j["task_id"] and a.get("role") == "export")
    with fitz.open(m.path(pid) / a["path"]) as doc:
        assert "A | B" in doc[0].get_text() and "|x|" in doc[0].get_text()


def test_complete_precheck_lists_missing_partial_and_ambiguous_mapping(project):
    m, pid, aid = project
    historical(m, pid, aid, number=9, code="TRANSCRIPTION_PARTIAL")
    p = m.get(pid)
    a = next(a for a in p["artifacts"] if a["artifact_id"] == aid)
    next(v for v in a["pages"] if v["source_page"] == 8)["source_pages"] = [8, 9]
    m.save(m.path(pid), p)
    job = m.export_documents(
        pid, {"source_artifact_id": aid, "pages": "6-11", "formats": ["pdf"], "purpose": "check"}
    )
    p, t = terminal(m, pid, job["task_id"])
    assert t["status"] == "SUCCEEDED", t.get("error")
    assert not t["direct_report"]["ready"]
    assert {i["source_page"] for i in t["direct_report"]["issues"]} == {8, 9, 11}
    assert not any(a.get("task_id") == job["task_id"] for a in p["artifacts"])


def test_long_browser_task_progress_cancel_preserves_sibling(project):
    m, pid, _ = project
    root = m.path(pid)
    p = m.get(pid)
    views = []
    texts = []
    for n in range(1, 81):
        text = f"# 合成来源页 {n}\n\n中文 **加粗** *斜体* ①②。"
        texts.append(text)
        data = f"content/long-{n}.js"
        page_data(root, data, {"text": text})
        views.append({"source_page": n, "locator": {"kind": "block", "id": f"long-{n}"}, "data": data})
    (root / "content/long.md").write_text("\n\n".join(texts))
    a = register_artifact(
        root, p, name="长文档取消合成", format="markdown", path="content/long.md", pages=views
    )
    m.save(root, p)
    sibling = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    try:
        job = m.export_documents(
            pid,
            {"source_artifact_id": a["artifact_id"], "pages": "全部", "formats": ["pdf"], "purpose": "check"},
        )
        end = time.monotonic() + 30
        while time.monotonic() < end:
            t = m.task(m.get(pid), job["task_id"])
            if t.get("direct_progress", {}).get("completed", 0) >= 2:
                break
            time.sleep(0.05)
        assert 2 <= t["direct_progress"]["completed"] < 80
        m.cancel(pid, job["task_id"])
        p, t = terminal(m, pid, job["task_id"])
        assert t["status"] == "CANCELLED"
        assert sibling.poll() is None
        assert not any(a.get("task_id") == job["task_id"] for a in p["artifacts"])
    finally:
        sibling.kill()
        sibling.wait(timeout=5)


def test_missing_renderer_output_cannot_publish_success(project):
    m, pid, aid = project
    before = m.get(pid)
    original = m.run_child

    def incomplete(request, *args, **kwargs):
        if kwargs.get("module") == "nas_filetools.standalone.documents":
            return {"status": "SUCCEEDED"}  # A broken child protocol, with no PDF on disk.
        return original(request, *args, **kwargs)

    with patch.object(m, "run_child", side_effect=incomplete):
        job = m.export_documents(pid, {"source_artifact_id": aid, "pages": "6", "formats": ["pdf"]})
        p, t = terminal(m, pid, job["task_id"])
    assert t["status"] == "FAILED"
    # Failure diagnostics remain available; no deliverable may be published.
    existing = {a["artifact_id"] for a in before["artifacts"]}
    added = [a for a in p["artifacts"] if a["artifact_id"] not in existing]
    assert all(a.get("role") == "diagnostic" and a["format"] == "json" for a in added)
    assert [a for a in p["artifacts"] if a["artifact_id"] in existing] == before["artifacts"]
    assert not (m.path(pid) / "tasks" / job["task_id"] / "published" / "document.pdf").exists()
    assert all(digest(m.path(pid) / a["path"]) == a["sha256"] for a in before["artifacts"])
