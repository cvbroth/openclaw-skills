"""Restart must not rewrite registered historical text to add presentation HTML."""

import json

from nas_filetools.artifact_project import create_project, digest, page_data, register_artifact
from nas_filetools.standalone.tasks import Projects
from test_standalone_http import configuration


def test_repeated_restart_preserves_legacy_text_resource_and_editability(tmp_path):
    store = tmp_path / "store"
    root = store / "projects" / "legacy"
    project = create_project(root, "合成历史文字", "synthetic")
    root.rename(root.parent / project["project_id"])
    root = root.parent / project["project_id"]
    text = "历史正文 ⸺ 📖\n\n第二段，保留原样。"
    (root / "content/legacy.md").write_text(text, encoding="utf-8")
    page_data(root, "content/legacy.js", {"text": text})
    artifact = register_artifact(
        root,
        project,
        name="历史稿",
        format="markdown",
        path="content/legacy.md",
        pages=[{"label": "整份文字", "locator": {"kind": "document"}, "data": "content/legacy.js"}],
    )
    (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    original = (root / "content/legacy.js").read_bytes()
    expected_hash = digest(root / "content/legacy.js")
    for _ in range(2):
        manager = Projects(store, configuration(), start_worker=False)
        try:
            current = manager.get(project["project_id"])
            view = next(a for a in current["artifacts"] if a["artifact_id"] == artifact["artifact_id"])[
                "pages"
            ][0]
            assert (root / "content/legacy.js").read_bytes() == original
            assert view["data_sha256"] == expected_hash
            assert (
                manager.text_artifact(project["project_id"], artifact["artifact_id"])["pages"][0]["text"]
                == text
            )
        finally:
            manager.close()
