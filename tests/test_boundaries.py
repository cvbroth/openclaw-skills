import zipfile
from dataclasses import replace

import fitz
import pytest
from docx import Document

from conftest import register
from nas_filetools.contracts import Fault, Limits
from nas_filetools.engines import Processor, probe
from nas_filetools.store import Store


def test_empty_text_cannot_succeed(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("\n\n", encoding="utf-8")
    info = probe(path, Limits())
    result = Processor(Limits()).process(path, info, {"mode": "full", "ocr": "auto"}, tmp_path)
    assert result["status"] == "FAILED" and result["failures"][0]["code"] == "NO_CONTENT"


def test_utf8_is_required(tmp_path):
    path = tmp_path / "gbk.txt"
    path.write_bytes("中文".encode("gbk"))
    with pytest.raises(UnicodeDecodeError):
        probe(path, Limits())


def test_encrypted_pdf_is_explicitly_rejected(tmp_path):
    path = tmp_path / "encrypted.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="private")
    with pytest.raises(Fault, match="INVALID_OR_ENCRYPTED_PDF"):
        probe(path, Limits())


def test_docx_expansion_and_member_paths_are_bounded(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as file:
        file.writestr("word/document.xml", "x" * 2000)
    with pytest.raises(Fault, match="EXPANDED_SIZE_LIMIT"):
        probe(path, replace(Limits(), max_docx_expanded_bytes=1000))
    path = tmp_path / "traversal.docx"
    with zipfile.ZipFile(path, "w") as file:
        file.writestr("word/document.xml", "xml")
        file.writestr("../escape", "x")
    with pytest.raises(Fault, match="INVALID_DOCX"):
        probe(path, Limits())


def test_image_only_docx_is_not_text_success(samples, tmp_path):
    document = Document()
    document.add_picture(str(samples / "printed.png"))
    path = tmp_path / "picture.docx"
    document.save(path)
    result = Processor(Limits()).process(path, probe(path, Limits()), {"mode": "full", "ocr": "auto"}, tmp_path)
    assert result["status"] == "FAILED" and result["assets"]
    assert result["segments"][0]["image_only"]


def test_limits_config_is_validated():
    for setting in [{"concurrency": 3}, {"engine_threads": 0}, {"worker_memory_mb": 1},
                    {"max_bytes": True}, {"offline": "yes"}, {"inspection_timeout_seconds": 61}]:
        with pytest.raises(Fault, match="INVALID_CONFIG"):
            Limits(**setting)


def test_job_quota_and_attachment_id_content_conflict(tmp_path, identity, samples):
    store = Store(tmp_path / "state", replace(Limits(), max_jobs_per_scope=1))
    register(store, identity, samples / "notes.md")
    store.submit(identity, "1" * 32, {"mode": "preview"})
    with pytest.raises(Fault, match="JOB_QUOTA"):
        store.submit(identity, "1" * 32, {"mode": "full"})
    (samples / "notes.md").write_text("Changed original", encoding="utf-8")
    with pytest.raises(Fault, match="ATTACHMENT_CHANGED"):
        register(store, identity, samples / "notes.md")


def test_source_and_artifact_access_cannot_be_substituted(store, identity, samples):
    register(store, identity, samples / "notes.md")
    job = store.submit(identity, "1" * 32, {"mode": "full"})
    # A queued job has no published artifact; arbitrary IDs must not become paths.
    with pytest.raises(Fault, match="NOT_READY"):
        store.read(identity, job["job_id"], {"artifact_id": "f" * 32})
    for value in ["../outside", "C:\\private.txt", "a" * 64]:
        with pytest.raises(Fault, match="INVALID_ID"):
            store.status(identity, value)
    assert not list(store.root.rglob("*outside*"))


def test_state_symlink_rejected(tmp_path):
    original = tmp_path / "preserve"
    original.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    try:
        (state / "tasks").symlink_to(original, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable on this Windows runner")
    with pytest.raises(Fault, match="UNSAFE_STATE_DIRECTORY"):
        Store(state, Limits())
    assert original.exists()


def test_expired_job_denied_but_original_snapshot_retained(store, identity, samples):
    register(store, identity, samples / "notes.md")
    job = store.submit(identity, "1" * 32, {"mode": "full"})
    with store.db() as db:
        db.execute("UPDATE jobs SET status='CANCELLED',expires=0 WHERE id=?", (job["job_id"],))
    with pytest.raises(Fault, match="NOT_FOUND"):
        store.status(identity, job["job_id"])
    store.cleanup()
    assert list((store.root / "originals").rglob("*.md"))
    assert (samples / "notes.md").is_file()


def test_docx_preview_uses_original_body_block_locations(samples):
    info = probe(samples / "ordered.docx", Limits())
    assert info["preview_coverage"] == [1, 2, 3]
    assert [p["paragraph"] for p in info["preview"]] == [1, 2, 3]
    assert [p["kind"] for p in info["preview"]] == ["paragraph", "table", "paragraph"]


def test_queued_task_has_empty_content_and_trusted_provenance(store, identity, samples):
    import json
    register(store, identity, samples / "notes.md")
    job = store.submit(identity, "1" * 32, {"mode": "full"})
    folder = store.task(job["job_id"])
    assert (folder / "content.md").read_text() == ""
    manifest = json.loads((folder / "sources.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "QUEUED" and manifest["segments"] == []
    assert manifest["attachment_id"] == "1" * 32 and manifest["original"]["filename"] == "notes.md"
    assert not manifest["coverage"]["full_document"]


def test_exclusive_snapshot_race_never_deletes_an_existing_original(store, identity, samples, monkeypatch):
    from pathlib import Path
    from nas_filetools.contracts import owner
    file = samples / "notes.md"
    target = store.original(owner(identity), "1" * 32, file.name)
    actual_open = Path.open
    def raced_open(path, mode="r", *args, **kwargs):
        if path == target and mode == "xb":
            with actual_open(path, "wb") as writer:
                writer.write(b"pre-existing original")
            raise FileExistsError("exclusive create lost race")
        return actual_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", raced_open)
    with pytest.raises(FileExistsError):
        register(store, identity, file)
    assert target.read_bytes() == b"pre-existing original"
    assert file.is_file()
