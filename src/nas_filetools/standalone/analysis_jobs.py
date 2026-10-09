"""Independent source analysis states, persisted separately from conversion jobs."""

import threading
import uuid
from ..artifact_project import register_artifact
from .source_analysis import atomic


class AnalysisJobs:
    def analyze(self, pid):
        with self.lock:
            p = self.get(pid)
            if p.get("source_info", {}).get("kind") not in {"pdf", "image"}:
                raise ValueError("项目没有可分析的本地PDF或图片原件。")
            if p.get("analysis", {}).get("status") in {"QUEUED", "RUNNING"}:
                raise ValueError("analysis already active")
            aid = str(uuid.uuid4())
            p["analysis"] = {
                "status": "QUEUED",
                "analysis_id": aid,
                "path": f"diagnostics/analysis/{aid}/analysis.json",
                "completed_pages": 0,
                "total_pages": None,
            }
            self.save(self.path(pid), p)
            self.queue.put((pid, "analysis:" + aid))
            return {"project_id": pid, "analysis_id": aid, "status": "QUEUED"}

    def execute_analysis(self, pid, aid):
        root = self.path(pid)
        p = self.get(pid)
        source = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
        output = root / p["analysis"]["path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            p = self.get(pid)
            p["analysis"]["status"] = "RUNNING"
            self.save(root, p)
        result = self.run_child(
            {
                "source": str(root / source["path"]),
                "source_sha256": source["sha256"],
                "kind": p["source_info"].get("kind"),
                "max_pages": self.config["service"]["max_pages"],
                "max_pixels": self.config["service"]["max_pixels"],
                "engine": {"cpu_threads": 2, "credential_env": ""},
            },
            output,
            120,
            threading.Event(),
            module="nas_filetools.standalone.source_analysis",
        )
        with self.lock:
            p = self.get(pid)
            p["analysis"].update(result, analysis_id=aid, path=str(output.relative_to(root)))
            if result.get("status") == "FAILED" and p["analysis"].get("completed_pages", 0):
                p["analysis"]["status"] = "PARTIAL"
            if result.get("actual_type"):
                p["source_info"].update(actual_type=result["actual_type"], units=result.get("total_pages"))
                if result.get("dimensions"):
                    p["source_info"]["dimensions"] = result["dimensions"]
                p["source_info"]["validation_status"] = "SUCCEEDED"
                p["source_info"].pop("error", None)
            if output.is_file():
                atomic(output, p["analysis"])
                artifact = register_artifact(
                    root,
                    p,
                    name="原件逐页分析.json",
                    format="json",
                    path=str(output.relative_to(root)),
                    parents=[source["artifact_id"]],
                )
                artifact["role"] = "diagnostic"
            self.save(root, p)
