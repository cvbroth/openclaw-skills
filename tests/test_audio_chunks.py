"""Generated wave + real FFmpeg decoding, injected ASR; NOT real speech recognition."""
import json
import wave
from dataclasses import replace
from types import SimpleNamespace

import pytest

from nas_filetools.audio import ranges, transcribe
from nas_filetools.contracts import Fault, Limits
from nas_filetools.engines import Processor


def fixture_wave(path, seconds=24):
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b"\0\0"*16000*seconds)


def test_generated_four_hour_plan_has_no_gaps_and_bounded_chunks():
    planned = ranges([0, 4*3600], 600)
    assert len(planned) == 24 and planned[0] == (0, 600) and planned[-1] == (13800, 14400)
    assert all(a[1] == b[0] for a, b in zip(planned, planned[1:]))
    assert ranges([300, 1501], 600) == [(300, 900), (900, 1500), (1500, 1501)]


def test_checkpoint_resume_global_timestamps_overlap_and_partial_failure(tmp_path):
    file = tmp_path/"generated.wav"
    fixture_wave(file)
    class ASR:
        calls = 0
        fail = True
        def transcribe(self, samples, **kwargs):
            self.calls += 1
            if self.calls == 2 and self.fail:
                raise RuntimeError("simulated engine failure")
            duration = len(samples)/16000
            words = [SimpleNamespace(start=s, end=min(s+0.4, duration), word=f" {s}")
                     for s in range(int(duration))]
            return [SimpleNamespace(start=0, end=duration, text="generated", words=words)], None
    engine = ASR()
    limits = replace(Limits(), audio_chunk_seconds=10, audio_overlap_seconds=2)
    processor = Processor(limits, transcriber=engine)
    out = tmp_path/"job"
    out.mkdir()
    config = {"mode": "full", "language": "en", "_checkpoint_fingerprint": "test"}
    chunks = transcribe(processor, file, [0, 24], config, out, lambda *_: None)
    assert [c["status"] for c in chunks] == ["DONE", "FAILED", "DONE"]
    assert chunks[1]["start"] == 10 and chunks[1]["end"] == 20
    assert len(json.loads((out/"checkpoint.json").read_text())["chunks"]) == 3
    assert not (out/"selected.wav").exists()
    # Resume processes only the failed block; completed checkpoints survive interruption.
    engine.fail = False
    resumed = transcribe(processor, file, [0, 24], config, out, lambda *_: None)
    assert engine.calls == 4 and all(c["status"] == "DONE" for c in resumed)
    for chunk in resumed:
        for segment in chunk["segments"]:
            midpoint = sum(segment["source"].values())/2
            assert chunk["start"] <= midpoint <= chunk["end"]
    assert resumed[-1]["segments"][0]["source"]["start"] == 20
    with pytest.raises(Fault, match="CHECKPOINT_MISMATCH"):
        transcribe(processor, file, [0, 24], {**config, "language": "zh"}, out, lambda *_: None)


def test_no_speech_is_not_success(tmp_path):
    file = tmp_path/"generated.wav"
    fixture_wave(file, 2)
    class Empty:
        def transcribe(self, *_args, **_kwargs):
            return [], None
    result = Processor(Limits(), transcriber=Empty()).process(file,
        {"kind": "audio", "duration": 2, "units": 1, "warnings": []}, {"mode": "full"}, tmp_path)
    assert result["status"] == "FAILED" and result["failures"][0]["code"] == "NO_CONTENT"
