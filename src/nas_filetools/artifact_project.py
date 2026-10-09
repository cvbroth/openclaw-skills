"""Development-only portable task projects and artifact-bound feedback.

Not a production registration API. External references are never followed/copied.
Feedback identity is self-declared, not authenticated; comments do not approve content.
"""

import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import uuid

SCHEMA = "filetools-project-v1"
FEEDBACK_SCHEMA = "filetools-artifact-feedback-v1"
FORMATS = {"image", "pdf", "docx", "markdown", "json", "reference", "xlsx"}
LOCATORS = {"document", "physical_page", "source_page", "block", "paragraph", "sheet_range", "output_page"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def relative(root, value):
    part = PurePosixPath(value)
    if not value or part.is_absolute() or ".." in part.parts or "\\" in value:
        raise ValueError("unsafe relative path")
    target = Path(root).joinpath(*part.parts)
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("path escapes project")
    return target


def create_project(root, name, task_id):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    for folder in ("sources", "content", "templates", "outputs", "review", "diagnostics"):
        (root / folder).mkdir()
    project = {
        "schema": SCHEMA,
        "project_id": str(uuid.uuid4()),
        "name": name,
        "task_id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revision": 1,
        "artifacts": [],
        "templates": [],
    }
    write_json(root / "project.json", project)
    return project


def register_artifact(
    root,
    project,
    *,
    name,
    format,
    path=None,
    external_reference=None,
    version="1",
    parents=(),
    pages=None,
    preview=None,
):
    if format not in FORMATS or bool(path) == bool(external_reference):
        raise ValueError("known format and exactly one path/reference required")
    ids = {a["artifact_id"] for a in project["artifacts"]}
    if any(p not in ids for p in parents):
        raise ValueError("unknown parent")
    if external_reference:
        if not external_reference.get("sha256") or not external_reference.get("path"):
            raise ValueError("reference hash/path required; caller verifies original")
        sha = external_reference["sha256"]
    else:
        sha = digest(relative(root, path))
    item = {
        "artifact_id": str(uuid.uuid4()),
        "name": name,
        "format": format,
        "version": version,
        "sha256": sha,
        "path": path,
        "external_reference": external_reference,
        "parents": list(parents),
        "pages": pages or [],
        "preview": preview,
        "mapping_note": "左右位置独立选择，未推断页码对应关系。",
    }
    project["artifacts"].append(item)
    return item


def snapshot_template(root, project, source, *, template_id, version):
    sha = digest(source)
    path = "templates/" + sha + ".json"
    shutil.copyfile(source, relative(root, path))
    project["templates"].append({"path": path, "sha256": sha, "id": template_id, "version": version})


def locator_valid(locator, artifact):
    if not isinstance(locator, dict) or locator.get("kind") not in LOCATORS:
        raise ValueError("invalid locator")
    kind = locator["kind"]
    if kind == "document":
        if set(locator) != {"kind"}:
            raise ValueError("unexpected document locator")
        return
    allowed = {
        "physical_page": "page",
        "output_page": "page",
        "source_page": "page",
        "block": "id",
        "paragraph": "id",
        "sheet_range": "sheet",
    }
    key = allowed[kind]
    if key not in locator:
        raise ValueError("locator target missing")
    if kind in {"physical_page", "source_page", "output_page"}:
        if type(locator[key]) is not int or locator[key] < 1:
            raise ValueError("invalid page")
        if locator not in [
            p["locator"] for p in artifact.get("pages", []) + artifact.get("legacy_pages", [])
        ]:
            raise ValueError("page not registered")
    elif kind in {"block", "paragraph"}:
        if locator not in [
            p["locator"] for p in artifact.get("pages", []) + artifact.get("legacy_pages", [])
        ]:
            raise ValueError("block not registered")
    elif artifact["format"] != "xlsx" or not locator.get("range"):
        raise ValueError("sheet range unavailable")


def validate_feedback(project, receipt):
    if receipt.get("schema") != FEEDBACK_SCHEMA or receipt.get("project_id") != project["project_id"]:
        raise ValueError("wrong project/schema")
    if receipt.get("project_revision") != project["revision"]:
        raise ValueError("stale project revision")
    if receipt.get("reviewer_type") not in {"human", "developer-agent"}:
        raise ValueError("reviewer type must be explicitly declared")
    artifacts = {a["artifact_id"]: a for a in project["artifacts"]}
    comments = receipt.get("comments")
    if not isinstance(comments, list):
        raise ValueError("comments required")
    seen = set()
    for comment in comments:
        if comment.get("project_id") != project["project_id"]:
            raise ValueError("comment project mismatch")
        target = artifacts.get(comment.get("artifact_id"))
        if not target or comment.get("artifact_sha256") != target["sha256"]:
            raise ValueError("unknown artifact or stale hash")
        object_type = comment.get("object_type", "artifact")
        if object_type not in {"artifact", "source_page"}:
            raise ValueError("unknown comment object")
        if object_type == "source_page" and (
            target["artifact_id"] != project.get("source_artifact_id")
            or comment.get("locator", {}).get("kind") not in {"physical_page", "source_page"}
        ):
            raise ValueError("source comment must target registered original page")
        locator_valid(comment.get("locator"), target)
        reference = artifacts.get(comment.get("reference_artifact_id"))
        if comment.get("reference_artifact_id"):
            if not reference or comment.get("reference_sha256") != reference["sha256"]:
                raise ValueError("unknown/stale reference")
            locator_valid(comment.get("reference_locator"), reference)
        if not isinstance(comment.get("text"), str) or len(comment["text"]) > 100000:
            raise ValueError("invalid text")
        try:
            stamp = datetime.fromisoformat(comment["updated_at"].replace("Z", "+00:00"))
            if not stamp.tzinfo:
                raise ValueError("timezone required")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid update time") from exc
        key = json.dumps(
            [comment.get("object_type", "artifact"), comment["artifact_id"], comment["locator"]],
            sort_keys=True,
        )
        if key in seen:
            raise ValueError("conflicting duplicate comment target")
        seen.add(key)
    return copy.deepcopy(receipt)


def import_feedback(root, receipt):
    """Append-only revisions, optimistic concurrency; comments never alter artifacts."""
    root = Path(root)
    project = json.loads((root / "project.json").read_text())
    receipt = validate_feedback(project, receipt)
    referenced = {c["artifact_id"] for c in receipt["comments"]} | {
        c.get("reference_artifact_id") for c in receipt["comments"]
    }
    for artifact in project["artifacts"]:
        if (
            artifact["artifact_id"] in referenced
            and artifact["path"]
            and digest(relative(root, artifact["path"])) != artifact["sha256"]
        ):
            raise ValueError("registered file bytes changed")
    review = root / "review"
    lock = review / ".feedback-lock"
    with lock.open("x"):
        pass
    try:
        current = review / "feedback.json"
        previous = json.loads(current.read_text()) if current.exists() else {"revision": 0}
        if receipt.get("base_feedback_revision", 0) != previous["revision"]:
            raise ValueError("stale feedback revision / duplicate import")
        receipt_hash = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
        if previous.get("receipt_sha256") == receipt_hash:
            raise ValueError("duplicate import")
        number = previous["revision"] + 1
        record = {
            "revision": number,
            "receipt_sha256": receipt_hash,
            "receipt": receipt,
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }
        revisions = review / "feedback-history"
        revisions.mkdir(exist_ok=True)
        target = revisions / f"revision-{number}.json"
        with target.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        staging = review / ".feedback-next.json"
        with staging.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        os.replace(staging, current)
        emit_feedback_script(root, record)
        return target
    finally:
        lock.unlink()


def emit_feedback_script(root, record):
    review = Path(root) / "review"
    staging = review / ".feedback-script-next.js"
    staging.write_text(
        "window.PROJECT_FEEDBACK=" + json.dumps(record, ensure_ascii=True).replace("<", "\\u003c") + ";",
        encoding="utf-8",
    )
    os.replace(staging, review / "feedback.js")


def emit_viewer(root, project):
    """JSONP-like local scripts avoid file:// fetch restrictions; text is never HTML."""
    root = Path(root)
    if not (root / "review" / "feedback.json").exists():
        write_json(
            root / "review" / "feedback.json", {"revision": 0, "comments": [], "status": "unconfirmed"}
        )
    emit_feedback_script(root, json.loads((root / "review/feedback.json").read_text()))
    for artifact in project["artifacts"]:
        for page in artifact["pages"]:
            for key in ("image", "data", "pdf"):
                if page.get(key):
                    resource = relative(root, page[key])
                    if resource.is_file():
                        page[key + "_sha256"] = digest(resource)
                        page.pop(key + "_availability", None)
                    else:
                        # Retain the expected hash and location. Missing previews must not
                        # prevent opening a project or silently erase source provenance.
                        page[key + "_availability"] = "missing"
    write_json(root / "project.json", project)
    (root / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>项目首页</title><h1>'
        + html.escape(project["name"])
        + '</h1><p><a href="review/index.html">打开本项目产物评审</a></p>'
        + '<p><a href="../index.html">返回交付包项目列表（仅完整交付包内有效）</a></p>'
        + "<p>项目可单独移动，内部预览与评论导入仍可用。移动前请导出本机草稿。</p>",
        encoding="utf-8",
    )
    assets = Path(__file__).parent / "project_assets"
    for name in ("index.html", "viewer.js", "viewer.css", "editor.js", "workbench.js"):
        shutil.copyfile(assets / name, root / "review" / name)
    (root / "review" / "project.js").write_text(
        "window.PROJECT=" + json.dumps(project, ensure_ascii=True).replace("<", "\\u003c") + ";",
        encoding="utf-8",
    )


def page_data(root, path, data):
    target = relative(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "window.PROJECT_PAGE=" + json.dumps(data, ensure_ascii=True).replace("<", "\\u003c") + ";",
        encoding="utf-8",
    )
