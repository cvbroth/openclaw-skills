"""Explicit offline project COPY into standalone development store; no reference reads."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_filetools.artifact_project import digest, emit_viewer, relative


def copy_project(source, store):
    project = json.loads((source / "project.json").read_text())
    uuid.UUID(project["project_id"])
    if project["schema"] != "filetools-project-v1":
        raise ValueError("unsupported legacy schema")
    if any(file.is_symlink() for file in source.rglob("*")):
        raise ValueError("symlink import refused")
    for artifact in project["artifacts"]:
        if artifact["path"] and digest(relative(source, artifact["path"])) != artifact["sha256"]:
            raise ValueError("artifact bytes changed")
    target = store / "projects" / project["project_id"]
    if target.exists():
        raise ValueError("project ID already exists; not merged by source hash")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    project["tasks"] = []
    project["legacy_import"] = {
        "original_project_name": project["name"],
        "mode": "review-copy; external original not followed",
    }
    reference = next(
        (a.get("external_reference") for a in project["artifacts"] if a.get("external_reference")), None
    )
    if reference:
        project["name"] = Path(reference["path"]).stem
    if project.get("adapter", {}).get("name") == "legacy-m3-quality50-v1":
        rows = json.loads((target / "content/structure.json").read_text())["pages"]
        statuses = {row["physical_page"]: row["status"] for row in rows}
        for artifact in project["artifacts"]:
            for page in artifact["pages"]:
                status = statuses.get(page.get("source_page"))
                if status in {"failed-http", "failed-format"}:
                    page["error_category"] = "remote" if status == "failed-http" else "local"
    emit_viewer(target, project)
    return project["project_id"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    a = p.parse_args()
    print(copy_project(a.source, a.store))
