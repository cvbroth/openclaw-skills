"""Template integrity and attachment isolation, with no private sample data."""
import json
import shutil

import pytest

from nas_filetools import document_templates as templates
from nas_filetools.document_entry import validate_request


def test_published_config_is_independent_and_validated():
    selected = templates.load_template("questions-zh-cn", "1.0.0")
    selected["parameters"]["body_pt"] = 99
    assert templates.load_template()["parameters"]["body_pt"] == 11.5
    assert selected["record"]["required_capabilities"]


@pytest.mark.parametrize("choice", [("../../input", "1.0.0"), ("questions-zh-cn", "../input"),
                                    ("unpublished", "1.0.0"), ("questions-zh-cn", "9.0.0")])
def test_unknown_versions_and_paths_are_rejected(choice):
    with pytest.raises(ValueError, match="TEMPLATE_"):
        templates.load_template(*choice)


def test_changed_published_bytes_fail_before_generation(tmp_path, monkeypatch):
    root = tmp_path / "templates"
    shutil.copytree(templates.TEMPLATE_ROOT, root)
    monkeypatch.setattr(templates, "TEMPLATE_ROOT", root)
    path = root / "published/questions-zh-cn/1.0.0.json"
    config = json.loads(path.read_bytes())
    config["parameters"]["body_pt"] = 12
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="VERSION_HASH_MISMATCH"):
        templates.load_template()


def test_unpublished_and_unsupported_capability_fail(tmp_path, monkeypatch):
    root = tmp_path / "templates"
    shutil.copytree(templates.TEMPLATE_ROOT, root)
    monkeypatch.setattr(templates, "TEMPLATE_ROOT", root)
    path = root / "catalog.json"
    catalog = json.loads(path.read_bytes())
    catalog["templates"][0]["status"] = "draft"
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="NOT_PUBLISHED"):
        templates.load_template()
    catalog["templates"][0]["status"] = "published"
    catalog["templates"][0]["required_capabilities"] += ["arbitrary-tables"]
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="CAPABILITY_UNAVAILABLE"):
        templates.load_template()


def test_attachment_cannot_supply_inline_production_parameters():
    request = {"raw_ocr": "原文", "document": {"schema": "reviewed-single-choice-v1", "source_pages": [1, 1],
               "title": "合成", "template": {"id": "questions-zh-cn", "version": "1.0.0", "body_pt": 99}}}
    with pytest.raises(ValueError, match="DOCUMENT_INPUT_SCHEMA"):
        validate_request(request)


@pytest.mark.parametrize("key,value", [("body_pt", float("nan")), ("minimum_start_lines", True),
                                      ("margin_cm", 0), ("option_hanging_cm", 2)])
def test_invalid_parameters_cannot_be_published(key, value):
    params = templates.load_template()["parameters"]
    params[key] = value
    with pytest.raises(ValueError, match="TEMPLATE_"):
        templates.validate_parameters(params)
