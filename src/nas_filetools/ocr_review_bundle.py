"""Portable, text-safe offline review bundle and append-only local revisions.

No HTTP server, OCR execution, visual model, or production FileTools integration.
Reviewer identity is explicitly supplied, not authenticated by this local tool.
"""

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from .ocr_quality import fingerprint, sha
from .ocr_review import valid_box


ACTIONS = {"confirm_text", "edit_text", "place", "uncertain", "nonbody", "source_unreadable", "confirm_page"}
UNRESOLVED = {"unconfirmed", "uncertain", "source_unreadable"}


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def item_id(page, source, index):
    return f"p{page}-{source}-{index}"


def make_items(page, review, comparisons=None, source_damage=False):
    """Merge identical target+region+text warnings, retaining every source reason."""
    p = page["physical_page"]
    blocks = review["repaired_blocks"]
    items, merged = [], {}

    def add(kind, row, source, target=None, blocking=False):
        bbox = row.get("bbox", row.get("block_bbox"))
        text = row.get("text", row.get("block_content", ""))
        key = fingerprint([target, bbox, text])
        if key in merged:
            result = merged[key]
        else:
            result = {
                "id": item_id(p, "region", key[:20]),
                "physical_page": p,
                "printed_page": page.get("printed_page"),
                "bbox": bbox,
                "source_bbox": copy.deepcopy(bbox),
                "original_text": text,
                "current_text": text,
                "target": target,
                "status": "unconfirmed",
                "risks": [],
                "sources": [],
                "blocking": False,
                "context": [],
                "visual_review_records": [],
            }
            merged[key] = result
            items.append(result)
        if kind not in result["risks"]:
            result["risks"].append(kind)
        result["sources"].append(
            {
                "source": source,
                "reason": row.get("reason", kind),
                "raw_index": row.get("raw_index"),
                "placement": row.get("placement"),
                "recognition_score": row.get("recognition_score"),
            }
        )
        result["blocking"] |= blocking
        if target is not None:
            i = int(target.split("-b-")[-1])
            result["current_text"] = blocks[i]["block_content"]
            result["context"] = [blocks[j]["block_content"] for j in (i - 1, i + 1) if 0 <= j < len(blocks)]
        return result

    def target_for(row):
        if row.get("block_indices"):
            return item_id(p, "b", row["block_indices"][-1])
        if "raw_index" in row:
            matches = review["coverage_after"][row["raw_index"]]["matched_spans"]
            ids = {m["block_index"] for m in matches}
            if len(ids) == 1:
                return item_id(p, "b", next(iter(ids)))
        exact = [
            i
            for i, b in enumerate(blocks)
            if row.get("bbox") == b["block_bbox"] and row.get("text", "") in b["block_content"]
        ]
        return item_id(p, "b", exact[0]) if len(exact) == 1 else None

    for index, block in enumerate(blocks):
        add("body_review", block, "repaired_blocks", item_id(p, "b", index))
    for name, kind, blocking in [
        ("recovered", "recovered", True),
        ("pending_fragments", "pending", True),
        ("low_score_regions", "low_score", False),
        ("critical_regions", "critical_text", False),
    ]:
        for row in review[name]:
            add(kind, row, name, target_for(row), blocking)
    for name, kind in [
        ("order_candidates", "order"),
        ("duplicate_regions", "duplicate"),
        ("question_option_candidates", "question_option"),
    ]:
        for row in review["structure"][name]:
            entry = add(kind, row, "structure." + name, target_for(row), True)
            entry["related_targets"] = [item_id(p, "b", i) for i in row.get("block_indices", [])]
    for row in review["structure"]["original_markdown_gaps"]:
        candidates = [i for i, b in enumerate(blocks) if b.get("original_index") == row["original_index"]]
        add(
            "original_export_gap",
            row,
            "structure.original_markdown_gaps",
            item_id(p, "b", candidates[0]) if len(candidates) == 1 else None,
            False,
        )
    for n, comp in enumerate(comparisons or []):
        for row in comp["matched"]:
            if row["critical_disagreement"]:
                add(
                    "critical_disagreement",
                    {
                        "bbox": row["bbox"],
                        "text": row.get("original_text", ""),
                        "reason": "position-aligned variant critical text differs; no automatic winner",
                    },
                    f"variant-{n}",
                    target_for(row["original_lines"][0]) if len(row["original_lines"]) == 1 else None,
                    True,
                )["variant_text"] = row["processed_text"]
    for reason in page.get("screening", {}).get("image", {}).get("reasons", []):
        if "user reports" not in reason:
            add(
                "image_quality",
                {"bbox": [0, 0, page["width"], page["height"]], "text": "", "reason": reason},
                "image_metrics",
                None,
                False,
            )
    if source_damage:
        add(
            "source_damage",
            {
                "bbox": [0, 0, page["width"], page["height"]],
                "text": "",
                "reason": "用户确认物理23页源图质量很差；不可辨认处需要更清晰来源",
            },
            "user-source-quality-report",
            None,
            True,
        )
    return items


def seal(snapshot):
    snapshot.pop("revision_hash", None)
    snapshot["revision_hash"] = fingerprint(snapshot)
    return snapshot


def verify_snapshot(snapshot):
    expected = snapshot["revision_hash"]
    if fingerprint({k: v for k, v in snapshot.items() if k != "revision_hash"}) != expected:
        raise ValueError("REVISION_INTEGRITY")


def render_html(snapshot, destination, template):
    # Escaping < prevents </script>, HTML comment and executable payload injection.
    payload = {
        "snapshot": snapshot,
        "hashes": {
            "items": {i["id"]: fingerprint(i) for i in snapshot["items"]},
            "pages": {str(p["physical_page"]): fingerprint(p) for p in snapshot["pages"]},
        },
    }
    data = (
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
        .replace("<", "\\u003c")
        .replace("&", "\\u0026")
    )
    Path(destination).write_text(
        Path(template).read_text(encoding="utf-8").replace("/*__REVIEW_DATA__*/", data), encoding="utf-8"
    )


def initialize_bundle(destination, pages, config, config_sha, template):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "assets").mkdir()
    (destination / "revisions").mkdir()
    all_items, prepared = [], []
    from PIL import Image

    for page in pages:
        entry = {
            k: v
            for k, v in page.items()
            if k not in ("image_path", "native_path", "markdown_path", "review", "comparisons")
        }
        p = entry["physical_page"]
        for name, key in [("image", "image_path"), ("native", "native_path"), ("markdown", "markdown_path")]:
            suffix = Path(page[key]).suffix
            relative = f"assets/page-{p}-{name}{suffix}"
            shutil.copyfile(page[key], destination / relative)
            entry[name + "_asset"] = relative
            entry[name + "_sha256"] = sha(destination / relative)
        entry["blocks"] = [
            {**b, "id": item_id(p, "b", i)} for i, b in enumerate(page["review"]["repaired_blocks"])
        ]
        entry["review_status"] = "unconfirmed"
        items = make_items(entry, page["review"], page.get("comparisons"), page.get("source_damage", False))
        with Image.open(page["image_path"]) as image:
            for item in items:
                x0, y0, x1, y1 = item["bbox"]
                box = [
                    max(0, int(x0) - 12),
                    max(0, int(y0) - 12),
                    min(image.width, int(x1) + 12),
                    min(image.height, int(y1) + 12),
                ]
                if box[2] <= box[0] or box[3] <= box[1]:
                    raise ValueError("REGION_OUTSIDE_IMAGE")
                relative = f"assets/{item['id']}.png"
                image.crop(box).save(destination / relative)
                item["crop_asset"] = relative
                item["crop_sha256"] = sha(destination / relative)
        all_items.extend(items)
        prepared.append(entry)
    initial = seal(
        {
            "schema": "offline-ocr-review-v1",
            "revision": 0,
            "parent_hash": None,
            "config": config,
            "config_sha256": config_sha,
            "template_sha256": sha(template),
            "pages": prepared,
            "items": all_items,
            "history": [],
            "imported_ids": [],
            "boundary": "experimental developer package; no user confirmation; scores are not accuracy",
        }
    )
    write_json(destination / "revisions/revision-0.json", initial)
    (destination / "CURRENT").write_text("0\n")
    shutil.copyfile(template, destination / "template.html")
    render_html(initial, destination / "index.html", template)
    return initial


def check_assets(root, snapshot):
    if sha(root / "template.html") != snapshot["template_sha256"]:
        raise ValueError("TEMPLATE_ASSET_CHANGED")
    for page in snapshot["pages"]:
        for key in ("image", "native", "markdown"):
            relative = Path(page[key + "_asset"])
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or sha(root / relative) != page[key + "_sha256"]
            ):
                raise ValueError("SOURCE_ASSET_CHANGED")
    for item in snapshot["items"]:
        relative = Path(item["crop_asset"])
        if relative.is_absolute() or ".." in relative.parts or sha(root / relative) != item["crop_sha256"]:
            raise ValueError("CROP_ASSET_CHANGED")


def apply_receipt(base, receipt, reviewer_type, reviewer_name):
    verify_snapshot(base)
    if set(receipt) != {
        "schema",
        "receipt_id",
        "base_revision_hash",
        "reviewer_type",
        "reviewer_name",
        "operations",
    }:
        raise ValueError("RECEIPT_SCHEMA")
    if receipt["schema"] != "offline-ocr-confirmation-v1":
        raise ValueError("RECEIPT_SCHEMA")
    if not isinstance(receipt["receipt_id"], str) or not 1 <= len(receipt["receipt_id"]) <= 128:
        raise ValueError("RECEIPT_ID")
    if receipt["receipt_id"] in base["imported_ids"]:
        raise ValueError("DUPLICATE_IMPORT")
    if receipt["base_revision_hash"] != base["revision_hash"]:
        raise ValueError("STALE_REVISION")
    if reviewer_type not in ("human", "developer-agent") or not reviewer_name.strip():
        raise ValueError("REVIEWER_REQUIRED")
    if receipt["reviewer_type"] != reviewer_type or receipt["reviewer_name"] != reviewer_name:
        raise ValueError("REVIEWER_MISMATCH")
    result = copy.deepcopy(base)
    items = {i["id"]: i for i in result["items"]}
    base_items = {i["id"]: i for i in base["items"]}
    base_pages = {str(p["physical_page"]): p for p in base["pages"]}
    pages = {str(p["physical_page"]): p for p in result["pages"]}
    seen, changed_targets, page_ops = set(), set(), []
    ops = receipt["operations"]
    if not isinstance(ops, list) or not ops:
        raise ValueError("EMPTY_OPERATIONS")
    stamp = datetime.now(timezone.utc).isoformat()
    for op in ops:
        if not isinstance(op, dict) or set(op) - {
            "id",
            "action",
            "expected_hash",
            "text",
            "bbox",
            "before_target",
            "reason",
        }:
            raise ValueError("OPERATION_FIELDS")
        action, key = op.get("action"), op.get("id")
        if action not in ACTIONS or key in seen:
            raise ValueError("UNKNOWN_ACTION_OR_CONFLICT")
        seen.add(key)
        if not isinstance(op.get("reason"), str) or not op["reason"].strip():
            raise ValueError("REASON_REQUIRED")
        allowed_extra = {"edit_text": {"text"}, "place": {"bbox", "before_target"}}.get(action, set())
        if set(op) - ({"id", "action", "expected_hash", "reason"} | allowed_extra):
            raise ValueError("ACTION_FIELDS")
        if action == "confirm_page":
            if key not in pages or op.get("expected_hash") != fingerprint(base_pages[key]):
                raise ValueError("UNKNOWN_PAGE_OR_CONFLICT")
            page_ops.append(op)
            continue
        if key not in items:
            raise ValueError("UNKNOWN_ID")
        item = items[key]
        if op.get("expected_hash") != fingerprint(base_items[key]):
            raise ValueError("ITEM_CONFLICT")
        if "source_damage" in item["risks"] and action not in ("uncertain", "source_unreadable"):
            raise ValueError("DAMAGED_SOURCE_REQUIRES_UNCERTAINTY_OR_CLEARER_SOURCE")
        before = copy.deepcopy(item)
        page = pages[str(item["physical_page"])]
        target = item["target"]
        block = next((b for b in page["blocks"] if b["id"] == target), None)
        if action in ("edit_text", "place", "nonbody"):
            conflict_key = target or key
            if conflict_key in changed_targets:
                raise ValueError("TARGET_CONFLICT")
            changed_targets.add(conflict_key)
        if action == "edit_text":
            if not isinstance(op.get("text"), str) or not op["text"].strip():
                raise ValueError("EDIT_REQUIRES_TEXT")
            if block is None and "pending" not in item["risks"]:
                raise ValueError("EDIT_REQUIRES_UNAMBIGUOUS_TARGET_OR_PENDING_FRAGMENT")
            if block:
                block["block_content"] = op["text"]
            item["current_text"] = op["text"]
        if action == "place":
            bbox = op.get("bbox")
            if not valid_box(bbox) or not (
                0 <= bbox[0] < bbox[2] <= page["width"] and 0 <= bbox[1] < bbox[3] <= page["height"]
            ):
                raise ValueError("PLACEMENT_BOUNDS")
            anchor = op.get("before_target")
            if not anchor or anchor == target or not any(b["id"] == anchor for b in page["blocks"]):
                raise ValueError("PLACEMENT_TARGET")
            if block:
                page["blocks"].remove(block)
            else:
                if "pending" not in item["risks"]:
                    raise ValueError("NEW_PLACEMENT_ONLY_FOR_PENDING_FRAGMENT")
                block = {
                    "id": item["id"] + "-placed",
                    "block_label": "reviewed_fragment",
                    "block_content": item["current_text"],
                    "block_bbox": bbox,
                }
                item["target"] = block["id"]
            block["block_bbox"] = bbox
            page["blocks"].insert(next(i for i, b in enumerate(page["blocks"]) if b["id"] == anchor), block)
            item["bbox"] = bbox
        if action == "nonbody":
            if block:
                block["excluded_from_body"] = True
            item["status"] = "nonbody"
        elif action in ("uncertain", "source_unreadable"):
            item["status"] = action
        else:
            # Text confirmation alone never resolves uncertain layout/order/placement.
            unresolved_structure = any(r in item["risks"] for r in ("pending", "order", "duplicate"))
            item["status"] = (
                "text_confirmed_layout_pending"
                if action in ("confirm_text", "edit_text") and unresolved_structure
                else "confirmed"
            )
        item["reviewer_type"] = reviewer_type
        item["reviewer_name"] = reviewer_name
        item["confirmation_scope"] = "item only"
        item["source_receipt_id"] = receipt["receipt_id"]
        # Synchronize aliases without pretending the other warnings were reviewed.
        if block:
            for alias in items.values():
                if alias["target"] == item["target"]:
                    alias["current_text"] = block["block_content"]
        result["history"].append(
            {
                "id": key,
                "action": action,
                "before": before,
                "after": copy.deepcopy(item),
                "reason": op["reason"],
                "reviewer_type": reviewer_type,
                "reviewer_name": reviewer_name,
                "scope": "item",
                "source": "imported offline receipt (identity self-declared)",
                "receipt_id": receipt["receipt_id"],
                "imported_at": stamp,
            }
        )
    for op in page_ops:
        p = pages[op["id"]]
        relevant = [i for i in items.values() if i["physical_page"] == p["physical_page"]]
        blockers = [i for i in relevant if i["blocking"] and i["status"] not in ("confirmed", "nonbody")]
        if (
            reviewer_type != "human"
            or blockers
            or any(
                i["status"] in ("uncertain", "source_unreadable", "text_confirmed_layout_pending")
                for i in relevant
            )
        ):
            raise ValueError("PAGE_REQUIRES_HUMAN_AND_NO_UNRESOLVED_BLOCKERS")
        p["review_status"] = "human-page-confirmed"
        result["history"].append(
            {
                "id": op["id"],
                "action": "confirm_page",
                "scope": "whole page",
                "reviewer_type": reviewer_type,
                "reviewer_name": reviewer_name,
                "reason": op["reason"],
                "source": "imported offline receipt (identity self-declared)",
                "receipt_id": receipt["receipt_id"],
                "imported_at": stamp,
            }
        )
    affected = {i["physical_page"] for i in items.values() if i["id"] in seen}
    for p in pages.values():
        if p["physical_page"] in affected and str(p["physical_page"]) not in [op["id"] for op in page_ops]:
            p["review_status"] = "unconfirmed"  # Any new edit invalidates old whole-page acceptance.
    result["revision"] += 1
    result["parent_hash"] = base["revision_hash"]
    result["imported_ids"].append(receipt["receipt_id"])
    return seal(result)


def import_receipt(root, receipt, reviewer_type, reviewer_name):
    root = Path(root)
    lock = root / ".import-lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        current = int((root / "CURRENT").read_text())
        base = json.loads((root / f"revisions/revision-{current}.json").read_bytes())
        check_assets(root, base)
        result = apply_receipt(base, receipt, reviewer_type, reviewer_name)
        n = result["revision"]
        revision = root / f"revisions/revision-{n}.json"
        if revision.exists():
            raise ValueError("REVISION_EXISTS_REQUIRES_RECOVERY")
        write_json(revision, result)
        render_html(result, root / f"review-{n}.html", root / "template.html")
        text = "\n\n".join(
            b["block_content"]
            for p in result["pages"]
            for b in p["blocks"]
            if not b.get("excluded_from_body")
        )
        (root / f"revisions/revision-{n}.md").write_text(text + "\n", encoding="utf-8")
        (root / "CURRENT.next").write_text(str(n) + "\n")
        os.replace(root / "CURRENT.next", root / "CURRENT")
        return result
    finally:
        os.close(fd)
        lock.unlink()
