"""Explicit synthetic thousand-page scheduler exercise; no model/OCR inference.

Uses the real serial executor, publication, recovery and persisted metadata, but
replaces image rendering and engine child with deterministic synthetic results.
Never install this adapter in the normal development/production engine catalog.
"""

import argparse
import json
from pathlib import Path
import resource
import time
from unittest.mock import patch

import fitz
from PIL import Image
from nas_filetools.standalone.config import validate
from nas_filetools.standalone.tasks import Projects


def main(target):
    target.mkdir(parents=True, exist_ok=False)
    config = json.loads(Path("deploy/standalone-http.example.json").read_text())
    local = config["engines"]["local"]
    config["engines"] = {"fixture": {**local, "type": "fixture", "model": "simulated-1000", "timeout": 5}}
    config["conversion"]["generate_documents"] = False
    validate(config, testing=True)
    manager = Projects(target / "store", config, start_worker=False)
    temp = target / "synthetic.pdf"
    with fitz.open() as pdf:
        for _ in range(1000):
            pdf.new_page()
        pdf.save(temp)
    with patch.object(manager, "analyze", return_value={"analysis_id": "not-run-in-scheduler-exercise"}):
        uploaded = manager.upload(temp, "synthetic-1000.pdf", "模拟千页调度（无模型调用）")
    pid = uploaded["project_id"]
    sample = manager.path(pid) / "sources/synthetic-simulation.png"
    Image.new("RGB", (120, 160), "white").save(sample)
    item = manager.enqueue(pid, "fixture", "全部")
    tid = item["task_id"]
    calls = []
    stop_at = 100

    def fake_child(request, result, timeout, cancel, **kwargs):
        page = request["physical_page"]
        calls.append(page)
        if stop_at and len(calls) == stop_at:
            cancel.set()
        return {
            "status": "SUCCEEDED",
            "text": f"Synthetic simulated page {page}. No OCR performed.",
            "blocks": [],
            "quality": None,
            "error": None,
            "peak_rss_kib": None,
        }

    start = time.monotonic()
    with (
        patch.object(manager, "render", return_value=sample),
        patch.object(manager, "run_child", side_effect=fake_child),
    ):
        manager.execute(pid, tid)
    cancelled = manager.get(pid)
    task = manager.task(cancelled, tid)
    assert task["status"] == "CANCELLED"
    completed = {n: r["latest"]["result"] for n, r in task["pages"].items() if r["status"] == "SUCCEEDED"}
    assert len(completed) == 100
    # Isolated persisted interrupted-state injection, distinctly labelled simulation.
    task["status"] = "RUNNING"
    task["pages"]["101"]["status"] = "RUNNING"
    manager.save(manager.path(pid), cancelled)
    manager.close()
    manager = Projects(target / "store", config, start_worker=False)
    assert manager.task(manager.get(pid), tid)["status"] == "INTERRUPTED"
    resumed = manager.retry(pid, tid)
    assert len(resumed["retry_pages"]) == 900
    stop_at = 0
    with (
        patch.object(manager, "render", return_value=sample),
        patch.object(manager, "run_child", side_effect=fake_child),
    ):
        manager.execute(pid, tid)
    p = manager.get(pid)
    t = manager.task(p, tid)
    assert t["status"] == "SUCCEEDED"
    assert calls == list(range(1, 1001))
    assert all(
        t["pages"][n]["latest"]["result"] == file and len(t["pages"][n]["attempts"]) == 1
        for n, file in completed.items()
    )
    assert len(t["pages"]) == 1000
    # Do not expose this fixture as an available normal-service engine.
    manager.archive_task(pid, tid, False)
    report = {
        "scope": "simulation-only; deterministic child/render replacements",
        "project_id": pid,
        "task_id": tid,
        "selected_pages": 1000,
        "completed_pages": 1000,
        "cancelled_after_successful_pages": 100,
        "simulated_restart": "INTERRUPTED",
        "explicit_resume_pages": 900,
        "successful_pages_not_rerun": True,
        "sequential_calls_exact_order": True,
        "model_requests": 0,
        "scheduler_wall_seconds": time.monotonic() - start,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "document_generation": "not performed; fake content only",
    }
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    main(parser.parse_args().target)
