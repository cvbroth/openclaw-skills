"""Deterministic helpers for the private OCR/M3 comparison experiment.

This module never calls a model, OCR engine, network, or production FileTools.
Raw page text and images stay in caller-selected ignored directories.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


GRADES = {"good", "minor", "major", "unknown"}
DIMENSIONS = {"clarity", "glyph_damage", "contrast_background", "deformation", "crop_obstruction"}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_comparison_config(path):
    config = json.loads(Path(path).read_bytes())
    if set(config) != {"version", "visual_quality", "candidate_selection"}:
        raise ValueError("CONFIG_SCHEMA")
    if not isinstance(config["version"], str) or not config["version"]:
        raise ValueError("CONFIG_VERSION")
    quality = config["visual_quality"]
    if set(quality) != {
        "dimensions", "grade_values", "minimum_known_weight", "risk_thresholds", "critical_caps", "mandatory_review"
    }:
        raise ValueError("QUALITY_SCHEMA")
    if set(quality["dimensions"]) != DIMENSIONS:
        raise ValueError("QUALITY_DIMENSIONS")
    weights = []
    for name, value in quality["dimensions"].items():
        if set(value) != {"weight"}:
            raise ValueError(f"DIMENSION_KEYS:{name}")
        weight = value["weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"DIMENSION_WEIGHT:{name}")
        weights.append(weight)
    if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        raise ValueError("DIMENSION_WEIGHT_SUM")
    if set(quality["grade_values"]) != {"good", "minor", "major"}:
        raise ValueError("GRADE_VALUES")
    grades = [quality["grade_values"][k] for k in ("good", "minor", "major")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100 for v in grades):
        raise ValueError("GRADE_RANGE")
    if not grades[0] > grades[1] > grades[2]:
        raise ValueError("GRADE_ORDER")
    minimum = quality["minimum_known_weight"]
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not 0 < minimum <= 1:
        raise ValueError("KNOWN_WEIGHT")
    thresholds = quality["risk_thresholds"]
    if set(thresholds) != {"normal_min", "review_min"} or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in thresholds.values()
    ) or not 0 <= thresholds["review_min"] <= thresholds["normal_min"] <= 100:
        raise ValueError("RISK_THRESHOLDS")
    caps = quality["critical_caps"]
    if set(caps) != {"critical_body_unreadable", "critical_crop_obstruction"} or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100 for v in caps.values()
    ):
        raise ValueError("CRITICAL_CAPS")
    mandatory = quality["mandatory_review"]
    if not isinstance(mandatory, list) or set(mandatory) != {
        "invalid_response", "unknown_coverage", "pending", "order", "duplicate", "critical_disagreement", "source_damage"
    } or len(mandatory) != len(set(mandatory)):
        raise ValueError("MANDATORY_REVIEW")
    selection = config["candidate_selection"]
    if set(selection) != {
        "trigger_risks", "crop_padding_px", "merge_gap_px", "maximum_regions_per_page", "normal_page_sample_fraction"
    }:
        raise ValueError("CANDIDATE_SCHEMA")
    risks = selection["trigger_risks"]
    allowed_risks = {"pending", "order", "duplicate", "critical_disagreement", "source_damage", "recovered", "question_option", "low_score", "original_export_gap"}
    if not isinstance(risks, list) or not risks or any(not isinstance(v, str) for v in risks) or len(risks) != len(set(risks)) or not set(risks) <= allowed_risks:
        raise ValueError("TRIGGER_RISKS")
    for key in ("crop_padding_px", "merge_gap_px", "maximum_regions_per_page"):
        value = selection[key]
        maximum = 50 if key == "maximum_regions_per_page" else 500
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise ValueError(f"CANDIDATE_RANGE:{key}")
    if selection["maximum_regions_per_page"] < 1:
        raise ValueError("CANDIDATE_MAXIMUM")
    sample = selection["normal_page_sample_fraction"]
    if isinstance(sample, bool) or not isinstance(sample, (int, float)) or not 0 <= sample <= 1:
        raise ValueError("SAMPLE_RANGE")
    return config


def screening_decision(quality, blockers, image_sha, config):
    """Separate a system suggestion from human acceptance, with hard blockers."""
    blockers = sorted(set(blockers))
    suggestion = quality.get("screening_suggestion", "unknown")
    if "source_damage" in blockers:
        suggestion = "需要更清晰来源"
    if blockers and suggestion != "需要更清晰来源":
        suggestion = "需人工查看"
    if suggestion == "unknown":
        suggestion = "需人工查看"
    sampled = (
        suggestion == "正常抽查"
        and int(fingerprint([image_sha, config["version"]])[:8], 16) / 2**32
        < config["candidate_selection"]["normal_page_sample_fraction"]
    )
    return {"screening_suggestion": suggestion, "blockers": blockers,
            "normal_page_sample_selected": sampled, "human_acceptance_status": "未确认"}


def _valid_box(box):
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in box)
        and box[2] > box[0]
        and box[3] > box[1]
    )


def _expanded(box, gap):
    return [box[0] - gap, box[1] - gap, box[2] + gap, box[3] + gap]


def _touches(left, right, gap):
    a, b = _expanded(left, gap), _expanded(right, gap)
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _union(boxes):
    return [
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    ]


def select_review_regions(items, page_width, page_height, settings):
    """Select by configured program risks, then merge spatial neighbours.

    Text/reference correctness never participates in selection.
    """
    triggers = set(settings["trigger_risks"])
    selected = []
    for item in items:
        matched = sorted(triggers.intersection(item.get("risks", [])))
        box = item.get("source_bbox", item.get("bbox"))
        if not matched or not _valid_box(box):
            continue
        selected.append({"ids": [item["id"]], "bbox": list(box), "risks": matched})
    groups = []
    for entry in sorted(selected, key=lambda v: (v["bbox"][1], v["bbox"][0], v["ids"][0])):
        hits = [g for g in groups if _touches(g["bbox"], entry["bbox"], settings["merge_gap_px"])]
        if not hits:
            groups.append(entry)
            continue
        base = hits[0]
        base["ids"].extend(entry["ids"])
        base["risks"] = sorted(set(base["risks"] + entry["risks"]))
        base["bbox"] = _union([base["bbox"], entry["bbox"]])
        for extra in hits[1:]:
            base["ids"].extend(extra["ids"])
            base["risks"] = sorted(set(base["risks"] + extra["risks"]))
            base["bbox"] = _union([base["bbox"], extra["bbox"]])
            groups.remove(extra)
    padding = settings["crop_padding_px"]
    for index, group in enumerate(groups):
        x0, y0, x1, y1 = group["bbox"]
        group["bbox"] = [max(0, int(x0) - padding), max(0, int(y0) - padding), min(page_width, int(x1) + padding), min(page_height, int(y1) + padding)]
        group["ids"] = sorted(set(group["ids"]))
        group["region_id"] = f"region-{index + 1:02d}"
    groups.sort(key=lambda v: (v["bbox"][1], v["bbox"][0]))
    maximum = settings["maximum_regions_per_page"]
    overflow = groups[maximum:]
    return groups[:maximum], {
        "selected_item_count": len(selected),
        "merged_region_count": len(groups),
        "returned_region_count": min(len(groups), maximum),
        "overflow_region_count": len(overflow),
        "overflow_item_ids": sorted({i for g in overflow for i in g["ids"]}),
    }


def score_visual_quality(assessment, settings):
    """Create an experimental readability score from anchored model grades."""
    if not isinstance(assessment, dict) or set(assessment.get("dimensions", {})) != DIMENSIONS:
        raise ValueError("ASSESSMENT_DIMENSIONS")
    known_weight = 0.0
    weighted = 0.0
    details = {}
    for name, rule in settings["dimensions"].items():
        value = assessment["dimensions"][name]
        if not isinstance(value, dict) or value.get("grade") not in GRADES:
            raise ValueError(f"ASSESSMENT_GRADE:{name}")
        grade = value["grade"]
        reason = value.get("reason")
        regions = value.get("regions", [])
        if reason is not None and not isinstance(reason, str):
            raise ValueError(f"ASSESSMENT_REASON:{name}")
        if not isinstance(regions, list) or any(not _valid_box(r) for r in regions):
            raise ValueError(f"ASSESSMENT_REGIONS:{name}")
        weight = rule["weight"]
        if grade != "unknown":
            known_weight += weight
            weighted += settings["grade_values"][grade] * weight
        details[name] = {"grade": grade, "weight": weight, "reason": reason, "regions": regions}
    score = None
    if known_weight + 1e-12 >= settings["minimum_known_weight"]:
        score = weighted / known_weight
    flags = assessment.get("critical_flags", [])
    allowed_flags = set(settings["critical_caps"])
    if not isinstance(flags, list) or not set(flags) <= allowed_flags or len(flags) != len(set(flags)):
        raise ValueError("ASSESSMENT_FLAGS")
    if score is not None and flags:
        score = min(score, *(settings["critical_caps"][flag] for flag in flags))
    if score is None:
        recommendation = "unknown"
    elif "critical_crop_obstruction" in flags or "critical_body_unreadable" in flags:
        recommendation = "需要更清晰来源"
    elif score >= settings["risk_thresholds"]["normal_min"]:
        recommendation = "正常抽查"
    elif score >= settings["risk_thresholds"]["review_min"]:
        recommendation = "需人工查看"
    else:
        recommendation = "需要更清晰来源"
    return {
        "experimental_readability_score": None if score is None else round(score, 2),
        "known_weight": round(known_weight, 6),
        "missing_dimensions": sorted(name for name, item in details.items() if item["grade"] == "unknown"),
        "critical_flags": flags,
        "screening_suggestion": recommendation,
        "human_acceptance_status": "未确认",
        "dimensions": details,
        "not_accuracy_or_probability": True,
    }


def validate_usage(envelope):
    if envelope.get("provider") != "minimax-portal" or envelope.get("model") != "MiniMax-M3":
        raise ValueError("MODEL_ROUTE")
    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("USAGE_MISSING")
    result = {}
    for key in ("input", "output", "cacheRead", "cacheWrite", "total"):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"USAGE_FIELD:{key}")
        result[key] = value
    cost = usage.get("cost", {}).get("total")
    result["reported_cost"] = cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
    return result


def extract_response(final):
    """Preserve raw response; salvage bounded fields after JSON syntax failures.

    Salvaged data is explicitly flagged and cannot pass strict-schema acceptance.
    No model retry or transcription correction occurs here.
    """
    try:
        value = json.loads(final)
        return value, {"strict_json": True, "salvaged_fields": []}
    except json.JSONDecodeError as error:
        record = {"strict_json": False, "error_offset": error.pos, "salvaged_fields": []}
    start, end = final.find("{"), final.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(final[start:end + 1])
            record["salvaged_fields"] = ["wrapped_json_object"]
            return value, record
        except json.JSONDecodeError:
            pass
    value = {}
    body = re.search(r'"body_text"\s*:\s*"(.*?)"\s*,\s*"nonbody_text"', final, re.S)
    if body:
        text = body.group(1)
        # Decode valid JSON escapes individually; retain unescaped internal quotes.
        text = re.sub(
            r'\\(u[0-9a-fA-F]{4}|["\\/bfnrt])',
            lambda match: json.loads('"\\' + match.group(1) + '"'),
            text,
        )
        value["body_text"] = text.replace("\\n", "\n")
        record["salvaged_fields"].append("body_text")
    quality = re.search(r'"visual_quality"\s*:\s*', final)
    if quality:
        suffix = final[quality.end():].replace('\\\\"', '\\"')
        try:
            value["visual_quality"], _ = json.JSONDecoder().raw_decode(suffix)
            record["salvaged_fields"].append("visual_quality")
        except json.JSONDecodeError:
            pass
    candidates = re.search(r'"candidate_results"\s*:\s*\[(.*?)\]\s*,\s*"visual_quality"', final, re.S)
    if candidates:
        rows = []
        for match in re.finditer(r'\{\s*"id"\s*:\s*"([^"\n]+)"(.*?)(?=\}\s*,\s*\{\s*"id"|\}\s*$)', candidates.group(1), re.S):
            tail = match.group(2)
            status = re.search(r'"status"\s*:\s*"(keep|replace|uncertain|nonbody|reorder)"', tail)
            replacement = re.search(r'"replacement"\s*:\s*(null|"(?:\\.|[^"\\])*")\s*,\s*"reason"', tail)
            if not status or not replacement:
                continue
            rows.append({"id": match.group(1), "status": status.group(1),
                         "replacement": json.loads(replacement.group(1)),
                         "reason": "malformed JSON: retain raw response for full evidence"})
        if rows:
            value["candidate_results"] = rows
            record["salvaged_fields"].append("candidate_results_ids_status_replacement_only")
    return value, record


def apply_review_suggestions(page, items, blocks, results):
    """Build an unconfirmed derivative; never import model output as human review.

    Unknown/duplicate/missing IDs or conflicting target edits block application.
    Position and non-body proposals remain review candidates in this experiment.
    """
    import copy

    item_map = {item["id"]: item for item in items}
    ids = [row.get("id") for row in results]
    if len(ids) != len(set(ids)) or set(ids) != set(item_map):
        raise ValueError("CANDIDATE_ID_COVERAGE")
    proposed = {}
    decisions = []
    for row in results:
        item = item_map[row["id"]]
        status = row.get("status")
        if status not in {"keep", "replace", "uncertain", "nonbody", "reorder"}:
            raise ValueError("CANDIDATE_STATUS")
        decision = {"id": item["id"], "model_status": status, "applied": False, "human_status": "未确认"}
        target = item.get("target")
        if status == "replace":
            replacement = row.get("replacement")
            if not isinstance(replacement, str) or not replacement.strip():
                raise ValueError("EMPTY_REPLACEMENT")
            if target is None:
                decision["reason"] = "no reliable body target; retained as proposal"
            elif len(replacement) < len(item["current_text"]) * 0.5:
                decision["reason"] = "replacement discards most target text; requires human review"
            else:
                if target in proposed and proposed[target] != replacement:
                    raise ValueError("TARGET_EDIT_CONFLICT")
                proposed[target] = replacement
                decision["applied"] = True
        elif status in {"uncertain", "nonbody", "reorder"}:
            decision["reason"] = "requires source/position review; no automatic body exclusion or reorder"
        decisions.append(decision)
    revised = copy.deepcopy(blocks)
    for target, replacement in proposed.items():
        prefix = f"p{page}-b-"
        if not target.startswith(prefix):
            raise ValueError("TARGET_PAGE")
        index = int(target[len(prefix):])
        if not 0 <= index < len(revised):
            raise ValueError("TARGET_INDEX")
        revised[index]["block_content"] = replacement
    return revised, decisions
