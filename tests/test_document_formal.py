"""Source visibility is presentation only; mixed structures remain auditable."""
import json
from pathlib import Path

import fitz
from docx import Document

from nas_filetools.document_layout_checks import check_layout
from nas_filetools.document_sample import (document_paragraphs, paragraphs, structure_ocr,
                                          validate_pair, write_docx, write_pdf)
from nas_filetools.document_templates import load_template, validate_parameters


def test_hidden_sources_preserve_question_groups_audit_and_old_version(tmp_path):
    raw = "## Page 73\n1.短题干。\nA.完整选项\nB.完整选项\nC.完整选项\nD.完整选项\n2.后一题。\nA.甲\nB.乙\nC.丙\nD.丁"
    model = structure_ocr(raw, (73, 73))
    old = load_template()["parameters"]
    hidden = {**old, "show_source_labels": False}
    shown_items = paragraphs(model, "正式题册", old)
    items = paragraphs(model, "正式题册", hidden)
    assert items == [item for item in shown_items if item[0] != "Source"]
    assert model["source_sha256"] and model["blocks"][0]["fragments"][0]["page"] == 73
    font = tmp_path / "font.ttf"
    font.write_bytes(fitz.Font("cjk").buffer)
    write_docx(tmp_path / "formal.docx", items, font, hidden)
    write_pdf(tmp_path / "formal.pdf", items, font, hidden)
    validate_pair(tmp_path / "formal.docx", tmp_path / "formal.pdf", items, hidden)
    check = check_layout(tmp_path / "formal.pdf", items, font, hidden)
    assert check["passed"], check["failures"]
    assert len(check["questions"]) == 2
    assert all(q["source_page"] is None for q in check["questions"])
    doc = Document(tmp_path / "formal.docx")
    assert len(doc.tables) == 2
    assert not any(p.style.name == "Source" for p in document_paragraphs(doc))
    assert [(p.style.name, p.text) for p in document_paragraphs(doc)] == items
    assert load_template()["parameters"]["show_source_labels"] is True


def test_mixed_structure_reset_material_and_inline_options_are_independent():
    raw = ("## Page 73\n单项选择题\n8.保留这题。\nA.甲B.乙\nC.丙D.丁\n"
           "多项选择题\n1，保留多选。\nA.甲\nB.乙\nC.丙\nD.丁\n"
           "三、材料分析题\n1.结合材料回答问题：\n材料1\n原始材料。\n"
           "摘自原始资料\n（1）原始问题？")
    model = structure_ocr(raw, (73, 73), mixed=True)
    questions = [b for b in model["blocks"] if b["kind"] == "question"]
    assert [b["number"] for b in questions] == [8, 1, 1]
    assert [b["question_type"] for b in questions] == ["choice", "multiple-choice", "analysis"]
    assert [p["label"] for p in questions[0]["parts"] if p["kind"] == "option"] == list("ABCD")
    assert not model["issues"]
    assert any(r.get("inline_part") == 1 for r in questions[0]["fragments"])
    assert questions[-1]["parts"][-1]["text"] == "（1）原始问题？"


def test_draft_config_loads_without_mutating_published_parameters():
    path = Path(__file__).resolve().parents[1] / "src/nas_filetools/templates/drafts/questions-zh-cn/1.1.0.json"
    config = validate_parameters(json.loads(path.read_text())["parameters"])
    assert config["show_source_labels"] is False
    assert load_template("questions-zh-cn", "1.0.0")["parameters"]["show_source_labels"] is True


def test_hidden_word_does_not_merge_all_short_question_rows(tmp_path):
    import os
    import shutil
    import subprocess

    import pytest

    if shutil.which("libreoffice") is None:
        pytest.skip("independent native Word renderer unavailable")
    font = tmp_path / "font.ttf"
    font.write_bytes(fitz.Font("cjk").buffer)
    config = {**load_template()["parameters"], "show_source_labels": False}
    items = [("Title", "合成隐藏来源分页边界")]
    for number in range(1, 15):
        items += [("Question", f"{number}. 不按题号硬编码分页的短题。")]
        items += [("Option", f"{label}. 保留一个完整的选项。") for label in "ABCD"]
    items += [("Question", "15. " + "长题自然跨页，不与所有后续段落连续绑定。" * 180)]
    items += [("Option", f"{label}. 完整选项。") for label in "ABCD"]
    path = tmp_path / "hidden.docx"
    write_docx(path, items, font, config)
    output = tmp_path / "rendered"
    output.mkdir()
    subprocess.run(["libreoffice", "-env:UserInstallation=" + (tmp_path / "profile").as_uri(),
                    "--headless", "--convert-to", "pdf", "--outdir", str(output), str(path)],
                   check=True, capture_output=True, timeout=120,
                   env={**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache"), "GSETTINGS_BACKEND": "memory"})
    validate_pair(path, output / "hidden.pdf", items, config)
    evidence = check_layout(output / "hidden.pdf", items, font, config)
    assert evidence["passed"], evidence["failures"]
    assert len(evidence["questions"]) == 15
    assert len(evidence["questions"][-1]["pages"]) > 1
    # Adjacent tables must not become a single giant indivisible layout unit.
    from nas_filetools.document_sample import StoryLayout
    assert all(p["bottom_blank_pt"] < StoryLayout(font, config).short_limit
               for p in evidence["pages"][:-1])
