import time
from dataclasses import replace

import pytest

from conftest import register
from nas_filetools.contracts import Fault, Limits, options, owner
from nas_filetools.engines import Processor, probe
from nas_filetools.service import dispatch
from nas_filetools.store import Store
from nas_filetools.worker import ServiceLock, Supervisor, bounded_probe


def completed(store, identity, path, config=None):
    register(store, identity, path)
    job = store.submit(identity, "1" * 32, config or {"mode": "full"})
    supervisor = Supervisor(store)
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            supervisor.tick()
            result = store.status(identity, job["job_id"])
            if result["status"] not in ("QUEUED", "RUNNING"):
                return result
            time.sleep(0.05)
        raise AssertionError("Worker did not finish")
    finally:
        supervisor.close()


def test_worker_source_pagination_find_and_dedup(store, identity, samples):
    job = completed(store, identity, samples / "text.pdf")
    assert job["status"] == "SUCCEEDED"
    assert job["coverage"]["full_document"]
    first = store.read(identity, job["job_id"], {"pages": [2, 2], "max_chars": 10})
    assert first["truncated"] and first["next_offset"] == 10
    second = store.read(identity, job["job_id"], {"pages": [2, 2], "offset": 10})
    assert first["evidence"][0]["source"] == {"page": 2}
    assert "Cedar" in first["evidence"][0]["text"] + second["evidence"][0]["text"]
    hit = store.read(identity, job["job_id"], {"keyword": "Cedar", "pages": [2, 2]}, find=True)
    assert hit["status"] == "MATCHES" and hit["evidence"][0]["source"] == {"page": 2}
    missing = store.read(identity, job["job_id"], {"keyword": "unmatched"}, find=True)
    assert missing["status"] == "NO_MATCH" and "not proof" in missing["caution"]
    again = store.submit(identity, "1" * 32, {"mode": "full"})
    assert again["reused"] and again["job_id"] == job["job_id"]


def test_docx_order_and_images(samples, tmp_path):
    result = Processor(Limits()).process(samples / "ordered.docx", probe(samples / "ordered.docx", Limits()),
                                        {"mode": "full", "ocr": "auto"}, tmp_path)
    texts = [s["text"] for s in result["segments"]]
    assert texts[0] == "Before the table"
    assert "Device" in texts[1] and "Cedar" in texts[1]
    assert texts[2] == "After the table" and texts[-1] == "After the image"
    assert result["assets"] and (tmp_path / result["assets"][0]["file"]).is_file()
    assert result["assets"][0]["source"] == {"paragraph": 4}
    assert result["status"] == "PARTIAL"  # picture-only block is retained, not claimed as recognized text


def test_partial_ocr_failure_does_not_claim_hybrid_complete(samples, tmp_path):
    class BrokenOCR:
        def __call__(self, *_):
            raise RuntimeError("unavailable")
    result = Processor(Limits(), ocr=BrokenOCR()).process(samples / "mixed.pdf",
        probe(samples / "mixed.pdf", Limits()), {"mode": "full", "ocr": "auto"}, tmp_path)
    assert result["status"] == "PARTIAL"
    assert [f["source"]["page"] for f in result["failures"]] == [2, 3]
    assert result["segments"][-1]["incomplete"]
    assert result["segments"][-1]["source"] == {"page": 3}
    assert not result["coverage"]["full_document"]


def test_blank_ocr_is_failed(samples, tmp_path):
    result = Processor(Limits(), ocr=lambda _: (None, 0)).process(samples / "scan.pdf",
        probe(samples / "scan.pdf", Limits()), {"mode": "full", "ocr": "auto"}, tmp_path)
    assert result["status"] == "FAILED" and result["failures"][0]["code"] == "NO_CONTENT"


@pytest.mark.parametrize("other", [
    {"user_id": "liang", "agent_id": "liang", "session_hash": "a" * 64},
    {"user_id": "chen", "agent_id": "chen", "session_hash": "b" * 64},
    {"user_id": "chen", "agent_id": "main", "session_hash": "a" * 64},
])
def test_scope_refuses_every_id_access(store, identity, samples, other):
    register(store, identity, samples / "notes.md")
    job = store.submit(identity, "1" * 32, {"mode": "full"})
    assert store.inspect(other)["attachments"] == []
    for action in [lambda: store.inspect(other, "1" * 32),
                   lambda: store.submit(other, "1" * 32, {"mode": "full"}),
                   lambda: store.status(other, job["job_id"]),
                   lambda: store.cancel(other, job["job_id"]),
                   lambda: store.read(other, job["job_id"], {}),
                   lambda: store.save_minutes(other, job["job_id"], "steal", [1])]:
        with pytest.raises(Fault, match="NOT_FOUND"):
            action()


def test_parameters_and_identity_fail_closed(store, identity):
    for params in [{"path": "/etc/passwd"}, {"user_id": "chen"}]:
        with pytest.raises(Fault):
            dispatch(store, identity, "inspect", params)
    with pytest.raises(Fault, match="FORBIDDEN"):
        owner({**identity, "user_id": "azl"})
    with pytest.raises(Fault):
        options({"mode": "range", "pages": [2, 1]}, {"kind": "pdf", "units": 2})
    with pytest.raises(Fault):
        options({"mode": "full", "pages": [1, 2]}, {"kind": "pdf", "units": 2})


def test_limits_and_bounded_preview(samples, tmp_path, identity):
    with pytest.raises(Fault, match="PAGE_LIMIT"):
        probe(samples / "text.pdf", replace(Limits(), max_pages=1))
    with pytest.raises(Fault, match="PIXEL_LIMIT"):
        probe(samples / "printed.png", replace(Limits(), max_image_pixels=100))
    with pytest.raises(Fault, match="SIZE_LIMIT"):
        register(Store(tmp_path / "tiny", replace(Limits(), max_receive_bytes=10, max_process_bytes=10)), identity, samples / "text.pdf")
    info = probe(samples / "mixed.pdf", replace(Limits(), preview_pages=1, large_pages=1))
    assert len(info["preview"]) == 1 and info["preview_coverage"] == [1]
    assert info["requires_explicit_scope"]
    bogus = samples / "file.exe"
    bogus.write_text("text")
    with pytest.raises(Fault, match="UNSUPPORTED_TYPE"):
        probe(bogus, Limits())


def test_preview_and_range_never_claim_full(store, identity, samples):
    job = completed(store, identity, samples / "text.pdf", {"mode": "range", "pages": [2, 2]})
    assert job["status"] == "SUCCEEDED" and not job["coverage"]["full_document"]
    assert job["coverage"]["requested"] == [2, 2]


def test_cancel_queued_and_running(store, identity, samples):
    register(store, identity, samples / "notes.md")
    queued = store.submit(identity, "1" * 32, {"mode": "preview"})
    assert store.cancel(identity, queued["job_id"])["status"] == "CANCELLED"
    running = store.submit(identity, "1" * 32, {"mode": "full"})
    supervisor = Supervisor(store)
    supervisor.tick()
    assert store.cancel(identity, running["job_id"])["cancel_requested"]
    supervisor.tick()
    assert store.status(identity, running["job_id"])["status"] == "CANCELLED"
    assert not supervisor.processes


def test_restart_marks_running_interrupted_and_resumes_queued(store, identity, samples):
    register(store, identity, samples / "notes.md")
    interrupted = store.submit(identity, "1" * 32, {"mode": "full"})
    queued = store.submit(identity, "1" * 32, {"mode": "preview"})
    with store.db() as db:
        db.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (interrupted["job_id"],))
    restarted = Store(store.root, store.limits)
    supervisor = Supervisor(restarted)
    assert restarted.status(identity, interrupted["job_id"])["status"] == "INTERRUPTED"
    assert restarted.status(identity, queued["job_id"])["status"] == "QUEUED"
    supervisor.tick()
    assert queued["job_id"] in supervisor.processes
    supervisor.close()


def test_timeout_terminates_worker(store, identity, samples):
    register(store, identity, samples / "notes.md")
    job = store.submit(identity, "1" * 32, {"mode": "full"})
    supervisor = Supervisor(store)
    supervisor.tick()
    process, _ = supervisor.processes[job["job_id"]]
    supervisor.processes[job["job_id"]] = process, time.monotonic() - store.limits.timeout_seconds - 1
    supervisor.tick()
    assert store.status(identity, job["job_id"])["status"] == "TIMED_OUT"
    assert not process.is_alive()


def test_cleanup_preserves_originals_and_active_jobs(store, identity, samples):
    result = completed(store, identity, samples / "notes.md")
    pending = store.submit(identity, "1" * 32, {"mode": "preview"})
    with store.db() as db:
        db.execute("UPDATE jobs SET expires=0")
    removed = store.cleanup()
    assert removed["removed_jobs"] == [result["job_id"]] and removed["originals_deleted"] == 0
    assert store.task(pending["job_id"]).exists()
    assert list((store.root / "agents" / "chen" / "snapshots").rglob("*.md"))
    assert (samples / "notes.md").exists()


def test_service_singleton_refuses_cleanup(tmp_path):
    first = ServiceLock(tmp_path)
    try:
        with pytest.raises(Fault, match="SERVICE_ALREADY_RUNNING"):
            ServiceLock(tmp_path)
    finally:
        first.close()


def test_minutes_are_separate_and_validated(store, identity, samples):
    job = completed(store, identity, samples / "notes.md")
    before = (store.task(job["job_id"]) / "content.md").read_bytes()
    minutes = store.save_minutes(identity, job["job_id"], "Summary based on segment 1", [1])
    assert store.save_minutes(identity, job["job_id"], "Summary based on segment 1", [1])["reused"]
    assert (store.task(job["job_id"]) / "content.md").read_bytes() == before
    read = store.read(identity, job["job_id"], {"artifact_id": minutes["artifact_id"]})
    assert read["artifact_kind"] == "minutes" and read["source_segments"] == [1]
    with pytest.raises(Fault):
        store.save_minutes(identity, job["job_id"], "hallucination", [9999])


def test_bounded_probe_in_child(samples, tmp_path):
    info = bounded_probe(samples / "text.pdf", Limits(), tmp_path)
    assert info["units"] == 2
    assert not list(tmp_path.glob("*.json"))


def test_output_limit_is_partial(samples, tmp_path):
    result = Processor(replace(Limits(), max_output_chars=100)).process(samples / "text.pdf",
        probe(samples / "text.pdf", Limits()), {"mode": "full", "ocr": "auto"}, tmp_path)
    assert result["status"] == "PARTIAL" and result["failures"][0]["code"] == "OUTPUT_LIMIT"


def test_no_files_are_executed_and_text_is_untrusted(store, identity, samples):
    result = completed(store, identity, samples / "notes.md")
    read = store.read(identity, result["job_id"], {})
    assert read["content_trust"] == "untrusted"
    assert "import private" in read["evidence"][-1]["text"]
    assert not (store.root / "index").exists()


def test_worker_retains_canonical_message_reference(store, identity, samples):
    import json
    file = samples / "text.pdf"
    info = {**probe(file, store.limits), "source_message_id": "qq-message-123"}
    store.register(identity, "1" * 32, file.name, file, info)
    job = completed(store, identity, file)
    manifest = json.loads((store.task(job["job_id"]) / "sources.json").read_text(encoding="utf-8"))
    assert manifest["original"]["message_id"] == "qq-message-123"
    assert manifest["attachment_id"] == "1" * 32
    assert job["status"] == "SUCCEEDED"
