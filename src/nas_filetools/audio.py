"""Bounded audio chunks, durable checkpoints and global word timestamps."""
import gc
import math
import subprocess

from .catalog import atomic_json, digest_file
from .contracts import Fault


def ranges(wanted, seconds):
    start, end = wanted
    return [(start+i*seconds, min(end, start+(i+1)*seconds))
            for i in range(math.ceil((end-start)/seconds))]


def transcribe(processor, path, wanted, config, out, progress):
    import json
    import av
    import numpy as np
    limits = processor.limits
    checkpoint = out/"checkpoint.json"
    key = {"sha256": digest_file(path), "fingerprint": config.get("_checkpoint_fingerprint"),
           "config": config, "requested": wanted, "chunk_seconds": limits.audio_chunk_seconds}
    state = {"key": key, "chunks": []}
    if checkpoint.exists():
        if checkpoint.stat().st_size > limits.max_manifest_bytes:
            raise Fault("CHECKPOINT_LIMIT")
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state["key"] != key:
            raise Fault("CHECKPOINT_MISMATCH")
    if processor._transcriber is None:
        try:
            from faster_whisper import WhisperModel
            processor._transcriber = WhisperModel(limits.whisper_model, device="cpu", compute_type="int8",
                cpu_threads=limits.engine_threads, num_workers=1, download_root=limits.model_cache,
                local_files_only=limits.offline)
        except Exception:
            raise Fault("MODEL_UNAVAILABLE") from None
    planned = ranges(wanted, limits.audio_chunk_seconds)
    for index, (start, end) in enumerate(planned):
        old = next((c for c in state["chunks"] if c["start"] == start and c["end"] == end), None)
        if old and old["status"] == "DONE":
            progress(index+1, len(planned))
            continue
        chunk = {"start": start, "end": end, "status": "FAILED", "segments": []}
        offset = max(wanted[0], start-limits.audio_overlap_seconds)
        decode_end = min(wanted[1], end+limits.audio_overlap_seconds)
        wave = out/"selected.wav"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(offset), "-t", str(decode_end-offset),
                "-threads", str(limits.engine_threads), "-i", str(path), "-threads", str(limits.engine_threads),
                "-ac", "1", "-ar", "16000", "-f", "wav", str(wave)], capture_output=True,
                timeout=min(limits.stall_seconds, limits.timeout_seconds), check=True)
            if wave.stat().st_size > (decode_end-offset)*32000+65536:
                raise Fault("DECODE_SIZE_LIMIT")
            frames = []
            with av.open(str(wave)) as container:
                for frame in container.decode(audio=0):
                    frames.append(frame.to_ndarray().flatten())
            samples = np.concatenate(frames).astype(np.float32)/32768.0
            del frames
            values, _ = processor._transcriber.transcribe(samples, language=config.get("language"),
                beam_size=5, vad_filter=True, word_timestamps=True)
            for segment in values:
                words = getattr(segment, "words", None)
                # Assign overlapping words to exactly one primary interval by midpoint.
                if words:
                    selected = [w for w in words if start <= offset+(w.start+w.end)/2 < end]
                    if not selected:
                        continue
                    text = "".join(w.word for w in selected).strip()
                    first, last = selected[0].start, selected[-1].end
                else:
                    if not start <= offset+(segment.start+segment.end)/2 < end:
                        continue
                    text, first, last = segment.text.strip(), segment.start, segment.end
                if text:
                    chunk["segments"].append({"text": text, "source": {
                        "start": round(max(wanted[0], offset+first), 3),
                        "end": round(min(wanted[1], offset+last), 3)}})
                progress(index+min(0.99, segment.end/max(decode_end-offset, 1)), len(planned))
            del samples
            if not chunk["segments"]:
                raise Fault("NO_CONTENT")
            chunk["status"] = "DONE"
        except Exception as error:
            chunk["code"] = error.code if isinstance(error, Fault) else "AUDIO_CHUNK_FAILED"
        finally:
            wave.unlink(missing_ok=True)
            gc.collect()
        if old:
            state["chunks"].remove(old)
        state["chunks"].append(chunk)
        if len(json.dumps(state).encode()) > limits.max_manifest_bytes:
            raise Fault("CHECKPOINT_LIMIT")
        atomic_json(checkpoint, state)
        progress(index+1, len(planned))
    state["chunks"].sort(key=lambda c: c["start"])
    return state["chunks"]
