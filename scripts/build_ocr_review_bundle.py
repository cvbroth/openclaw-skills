"""Build a private offline bundle from an explicit successful OCR checkpoint."""

import argparse
from collections import Counter
import json
from pathlib import Path
import resource
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_filetools.ocr_quality import fingerprint, image_metrics, load_config, screen, sha  # noqa: E402
from nas_filetools.ocr_review import reconcile  # noqa: E402
from nas_filetools.ocr_review_bundle import initialize_bundle, write_json  # noqa: E402


def build(args):
    start = time.monotonic()
    config = load_config(args.config)
    checkpoint = json.loads(args.batch.read_bytes())["pages"]
    metadata = json.loads(args.metadata.read_bytes()) if args.metadata else {}
    selected = args.pages or sorted(map(int, checkpoint))
    if len(selected) != len(set(selected)) or any(str(p) not in checkpoint for p in selected):
        raise ValueError("EXPLICIT_PAGE_RANGE_NOT_IN_CHECKPOINT_OR_DUPLICATE")
    pages, public = [], []
    for p in selected:
        record = checkpoint[str(p)]
        if record["status"] not in ("SUCCEEDED", "REUSED_PRIOR_SUCCESS"):
            raise ValueError("CHECKPOINT_NOT_SUCCESSFUL")
        image = args.images / f"page-{p}.png"
        if sha(image) != record["input_image_sha256"]:
            raise ValueError("SOURCE_IMAGE_HASH")
        native_path = (
            Path(record["native_json"])
            if record.get("native_json")
            else Path(record["result_directory"]) / f"page-{p}" / f"page-{p}_res.json"
        )
        markdown = native_path.with_name(f"page-{p}.md")
        original = (sha(native_path), sha(markdown), sha(image))
        native = json.loads(native_path.read_bytes())
        review = reconcile(native, p, markdown.read_text(), config["ocr_structure"])
        comparisons = []
        if args.comparisons:
            for variant in ("contrast125", "median3-contrast125"):
                path = args.comparisons / f"{variant}-page-{p}-comparison.json"
                if path.is_file():
                    comparisons.append(json.loads(path.read_bytes()))
        meta = metadata.get(str(p), {})
        metrics = image_metrics(image, config["image"], meta.get("dpi"))
        damage = meta.get("source_damage", False)
        quality = screen(metrics, review, comparisons, config, damage)
        reasons = set(quality.get("mandatory_review_reasons", []))
        if quality["image"]["unknown"] or not comparisons:
            reasons.add("unknown")
        if review["low_score_regions"]:
            reasons.add("low_score")
        triggers = sorted(reasons & set(config["future_visual"]["trigger_risks"]))
        sampled = (
            int(fingerprint([original[2], config["version"]])[:8], 16) / 2**32
            < config["future_visual"]["normal_page_sample_fraction"]
        )
        quality["future_visual"] = {
            "trigger_reasons": triggers,
            "normal_page_sample_selected": bool(not triggers and sampled),
            "performed": False,
            "boundary": "reserved records only; no model dependency or call",
        }
        pages.append(
            {
                "physical_page": p,
                "printed_page": meta.get("printed_page"),
                "printed_page_evidence": meta.get(
                    "printed_page_evidence", "unknown; not inferred from arithmetic"
                ),
                "source_damage": damage,
                "width": native["width"],
                "height": native["height"],
                "image_path": image,
                "native_path": native_path,
                "markdown_path": markdown,
                "review": review,
                "comparisons": comparisons,
                "screening": quality,
            }
        )
        public.append(
            {
                "physical_page": p,
                "image_sha256": original[2],
                "native_sha256": original[0],
                "original_markdown_sha256": original[1],
                "screening": quality,
            }
        )
        if original != (sha(native_path), sha(markdown), sha(image)):
            raise ValueError("ORIGINAL_CHANGED")
    template = Path(__file__).resolve().parents[1] / "src/nas_filetools/review_assets/offline.html"
    snapshot = initialize_bundle(args.output, pages, config, sha(args.config), template)
    (args.output / "README.txt").write_text(
        "离线复核包（开发实验，未接入生产）\n解压整个目录，再打开 index.html；无需联网。\n"
        "可按页、风险、状态筛选；整页入口与裁片为原图。选择操作并填写理由，加入草稿后导出确认JSON。\n"
        "长时间复核请下载草稿JSON；浏览器不自动持久保存。重新打开同版本可导入草稿。\n"
        "将确认JSON交回开发侧导入；导入时校验源图、原始OCR、版本、目标与冲突。\n"
        "原始文件与历史修订不改；新修订产生 review-N.html 与 revisions/revision-N.{json,md}。\n"
        "用户身份为自行声明，本地包不提供账号认证。开发Agent不能冒充用户。\n"
        "某条确认不等于整页通过。源图看不清请选择原图无法辨认，需更清晰来源。\n"
        "数字、否定词、编号须对照原图。高分、无报警不表示正确。预处理默认关闭。\n",
        encoding="utf-8",
    )
    evidence = {
        "schema": "offline-review-screening-evidence-v1",
        "config_version": config["version"],
        "config_sha256": sha(args.config),
        "initial_revision_hash": snapshot["revision_hash"],
        "pages": public,
        "items": len(snapshot["items"]),
        "dimension_risk_counts": {
            d: dict(Counter(p["screening"][d]["risk"] for p in public))
            for d in ("image", "recognition", "structure")
        },
        "whole_pages_confirmed": 0,
        "all_initially_unconfirmed": all(i["status"] == "unconfirmed" for i in snapshot["items"]),
        "elapsed_seconds": time.monotonic() - start,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "inference_runs": 0,
        "model_calls": 0,
        "preprocessing_default": False,
        "calibration": "uncalibrated experimental rules; not accuracy",
    }
    if args.public_summary:
        if args.public_summary.exists():
            raise ValueError("PUBLIC_EVIDENCE_EXISTS")
        write_json(args.public_summary, evidence)
    if args.zip:
        if args.zip.exists():
            raise ValueError("ZIP_EXISTS")
        with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(args.output.rglob("*")):
                if path.is_file():
                    archive.write(path, str(Path(args.output.name) / path.relative_to(args.output)))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("batch", "images", "config", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("metadata", "comparisons", "public-summary", "zip"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument(
        "--pages", type=int, nargs="+", help="explicit subset, default checkpoint only; no discovery"
    )
    args = parser.parse_args()
    print(json.dumps(build(args), ensure_ascii=False))
