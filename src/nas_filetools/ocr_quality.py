"""Experimental offline screening: three independent dimensions, never accuracy."""

import hashlib
import json
import math
from pathlib import Path

from .ocr_review import checked_rules


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_config(path):
    c = json.loads(Path(path).read_bytes())
    expected = {"version", "image", "ocr_structure", "risk", "mandatory_review", "future_visual", "scoring"}
    if set(c) != expected or not isinstance(c["version"], str) or not c["version"]:
        raise ValueError("CONFIG_SCHEMA")
    ranges = {
        "image": {
            "analysis_width": (200, 1600),
            "blur_edge_variance_min": (0, 65025),
            "contrast_p95_p5_min": (0, 255),
            "skew_degrees_max": (0, 3),
            "skew_search_degrees": (1, 3),
            "skew_gain_min": (0, 10),
            "minimum_dpi": (50, 1200),
            "edge_band_fraction": (0.001, 0.1),
            "edge_ink_fraction_max": (0, 1),
        },
        "risk": {"low_score_fraction_high": (0, 1), "low_score_fraction_medium": (0, 1)},
        "future_visual": {"normal_page_sample_fraction": (0, 1)},
    }
    for group, rules in ranges.items():
        if set(c[group]) != set(rules) | ({"trigger_risks"} if group == "future_visual" else set()):
            raise ValueError(f"CONFIG_KEYS:{group}")
        for key, (lo, hi) in rules.items():
            v = c[group][key]
            if (
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or not lo <= v <= hi
            ):
                raise ValueError(f"CONFIG_RANGE:{group}.{key}")
    if any(not isinstance(c["image"][k], int) for k in ("analysis_width", "skew_search_degrees")):
        raise ValueError("CONFIG_INTEGER")
    if c["risk"]["low_score_fraction_medium"] > c["risk"]["low_score_fraction_high"]:
        raise ValueError("CONFIG_RISK_ORDER")
    triggers = c["future_visual"]["trigger_risks"]
    allowed_triggers = {
        "source_damage",
        "pending",
        "order",
        "duplicate",
        "critical_disagreement",
        "unknown",
        "recovered",
        "question_option",
        "low_score",
    }
    if (
        not isinstance(triggers, list)
        or not set(triggers) <= allowed_triggers
        or len(triggers) != len(set(triggers))
    ):
        raise ValueError("CONFIG_VISUAL_TRIGGERS")
    ocr = c["ocr_structure"]
    if not isinstance(ocr, dict) or any(isinstance(v, bool) for v in ocr.values()):
        raise ValueError("CONFIG_OCR_TYPES")
    if not isinstance(ocr.get("version"), str) or not ocr["version"]:
        raise ValueError("CONFIG_OCR_VERSION")
    c["ocr_structure"] = checked_rules(c["ocr_structure"])
    required = {
        "pending",
        "recovered",
        "order",
        "duplicate",
        "question_option",
        "critical_disagreement",
        "source_damage",
    }
    if set(c["mandatory_review"]) != required or any(
        type(v) is not bool for v in c["mandatory_review"].values()
    ):
        raise ValueError("CONFIG_MANDATORY")
    # Structural/critical blockers may never be averaged or configured away.
    if not all(
        c["mandatory_review"][k]
        for k in ("pending", "order", "duplicate", "critical_disagreement", "source_damage")
    ):
        raise ValueError("CONFIG_CANNOT_DISABLE_BLOCKERS")
    if c["scoring"] != {"enabled": False, "normalization": None, "weights": None}:
        raise ValueError("COMPOSITE_SCORE_NOT_IMPLEMENTED")
    return c


def percentile(hist, fraction):
    threshold, count = sum(hist) * fraction, 0
    for i, n in enumerate(hist):
        count += n
        if count >= threshold:
            return i
    return 255


def image_metrics(path, settings, dpi=None):
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(path) as source:
        size = list(source.size)
        image = source.convert("L")
        image.thumbnail((settings["analysis_width"], settings["analysis_width"] * 2))
    hist = image.histogram()
    # Fixed analysis scale; exclude border introduced by edge convolution.
    edges = image.filter(ImageFilter.FIND_EDGES).crop((1, 1, image.width - 1, image.height - 1))
    blur = ImageStat.Stat(edges).var[0]
    contrast = percentile(hist, 0.95) - percentile(hist, 0.05)
    band = max(1, round(min(image.size) * settings["edge_band_fraction"]))
    strips = [
        image.crop((0, 0, image.width, band)),
        image.crop((0, image.height - band, image.width, image.height)),
        image.crop((0, 0, band, image.height)),
        image.crop((image.width - band, 0, image.width, image.height)),
    ]
    edge_ink = [sum(s.histogram()[:128]) / max(1, s.width * s.height) for s in strips]
    # Coarse horizontal ink projection. Multi-column/vertical/sidebar content is a blind spot.
    binary = image.point(lambda x: 255 if x < 128 else 0)
    projections = {}
    for angle in range(-settings["skew_search_degrees"], settings["skew_search_degrees"] + 1):
        rotated = binary.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=0)
        rows = list(rotated.resize((1, rotated.height), Image.Resampling.BOX).getdata())
        mean = sum(rows) / len(rows)
        projections[angle] = sum((v - mean) ** 2 for v in rows) / len(rows)
    best = max(projections, key=projections.get)
    gain = (projections[best] - projections[0]) / max(1, projections[0])
    skew = -best if gain > 0 and gain >= settings["skew_gain_min"] else None
    return {
        "dimensions_px": size,
        "dpi": dpi,
        "dpi_source": "explicit manifest" if dpi else "unknown",
        "analysis_dimensions_px": list(image.size),
        "edge_variance": blur,
        "contrast_p95_p5": contrast,
        "edge_ink_fractions": edge_ink,
        "skew_degrees_coarse": skew,
        "skew_projection_gain": gain,
        "coverage": [
            "grayscale edge variance",
            "global histogram",
            "coarse ±3 degree horizontal projection",
            "edge ink proxy",
            "pixel dimensions and declared DPI",
        ],
        "blind_spots": [
            "not readability truth",
            "local damaged glyphs can escape global metrics",
            "edge ink is not proof of cropping",
            "layout/sidebars confound skew",
            "DPI does not measure effective glyph resolution",
        ],
    }


def screen(metrics, review, comparisons, config, source_damage=False):
    image_reasons, unknown = [], []
    t = config["image"]
    if metrics is None:
        unknown.append("image metrics unavailable")
    else:
        for key, triggered in [
            ("blur proxy", metrics["edge_variance"] < t["blur_edge_variance_min"]),
            ("global contrast", metrics["contrast_p95_p5"] < t["contrast_p95_p5_min"]),
            ("edge ink/crop candidate", max(metrics["edge_ink_fractions"]) > t["edge_ink_fraction_max"]),
        ]:
            if triggered:
                image_reasons.append(key)
        if metrics["dpi"] is None:
            unknown.append("effective resolution/DPI unknown")
        elif metrics["dpi"] < t["minimum_dpi"]:
            image_reasons.append("declared DPI below threshold")
        if metrics["skew_degrees_coarse"] is None:
            unknown.append("skew unresolved by coarse projection")
        elif abs(metrics["skew_degrees_coarse"]) > t["skew_degrees_max"]:
            image_reasons.append("coarse skew candidate")
    if source_damage:
        image_reasons.append("user reports damaged source; needs clearer source")
    image = {
        "risk": "high"
        if source_damage
        else ("medium" if image_reasons else ("unknown" if unknown else "low")),
        "reasons": image_reasons,
        "unknown": unknown,
        "metrics": metrics,
    }
    if review is None:
        return {
            "image": image,
            "recognition": {"risk": "unknown", "reasons": ["native result missing"]},
            "structure": {"risk": "unknown", "reasons": ["coverage not checked"]},
            "review_status": "无法确定",
            "page_verified": False,
            "total_score": None,
        }
    scores = review["recognition"]["line_scores"]
    low = len(review["low_score_regions"])
    # Exclude empty native rows consistently with low_score_regions denominator.
    nonempty = sum(bool(r["text"].strip()) for r in review["coverage_before"])
    fraction = low / nonempty if nonempty else None
    differences = sum(sum(bool(m["critical_disagreement"]) for m in c["matched"]) for c in comparisons)
    recognition_reasons = []
    if low:
        recognition_reasons.append(f"{low} low native score regions")
    if review["critical_regions"]:
        recognition_reasons.append(
            f"{len(review['critical_regions'])} critical-text regions require checking"
        )
    if differences:
        recognition_reasons.append(f"{differences} variant critical disagreements")
    risk = (
        "high"
        if differences or (fraction is not None and fraction >= config["risk"]["low_score_fraction_high"])
        else "medium"
        if fraction is not None and fraction >= config["risk"]["low_score_fraction_medium"]
        else "low"
        if fraction is not None
        else "unknown"
    )
    structure = review["structure"]
    counts = {
        "pending": structure["pending_lines"],
        "recovered": structure["recovered_lines"],
        "order": len(structure["order_candidates"]),
        "duplicate": len(structure["duplicate_regions"]),
        "question_option": len(structure["question_option_candidates"]),
        "original_export_gap": len(structure["original_markdown_gaps"]),
    }
    blockers = [k for k, v in counts.items() if v and config["mandatory_review"].get(k, False)]
    if differences:
        blockers.append("critical_disagreement")
    if source_damage:
        blockers.append("source_damage")
    return {
        "image": image,
        "recognition": {
            "risk": risk,
            "reasons": recognition_reasons,
            "native_score_source": review["recognition"]["source"],
            "low_score_fraction": fraction,
            "native_mean_score": sum(scores) / len(scores) if scores else None,
            "variant_coverage": "available" if comparisons else "unknown: no same-page variants",
            "critical_disagreements": differences,
            "not_correctness_probability": True,
        },
        "structure": {
            "risk": "high" if blockers else ("medium" if any(counts.values()) else "low"),
            "reasons": blockers,
            "counts": counts,
            "coverage": "text and spatial checks; not full semantic validation",
        },
        "mandatory_review_reasons": blockers,
        "review_status": "无法确定" if counts["pending"] or source_damage else "需复核",
        "page_verified": False,
        "total_score": None,
    }
