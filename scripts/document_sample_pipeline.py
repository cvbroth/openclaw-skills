"""Isolated developer pipeline using existing FileTools IDs/publication, never production.

--extract reads only an already made five-page development PDF excerpt.
--generate calls the preinstalled reusable module in a candidate Worker, consumes a
published OCR file_id, and verifies copies retrieved through artifact_path.
"""
import argparse
import hashlib
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path

from nas_filetools.contracts import Limits
from nas_filetools.management import register_source
from nas_filetools.service import dispatch
from nas_filetools.shared_workspace import WorkspaceHub, WorkspaceSupervisor, mapped_store


def wait(hub, identity, job):
    supervisor = WorkspaceSupervisor(hub)
    try:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            supervisor.tick()
            result = dispatch(hub, identity, "status", {"job_id": job["job_id"]})
            if result["status"] not in ("QUEUED", "RUNNING"):
                return result
            time.sleep(0.2)
        raise RuntimeError("DEVELOPMENT_JOB_TIMEOUT")
    finally:
        supervisor.close()


def retrieve_outputs(root, hub, identity, job, status):
    delivery = root / "delivery"
    delivery.mkdir(exist_ok=True)
    published = []
    for artifact in status["artifacts"]:
        if artifact["kind"] != "output":
            continue
        reference = dispatch(hub, identity, "files", {"action": "artifact_path", "job_id": job["job_id"], "artifact_id": artifact["artifact_id"]})
        source_path = Path(reference["gateway_path"])
        target = delivery / source_path.name
        shutil.copyfile(source_path, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        assert digest == reference["sha256"] and target.stat().st_size == reference["bytes"]
        published.append({"name": target.name, "job_id": job["job_id"], "artifact_id": artifact["artifact_id"],
                          "file_id": artifact["file_id"], "bytes": reference["bytes"], "sha256": digest})
    return published


def pipeline(root, stage, report_name="DOCUMENT_SAMPLE_REPORT.md"):
    root = Path(root).resolve()
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    limits = replace(Limits(), enabled_agents=("chen",), script_isolation="landlock", script_timeout_seconds=120)
    profile = {"workspace": str(workspace), "service_root": str(workspace / "filetools")}
    hub = WorkspaceHub(root / "control", limits, {"chen": profile})
    store = mapped_store(profile, "chen", limits, "gateway")
    identity = {"user_id": "chen", "agent_id": "chen", "session_hash": "d" * 64}
    receipt_path = root / "pipeline-receipt.json"
    receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    if stage == "extract":
        target = workspace / "original-pages6-10.pdf"
        if not target.exists():
            shutil.copyfile(root / target.name, target)
        registered = register_source(store, identity, {"source_path": target.name})
        job = dispatch(hub, identity, "extract", {"attachment_id": registered["attachment_id"],
            "config": {"mode": "full", "ocr": "always"}})
        status = wait(hub, identity, job)
        if status["status"] != "SUCCEEDED":
            raise RuntimeError(json.dumps(status))
        manifest = store.manifest(store.job(identity, job["job_id"]))
        # Keep the excerpt's true FileTools page labels 1–5; separate map records
        # their authorized original pages 6–10. Do not falsify engine sources.
        content = next(a for a in status["artifacts"] if a["kind"] == "content")
        raw_path = store.task(job["job_id"]) / content["file"]
        shutil.copyfile(raw_path, root / "excerpt-raw-ocr.md")
        (root / "excerpt-ocr-sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        receipts["extraction"] = {"job_id": job["job_id"], "ocr_file_id": content["file_id"],
            "artifact_id": content["artifact_id"], "source_sha256": content["sha256"], "status": status["status"]}
        # Small annotated derivative retains raw strings, with an explicit map.
        mapped = "\n".join(f"## 第 {s['source']['page'] + 5} 页\n{s['text']}\n" for s in manifest["segments"])
        (workspace / "mapped-ocr.md").write_text(mapped, encoding="utf-8")
        print(json.dumps({"extraction": receipts["extraction"], "pages": len(manifest["segments"])}))
    elif stage == "generate":
        # Prove the actual existing published OCR product can be reused by ID.
        selected = register_source(store, identity, {"file_id": receipts["extraction"]["ocr_file_id"]})
        probe = dispatch(hub, identity, "python", {"attachment_id": selected["attachment_id"],
            "description": "Read existing published OCR through FILETOOLS_INPUT only",
            "code": 'import os,hashlib\nfrom pathlib import Path\np=Path(os.environ["FILETOOLS_INPUT"])\nPath("input-proof.json").write_text(__import__("json").dumps({"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"input_name":p.name}))',
            "outputs": ["input-proof.json"]})
        status = wait(hub, identity, probe)
        assert status["status"] == "SUCCEEDED", status
        proof_artifact = next(a for a in status["artifacts"] if a["kind"] == "output")
        proof_value = json.loads(dispatch(hub, identity, "read", {"job_id": probe["job_id"], "artifact_id": proof_artifact["artifact_id"]})["text"])
        assert proof_value["sha256"] == receipts["extraction"]["source_sha256"]
        # The user-provided OLD OCR plus independent page-reviewed evidence is
        # one registered input; newly extracted OCR remains separate.
        registered = register_source(store, identity, {"source_path": "review-input.json"})
        code = 'import os\nfrom pathlib import Path\nfrom nas_filetools.document_sample import generate_sample\ngenerate_sample(Path(os.environ["FILETOOLS_INPUT"]), Path.cwd(), "/usr/share/fonts/truetype/filetools/DroidSansFallback.ttf", title="肖1000 第6–10页开发样本（旧OCR，按原页核对）")\n'
        job = dispatch(hub, identity, "python", {"attachment_id": registered["attachment_id"], "description": "Generate five-page source sample DOCX/PDF from sole registered OCR input",
            "code": code, "outputs": ["sample.docx", "sample.pdf", "structured.json", "original-ocr.md", "issues.md", "validation.json"]})
        status = wait(hub, identity, job)
        assert status["status"] == "SUCCEEDED", status
        published = retrieve_outputs(root, hub, identity, job, status)
        receipts["generation"] = {"job_id": job["job_id"], "isolation": "landlock", "outputs": published,
            "published_input_reuse_job": probe["job_id"], "delivery": "real isolated core artifact_path + local hash-verified copies; not QQ"}
        print(json.dumps(receipts["generation"], ensure_ascii=False))
    elif stage == "report":
        if Path(report_name).name != report_name or not report_name.endswith(".md"):
            raise ValueError("DEVELOPMENT_REPORT_NAME_REQUIRED")
        source = Path(__file__).resolve().parents[1] / "docs" / report_name
        shutil.copyfile(source, workspace / "document-report.md")
        registered = register_source(store, identity, {"source_path": "document-report.md"})
        job = dispatch(hub, identity, "python", {"attachment_id": registered["attachment_id"],
            "description": "Publish the completed development validation report",
            "code": 'import os\nfrom pathlib import Path\nPath("report.md").write_bytes(Path(os.environ["FILETOOLS_INPUT"]).read_bytes())',
            "outputs": ["report.md"]})
        status = wait(hub, identity, job)
        assert status["status"] == "SUCCEEDED", status
        receipts["report"] = {"job_id": job["job_id"], "outputs": retrieve_outputs(root, hub, identity, job, status)}
        print(json.dumps(receipts["report"], ensure_ascii=False))
    receipt_path.write_text(json.dumps(receipts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=["extract", "generate", "report"])
    parser.add_argument("--report-name", default="DOCUMENT_SAMPLE_REPORT.md")
    args = parser.parse_args()
    pipeline(args.root, args.stage, args.report_name)
