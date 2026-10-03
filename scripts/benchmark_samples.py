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
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    samples = make_samples(args.output / "samples")
    limits = replace(Limits(), whisper_model=args.model or "small")
    store = Store(args.output / "state", limits)
    lock = ServiceLock(store.root)
    identity = {"user_id": "chen", "agent_id": "chen", "session_hash": "a" * 64}
    records = []
    supervisor = Supervisor(store)
    try:
        files = [samples / name for name in ("text.pdf", "scan.pdf", "mixed.pdf", "ordered.docx", "printed.png", "notes.md")]
        if args.audio:
            files.append(args.audio)
        for file in files:
            identifier = uuid.uuid4().hex
            started = time.monotonic()
            info = probe(file, limits)
            inspection_seconds = time.monotonic() - started
            store.register(identity, identifier, file.name, file, info)
            started = time.monotonic()
            result = store.submit(identity, identifier, {"mode": "full", "language": "en"} if file == args.audio else {"mode": "full"})
            while result["status"] in ("QUEUED", "RUNNING"):
                supervisor.tick()
                result = store.status(identity, result["job_id"])
                time.sleep(0.05)
            records.append({"filename": file.name, "bytes": file.stat().st_size, "kind": info["kind"],
                "units": info["units"], "duration": info.get("duration"), "inspection_seconds": round(inspection_seconds, 3),
                "worker_wall_seconds": round(time.monotonic() - started, 3), "result": result})
        report = {"platform": platform.platform(), "processor": platform.processor(), "python": platform.python_version(),
            "note": "Real engines in separate CPU workers on this development machine. Not NAS or Gateway E2E.",
            "memory_cap_applied": sys.platform == "linux", "limits": limits.dict(), "cases": records}
        (args.output / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"results": [{"file": r["filename"], "status": r["result"]["status"],
            "seconds": r["worker_wall_seconds"]} for r in records]}, ensure_ascii=False))
    finally:
        supervisor.close()
        lock.close()


if __name__ == "__main__":
    main()
