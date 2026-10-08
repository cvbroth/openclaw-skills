import importlib.util
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location(
    "m3_quality", Path(__file__).parents[1] / "scripts/m3_transcription_quality.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def quality(page=23):
    return {
        "physical_page": page,
        "overall_quality": "undetermined",
        "suggested_action": "undetermined",
        "visible_defects": [],
        "affected_area": "unknown",
        "evidence": [],
        "assessment_confidence": "low",
        "uncertainty_note": "synthetic",
    }


def test_selection_prefers_unseen_and_keeps_three_fixed_pages():
    old = list(range(6, 56)) + [136]
    pages = m.sample(2026100802, old)
    assert len(pages) == len(set(pages)) == 50
    assert set(pages) & set(old) == {12, 23, 136}
    assert pages == m.sample(2026100802, old)
    assert all(6 <= p <= 169 for p in pages)


def test_delimiters_preserve_text_including_whitespace_and_unsafe_html():
    text = "\n  A. synthetic </script>\nB. unchanged  \n"
    raw = (
        "<transcription_markdown>"
        + text
        + "</transcription_markdown>\n<quality_json>"
        + json.dumps(quality())
        + "</quality_json>"
    )
    assert m.parse(raw, 23) == (text, quality())
    with pytest.raises(ValueError, match="PHYSICAL_PAGE_MISMATCH"):
        m.parse(raw, 12)
    with pytest.raises(ValueError):
        m.parse(raw + " commentary", 23)
    with pytest.raises(ValueError):
        m.parse("empty", 23)


@pytest.mark.parametrize(
    "field,value",
    [
        ("overall_quality", "excellent"),
        ("evidence", ["a"] * 4),
        ("visible_defects", "blur"),
        ("assessment_confidence", 0.99),
    ],
)
def test_invalid_self_assessment_is_not_defaulted_to_good(field, value):
    q = quality()
    q[field] = value
    with pytest.raises((ValueError, TypeError)):
        m.parse(
            "<transcription_markdown>text</transcription_markdown><quality_json>"
            + json.dumps(q)
            + "</quality_json>",
            23,
        )


def test_missing_required_fields_rejected():
    with pytest.raises(ValueError):
        m.parse("<transcription_markdown>text</transcription_markdown><quality_json>{}</quality_json>", 23)


def test_bundle_preserves_raw_text_and_keeps_failed_page_unjudged(tmp_path):
    import argparse

    root = tmp_path / "experiment"
    (root / "images").mkdir(parents=True)
    image = b"synthetic-image-placeholder"
    (root / "images/page-23.png").write_bytes(image)
    source = {
        "physical_page": 23,
        "image": "images/page-23.png",
        "sha256": m.base.sha(image),
        "width": 40,
        "height": 20,
        "bytes": len(image),
    }
    m.base.write_json(root / "manifest.json", {"source_pdf_sha256": "synthetic", "images": [source]})
    attempt = root / "attempts/page-23/attempt-1"
    attempt.mkdir(parents=True)
    m.base.write_json(
        attempt / "receipt.json", {"status": "failed-http", "attempt": 1, "elapsed_seconds": 1, "usage": None}
    )
    (attempt / "response.raw.json").write_bytes(b'{"error":"synthetic"}')
    output = tmp_path / "delivery"
    m.bundle(argparse.Namespace(directory=root, output=output, zip=None))
    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["unjudged_pages"] == [23]
    assert summary["quality_pages"]["good"] == []
    assert summary["attempts_without_usage"] == 1
    assert summary["actual_account_cost"].startswith("unknown")
    assert "审核" not in (output / "index.html").read_text()
    assert json.loads((output / "structure.json").read_bytes())["pages"][0]["coordinates"] is None


def test_successful_bundle_escapes_script_and_keeps_transcription_exact(tmp_path):
    import argparse

    root = tmp_path / "experiment"
    (root / "images").mkdir(parents=True)
    (root / "images/page-23.png").write_bytes(b"placeholder")
    m.base.write_json(
        root / "manifest.json",
        {"source_pdf_sha256": "synthetic", "images": [{"physical_page": 23, "image": "images/page-23.png"}]},
    )
    attempt = root / "attempts/page-23/attempt-1"
    attempt.mkdir(parents=True)
    m.base.write_json(attempt / "receipt.json", {"status": "succeeded", "attempt": 1})
    text = "\n  A. </script><img src=x onerror=alert(1)>\nB. 不修改  \n"
    (attempt / "transcription.txt").write_text(
        "<transcription_markdown>"
        + text
        + "</transcription_markdown><quality_json>"
        + json.dumps(quality())
        + "</quality_json>"
    )
    output = tmp_path / "delivery"
    m.bundle(argparse.Namespace(directory=root, output=output, zip=None))
    assert (output / "attempts/page-23/attempt-1/transcription.md").read_text() == text
    html = (output / "index.html").read_text()
    assert text not in html and "\\u003c/script>" in html
    assert json.loads((output / "structure.json").read_bytes())["pages"][0]["text"] == text


def test_total_attempt_limit_rejects_before_credential_or_request(tmp_path, monkeypatch):
    import argparse

    m.base.write_json(
        tmp_path / "manifest.json", {"schema": "m3-transcription-quality-v1", "prompt": m.PROMPT}
    )
    for number in range(60):
        (tmp_path / "attempts" / f"page-{number}" / "attempt-1").mkdir(parents=True)
    monkeypatch.setattr(m.base, "run", lambda args: pytest.fail("must not call transport"))
    with pytest.raises(ValueError, match="TOTAL_CALL_LIMIT_60"):
        m.run(argparse.Namespace(directory=tmp_path, limit=1, phase="pilot"))


def test_invalid_quality_json_does_not_discard_independent_transcription(tmp_path):
    import argparse

    root = tmp_path / "experiment"
    (root / "images").mkdir(parents=True)
    (root / "images/page-23.png").write_bytes(b"placeholder")
    m.base.write_json(
        root / "manifest.json",
        {"source_pdf_sha256": "synthetic", "images": [{"physical_page": 23, "image": "images/page-23.png"}]},
    )
    attempt = root / "attempts/page-23/attempt-1"
    attempt.mkdir(parents=True)
    m.base.write_json(attempt / "receipt.json", {"status": "succeeded", "attempt": 1})
    text = "\n A. 保留原始文字  \n"
    raw_quality = '\n{"evidence": ["unescaped "quote""]}\n'
    (attempt / "transcription.txt").write_text(
        "<transcription_markdown>"
        + text
        + "</transcription_markdown><quality_json>"
        + raw_quality
        + "</quality_json>"
    )
    output = tmp_path / "delivery"
    m.bundle(argparse.Namespace(directory=root, output=output, zip=None))
    assert (output / "attempts/page-23/attempt-1/transcription.md").read_text() == text
    assert (output / "attempts/page-23/attempt-1/quality.raw.txt").read_text() == raw_quality
    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["successful_transcription_pages"] == 1
    assert summary["successful_transcription_and_quality"] == 0
    assert summary["quality_format_failed_pages"] == [23]
    row = json.loads((output / "structure.json").read_bytes())["pages"][0]
    assert row["quality"] is None and row["text"] == text and row["status"] == "failed-format"
