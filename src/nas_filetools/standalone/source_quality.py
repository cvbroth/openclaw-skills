"""Evidence-bound source image assessments. Never infers quality from conversion success."""

import hashlib
import json
from pathlib import Path
from PIL import Image
from ..artifact_project import digest, relative

LEVELS = {"good", "usable_with_defects", "poor", "undetermined"}


def source_artifact(project):
    if project.get("source_artifact_id"):
        return next(a for a in project["artifacts"] if a["artifact_id"] == project["source_artifact_id"])
    return next(
        (
            a
            for a in project["artifacts"]
            if a["format"] in {"reference", "image", "pdf"} and not a["parents"]
        ),
        None,
    )


def migrate(root, project):
    """Idempotent append-only evaluation migration, preserving old payloads/receipts."""
    root = Path(root)
    source = source_artifact(project)
    if not source:
        return
    project["source_artifact_id"] = source["artifact_id"]
    project.setdefault("source_evaluations", [])
    project.setdefault("legacy_quality_records", [])
    # Source pages with same position+image bytes are one display entry, all task origins retained.
    merged = {}
    for page in source["pages"]:
        key = (json.dumps(page["locator"], sort_keys=True), page.get("image_sha256"))
        if not key[1]:
            key = (*key, page.get("image"))
        if key not in merged:
            merged[key] = {**page, "task_ids": list(page.get("task_ids", []))}
        if page.get("task_id") and page["task_id"] not in merged[key]["task_ids"]:
            merged[key]["task_ids"].append(page["task_id"])
    source["pages"] = list(merged.values())
    ids = {r["evaluation_id"] for r in project["source_evaluations"] + project["legacy_quality_records"]}

    def add(
        quality,
        submitted,
        locator,
        task,
        attempt,
        model,
        timestamp,
        evidence_path,
        policy="historical-original-policy; not re-evaluated",
    ):
        identity = [source["artifact_id"], locator, task, attempt, evidence_path]
        rid = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        if rid in ids:
            return
        candidates = [
            p
            for p in source["pages"]
            if p["locator"] == locator and p.get("image_sha256") == (submitted or {}).get("sha256")
        ]
        reason = None
        if not isinstance(quality, dict) or quality.get("overall_quality") not in LEVELS:
            reason = "quality schema unavailable or invalid; no inferred grade"
        elif not candidates:
            reason = "submitted image not proven to match source page preview"
        else:
            image = relative(root, candidates[0]["image"])
            try:
                with Image.open(image) as picture:
                    dims = picture.size
                if digest(image) != submitted["sha256"] or dims != (
                    submitted.get("width"),
                    submitted.get("height"),
                ):
                    reason = "submitted image hash/dimensions mismatch"
            except (OSError, ValueError):
                reason = "source page image unavailable or unreadable; association not verified"
        record = {
            "evaluation_id": rid,
            "task_id": task,
            "attempt": attempt,
            "model": model,
            "assessed_at": timestamp,
            "time_status": "recorded" if timestamp else "unknown",
            "quality": quality,
            "evidence_path": evidence_path,
            "submitted_image": submitted,
            "uncalibrated_model_self_assessment": True,
            "policy": policy,
        }
        if reason:
            record["migration_reason"] = reason
            project["legacy_quality_records"].append(record)
        else:
            record.update(
                source_artifact_id=source["artifact_id"],
                source_sha256=source["sha256"],
                source_version=source["version"],
                source_locator=locator,
            )
            project["source_evaluations"].append(record)
        ids.add(rid)

    for task in project.get("tasks", []):
        for number, page in task["pages"].items():
            for attempt in page["attempts"]:
                if not attempt.get("result"):
                    continue
                result = json.loads(relative(root, attempt["result"]).read_text())
                if result.get("quality") is None:
                    continue  # Local OCR never overwrites a visual assessment.
                add(
                    result["quality"],
                    result.get("submitted_input"),
                    {"kind": "physical_page", "page": int(number)},
                    task["task_id"],
                    attempt["attempt"],
                    result.get("returned_model") or task["engine"]["model"],
                    attempt.get("finished_at") or task.get("finished_at"),
                    attempt["result"],
                    result.get("quality_policy", "historical-original-policy; not re-evaluated"),
                )
    if project.get("adapter", {}).get("name") == "legacy-m3-quality50-v1":
        path = root / "content/structure.json"
        for page in json.loads(path.read_text())["pages"]:
            if len(page.get("attempts", [])) != 1:
                # This legacy export has page-level quality, not attempt-level quality.
                # Without one unambiguous receipt do not assign it to any request.
                if page.get("quality") is not None or page.get("quality_raw"):
                    add(
                        page.get("quality"),
                        None,
                        {"kind": "physical_page", "page": page["physical_page"]},
                        project["task_id"],
                        0,
                        None,
                        None,
                        "content/structure.json#page-" + str(page["physical_page"]),
                    )
                continue
            for attempt in page.get("attempts", []):
                receipt = attempt.get("receipt", {})
                if page.get("quality") is None and not page.get("quality_raw"):
                    continue
                add(
                    page.get("quality"),
                    receipt.get("submitted"),
                    {"kind": "physical_page", "page": page["physical_page"]},
                    project["task_id"],
                    receipt.get("attempt", 1),
                    receipt.get("returned_model") or receipt.get("requested_model"),
                    receipt.get("finished_at"),
                    "content/structure.json#page-" + str(page["physical_page"]),
                )
    project["source_quality_schema"] = "source-image-assessment-v1"
