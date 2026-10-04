"""Self-made document fixtures and real engine worker timings; never extrapolate to a production NAS."""
import argparse
import json
import platform
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import make_samples  # noqa: E402
from nas_filetools.contracts import Limits  # noqa: E402
from nas_filetools.engines import probe  # noqa: E402
from nas_filetools.store import Store  # noqa: E402
from nas_filetools.worker import ServiceLock, Supervisor  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--model", help="Immutable offline Whisper snapshot")
    parser.add_argument("--shared-workspaces", action="store_true", help="Exercise V1.2 registration and actual shared published paths")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    samples = make_samples(args.output / ("workspace/samples" if args.shared_workspaces else "samples"))
    limits = replace(Limits(), whisper_model=args.model or "small", enabled_agents=("chen",))
    if args.shared_workspaces:
        from nas_filetools.shared_workspace import WorkspaceHub, WorkspaceSupervisor, mapped_store
        profile = {"workspace": str((args.output/"workspace").resolve()), "service_root": str((args.output/"workspace/filetools").resolve())}
        hub = WorkspaceHub(args.output/"control", limits, {"chen": profile})
        store = mapped_store(profile, "chen", limits, "gateway")
        supervisor = WorkspaceSupervisor(hub)
        lock = ServiceLock(hub.root)
    else:
        store = Store(args.output / "state", limits)
        lock = ServiceLock(store.root)
        supervisor = Supervisor(store)
    identity = {"user_id": "chen", "agent_id": "chen", "session_hash": "a" * 64}
    records = []
    try:
        files = [samples / name for name in ("text.pdf", "scan.pdf", "mixed.pdf", "ordered.docx", "printed.png", "notes.md")]
        if args.audio:
            if args.shared_workspaces:
                import shutil
                target = samples/args.audio.name
                shutil.copyfile(args.audio, target)
                args.audio = target
            files.append(args.audio)
        for file in files:
            identifier = uuid.uuid4().hex
            started = time.monotonic()
            if args.shared_workspaces:
                from nas_filetools.management import register_source
                registered = register_source(store, identity, {"source_path": str(file.resolve()), "request_id": identifier})
                registration_seconds = time.monotonic()-started
                started = time.monotonic()
                info = store.inspect(identity, registered["attachment_id"])
            else:
                info = probe(file, limits)
                store.register(identity, identifier, file.name, file, info)
                registration_seconds = None
            inspection_seconds = time.monotonic() - started
            started = time.monotonic()
            result = store.submit(identity, identifier, {"mode": "full", "language": "en"} if file == args.audio else {"mode": "full"})
            while result["status"] in ("QUEUED", "RUNNING"):
                supervisor.tick()
                result = store.status(identity, result["job_id"])
                time.sleep(0.05)
            records.append({"filename": file.name, "bytes": file.stat().st_size, "kind": info["kind"],
                "units": info["units"], "duration": info.get("duration"), "inspection_seconds": round(inspection_seconds, 3),
                "registration_seconds": round(registration_seconds, 3) if registration_seconds is not None else None,
                "worker_wall_seconds": round(time.monotonic() - started, 3), "result": result})
        report = {"platform": platform.platform(), "processor": platform.processor(), "python": platform.python_version(),
            "note": "Real engines in separate CPU workers on this development machine. Not NAS or Gateway E2E.",
            "memory_cap_applied": sys.platform == "linux", "limits": limits.dict(), "cases": records}
        report["shared_workspace"] = args.shared_workspaces
        (args.output / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"results": [{"file": r["filename"], "status": r["result"]["status"],
            "seconds": r["worker_wall_seconds"]} for r in records]}, ensure_ascii=False))
    finally:
        supervisor.close()
        lock.close()


if __name__ == "__main__":
    main()
