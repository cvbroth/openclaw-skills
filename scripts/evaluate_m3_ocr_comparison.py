"""Evaluate five explicit private pages without new OCR/model requests.

Reference text must have been checked against source images. Model responses
never supply truth. Outputs contain business text; keep them out of Git.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_filetools.ocr_m3_comparison import (  # noqa: E402
    apply_review_suggestions, extract_response, load_comparison_config,
    score_visual_quality, screening_decision, validate_usage,
)
from nas_filetools.ocr_quality import sha  # noqa: E402
from evaluate_ocr_review import roi_hypothesis  # noqa: E402
from score_ocr_blocks import character_errors  # noqa: E402


PAGES = (11, 23, 114, 127, 131)


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def question_blocks(text):
    text = text.replace("\\n", "\n")
    markers = list(re.finditer(r"(?m)^\s*(\d{1,3})[.．、]\s*", text))
    return [
        (int(m.group(1)), text[m.start():markers[i + 1].start() if i + 1 < len(markers) else len(text)].strip())
        for i, m in enumerate(markers)
    ]


def direct_hypothesis(text, reference):
    blocks = question_blocks(text)
    block_id = reference["id"]
    if block_id == "p23-confirmable-option-c":
        # Fifth visible question, not an inferred ambiguous printed number.
        body = blocks[4][1] if len(blocks) >= 5 else ""
        found = re.search(r"(?m)^\s*C(?:[.．、]|\s).*?(?=^\s*D(?:[.．、]|\s)|\Z)", body, re.S)
        return found.group(0).strip() if found else ""
    if block_id == "p23-confirmable-q130-options":
        body = next((s for n, s in blocks if n == 130), "")
        marker = re.search(r"(?m)^\s*A(?:[.．、]|\s)", body)
        return body[marker.start():].strip() if marker else ""
    number = int(re.search(r"-q(\d+)$", block_id).group(1))
    return next((s for n, s in blocks if n == number), "")


def block_roi(blocks, reference, width, height):
    bw, bh = reference["bbox_basis"]
    box = [v * (width / bw if i % 2 == 0 else height / bh) for i, v in enumerate(reference["bbox_on_basis"])]
    selected = [b for b in blocks if box[0] <= (b["block_bbox"][0] + b["block_bbox"][2]) / 2 <= box[2]
                and box[1] <= (b["block_bbox"][1] + b["block_bbox"][3]) / 2 <= box[3]]
    return "\n".join(b["block_content"] for b in selected)


def evaluate(args):
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS")
    args.output.mkdir(parents=True)
    config = load_comparison_config(args.config)
    snapshot = json.loads(args.snapshot.read_text())
    manifest = json.loads(args.manifest.read_text())
    refs = json.loads(args.reference.read_text())["blocks"]
    extra = json.loads(args.additional_reference.read_text())
    refs = [r for r in refs if r["physical_page"] in PAGES]
    refs += [{**r, "review_method": extra["review_method"]} for r in extra["blocks"]]
    checkpoint = json.loads(args.batch.read_text())["pages"]
    pages, private, scores, sources = [], {}, [], {}
    for page in PAGES:
        record = checkpoint[str(page)]
        native_path = Path(record["native_json"]) if record.get("native_json") else Path(record["result_directory"]) / f"page-{page}" / f"page-{page}_res.json"
        native = json.loads(native_path.read_text())
        review = json.loads((args.reviews / f"page-{page}" / "review.json").read_text())
        image_path = args.images / f"page-{page}.png"
        if sha(image_path) != record["input_image_sha256"]:
            raise ValueError("IMAGE_HASH")
        selected = next(p for p in manifest["pages"] if p["physical_page"] == page)
        ids = {i for region in selected["regions"] for i in region["ids"]}
        items = [i for i in snapshot["items"] if i["physical_page"] == page and i["id"] in ids]
        prior_page = next(p for p in snapshot["pages"] if p["physical_page"] == page)
        current = {"native": native, "items": items}
        route_rows = {}
        for route in ("direct", "review"):
            prefix = args.responses / route / f"page-{page}"
            envelope = json.loads(prefix.with_suffix(".response.json").read_text())
            value, parsing = extract_response(envelope.get("final", ""))
            log = prefix.with_suffix(".stderr").read_text()
            row = {
                "ok": envelope.get("ok"), "model": envelope.get("model"), "provider": envelope.get("provider"),
                "usage": validate_usage(envelope), "parse": parsing,
                "elapsed_seconds": float(prefix.with_suffix(".finished").read_text()) - float(prefix.with_suffix(".started").read_text()),
                "view_image_log_mentions": log.count("view_image"),
                "image_tool_calls": len(re.findall(r"tool start:.*?tool=view_image", log)),
                "provider_http_requests": len(re.findall(r"\[model-fetch\] start provider=minimax-portal", log)),
                "tool_names": sorted(set(re.findall(r"tool=(\w+)", log))),
                "provider_200": "status=200" in log,
                "response_sha256": sha(prefix.with_suffix(".response.json")),
                "actual_prompt_sha256": sha(args.responses.parent / "prompts" / f"page-{page}-{route}.md"),
                "prepared_prompt_sha256": selected[route + "_prompt_sha256"],
            }
            row["prompt_matches_preparation"] = row["actual_prompt_sha256"] == row["prepared_prompt_sha256"]
            try:
                row["quality"] = score_visual_quality(value["visual_quality"], config["visual_quality"])
            except (KeyError, ValueError) as error:
                row["quality"] = {"screening_suggestion": "unknown", "error": str(error), "human_acceptance_status": "未确认"}
            current[route] = value
            blockers = []
            if not parsing["strict_json"]:
                blockers.append("invalid_response")
            if not value.get("coverage", {}).get("whole_page_viewed"):
                blockers.append("unknown_coverage")
            if route == "review":
                if review["structure"]["pending_lines"]:
                    blockers.append("pending")
                if review["structure"]["order_candidates"]:
                    blockers.append("order")
                if review["structure"]["duplicate_regions"]:
                    blockers.append("duplicate")
                if prior_page.get("screening", {}).get("recognition", {}).get("critical_disagreements"):
                    blockers.append("critical_disagreement")
                if prior_page.get("source_damage"):
                    blockers.append("source_damage")
            row["system_screening"] = screening_decision(row["quality"], blockers, sha(image_path), config)
            route_rows[route] = row
        revised, decisions = apply_review_suggestions(
            page, items, review["repaired_blocks"], current["review"].get("candidate_results", [])
        )
        current["revised_blocks"] = revised
        current["decisions"] = decisions
        current["source_review"] = review
        route_rows["review"]["candidate_status_counts"] = dict(Counter(d["model_status"] for d in decisions))
        route_rows["review"]["applied_unconfirmed_text_edits"] = sum(d["applied"] for d in decisions)
        pages.append({"physical_page": page, "image_sha256": sha(image_path), "native_sha256": sha(native_path),
                      "local_structure": review["structure"], "candidate_receipt": selected["candidate_receipt"], "routes": route_rows})
        sources[page] = current
        private[str(page)] = current
    for reference in refs:
        page = reference["physical_page"]
        source = sources[page]
        if not reference.get("image_verified") or sha(args.images / f"page-{page}.png") != reference["reference_image_sha256"]:
            raise ValueError("REFERENCE_SOURCE")
        native, review = source["native"], source["source_review"]
        hypotheses = {
            "local_raw": roi_hypothesis(native, reference)[0],
            "local_native_assembly": block_roi(native["parsing_res_list"], reference, native["width"], native["height"]),
            "local_recovered": block_roi(review["repaired_blocks"], reference, native["width"], native["height"]),
            "m3_direct": direct_hypothesis(source["direct"].get("body_text", ""), reference),
            "local_m3_review": block_roi(source["revised_blocks"], reference, native["width"], native["height"]),
        }
        row = {"id": reference["id"], "physical_page": page,
               "reference_characters": len("".join(reference["reference"].split())),
               "reference_sha256": __import__("hashlib").sha256(reference["reference"].encode()).hexdigest(),
               "scores": {k: character_errors(reference["reference"], v) for k, v in hypotheses.items()}}
        scores.append(row)
        private.setdefault("reference_blocks", []).append({**reference, "hypotheses": hypotheses, "scores": row["scores"]})
    summary = {"schema": "ocr-m3-comparison-evidence-v1", "config_sha256": sha(args.config),
               "prompt_preparation_config_sha256": manifest["config_sha256"],
               "config_version": config["version"], "pages": pages, "reference_scores": scores,
               "reference_status": "开发侧看图核对，未经用户确认", "scope": "selected blocks; not page/book accuracy",
               "totals": {}}
    for route in scores[0]["scores"]:
        count = sum(r["scores"][route]["reference_characters"] for r in scores)
        errors = sum(r["scores"][route]["edit_distance"] for r in scores)
        summary["totals"][route] = {"reference_characters": count, "edit_distance": errors, "cer": errors / count}
    # Structure records may contain business text: private only. Public evidence
    # retains counts, never candidate or order-candidate strings.
    write(args.output / "private-analysis.json", private)
    write(args.output / "summary-private.json", summary)
    for page in summary["pages"]:
        structure = page.pop("local_structure")
        page["local_structure_counts"] = {k: v for k, v in structure.items() if isinstance(v, (int, float))}
        for route in page["routes"].values():
            quality = route.get("quality", {})
            quality["dimensions"] = {k: {"grade": v["grade"], "weight": v["weight"], "region_count": len(v["regions"])}
                                     for k, v in quality.get("dimensions", {}).items()}
    write(args.output / "summary-redacted.json", summary)
    print(json.dumps(summary["totals"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("config", "snapshot", "manifest", "reference", "additional-reference", "batch", "reviews", "images", "responses", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    evaluate(parser.parse_args())
