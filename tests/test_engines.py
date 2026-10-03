"""Opt-in real engine checks; these contain no OCR or ASR doubles."""
import os
from dataclasses import replace
from pathlib import Path

import pytest

from nas_filetools.contracts import Limits
from nas_filetools.engines import Processor, probe

pytestmark = [pytest.mark.engines, pytest.mark.skipif(os.environ.get("FILETOOLS_REAL_ENGINES") != "1",
                                                    reason="Set FILETOOLS_REAL_ENGINES=1 to run real engines")]


@pytest.mark.parametrize("name", ["scan.pdf", "mixed.pdf", "printed.png"])
def test_real_ocr(samples, tmp_path, name):
    info = probe(samples / name, Limits())
    result = Processor(Limits()).process(samples / name, info, {"mode": "full", "ocr": "auto"}, tmp_path)
    assert result["status"] == "SUCCEEDED", result["failures"]
    assert any("backup" in s["text"].lower() for s in result["segments"])
    if name == "mixed.pdf":
        assert [s["source"]["page"] for s in result["segments"]] == [1, 2, 3]
        assert [s["engine"] for s in result["segments"]] == ["pymupdf", "rapidocr", "rapidocr"]


def test_real_speech_and_time_range(tmp_path):
    sample = os.environ.get("FILETOOLS_AUDIO_SAMPLE")
    model = os.environ.get("FILETOOLS_WHISPER_MODEL")
    if not sample or not model:
        pytest.skip("Provide FILETOOLS_AUDIO_SAMPLE and an immutable FILETOOLS_WHISPER_MODEL snapshot")
    limits = replace(Limits(), whisper_model=model, model_cache=str(tmp_path / "cache"))
    info = probe(Path(sample), limits)
    result = Processor(limits).process(sample, info, {"mode": "full", "ocr": "auto", "language": "en"}, tmp_path)
    assert result["status"] == "SUCCEEDED", result["failures"]
    expected = os.environ.get("FILETOOLS_AUDIO_EXPECT", "backup")
    assert any(expected in s["text"].lower() for s in result["segments"])
    assert all(0 <= s["source"]["start"] < s["source"]["end"] <= info["duration"] + 0.1
               for s in result["segments"])
    assert result["coverage"]["full_document"]
    (tmp_path / "range").mkdir()
    end = min(info["duration"], 4)
    partial = Processor(limits).process(sample, info, {"mode": "range", "time_range": [0, end],
                                        "ocr": "auto", "language": "en"}, tmp_path / "range")
    assert not partial["coverage"]["full_document"]
    assert all(s["source"]["end"] <= end + 0.1 for s in partial["segments"])
