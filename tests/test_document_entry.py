"""Explicit scope and stable preinstalled entry; synthetic inputs only."""
import json
from pathlib import Path

import pytest

from nas_filetools.document_entry import generate_registered_input, prepare_registered_ocr


@pytest.mark.parametrize("spec", [{}, {"schema": "reviewed-single-choice-v1", "source_pages": [1, True],
                                     "title": "边界"},
                                  {"schema": "reviewed-single-choice-v1", "source_pages": [9, 2],
                                   "title": "边界"}])
def test_missing_or_invalid_scope_writes_nothing(tmp_path, monkeypatch, spec):
    incoming = tmp_path / "input.json"
    incoming.write_text(json.dumps({"raw_ocr": "原文", "document": spec}))
    monkeypatch.setenv("FILETOOLS_INPUT", str(incoming))
    output = tmp_path / "out"
    output.mkdir()
    monkeypatch.chdir(output)
    with pytest.raises(ValueError, match="EXPLICIT_SCOPE_REQUIRED"):
        generate_registered_input()
    assert list(Path.cwd().iterdir()) == []


def test_package_arbitrary_source_pages_retains_exact_ocr(tmp_path, monkeypatch):
    raw = "## Page 73\n1. 合成题干？\nA. 甲\nB. 乙\nC. 丙\nD. 丁\n"
    incoming = tmp_path / "ocr.md"
    incoming.write_bytes(raw.encode("utf-8"))
    monkeypatch.setenv("FILETOOLS_INPUT", str(incoming))
    output = tmp_path / "out"
    output.mkdir()
    monkeypatch.chdir(output)
    prepare_registered_ocr({"schema": "reviewed-single-choice-v1", "source_pages": [73, 73], "title": "合成",
                            "template": {"id": "questions-zh-cn", "version": "1.0.0"}})
    request = json.loads(Path("reviewed-input.json").read_bytes())
    assert request["raw_ocr"] == raw
    assert incoming.read_bytes() == raw.encode("utf-8")
    assert request["document"]["source_pages"] == [73, 73]


def test_valid_document_metadata_without_ocr_fails_before_generation(tmp_path, monkeypatch):
    request = {"document": {"schema": "reviewed-single-choice-v1", "source_pages": [1, 1],
                            "title": "合成烟测", "template": {"id": "questions-zh-cn", "version": "1.0.0"}},
               "margin_evidence": [], "reviewed_edits": [], "review_notes": []}
    incoming = tmp_path / "input.json"
    incoming.write_text(json.dumps(request))
    monkeypatch.setenv("FILETOOLS_INPUT", str(incoming))
    output = tmp_path / "out"
    output.mkdir()
    monkeypatch.chdir(output)
    with pytest.raises(ValueError, match="DOCUMENT_INPUT_SCHEMA_OR_EXPLICIT_SCOPE_REQUIRED"):
        generate_registered_input()
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("kind", ["多项选择题", "三、材料分析题"])
def test_production_single_choice_cannot_silently_process_other_types(kind):
    from nas_filetools.document_entry import validate_request
    request = {"raw_ocr": "## Page 73\n" + kind + "\n1.原始题干。",
               "document": {"schema": "reviewed-single-choice-v1", "source_pages": [73, 73],
                            "title": "合成", "template": {"id": "questions-zh-cn", "version": "1.0.0"}}}
    with pytest.raises(ValueError, match="UNSUPPORTED_QUESTION_TYPE"):
        validate_request(request)
    request["raw_ocr"] = "## Page 1\n" + kind + "\n## Page 73\n1.单选范围。"
    assert validate_request(request) == ([73, 73], "合成")
