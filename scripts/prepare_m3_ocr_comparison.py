"""Prepare private, deterministic prompts/crops for an OCR/M3 comparison.

The script does not call a model. Outputs contain source text and must stay in an
ignored private directory.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_filetools.ocr_m3_comparison import (  # noqa: E402
    fingerprint,
    load_comparison_config,
    select_review_regions,
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(value, encoding="utf-8")


QUALITY_INSTRUCTIONS = """逐项评价原图本身，不参考文字是否通顺或OCR分数：
- clarity（清晰度）
- glyph_damage（局部字形缺损、粘连）
- contrast_background（对比度和背景干扰）
- deformation（变形、弯曲、倾斜）
- crop_obstruction（裁切、遮挡）
每项grade只能是good/minor/major/unknown。good=检查范围内稳定清楚；minor=有局部轻微问题但无需猜测仍可辨认；major=关键正文或多处必须猜测/无法辨认；unknown=图片未覆盖或无法判断。reason须基于肉眼图像，regions用原图像素坐标[x0,y0,x1,y1]。不要给总分。
critical_flags只可含critical_body_unreadable、critical_crop_obstruction；关键正文不可辨认或被裁掉才使用。"""


def direct_prompt(page, image_path, width, height):
    return f"""这是独立的MiniMax M3直接看图转写请求，物理页{page}。必须使用内置图片查看工具实际打开 `{image_path}`。原图尺寸{width}×{height}像素。

禁止读取同目录其他文件，禁止OCR/文件提取/shell/Python/搜索，禁止引用既有OCR、参考文字、历史错误标签或常识补全。只依据这张原图。若图片无法打开，返回{{\"schema\":\"m3-direct-v1\",\"image_read\":false}}。

完整转写正文中的章节标题、题号、题干和A-D等选项，保持视觉阅读顺序。页眉、页脚、侧栏另列为nonbody_text，不混入body_text。不要润色、纠错、补答案；看不清写 `⟦无法辨认⟧`，并在uncertain_regions给坐标与原因。

{QUALITY_INSTRUCTIONS}

只返回严格JSON，不加Markdown：
{{"schema":"m3-direct-v1","physical_page":{page},"image_read":true,"tool_observed_dimensions_px":[宽,高],"body_text":"...","nonbody_text":["..."],"uncertain_regions":[{{"bbox":[x0,y0,x1,y1],"reason":"..."}}],"visual_quality":{{"dimensions":{{"clarity":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"glyph_damage":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"contrast_background":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"deformation":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"crop_obstruction":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}}}},"critical_flags":[]}},"coverage":{{"whole_page_viewed":true,"notes":"..."}}}}
"""


def review_prompt(page, image_path, width, height, regions, item_map, container_root):
    candidates = []
    crop_paths = []
    for region in regions:
        if region["bbox"] == [0, 0, width, height]:
            crop_paths.append(image_path)
        else:
            crop_paths.append(f"{container_root}/page-{page}-{region['region_id']}.png")
        for item_id in region["ids"]:
            item = item_map[item_id]
            candidates.append(
                {
                    "id": item_id,
                    "bbox": item.get("source_bbox", item["bbox"]),
                    "risks": [r for r in item["risks"] if r != "source_damage"],
                    "current_text": item["current_text"],
                    "context": item.get("context", []),
                    "crop": crop_paths[-1],
                }
            )
    payload = json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    paths = json.dumps(crop_paths, ensure_ascii=False)
    return f"""这是独立的“本地OCR＋MiniMax M3疑点复核”请求，物理页{page}。必须用内置图片查看工具先打开整页 `{image_path}`，再逐一打开裁片{paths}。原图尺寸{width}×{height}像素。

禁止OCR工具、文件提取、shell、Python、搜索和外部知识。只复核程序按固定风险规则选出的候选，不重写全文，不根据答案或参考文本挑区域。输入OCR可能错；原图也可能无法辨认。不得凭上下文猜补。

候选JSON：{payload}

每个候选ID必须恰好返回一次：keep=原文字得到图片支持；replace=图片明确支持不同文字；uncertain=无法可靠裁定；nonbody=图像明确证明非正文；reorder=图片明确支持位置/顺序调整。replace时给replacement，其他状态replacement为null。reason说明可见依据；evidence_bbox用原图像素坐标。不要修改候选外的全文。

{QUALITY_INSTRUCTIONS}

只返回严格JSON，不加Markdown：
{{"schema":"m3-review-v1","physical_page":{page},"image_read":true,"tool_observed_dimensions_px":[宽,高],"candidate_results":[{{"id":"...","status":"keep|replace|uncertain|nonbody|reorder","replacement":null,"reason":"...","evidence_bbox":[x0,y0,x1,y1],"order_target":null}}],"visual_quality":{{"dimensions":{{"clarity":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"glyph_damage":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"contrast_background":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"deformation":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}},"crop_obstruction":{{"grade":"good|minor|major|unknown","reason":"...","regions":[]}}}},"critical_flags":[]}},"coverage":{{"whole_page_viewed":true,"candidate_ids_reviewed":[],"notes":"..."}}}}
"""


def prepare(args):
    config = load_comparison_config(args.config)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS")
    args.output.mkdir(parents=True)
    (args.output / "prompts").mkdir()
    (args.output / "assets").mkdir()
    page_records = {p["physical_page"]: p for p in snapshot["pages"]}
    all_items = snapshot["items"]
    manifest = {
        "schema": "m3-ocr-comparison-input-v1",
        "config_version": config["version"],
        "config_sha256": sha(args.config),
        "source_revision_hash": snapshot["revision_hash"],
        "pages": [],
    }
    from PIL import Image

    for page in args.pages:
        if page not in page_records:
            raise ValueError(f"PAGE_NOT_IN_SNAPSHOT:{page}")
        record = page_records[page]
        source = args.images / f"page-{page}.png"
        if sha(source) != record["image_sha256"]:
            raise ValueError(f"IMAGE_HASH:{page}")
        page_asset = args.output / "assets" / f"page-{page}.png"
        shutil.copyfile(source, page_asset)
        with Image.open(page_asset) as image:
            width, height = image.size
            if [width, height] != [record["width"], record["height"]]:
                raise ValueError(f"IMAGE_SIZE:{page}")
            items = [i for i in all_items if i["physical_page"] == page]
            regions, receipt = select_review_regions(
                items, width, height, config["candidate_selection"]
            )
            for region in regions:
                crop = image.crop(tuple(region["bbox"]))
                crop.save(args.output / "assets" / f"page-{page}-{region['region_id']}.png")
        container_page = f"{args.container_root}/assets/page-{page}.png"
        item_map = {i["id"]: i for i in items}
        write(
            args.output / "prompts" / f"page-{page}-direct.md",
            direct_prompt(page, container_page, width, height),
        )
        write(
            args.output / "prompts" / f"page-{page}-review.md",
            review_prompt(page, container_page, width, height, regions, item_map, args.container_root + "/assets"),
        )
        manifest["pages"].append(
            {
                "physical_page": page,
                "image_sha256": sha(page_asset),
                "dimensions_px": [width, height],
                "candidate_receipt": receipt,
                "regions": [
                    {
                        **region,
                        "crop_sha256": sha(args.output / "assets" / f"page-{page}-{region['region_id']}.png"),
                    }
                    for region in regions
                ],
                "direct_prompt_sha256": sha(args.output / "prompts" / f"page-{page}-direct.md"),
                "review_prompt_sha256": sha(args.output / "prompts" / f"page-{page}-review.md"),
            }
        )
    manifest["manifest_hash"] = fingerprint(manifest)
    write(args.output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container-root", required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True)
    print(json.dumps(prepare(parser.parse_args()), ensure_ascii=False))
