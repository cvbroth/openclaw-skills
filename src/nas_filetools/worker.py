"""One supervisor, killable child processes and crash-safe artifact publication."""

import json
import multiprocessing
import os
import signal
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path

from .catalog import timestamp
from .contracts import AGENT_USERS, Fault, Limits
from .engines import Processor, probe
from .store import Store, write_json


class ServiceLock:
    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.file = (Path(root) / "service.lock").open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise Fault("SERVICE_ALREADY_RUNNING") from None

    def close(self):
        self.file.close()


def isolate_child(parent):
    if os.name != "nt":
        os.setsid()
        # Linux NAS: abort children and ffmpeg when the supervisor unexpectedly dies.
        def shutdown(*_):
            os.killpg(os.getpgrp(), signal.SIGKILL)
        signal.signal(signal.SIGTERM, shutdown)
        try:
            import ctypes
            if ctypes.CDLL(None).prctl(1, signal.SIGTERM) != 0:
                raise OSError("prctl")
            if os.getppid() != parent:
                shutdown()
        except AttributeError:
            pass  # Other Unix platforms rely on the service manager process group.


def resource_limits(settings):
    threads = str(settings["engine_threads"])
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = threads
    if os.name == "posix":
        import resource
        ceiling = settings["worker_memory_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))



def inspect_child(path, settings, result_file, parent):
    isolate_child(parent)
    resource_limits(settings)
    try:
        write_json(result_file, {"info": probe(path, Limits(**settings))})
    except Exception as error:
        write_json(result_file, {"error": error.code if isinstance(error, Fault) else "INSPECTION_FAILED"})


def terminate(process):
    if process.is_alive():
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        process.join(3)
        if process.is_alive():
            process.kill()
            process.join(3)


def bounded_probe(path, limits, workspace):
    result = Path(workspace) / (uuid.uuid4().hex + ".json")
    process = multiprocessing.get_context("spawn").Process(
        target=inspect_child, args=(str(path), asdict(limits), str(result), os.getpid()), daemon=True)
    process.start()
    process.join(limits.inspection_timeout_seconds)
    try:
        if process.is_alive():
            terminate(process)
            raise Fault("INSPECTION_TIMEOUT")
        if not result.exists():
            raise Fault("INSPECTION_FAILED")
        value = json.loads(result.read_text(encoding="utf-8"))
        if "error" in value:
            raise Fault(value["error"])
        return value["info"]
    finally:
        terminate(process)
        result.unlink(missing_ok=True)


def run_job(root, settings, row, parent):
    isolate_child(parent)
    resource_limits(settings)
    # Third-party engines may print; child output is never a JSON transport.
    store = Store(root, Limits(**settings))
    out = store.task(row["id"])
    with (out / "engine.log").open("w", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
        try:
            limits = Limits(**settings)
            store = Store(root, limits)
            with store.db() as db:
                attachment = dict(db.execute("SELECT * FROM attachments WHERE owner=? AND id=?",
                                             (row["owner"], row["attachment"])).fetchone())
            original = store.original(row["owner"], row["attachment"], attachment["filename"])
            from .catalog import digest_file
            if digest_file(original) != attachment["sha"]:
                raise Fault("SNAPSHOT_CHANGED")
            config = json.loads(row["config"])
            def progress(done, total):
                with store.db() as db:
                    db.execute("UPDATE jobs SET progress=?,updated=? WHERE id=? AND status='RUNNING'",
                               (min(0.99, done / max(total, 1)), time.time(), row["id"]))
            if row.get("kind") == "script":
                from .scripts import execute_script
                result = execute_script(original, json.loads(row["payload"]), out, limits, row)
            else:
                config["_checkpoint_fingerprint"] = row["fingerprint"]
                result = Processor(limits).process(original, json.loads(attachment["info"]), config, out, progress)
                result["config"].pop("_checkpoint_fingerprint", None)
            result.update(schema_version="1.1", job_id=row["id"], attachment_id=row["attachment"], file_id=attachment["file_id"],
                          original={"filename": attachment["filename"], "sha256": attachment["sha"],
                                    "bytes": attachment["size"],
                                    "message_id": json.loads(attachment["source"]).get("message_id")},
                          limits={k: v for k, v in settings.items() if k not in ("model_cache", "whisper_model")},
                          model={"reference": Path(limits.whisper_model).name, "offline": limits.offline},
                          created_at=timestamp(row["created"]), expires_at=timestamp(row["expires"]), content_trust="untrusted")
            content_id, source_id = uuid.uuid4().hex, uuid.uuid4().hex
            result["artifacts"] = [{"artifact_id": content_id, "file": "content.md", "kind": "content"},
                                   {"artifact_id": source_id, "file": "sources.json", "kind": "sources"},
                                   *result.pop("assets")]
            content = []
            for segment in result["segments"]:
                source = segment["source"]
                label = f"Page {source['page']}" if "page" in source else (
                    f"{source['start']:.3f}–{source['end']:.3f}s" if "start" in source else
                    f"Body block {source.get('paragraph', 1)}")
                content.append(f"<!-- segment:{segment['segment']} -->\n## {label}\n\n{segment['text']}\n")
            (out / "content.md").write_text("\n".join(content), encoding="utf-8")
            if result["coverage"]["kind"] == "audio":
                (out / "transcript.md").write_text("\n".join(content), encoding="utf-8")
                result["artifacts"].append({"artifact_id": uuid.uuid4().hex, "file": "transcript.md", "kind": "transcript"})
                result["warnings"].append("No minutes generated. Any later minutes must be stored separately from transcript.md.")
            if len(json.dumps(result).encode()) > limits.max_manifest_bytes:
                raise Fault("MANIFEST_LIMIT")
            write_json(out / "sources.json", result)
            write_json(out / "result.json", {"status": result["status"]})
        except Exception as error:
            write_json(out / "result.json", {"status": "FAILED", "code": error.code if isinstance(error, Fault)
                                             else "WORKER_ERROR", "error_type": type(error).__name__})


class Supervisor:
    def __init__(self, store):
        self.store = store
        self.processes = {}
        self.last_cleanup = 0
        # Requires service lock: no second supervisor may mark a live worker interrupted.
        with store.db() as db:
            db.execute("UPDATE jobs SET status='INTERRUPTED',updated=? WHERE status='RUNNING'", (time.time(),))
            db.execute("UPDATE jobs SET status='CANCELLED' WHERE cancel=1 AND status='QUEUED'")

    def finish(self, identifier, status):
        out = self.store.task(identifier)
        source_file = out / "sources.json"
        manifest = json.loads(source_file.read_text(encoding="utf-8")) if source_file.exists() else {
            "coverage": {"full_document": False, "processed": []}, "segments": [], "artifacts": [],
            "warnings": [], "failures": []}
        if status == "FAILED":
            marker = out / "result.json"
            failure = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {"code": "WORKER_CRASH"}
            if "code" in failure or manifest.get("status") != "FAILED":
                manifest.update(status="FAILED", segments=[], artifacts=[], failures=[{"code": failure.get("code", "WORKER_ERROR"),
                                  "error_type": failure.get("error_type", "Unknown")}])
                manifest["coverage"].update(full_document=False, processed=[])
                manifest["warnings"] = ["Processing failed; no published content."]
            write_json(source_file, manifest)
        elif status in ("CANCELLED", "TIMED_OUT", "INTERRUPTED"):
            manifest.update(status=status, artifacts=[], segments=[])
            manifest["coverage"].update(full_document=False, processed=[])
            manifest["warnings"] = [f"{status}: no evidence published for tool reads."]
            write_json(source_file, manifest)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status=?,progress=?,updated=?,expires=? WHERE id=? AND status='RUNNING'",
                       (status, 1 if status in ("SUCCEEDED", "PARTIAL") else 0, time.time(), time.time()+self.store.limits.ttl_seconds, identifier))

    def tick(self):
        with self.store.lock:
            for identifier, (process, started) in list(self.processes.items()):
                with self.store.db() as db:
                    row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
                status = None
                if row["cancel"]:
                    status = "CANCELLED"
                elif (self.store.task(identifier)/"engine.log").exists() and (self.store.task(identifier)/"engine.log").stat().st_size > self.store.limits.max_engine_log_bytes:
                    write_json(self.store.task(identifier)/"result.json", {"status": "FAILED", "code": "ENGINE_LOG_LIMIT"})
                    status = "FAILED"
                elif time.monotonic() - started > self.budget(row) or time.time()-row["updated"] > self.store.limits.stall_seconds:
                    status = "TIMED_OUT"
                elif not process.is_alive():
                    result = self.store.task(identifier) / "result.json"
                    status = json.loads(result.read_text(encoding="utf-8"))["status"] if result.exists() else "FAILED"
                if status:
                    terminate(process)
                    process.join()
                    self.finish(identifier, status)
                    del self.processes[identifier]
            with self.store.db() as db:
                queued = db.execute("SELECT * FROM jobs WHERE status='QUEUED' ORDER BY created LIMIT ?",
                                    (max(0, self.store.limits.concurrency - len(self.processes)),)).fetchall()
                for row in queued:
                    db.execute("UPDATE jobs SET status='RUNNING',updated=? WHERE id=?", (time.time(), row["id"]))
            for row in queued:
                process = None
                try:
                    # Never adopt an old result marker after an explicit resume/crash.
                    (self.store.task(row["id"])/"result.json").unlink(missing_ok=True)
                    scope = {"agent_id": row["agent"], "user_id": AGENT_USERS.get(row["agent"], row["agent"]), "session_hash": "0"*64}
                    estimate = self.store.limits.max_asset_bytes+self.store.limits.max_manifest_bytes+32*1024**2
                    if row["kind"] == "script":
                        with self.store.db() as db:
                            size = db.execute("SELECT size FROM attachments WHERE owner=? AND id=?", (row["owner"], row["attachment"])).fetchone()[0]
                        estimate = size+self.store.limits.script_output_bytes+4*1024**2
                    self.store.room(scope, "cache", estimate)
                    process = multiprocessing.get_context("spawn").Process(target=run_job,
                        args=(str(self.store.root), self.store.limits.dict(), dict(row), os.getpid()), daemon=True)
                    process.start()
                    self.processes[row["id"]] = (process, time.monotonic())
                except Exception as error:
                    if process is not None and hasattr(process, "is_alive"):
                        terminate(process)
                    write_json(self.store.task(row["id"])/"result.json", {"status": "FAILED", "code": error.code
                               if isinstance(error, Fault) else "WORKER_START_FAILED"})
                    self.finish(row["id"], "FAILED")
            if time.time() - self.last_cleanup > self.store.limits.cleanup_interval_seconds:
                self.store.cleanup()
                self.last_cleanup = time.time()

    def budget(self, row):
        if row["kind"] == "script":
            return self.store.limits.script_timeout_seconds+10
        with self.store.db() as db:
            attachment = db.execute("SELECT info FROM attachments WHERE owner=? AND id=?", (row["owner"], row["attachment"])).fetchone()
        info = json.loads(attachment[0])
        if info.get("kind") == "audio":
            return min(self.store.limits.max_job_seconds, max(self.store.limits.timeout_seconds,
                       info.get("duration", 0)*self.store.limits.audio_wall_factor))
        return self.store.limits.timeout_seconds

    def close(self):
        for identifier, (process, _) in self.processes.items():
            terminate(process)
            self.finish(identifier, "INTERRUPTED")
        self.processes.clear()
