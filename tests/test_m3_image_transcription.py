import argparse
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

SPEC = importlib.util.spec_from_file_location("m3_direct", Path(__file__).parents[1] / "scripts/m3_image_transcription.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture_image():
    stream = io.BytesIO()
    Image.new("RGB", (1819, 2573), "white").save(stream, format="PNG")
    image = stream.getvalue()
    return image, {"physical_page": 23, "image": "images/page-23.png", "width": 1819, "height": 2573,
                   "bytes": len(image), "sha256": M.sha(image), "mime": "image/png"}


def test_reproducible_distinct_sample():
    pages = M.sample_pages(2026100701)
    assert len(pages) == len(set(pages)) == 50
    assert 23 in pages and min(pages) >= 6 and max(pages) <= 169
    assert pages == M.sample_pages(2026100701)
    assert pages != M.sample_pages(2026100702)
    with pytest.raises(ValueError):
        M.sample_pages(0, 165)


def test_actual_serialized_image_preserves_pixels_and_bytes():
    image, record = fixture_image()
    body, sent = M.make_request(image, record)
    request = json.loads(body)
    assert sent == {"width": 1819, "height": 2573, "format": "PNG", "mime": "image/png", "bytes": len(image), "sha256": M.sha(image)}
    assert len(request["messages"]) == 1
    assert "system" not in request and "tools" not in request
    assert request["messages"][0]["content"][1]["text"] == M.PROMPT
    with pytest.raises(ValueError, match="SOURCE_IMAGE_CHANGED"):
        M.make_request(image + b"x", record)


def test_response_text_is_not_cleaned_and_truncation_is_preserved():
    response = {"content": [{"type": "text", "text": "  原始\n"}, {"type": "text", "text": "错字  "}], "stop_reason": "end_turn"}
    assert M.extract_response(response) == ("  原始\n错字  ", "succeeded")
    response["stop_reason"] = "max_tokens"
    assert M.extract_response(response)[1] == "truncated"
    assert M.extract_response({"content": [], "stop_reason": "end_turn"})[1] == "failed-empty-text"


def test_resume_preserves_existing_failed_or_interrupted_attempt(tmp_path):
    image, record = fixture_image()
    M.write_json(tmp_path / "manifest.json", {"images": [record]})
    attempt = tmp_path / "attempts/page-23/attempt-1"
    attempt.mkdir(parents=True)
    original = b'{"status":"started"}'
    (attempt / "receipt.json").write_bytes(original)
    with patch("sys.stdin", io.StringIO("synthetic-not-a-real-key\n")), patch("urllib.request.urlopen", side_effect=AssertionError("must not repeat")):
        M.run(argparse.Namespace(directory=tmp_path, limit=0, timeout=180))
    assert (attempt / "receipt.json").read_bytes() == original


def test_offline_bundle_safe_text_and_empty_human_state(tmp_path):
    image, record = fixture_image()
    experiment = tmp_path / "experiment"
    (experiment / "images").mkdir(parents=True)
    (experiment / record["image"]).write_bytes(image)
    M.write_json(experiment / "manifest.json", {"images": [record], "seed": 1, "source_pdf_sha256": "synthetic", "physical_pages": [23]})
    attempt = experiment / "attempts/page-23/attempt-1"
    attempt.mkdir(parents=True)
    dangerous = '</script><img src=x onerror=alert(1)>&\n'
    (attempt / "transcription.txt").write_text(dangerous)
    (attempt / "response.raw.json").write_text('{}')
    M.write_json(attempt / "receipt.json", {"status": "succeeded", "usage": {"input_tokens": 8, "output_tokens": 4}, "transcription_sha256": M.sha(dangerous.encode())})
    output, archive = tmp_path / "bundle", tmp_path / "bundle.zip"
    M.bundle(argparse.Namespace(directory=experiment, output=output, zip=archive))
    html = (output / "index.html").read_text()
    assert dangerous not in html and "\\u003c/script>" in html
    assert "{rating:'',notes:''}" in html
    assert (output / "transcriptions/page-23.txt").read_text() == dangerous
    summary = json.loads((output / "summary.json").read_text())
    assert summary["human_reviews"] == 0 and summary["accuracy"] == "not-measured"
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        M.bundle(argparse.Namespace(directory=experiment, output=output, zip=archive))


def test_bounded_explicit_retry_keeps_failed_response_and_all_costs(tmp_path):
    image, record = fixture_image()
    (tmp_path / "images").mkdir()
    (tmp_path / record["image"]).write_bytes(image)
    M.write_json(tmp_path / "manifest.json", {"images": [record], "seed": 1, "source_pdf_sha256": "synthetic", "physical_pages": [23]})
    first = tmp_path / "attempts/page-23/attempt-1"
    first.mkdir(parents=True)
    M.write_json(first / "receipt.json", {"status": "failed-http", "attempt": 1, "http_status": 500, "elapsed_seconds": 2})
    error = b'{"error":"synthetic service failure"}'
    (first / "response.raw.json").write_bytes(error)
    args = argparse.Namespace(directory=tmp_path, limit=0, timeout=180, retry_page=[23], retry_reason="bounded synthetic retry")
    with patch("sys.stdin", io.StringIO("synthetic-not-a-real-key\n")), patch("urllib.request.urlopen") as call:
        response = call.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = json.dumps({"model": "MiniMax-M3", "content": [{"type": "text", "text": "  合成原文\n"}], "stop_reason": "end_turn", "usage": {"input_tokens": 10}}).encode()
        M.run(args)
        assert call.call_count == 1
    assert (first / "response.raw.json").read_bytes() == error
    assert (first / "receipt.json").exists()
    assert "synthetic-not-a-real-key" not in (tmp_path / "attempts/page-23/attempt-2/request.json").read_text()
    with patch("sys.stdin", io.StringIO("synthetic-not-a-real-key\n")):
        with pytest.raises(ValueError, match="EXACTLY_ONE_PREVIOUS"):
            M.run(args)
    output, archive = tmp_path / "bundle", tmp_path / "bundle.zip"
    M.bundle(argparse.Namespace(directory=tmp_path, output=output, zip=archive))
    summary = json.loads((output / "summary.json").read_text())
    assert summary["requests"] == 2 and summary["retry_requests"] == 1
    assert summary["failed_attempts"] == 1 and summary["failed"] == 0
    assert summary["attempts_without_usage"] == 1
    assert (output / "responses/page-23-attempt-1.raw.json").read_bytes() == error


def test_audit_rejects_modified_response_and_excludes_private_text(tmp_path):
    image, record = fixture_image()
    (tmp_path / "images").mkdir()
    (tmp_path / record["image"]).write_bytes(image)
    M.write_json(tmp_path / "manifest.json", {"images": [record], "seed": 1, "count": 1, "dpi": 220, "renderer": "synthetic",
                 "prompt_sha256": M.sha(M.PROMPT.encode()), "source_pdf_sha256": "synthetic", "physical_pages": [23]})
    attempt = tmp_path / "attempts/page-23/attempt-1"
    attempt.mkdir(parents=True)
    body, submitted = M.make_request(image, record)
    (attempt / "request.json").write_bytes(body)
    raw = json.dumps({"content": [{"type": "text", "text": "private-synthetic-text"}], "stop_reason": "end_turn"}).encode()
    (attempt / "response.raw.json").write_bytes(raw)
    (attempt / "transcription.txt").write_bytes(b"private-synthetic-text")
    M.write_json(attempt / "receipt.json", {"physical_page": 23, "attempt": 1, "status": "succeeded", "http_status": 200,
                 "request_body_sha256": M.sha(body), "submitted": submitted, "source": record, "endpoint": M.ENDPOINT,
                 "response_sha256": M.sha(raw)})
    target = tmp_path / "audit.json"
    M.audit(argparse.Namespace(directory=tmp_path, output=target))
    assert "private-synthetic-text" not in target.read_text()
    (attempt / "response.raw.json").write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="RESPONSE_CHANGED"):
        M.audit(argparse.Namespace(directory=tmp_path, output=tmp_path / "audit-tampered.json"))
