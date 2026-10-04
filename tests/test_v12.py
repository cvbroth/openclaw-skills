"""Real shared-filesystem/core/CLI/script checks. Docker and channel transports are separate acceptance."""
import json
import subprocess
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from nas_filetools.catalog import digest_file
from nas_filetools.contracts import Fault, Limits
from nas_filetools.management import register_source, readable_text
from nas_filetools.service import dispatch
from nas_filetools.shared_workspace import WorkspaceHub, WorkspaceSupervisor, mapped_store, management_call


@pytest.fixture
def mapped(tmp_path):
    profiles = {}
    for agent in ("main", "chen"):
        workspace = tmp_path/agent
        workspace.mkdir()
        profiles[agent] = {"workspace": str(workspace), "service_root": str(workspace/"filetools")}
    limits = replace(Limits(), enabled_agents=("main", "chen"), script_isolation="development")
    hub = WorkspaceHub(tmp_path/"control", limits, profiles)
    config = tmp_path/"management.json"
    config.write_text(json.dumps({"limits": limits.dict(), "workspaces": profiles}))
    return hub, profiles, config


def finish(hub, identity, job):
    supervisor = WorkspaceSupervisor(hub)
    try:
        for _ in range(800):
            supervisor.tick()
            result = dispatch(hub, identity, "status", {"job_id": job["job_id"]})
            if result["status"] not in ("QUEUED", "RUNNING"):
                return result
            time.sleep(0.025)
        raise AssertionError("job timeout")
    finally:
        supervisor.close()


def source(mapped, identity, name="notes.txt", text="Cedar evidence"):
    hub, profiles, _ = mapped
    file = Path(profiles[identity["agent_id"]]["workspace"])/name
    file.write_text(text, encoding="utf-8")
    store = mapped_store(profiles[identity["agent_id"]], identity["agent_id"], hub.limits, "gateway")
    return store, file, register_source(store, identity, {"source_path": name})


def test_real_workspace_cli_snapshot_dedup_and_agent_separation(mapped, identity):
    hub, profiles, configuration = mapped
    store, file, result = source(mapped, identity)
    assert (file.parent/"filetools"/"registry.sqlite").is_file()
    assert not (file.parent/"filetools"/"agents"/"chen").exists()
    same = register_source(store, identity, {"source_path": file.name})
    assert same["attachment_id"] == result["attachment_id"] and same["reused"]
    different_event = register_source(store, identity, {"source_path": file.name, "request_id": "2"*32})
    assert different_event["file_id"] == result["file_id"]
    incoming = {"identity": identity, "operation": "register", "params": {"source_path": file.name}}
    cli = Path(__file__).parents[1]/"scripts"/"filetools_manage.py"
    completed = subprocess.run([sys.executable, "-I", "-S", str(cli), "--config", str(configuration)],
        input=json.dumps(incoming), text=True, capture_output=True, check=True)
    assert json.loads(completed.stdout)["file_id"] == result["file_id"]
    main = {**identity, "agent_id": "main"}
    _, _, separate = source(mapped, main)
    assert separate["file_id"] != result["file_id"]
    with pytest.raises(Fault, match="NOT_FOUND"):
        dispatch(hub, main, "files", {"action": "select", "file_id": result["file_id"]})
    with pytest.raises(Fault, match="NOT_FOUND"):
        store.attachment({**identity, "session_hash": "b"*64}, result["attachment_id"])
    assert (Path(profiles["main"]["workspace"])/"filetools"/"registry.sqlite").is_file()


def test_reference_current_hash_missing_no_external_delete(mapped, identity):
    hub, profiles, _ = mapped
    store, file, _ = source(mapped, identity)
    result = register_source(store, identity, {"source_path": file.name, "mode": "reference"})
    # Gateway and processing roots must be explicit; ordinary workspace references are not mounted by default.
    hub.stores["chen"].limits = replace(hub.stores["chen"].limits,
        source_roots={"workspace": {"path": profiles["chen"]["workspace"], "kind": "workspace"}})
    store.inspect(identity, result["attachment_id"])
    file.write_text("New version")
    with pytest.raises(Fault, match="REFERENCE_CHANGED"):
        store.inspect(identity, result["attachment_id"])
    file.unlink()
    with pytest.raises(Fault, match="SOURCE_NOT_FOUND"):
        store.inspect(identity, result["attachment_id"])
    file.write_text("New version")
    assert store.files(identity, "delete_original", file_id=result["file_id"])["external_original_deleted"] is False
    assert file.read_text() == "New version"


def test_registration_path_source_trust_and_incomplete(mapped, identity):
    store, file, _ = source(mapped, identity)
    for path, code in [("../main/notes.txt", "SOURCE_PATH_ESCAPE"), ("https://host/file", "SOURCE_NOT_FOUND"),
                        ("missing", "SOURCE_NOT_FOUND")]:
        with pytest.raises(Fault, match=code):
            register_source(store, identity, {"source_path": path, "source": {"root": str(file.parent)}})
    for name, code in [("pending.part", "SOURCE_INCOMPLETE"), ("SOUL.md", "SYSTEM_FILE_EXCLUDED")]:
        (file.parent/name).write_text("untrusted")
        with pytest.raises(Fault, match=code):
            register_source(store, identity, {"source_path": name})
    with pytest.raises(Fault, match="SOURCE_ROOT_DENIED"):
        register_source(store, identity, {"source_path": str(file), "source_root": "invented"})
    binary = file.with_name("misleading.md")
    binary.write_bytes(b"PK\x03\x04\0\xff")
    with pytest.raises(Fault, match="BINARY_ARTIFACT"):
        readable_text(binary, store.limits)


def test_published_output_read_save_after_cleanup_touch_and_no_copy(mapped, identity):
    hub, _, configuration = mapped
    store, file, result = source(mapped, identity)
    original_hash = digest_file(file)
    code = "from pathlib import Path\nimport os\ntext=Path(os.environ['FILETOOLS_INPUT']).read_text()\nPath('result.md').write_text('# Answer\\n'+text)"
    job = dispatch(hub, identity, "python", {"attachment_id": result["attachment_id"], "code": code,
        "description": "write Markdown copy", "outputs": ["result.md"]})
    completed = finish(hub, identity, job)
    assert completed["status"] == "SUCCEEDED", completed
    manifest = store.manifest(store.job(identity, job["job_id"]))
    output = next(a for a in manifest["artifacts"] if a["kind"] == "output")
    assert Path(output["gateway_path"]).read_text() == "# Answer\nCedar evidence"
    assert "published/" in output["workspace_relative_path"]
    read = store.read(identity, job["job_id"], {"artifact_id": output["artifact_id"]})
    assert "Cedar" in read["text"]
    product = register_source(store, identity, {"file_id": output["file_id"]})
    assert product["file_id"] == output["file_id"] and product["mode"] == "artifact"
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM files WHERE mode='snapshot'").fetchone()[0] == 1
        db.execute("UPDATE jobs SET expires=? WHERE id=?", (time.time()+10, job["job_id"]))
    before = store.job(identity, job["job_id"])["expires"]
    store.status(identity, job["job_id"])
    assert store.job(identity, job["job_id"])["expires"] == before
    assert management_call(configuration, identity, "touch_path", {"path": output["workspace_relative_path"]})["status"] == "TOUCHED"
    assert store.job(identity, job["job_id"])["expires"] > before+100
    saved = store.save_result(identity, job["job_id"], output["artifact_id"])
    store.files(identity, "delete_cache", job_id=job["job_id"])
    saved_read = store.saved_read(identity, saved["saved_id"], 0, output["artifact_id"])
    assert "Cedar" in saved_read["text"] and Path(saved_read["gateway_path"]).is_file()
    assert digest_file(file) == original_hash


def test_status_does_not_advertise_expired_or_removed_products(mapped, identity):
    hub, _, _ = mapped
    store, _, attachment = source(mapped, identity)
    job = dispatch(hub, identity, "extract", {"attachment_id": attachment["attachment_id"], "config": {"mode": "full"}})
    assert finish(hub, identity, job)["status"] == "SUCCEEDED"
    artifact = store.status(identity, job["job_id"])["artifacts"][0]
    path = Path(artifact["gateway_path"])
    path.chmod(0o600)  # Windows requires clearing the read-only attribute for this fault injection.
    path.unlink()
    missing = store.status(identity, job["job_id"])["artifacts"][0]
    assert missing["availability"] == "ARTIFACT_UNAVAILABLE" and "gateway_path" not in missing
    with store.db() as db:
        db.execute("UPDATE jobs SET expires=0 WHERE id=?", (job["job_id"],))
    expired = store.status(identity, job["job_id"])
    assert expired["availability"] == "CACHE_EXPIRED" and expired["artifacts"] == []
    with pytest.raises(Fault, match="CACHE_EXPIRED"):
        store.save_minutes(identity, job["job_id"], "Expired derived text", [1])


def test_leases_active_product_input_and_restart_protect_cleanup(mapped, identity):
    hub, _, config = mapped
    store, _, attachment = source(mapped, identity)
    job = dispatch(hub, identity, "extract", {"attachment_id": attachment["attachment_id"], "config": {"mode": "full"}})
    assert finish(hub, identity, job)["status"] == "SUCCEEDED"
    output = store.manifest(store.job(identity, job["job_id"]))["artifacts"][0]
    management_call(config, identity, "lease_path", {"path": output["gateway_path"], "token": "read"})
    with store.db() as db:
        db.execute("UPDATE jobs SET expires=0 WHERE id=?", (job["job_id"],))
    assert not store.cleanup()["removed_jobs"]
    with pytest.raises(Fault, match="FILE_BUSY"):
        store.files(identity, "delete_cache", job_id=job["job_id"])
    management_call(config, identity, "finish_access", {"path": output["gateway_path"], "token": "read", "success": True})
    product = register_source(store, identity, {"file_id": output["file_id"]})
    queued = dispatch(hub, identity, "python", {"attachment_id": product["attachment_id"], "code": "pass",
        "description": "pending dependent job", "outputs": ["result.txt"]})
    with store.db() as db:
        db.execute("UPDATE jobs SET expires=0 WHERE id=?", (job["job_id"],))
    assert not store.cleanup()["removed_jobs"]
    store.cancel(identity, queued["job_id"])
    assert job["job_id"] in store.cleanup()["removed_jobs"]
    pending = dispatch(hub, identity, "extract", {"attachment_id": attachment["attachment_id"], "config": {"mode": "preview"}})
    with store.db() as db:
        db.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (pending["job_id"],))
    restart = WorkspaceSupervisor(hub)
    try:
        assert store.status(identity, pending["job_id"])["status"] == "INTERRUPTED"
        assert store.files(identity, "resume", job_id=pending["job_id"])["status"] == "QUEUED"
        assert store.cancel(identity, pending["job_id"])["status"] == "CANCELLED"
    finally:
        restart.close()


def test_real_large_registration_has_independent_snapshot(mapped, identity):
    hub, profiles, _ = mapped
    workspace = Path(profiles["chen"]["workspace"])
    source = workspace/"large.bin"
    with source.open("wb") as file:
        block = b"V12 real bytes\0"*(1024**2//15+1)
        for _ in range(201):
            file.write(block[:1024**2])
    store = mapped_store(profiles["chen"], "chen", hub.limits, "gateway")
    result = register_source(store, identity, {"source_path": source.name})
    assert result["bytes"] == 201*1024**2
    snapshot = Path(result["file_reference"]["gateway_path"])
    assert digest_file(snapshot) == digest_file(source) and snapshot.stat().st_ino != source.stat().st_ino


@pytest.mark.engines
@pytest.mark.skipif(__import__("os").environ.get("FILETOOLS_REAL_ENGINES") != "1", reason="Opt-in real engines, no mocks")
@pytest.mark.parametrize("name", ["text.pdf", "scan.pdf", "mixed.pdf", "ordered.docx", "printed.png", "jfk.flac"])
def test_real_engine_shared_workspace_range_save_and_cleanup(mapped, identity, samples, name):
    hub, profiles, _ = mapped
    workspace = Path(profiles["chen"]["workspace"])
    origin = Path(__import__("os").environ["FILETOOLS_AUDIO_SAMPLE"]) if name == "jfk.flac" else samples/name
    file = workspace/name
    shutil.copyfile(origin, file)
    limits = replace(hub.limits, whisper_model=__import__("os").environ.get("FILETOOLS_WHISPER_MODEL", "small"))
    hub.stores["chen"].limits = replace(hub.stores["chen"].limits, whisper_model=limits.whisper_model)
    store = mapped_store(profiles["chen"], "chen", limits, "gateway")
    registered = register_source(store, identity, {"source_path": name})
    config = {"mode": "full", "language": "en"} if name == "jfk.flac" else {"mode": "full"}
    job = dispatch(hub, identity, "extract", {"attachment_id": registered["attachment_id"], "config": config})
    result = finish(hub, identity, job)
    assert result["status"] in ("SUCCEEDED", "PARTIAL"), result
    artifact = result["artifacts"][0]
    text = Path(artifact["gateway_path"]).read_text(encoding="utf-8")
    assert "country" in text.lower() if name == "jfk.flac" else len(text) > 20
    read = store.read(identity, job["job_id"], {})
    assert read["evidence"]
    if name.endswith(".pdf"):
        assert "page" in read["evidence"][0]["source"]
    if name == "jfk.flac":
        assert "start" in read["evidence"][0]["source"]
    saved = store.save_result(identity, job["job_id"], artifact["artifact_id"])
    store.files(identity, "delete_cache", job_id=job["job_id"])
    assert store.saved_read(identity, saved["saved_id"], 0)["text"] == text


@pytest.mark.parametrize("outcome", ["normal", "failed", "timeout"])
def test_real_process_tree_leader_exit_never_publishes_live_writer(mapped, identity, outcome):
    hub, _, _ = mapped
    store, _, attachment = source(mapped, identity)
    hub.stores["chen"].limits = replace(hub.stores["chen"].limits, script_timeout_seconds=1)
    if sys.platform == "linux":
        hub.stores["chen"].limits = replace(hub.stores["chen"].limits, script_isolation="landlock")
    marker = Path(str(store.root).removeprefix("\\\\?\\"))/"escaped-writer.txt"
    child = f"import time;from pathlib import Path;time.sleep(1.5);Path('late-marker.txt').write_text('escaped');Path({str(marker)!r}).write_text('escaped')"
    code = f"import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c',{child!r}]);Path('descendant.pid').write_text(str(p.pid))\nPath('result.txt').write_text('stable')\n"
    if outcome == "failed":
        code += "raise RuntimeError('expected')\n"
    elif outcome == "timeout":
        code += "time.sleep(10)\n"
    job = dispatch(hub, identity, "python", {"attachment_id": attachment["attachment_id"], "code": code,
        "description": "tree reclamation", "outputs": ["result.txt"]})
    result = finish(hub, identity, job)
    assert result["status"] == ("SUCCEEDED" if outcome == "normal" else "FAILED"), result
    if outcome == "normal":
        manifest = store.manifest(store.job(identity, job["job_id"]))
        output = next(a for a in manifest["artifacts"] if a["kind"] == "output")
        before = digest_file(output["gateway_path"])
    time.sleep(1.7)
    assert not marker.exists()
    execution = store.task(job["job_id"])/".private"/"execution"
    assert not (execution/"late-marker.txt").exists()
    if sys.platform == "linux":
        assert not Path("/proc", (execution/"descendant.pid").read_text()).exists()
    if outcome == "normal":
        assert digest_file(output["gateway_path"]) == before


def test_real_cancel_reclaims_script_descendants_and_global_slot(mapped, identity):
    hub, _, _ = mapped
    store, _, attachment = source(mapped, identity)
    if sys.platform == "linux":
        hub.stores["chen"].limits = replace(hub.stores["chen"].limits, script_isolation="landlock")
    marker = Path(str(store.root).removeprefix("\\\\?\\"))/"cancel-escaped.txt"
    child = f"import time;from pathlib import Path;time.sleep(2);Path('late-marker.txt').write_text('BAD');Path({str(marker)!r}).write_text('BAD')"
    code = f"import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c',{child!r}]);Path('descendant.pid').write_text(str(p.pid))\nPath('started.txt').write_text('ready')\ntime.sleep(10)\n"
    job = dispatch(hub, identity, "python", {"attachment_id": attachment["attachment_id"], "code": code,
        "description": "cancel process tree", "outputs": ["result.txt"]})
    main = {**identity, "agent_id": "main"}
    _, _, second = source(mapped, main)
    other = dispatch(hub, main, "extract", {"attachment_id": second["attachment_id"], "config": {"mode": "full"}})
    supervisor = WorkspaceSupervisor(hub)
    try:
        supervisor.tick()
        assert len(supervisor.processes) == 1
        assert dispatch(hub, main, "status", {"job_id": other["job_id"]})["status"] == "QUEUED"
        flag = store.task(job["job_id"])/".private"/"execution"/"started.txt"
        for _ in range(100):
            if flag.exists():
                break
            time.sleep(.025)
        assert flag.exists(), "script child must really have started before cancellation"
        store.cancel(identity, job["job_id"])
        supervisor.tick()
        assert store.status(identity, job["job_id"])["status"] == "CANCELLED"
        assert store.status(identity, job["job_id"])["cancel_requested"]
        time.sleep(2.1)
        assert not marker.exists()
        assert not (flag.parent/"late-marker.txt").exists()
        if sys.platform == "linux":
            assert not Path("/proc", (flag.parent/"descendant.pid").read_text()).exists()
    finally:
        supervisor.close()


@pytest.mark.skipif(sys.platform != "linux", reason="Real Linux Landlock/Docker acceptance; Windows is not equivalent")
def test_linux_script_input_is_readonly_and_escaped_process_reclaimed(mapped, identity):
    hub, _, _ = mapped
    _, _, attachment = source(mapped, identity)
    hub.stores["chen"].limits = replace(hub.stores["chen"].limits, script_isolation="landlock")
    code = "import os\nfrom pathlib import Path\np=Path(os.environ['FILETOOLS_INPUT'])\ntry:\n p.write_text('BAD')\nexcept PermissionError:\n Path('proof.txt').write_text('denied')\n"
    result = finish(hub, identity, dispatch(hub, identity, "python", {"attachment_id": attachment["attachment_id"],
        "code": code, "description": "readonly proof", "outputs": ["proof.txt"]}))
    assert result["status"] == "SUCCEEDED", result


@pytest.mark.skipif(sys.platform != "linux", reason="Real Linux filesystem and seccomp boundaries")
def test_linux_denies_registry_saved_other_agent_published_and_process_escape(mapped, identity):
    hub, profiles, _ = mapped
    store, _, attachment = source(mapped, identity)
    prior = dispatch(hub, identity, "extract", {"attachment_id": attachment["attachment_id"], "config": {"mode": "full"}})
    assert finish(hub, identity, prior)["status"] == "SUCCEEDED"
    saved = store.save_result(identity, prior["job_id"])
    public = store.task(prior["job_id"])/"published"/"content.md"
    other = Path(profiles["main"]["workspace"])/"secret.txt"
    other.write_text("private")
    paths = [str(store.root/"registry.sqlite"), str(public), str(other), store.saved_read(identity, saved["saved_id"], 0)["gateway_path"]]
    hub.stores["chen"].limits = replace(hub.stores["chen"].limits, script_isolation="landlock")
    code = f"""import os,socket
from pathlib import Path
for target in {paths!r}:
 for mode in ('r', 'w'):
  try:
   with open(target, mode) as file:
    file.read() if mode == 'r' else file.write('BAD')
  except PermissionError: pass
  else: raise AssertionError(target+' was accessible')
for operation in (os.setsid, lambda: os.setpgid(0,0), socket.socket):
 try: operation()
 except PermissionError: pass
 else: raise AssertionError('escape/network allowed')
Path('proof.txt').write_text('all denied')
"""
    result = finish(hub, identity, dispatch(hub, identity, "python", {"attachment_id": attachment["attachment_id"],
        "code": code, "description": "real Linux denial checks", "outputs": ["proof.txt"]}))
    assert result["status"] == "SUCCEEDED", result
    assert other.read_text() == "private" and "Cedar" in public.read_text()


@pytest.mark.skipif(sys.platform != "linux", reason="Real Linux double-fork / setsid reclamation")
def test_linux_development_double_fork_detached_writer_is_reclaimed(mapped, identity):
    hub, _, _ = mapped
    store, _, attachment = source(mapped, identity)
    marker = store.root/"double-fork-escaped.txt"
    code = f"""import os,time
from pathlib import Path
pid=os.fork()
if pid == 0:
 os.setsid()
 if os.fork() == 0:
  time.sleep(1.5)
  Path({str(marker)!r}).write_text('BAD')
  os._exit(0)
 os._exit(0)
os.waitpid(pid,0)
Path('result.txt').write_text('stable')
"""
    result = finish(hub, identity, dispatch(hub, identity, "python", {"attachment_id": attachment["attachment_id"],
        "code": code, "description": "detached process reclamation", "outputs": ["result.txt"]}))
    assert result["status"] == "SUCCEEDED", result
    time.sleep(1.7)
    assert not marker.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Real unprivileged Linux permissions")
def test_linux_unreadable_source_returns_permission_error(mapped, identity):
    import os
    if os.getuid() == 0:
        pytest.skip("Root bypasses discretionary permissions; use the unprivileged test container")
    _, profiles, configuration = mapped
    path = Path(profiles["chen"]["workspace"])/"unreadable.txt"
    path.write_text("private")
    path.chmod(0)
    try:
        cli = Path(__file__).parents[1]/"scripts"/"filetools_manage.py"
        result = subprocess.run([sys.executable, "-I", "-S", str(cli), "--config", str(configuration)],
            input=json.dumps({"identity": identity, "operation": "register", "params": {"source_path": path.name}}),
            text=True, capture_output=True, check=True)
        assert json.loads(result.stdout)["code"] == "SOURCE_PERMISSION_DENIED"
    finally:
        path.chmod(0o600)
