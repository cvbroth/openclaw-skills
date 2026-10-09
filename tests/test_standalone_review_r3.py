"""Synthetic Markdown, declarative template and portable-export regressions."""

import copy
import json
import pytest
from nas_filetools.standalone.content_structure import parse_markdown, reading_html, items
from nas_filetools.standalone.template_library import TemplateLibrary
from nas_filetools.standalone.export_policy import exportable, windows_safe
from nas_filetools.standalone.naming import decorate


def test_markdown_structure_and_literal_symbols():
    text = "# 一级\n\n## 二级\n\n### 三级\n\n普通 **粗体** 与 *斜体* 和 \\*文字\\*。\n同段换行\n\n- 选项甲\n- 选项乙\n\n3. 保留三\n7. 保留七\n"
    m = parse_markdown(text, {"artifact_id": "fixed"})
    assert [b["style"] for b in m["blocks"][:3]] == ["Heading 1", "Heading 2", "Heading 3"]
    p = m["blocks"][3]
    assert "**" not in p["text"] and "*文字*" in p["text"] and "\n同段换行" in p["text"]
    assert any(r.get("bold") for r in p["runs"]) and any(r.get("italic") for r in p["runs"])
    assert m["blocks"][-2]["text"].startswith("3.") and m["blocks"][-1]["text"].startswith("7.")
    assert len({b["id"] for b in m["blocks"]}) == len(m["blocks"])
    assert m == parse_markdown(text, {"artifact_id": "fixed"})
    assert all(b["source_lines"] for b in m["blocks"])
    assert items(m)[3][1].runs == p["runs"]


def test_untrusted_html_and_unsupported_content_preserved():
    m = parse_markdown(
        "<img src=x onerror=alert(1)>\n\n![图](private.png)\n\n|甲|乙|\n|--|--|\n\n```\n**有意源码**\n```"
    )
    rendered = reading_html(m)
    assert "<img" not in rendered and "&lt;img" in rendered
    assert "**有意源码**" in rendered
    assert {
        "IMAGE_REFERENCE_NOT_RENDERED",
        "POSSIBLE_TABLE_PRESERVED_AS_TEXT",
        "LITERAL_BLOCK_PRESERVED",
    } <= {d["code"] for d in m["diagnostics"]}


def test_template_version_fields_font_and_immutability(tmp_path):
    lib = TemplateLibrary(tmp_path / "library")
    loaded = lib.load("questions-zh-cn", "1.0.0")
    before = lib.path(loaded["record"]).read_bytes()
    d = loaded["document"]
    d.update(id="test-template", name="合成配置")
    saved = lib.save(d)
    assert saved["status"] == "drafts"
    with pytest.raises(ValueError, match="already exists"):
        lib.save(d)
    with pytest.raises(ValueError, match="preview-only"):
        lib.load(d["id"], d["version"])
    for field, value in [
        ("body_pt", 200),
        ("page_numbers", "yes"),
        ("font_family", "missing-font"),
        ("script", "print(1)"),
    ]:
        broken = copy.deepcopy(d)
        broken["parameters"][field] = value
        with pytest.raises(ValueError):
            lib.validate(broken)
    with pytest.raises(ValueError, match="fixed synthetic"):
        lib.publish(d["id"], d["version"], {"tasks": []})
    assert lib.path(loaded["record"]).read_bytes() == before
    assert json.loads(lib.path(saved).read_text())["parameters"] == d["parameters"]


def test_export_excludes_profiles_locks_and_windows_unsafe_paths():
    from pathlib import Path

    for p in [
        "diagnostics/lo-profile/user/registrymodifications.xcu",
        "a/.lock",
        "a/~$document.docx",
        "a/test.tmp",
        "a/__pycache__/x.pyc",
    ]:
        assert not exportable(Path(p))
    assert exportable(Path("outputs/document.docx"))
    for p in ["a/CON.txt", "a/name:bad", "../escape", "a/end."]:
        assert not windows_safe(Path(p))
    assert windows_safe(Path("review/中文评论.json"))


def test_naming_changes_only_presentation():
    p = {
        "name": "示例.pdf",
        "source_artifact_id": "s",
        "tasks": [],
        "artifacts": [
            {
                "artifact_id": "s",
                "format": "pdf",
                "path": "sources/document.pdf",
                "version": "1",
                "sha256": "x",
            },
            {
                "artifact_id": "a",
                "format": "docx",
                "path": "outputs/document.docx",
                "version": "2",
                "sha256": "y",
                "content_nature": "markdown-basic",
            },
        ],
    }
    decorate(p)
    old = copy.deepcopy(p)
    p["name"] = "新名称"
    decorate(p)
    for a, b in zip(old["artifacts"], p["artifacts"]):
        assert all(a[k] == b[k] for k in ["artifact_id", "path", "version", "sha256"])
        assert b["download_name"].startswith("新名称_")
    assert "未核对" in p["artifacts"][1]["display_name"]


def test_actual_markdown_docx_pdf_and_page_number_switch(tmp_path):
    import fitz
    from docx import Document
    from nas_filetools.standalone.documents import generate
    from nas_filetools.document_sample import document_paragraphs

    lib = TemplateLibrary(tmp_path / "library")
    td = lib.load("questions-zh-cn", "1.0.0")
    td["parameters"]["page_numbers"] = False
    out = tmp_path / "out"
    out.mkdir()
    generate(
        {
            "output": str(out),
            "template_data": td,
            "title": "合成排版测试",
            "source_artifact_id": "synthetic",
            "source_sha256": "fixed",
            "pages": [
                {
                    "physical_page": 1,
                    "text": "# 一级标题\n\n这是 **粗体** 和 *斜体* 与 \\*文字\\*。\n下一行\n\n3. 第三项\n7. 第七项\n\n- 无序列表\n",
                }
            ],
        }
    )
    d = Document(out / "document.docx")
    ps = document_paragraphs(d)
    assert any(p.style.name == "Heading 1" and p.text == "一级标题" for p in ps)
    assert any(r.bold and r.text == "粗体" for p in ps for r in p.runs)
    assert any(r.italic and r.text == "斜体" for p in ps for r in p.runs)
    alltext = "\n".join(p.text for p in ps)
    assert "**粗体**" not in alltext and "*文字*" in alltext
    assert "3. 第三项" in alltext and "7. 第七项" in alltext
    assert not any(p.text for p in d.sections[0].footer.paragraphs)
    with fitz.open(out / "document.pdf") as pdf:
        text = "".join(p.get_text() for p in pdf)
        assert "**" not in text and "文档第" not in text
    assert json.loads((out / "content-structure.json").read_text())["source_artifact_id"] == "synthetic"


def test_inline_format_survives_flow_slicing():
    from nas_filetools.standalone.content_structure import RichText

    r = RichText(
        [
            {"text": "开头", "bold": False},
            {"text": "粗体中段", "bold": True},
            {"text": "尾部", "italic": True},
        ]
    )
    cut = r[3:7]
    assert str(cut) == "体中段尾"
    assert cut.runs[0]["bold"] and cut.runs[-1]["italic"]
    assert "<b>" in cut.safe_html and "<i>" in cut.safe_html


def test_installed_font_without_required_glyphs_is_not_substituted(tmp_path):
    from nas_filetools.standalone.documents import generate

    lib = TemplateLibrary(tmp_path / "library")
    td = lib.load("questions-zh-cn", "1.0.0")
    if "DejaVu Sans" not in lib.fonts:
        pytest.skip("test requires installed non-CJK font")
    td["font"] = lib.fonts["DejaVu Sans"]
    td["parameters"]["font_family"] = "DejaVu Sans"
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="FONT_MISSING_GLYPHS"):
        generate(
            {
                "output": str(out),
                "template_data": td,
                "title": "中文合成",
                "pages": [{"physical_page": 1, "text": "不允许静默换字体。"}],
            }
        )
    assert not (out / "document.docx").exists()


def test_changed_view_cannot_replace_registered_markdown(tmp_path):
    from test_standalone_http import configuration
    from nas_filetools.standalone.tasks import Projects
    from nas_filetools.artifact_project import (
        create_project,
        register_artifact,
        page_data,
        emit_viewer,
        digest,
    )

    manager = Projects(tmp_path / "store", configuration(), start_worker=False)
    root = manager.root / "projects" / "temporary"
    p = create_project(root, "合成来源", "synthetic")
    target = manager.root / "projects" / p["project_id"]
    root.rename(target)
    root = target
    (root / "content/content.md").write_text("原始合成文字")
    page_data(root, "content/view.js", {"text": "原始合成文字"})
    a = register_artifact(
        root,
        p,
        name="合成",
        format="markdown",
        path="content/content.md",
        pages=[{"locator": {"kind": "block", "id": "fixed"}, "data": "content/view.js"}],
    )
    p["source_artifact_id"] = a["artifact_id"]
    p["tasks"] = []
    emit_viewer(root, p)
    manager.save(root, p)
    before = digest(root / a["path"])
    job = manager.format_artifact(
        p["project_id"], a["artifact_id"], {"id": "questions-zh-cn", "version": "1.0.0"}
    )
    page_data(root, "content/view.js", {"text": "悄悄替换的文字"})
    try:
        with pytest.raises(ValueError, match="SOURCE_VIEW_HASH_CHANGED"):
            manager.execute_format(p["project_id"], job["task_id"])
        assert digest(root / a["path"]) == before
        assert not list((root / "outputs").glob("*.docx"))
    finally:
        manager.close()


def test_portable_aliases_keep_registered_identity_and_handle_collisions():
    from nas_filetools.standalone.export_policy import portable_manifest

    p = {
        "name": "很长的中文项目名称" * 12,
        "source_artifact_id": "source",
        "tasks": [],
        "artifacts": [
            {
                "artifact_id": "unique-a",
                "format": "docx",
                "path": "outputs/a.docx",
                "version": "1",
                "sha256": "same",
            },
            {
                "artifact_id": "unique-b",
                "format": "docx",
                "path": "outputs/b.docx",
                "version": "1",
                "sha256": "same",
            },
        ],
    }
    decorate(p)
    before = copy.deepcopy(p)
    portable, aliases = portable_manifest(p)
    assert p == before
    assert len({x[1] for x in aliases}) == 2
    for a, b in zip(p["artifacts"], portable["artifacts"]):
        assert (a["artifact_id"], a["path"], a["sha256"]) == (b["artifact_id"], b["path"], b["sha256"])
        assert len(b["download_path"].split("/")[-1].encode()) < 255
        assert b["download_path"].endswith(".docx")
