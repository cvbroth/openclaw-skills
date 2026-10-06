"""Isolated candidate smoke/benchmark via existing core; never Gateway or QQ.

Run in a network-none candidate container with only development mounts.
"""
import argparse
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path

from document_sample_pipeline import retrieve_outputs, wait
from nas_filetools.contracts import Limits
from nas_filetools.document_entry import OUTPUTS
from nas_filetools.management import register_source
from nas_filetools.service import dispatch
from nas_filetools.shared_workspace import WorkspaceHub, mapped_store


def check(root, input_path, pages, title, runs):
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    review = json.loads(input_path.read_bytes())
    review["document"] = {"schema": "reviewed-single-choice-v1", "source_pages": pages, "title": title,
                          "template": {"id": "questions-zh-cn", "version": "1.0.0"}}
    (workspace / "review-input.json").write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    limits = replace(Limits(), enabled_agents=("chen",), script_isolation="landlock", script_timeout_seconds=60)
    profile = {"workspace": str(workspace), "service_root": str(workspace / "filetools")}
    hub = WorkspaceHub(root / "control", limits, {"chen": profile})
    store = mapped_store(profile, "chen", limits, "gateway")
    identity = {"user_id": "chen", "agent_id": "chen", "session_hash": "a" * 64}
    (workspace / "ocr.md").write_bytes(review["raw_ocr"].encode("utf-8"))
    selected = register_source(store, identity, {"source_path": "ocr.md"})
    arguments = {k: review[k] for k in ("document", "margin_evidence", "reviewed_edits", "review_notes")
                 if k in review}
    code = ("import json\nfrom nas_filetools.document_entry import prepare_registered_ocr\n"
            + "prepare_registered_ocr(**json.loads(" + repr(json.dumps(arguments, ensure_ascii=False)) + "))\n")
    package_job = dispatch(hub, identity, "python", {"attachment_id": selected["attachment_id"],
        "description": "Package the sole registered OCR and independent supplied review records",
        "code": code, "outputs": ["reviewed-input.json"]})
    package_status = wait(hub, identity, package_job)
    if package_status["status"] != "SUCCEEDED":
        raise RuntimeError(json.dumps(package_status))
    package_outputs = retrieve_outputs(root, hub, identity, package_job, package_status)
    selected = register_source(store, identity, {"file_id": package_outputs[0]["file_id"]})
    receipts = []
    for number in range(runs):
        started = time.monotonic()
        job = dispatch(hub, identity, "python", {"attachment_id": selected["attachment_id"],
            "description": f"Candidate single-input document benchmark run {number + 1}",
            "code": "from nas_filetools.document_entry import generate_registered_input\ngenerate_registered_input()\n",
            "outputs": list(OUTPUTS)})
        status = wait(hub, identity, job)
        if status["status"] != "SUCCEEDED":
            raise RuntimeError(json.dumps(status))
        outputs = retrieve_outputs(root, hub, identity, job, status)
        metrics = json.loads((root / "delivery/generation-metrics.json").read_bytes())
        receipts.append({"job_id": job["job_id"], "status": status["status"],
                         "core_wall_seconds": round(time.monotonic() - started, 6),
                         "metrics": metrics, "outputs": outputs})
        shutil.copytree(root / "delivery", root / f"run-{number + 1}")
    # Chinese plain paragraphs are only a smoke test of the writers, not a
    # promise that the reviewed single-choice parser supports generic articles.
    smoke_code = '''from pathlib import Path
from nas_filetools.document_sample import write_docx, write_pdf, validate_pair
from nas_filetools.document_entry import FONT_PATH
items = [("Normal", "中文短文验证：保留原件，独立生成副本。"), ("Normal", "来源与文档页码区分，识别成功不代表文字准确。")]
write_docx(Path("smoke.docx"), items, FONT_PATH)
write_pdf(Path("smoke.pdf"), items, FONT_PATH)
validate_pair(Path("smoke.docx"), Path("smoke.pdf"), items)
'''
    job = dispatch(hub, identity, "python", {"attachment_id": selected["attachment_id"],
        "description": "Synthetic Chinese paragraph writers smoke; not a general article template",
        "code": smoke_code, "outputs": ["smoke.docx", "smoke.pdf"]})
    status = wait(hub, identity, job)
    if status["status"] != "SUCCEEDED":
        raise RuntimeError(json.dumps(status))
    smoke = retrieve_outputs(root, hub, identity, job, status)
    evidence = {"environment": "isolated candidate; no Gateway/QQ", "script_timeout_seconds": 60,
                "isolation": "landlock", "package_outputs": package_outputs,
                "runs": receipts, "plain_smoke_outputs": smoke}
    (root / "candidate-receipt.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps({"runs": [{k: r[k] for k in ("status", "core_wall_seconds", "metrics")} for r in receipts],
                      "plain_smoke_status": status["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs=2, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--runs", type=int, default=3, choices=range(1, 4))
    args = parser.parse_args()
    check(args.root, args.input, args.pages, args.title, args.runs)
