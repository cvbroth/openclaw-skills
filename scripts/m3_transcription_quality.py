"""Bounded direct-PNG transcription plus uncalibrated visual quality self-assessment.

Reuses the existing request/credential/resume mechanism. No OCR input or corrections.
Private response payloads must never be committed.
"""

import argparse
import json
from pathlib import Path
import random
import re
import shutil
import zipfile

import m3_image_transcription as base

PROMPT = """仅依据本张原图，完成两个独立输出。没有OCR或参考答案。
A：按原图阅读顺序逐字转写为Markdown，保留全部现存题号、题干、选项、否定词、数字和符号，以及页边文字。不解题、不润色、不按知识纠错、不补全、不重编号。难辨字符在原位置标记【无法辨认】，不得跳过或把凭上下文猜测写成看清了。
B：根据图片可见情况判断能否可靠读取，不以自己转写流畅代替看图。good：主要正文及关键字符可直接识别，未见影响读取的缺陷；usable_with_defects：部分可直接识别，部分模糊、遮挡或缺失，可能需要推测，这些文字仍须标疑点；poor：整体难读或关键正文明显缺失、模糊、遮挡；undetermined：输入或观察不足。轻微噪点或无关页边污迹不应单独导致请求更清晰来源。不要强制判任何页差。
只按以下标记输出，标记外不输出解释：
<transcription_markdown>
原样转写Markdown
</transcription_markdown>
<quality_json>
{"physical_page": 当前提供的PDF物理页码, "overall_quality": "good|usable_with_defects|poor|undetermined", "suggested_action": "keep|check_original|request_clearer_source|undetermined", "visible_defects": [], "affected_area": "上部/中部/下部及简短位置描述，无缺陷可写无；不要编造精确坐标", "evidence": ["最多3条简短可对照图片的观察"], "assessment_confidence": "high|medium|low", "uncertainty_note": "说明无法确认的字形、覆盖或其他限制；confidence是未校准自评，不代表准确率"}
</quality_json>"""
QUALITIES = {"good", "usable_with_defects", "poor", "undetermined"}
ACTIONS = {"keep", "check_original", "request_clearer_source", "undetermined"}


def sample(seed, historical):
    required = {12, 23, 136}
    unseen = sorted(set(range(6, 170)) - set(historical) - required)
    rng = random.Random(seed)
    chosen = rng.sample(unseen, min(47, len(unseen)))
    if len(chosen) < 47:
        chosen += rng.sample(sorted(set(range(6, 170)) - required - set(chosen)), 47 - len(chosen))
    return sorted(required | set(chosen))


def split_sections(text):
    match = re.fullmatch(
        r"\s*<transcription_markdown>(.*?)</transcription_markdown>\s*<quality_json>(.*?)</quality_json>\s*",
        text,
        re.S,
    )
    if not match or not match[1].strip():
        raise ValueError("RESPONSE_FORMAT_OR_EMPTY_TRANSCRIPTION")
    return match[1], match[2]


def parse(text, physical_page):
    transcription, quality_raw = split_sections(text)
    quality = json.loads(quality_raw)
    required = {
        "physical_page",
        "overall_quality",
        "suggested_action",
        "visible_defects",
        "affected_area",
        "evidence",
        "assessment_confidence",
        "uncertainty_note",
    }
    if not isinstance(quality, dict) or not required <= quality.keys():
        raise ValueError("QUALITY_FIELDS_MISSING")
    if type(quality["physical_page"]) is not int or quality["physical_page"] != physical_page:
        raise ValueError("PHYSICAL_PAGE_MISMATCH")
    if (
        quality["overall_quality"] not in QUALITIES
        or quality["suggested_action"] not in ACTIONS
        or quality["assessment_confidence"] not in {"high", "medium", "low"}
    ):
        raise ValueError("QUALITY_ENUM_INVALID")
    for key in ("visible_defects", "evidence"):
        if not isinstance(quality[key], list) or not all(isinstance(x, str) for x in quality[key]):
            raise ValueError("QUALITY_LIST_INVALID")
    if len(quality["evidence"]) > 3 or not all(
        isinstance(quality[k], str) for k in ("affected_area", "uncertainty_note")
    ):
        raise ValueError("QUALITY_OBSERVATIONS_INVALID")
    return transcription, quality  # no strip, correction or normalization


def prepare(args):
    import fitz

    history = json.loads(args.history_manifest.read_bytes())
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS")
    if base.sha(args.pdf.read_bytes()) != history["source_pdf_sha256"]:
        raise ValueError("PDF_HASH_MISMATCH")
    pages = sample(args.seed, history["physical_pages"])
    args.output.mkdir(parents=True)
    (args.output / "images").mkdir()
    document = fitz.open(args.pdf)
    assert document.page_count == 169
    records = []
    by_page = {x["physical_page"]: x for x in history["images"]}
    for page in pages:
        output = args.output / "images" / f"page-{page}.png"
        old = by_page.get(page)
        if old:
            source = args.history_manifest.parent / old["image"]
            assert base.sha(source.read_bytes()) == old["sha256"]
            shutil.copy2(source, output)
            width, height = old["width"], old["height"]
            origin = "byte-identical historical original PNG"
        else:
            image = document[page - 1].get_pixmap(
                matrix=fitz.Matrix(220 / 72, 220 / 72), alpha=False, annots=False
            )
            image.save(output)
            width, height = image.width, image.height
            origin = "new render; same 220dpi RGB alpha=false annots=false"
        records.append(
            {
                "physical_page": page,
                "image": str(output.relative_to(args.output)),
                "width": width,
                "height": height,
                "bytes": output.stat().st_size,
                "sha256": base.sha(output.read_bytes()),
                "mime": "image/png",
                "origin": origin,
            }
        )
    # Explicit three-page pilot precedes remaining pages; fixed selection stays sorted separately.
    records.sort(
        key=lambda x: (
            [12, 23, 136].index(x["physical_page"])
            if x["physical_page"] in (12, 23, 136)
            else 3 + x["physical_page"]
        )
    )
    base.write_json(
        args.output / "manifest.json",
        {
            "schema": "m3-transcription-quality-v1",
            "source_pdf_sha256": history["source_pdf_sha256"],
            "history_manifest_sha256": base.sha(args.history_manifest.read_bytes()),
            "seed": args.seed,
            "sampling": "fixed12,23,136; sample47 from sorted historical-unseen6..169; fallback seen only if insufficient",
            "historical_pages": history["physical_pages"],
            "overlap_pages": sorted(set(pages) & set(history["physical_pages"])),
            "physical_pages": pages,
            "count": 50,
            "dpi": 220,
            "renderer": f"PyMuPDF {fitz.VersionBind}",
            "images": records,
            "prompt": PROMPT,
            "prompt_sha256": base.sha(PROMPT.encode()),
            "model": base.MODEL,
            "endpoint": base.ENDPOINT,
            "provider_internal_image_processing": "unknown",
            "human_accuracy": "not-measured",
        },
    )
    print(json.dumps({"pages": pages, "overlap": sorted(set(pages) & set(history["physical_pages"]))}))


def adapt(directory):
    results = []
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for source in manifest["images"]:
        page = source["physical_page"]
        for attempt in sorted((directory / "attempts" / f"page-{page}").glob("attempt-*")):
            receipt = json.loads((attempt / "receipt.json").read_bytes())
            result = {
                "physical_page": page,
                "attempt": receipt.get("attempt"),
                "call_status": receipt["status"],
                "parse_status": "not-evaluated",
                "adapter_version": "independent-sections-v2",
                "transcription_parse_status": "not-evaluated",
                "quality_parse_status": "not-evaluated",
            }
            raw = attempt / "transcription.txt"  # unchanged combined model text from existing transport
            if raw.exists() and receipt["status"] == "succeeded":
                try:
                    text, quality_raw = split_sections(raw.read_text())
                    (attempt / "transcription.md").write_text(text)
                    (attempt / "quality.raw.txt").write_text(quality_raw)
                    result.update(
                        {
                            "transcription_parse_status": "succeeded",
                            "transcription_sha256": base.sha(text.encode()),
                        }
                    )
                    _, quality = parse(raw.read_text(), page)
                    base.write_json(attempt / "quality.json", quality)
                    result.update(
                        {
                            "parse_status": "succeeded",
                            "quality_parse_status": "succeeded",
                            "transcription_sha256": base.sha(text.encode()),
                            "quality_sha256": base.sha((attempt / "quality.json").read_bytes()),
                        }
                    )
                except (ValueError, TypeError, KeyError) as error:
                    result.update(
                        {
                            "parse_status": "failed-format",
                            "quality_parse_status": "failed-format",
                            "error_category": type(error).__name__,
                        }
                    )
            base.write_json(attempt / "parse-receipt.json", result)
            results.append(result)
    return results


def run(args):
    manifest = json.loads((args.directory / "manifest.json").read_bytes())
    if manifest.get("schema") != "m3-transcription-quality-v1" or manifest["prompt"] != PROMPT:
        raise ValueError("MANIFEST_OR_PROMPT_MISMATCH")
    total = len(list((args.directory / "attempts").glob("page-*/attempt-*")))
    if total >= 60 or args.limit < 1 or args.limit > 60 - total:
        raise ValueError("TOTAL_CALL_LIMIT_60")
    if args.phase == "pilot" and args.limit != 3:
        raise ValueError("PILOT_MUST_BE_THREE_REQUESTS")
    if args.phase == "remainder":
        pilot = [x for x in adapt(args.directory) if x["physical_page"] in (12, 23, 136)]
        if (
            len(pilot) != 3
            or sum(x["call_status"] == "succeeded" and x["parse_status"] == "succeeded" for x in pilot) < 2
            or any(x["call_status"] == "succeeded" and x["parse_status"] != "succeeded" for x in pilot)
            or any(x["call_status"] == "started" for x in pilot)
        ):
            raise ValueError("PILOT_NOT_PASSED")
    original = base.make_request
    original_prompt = base.PROMPT

    def make_request(image, record):
        body, submitted = original(image, record)
        payload = json.loads(body)
        payload["messages"][0]["content"][1]["text"] = (
            PROMPT + "\n本张PDF物理页码：" + str(record["physical_page"])
        )
        return json.dumps(payload, ensure_ascii=False).encode(), submitted

    base.PROMPT = PROMPT
    base.make_request = make_request
    try:
        base.run(args)
    finally:
        base.make_request = original
        base.PROMPT = original_prompt
        adapt(args.directory)


def bundle(args):
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS")
    adapt(args.directory)
    args.output.mkdir(parents=True)
    manifest = json.loads((args.directory / "manifest.json").read_bytes())
    shutil.copy2(args.directory / "manifest.json", args.output / "manifest.json")
    shutil.copytree(args.directory / "images", args.output / "images")
    shutil.copytree(args.directory / "attempts", args.output / "attempts")
    pages = []
    all_attempts = []
    usage = {}
    groups = {key: [] for key in sorted(QUALITIES)}
    actions = {key: [] for key in sorted(ACTIONS)}
    for source in sorted(manifest["images"], key=lambda x: x["physical_page"]):
        page = source["physical_page"]
        attempts = sorted((args.output / "attempts" / f"page-{page}").glob("attempt-*"))
        history = []
        for attempt in attempts:
            receipt = json.loads((attempt / "receipt.json").read_bytes())
            all_attempts.append(receipt)
            history.append({"path": str(attempt.relative_to(args.output)), "receipt": receipt})
            for key, value in (receipt.get("usage") or {}).items():
                if isinstance(value, (int, float)):
                    usage[key] = usage.get(key, 0) + value
        latest = attempts[-1] if attempts else None
        parsed = json.loads((latest / "parse-receipt.json").read_bytes()) if latest else {}
        quality = (
            json.loads((latest / "quality.json").read_bytes())
            if latest and parsed.get("parse_status") == "succeeded" and (latest / "quality.json").exists()
            else None
        )
        text = (
            (latest / "transcription.md").read_text()
            if latest
            and parsed.get("transcription_parse_status") == "succeeded"
            and (latest / "transcription.md").exists()
            else ""
        )
        if quality:
            groups[quality["overall_quality"]].append(page)
            actions[quality["suggested_action"]].append(page)
        status = (
            parsed.get("parse_status", "not-called")
            if history and history[-1]["receipt"]["status"] == "succeeded"
            else (history[-1]["receipt"]["status"] if history else "not-called")
        )
        pages.append(
            {
                "physical_page": page,
                "source": source,
                "status": status,
                "quality": quality,
                "quality_raw": (latest / "quality.raw.txt").read_text()
                if latest and (latest / "quality.raw.txt").exists()
                else None,
                "transcription_parse_status": parsed.get("transcription_parse_status", "not-evaluated"),
                "quality_parse_status": parsed.get("quality_parse_status", "not-evaluated"),
                "text": text,
                "attempts": history,
                "coordinates": None,
                "coordinate_system": None,
                "blocks": [
                    {
                        "id": f"p{page:03}-b0001",
                        "type": "unsegmented_model_transcription",
                        "text": text,
                        "reading_order": 0,
                        "coordinates": None,
                    }
                ]
                if text
                else [],
            }
        )
    summary = {
        "pages": len(pages),
        "calls": len(all_attempts),
        "successful_transcription_pages": sum(x["transcription_parse_status"] == "succeeded" for x in pages),
        "quality_format_failed_pages": [
            x["physical_page"] for x in pages if x["quality_parse_status"] == "failed-format"
        ],
        "successful_transcription_and_quality": sum(x["status"] == "succeeded" for x in pages),
        "failed_or_unparsed_pages": [x["physical_page"] for x in pages if x["status"] != "succeeded"],
        "quality_pages": groups,
        "action_pages": actions,
        "unjudged_pages": [x["physical_page"] for x in pages if not x["quality"]],
        "retries": sum(x.get("attempt", 1) > 1 for x in all_attempts),
        "elapsed_seconds_sum": sum(x.get("elapsed_seconds", 0) for x in all_attempts),
        "visible_usage": usage,
        "attempts_without_usage": sum(not x.get("usage") for x in all_attempts),
        "actual_account_cost": "unknown; no billing interface available",
        "assessment": "model self-assessment; uncalibrated; no human accuracy measured",
        "provider_internal_image_processing": "unknown",
    }
    base.write_json(args.output / "summary.json", summary)
    base.write_json(
        args.output / "structure.json",
        {
            "schema": "m3-transcription-quality-v1",
            "document_id": manifest["source_pdf_sha256"],
            "source_pdf_sha256": manifest["source_pdf_sha256"],
            "pages": pages,
            "conversion": "split explicit delimiters only; transcription whitespace/text unchanged; no native layout coordinates",
        },
    )
    (args.output / "content.md").write_text(
        "\n\n".join(
            f"<!-- PDF physical page {x['physical_page']}; status {x['status']} -->\n" + x["text"]
            for x in pages
        )
    )
    (args.output / "summary.md").write_text(
        "# M3原图转写＋视觉质量自评\n\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n\n仅模型自评，不能视为人工验收或准确率。每次原始响应、请求、回执与解析产物分开保存。无坐标，不按知识修订。\n"
    )
    payload = json.dumps(pages, ensure_ascii=False).replace("<", "\\u003c")
    (args.output / "index.html").write_text(HTML.replace("__DATA__", payload))
    (args.output / "README.md").write_text(
        "解压后离线打开index.html，按页、质量等级或处理状态筛选。点击原图放大。原始响应见各次attempt目录；正文和质量JSON分别保存。未判断、调用失败与格式错误不等于原图差。质量是未经校准的模型自评；没有人工验收或准确率。客户端PNG字节原样提交，服务内部处理未知。\n"
    )
    if args.zip:
        with zipfile.ZipFile(args.zip, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in sorted(args.output.rglob("*")):
                if file.is_file():
                    archive.write(file, file.relative_to(args.output))


HTML = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>M3原图转写与质量判断</title><style>body{font:16px "Microsoft YaHei",sans-serif;margin:20px}nav{position:sticky;top:0;background:white;padding:12px}main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7}section{min-width:0}select{font:inherit;margin:5px}</style><h1>M3原图转写＋质量自评</h1><p>模型自评未经校准，不是人工验收或文字准确率；原文未纠错。点击原图放大。客户端原PNG未改字节，服务内部处理未知。</p><nav>质量<select id="quality"><option value="">全部</option><option>good</option><option>usable_with_defects</option><option>poor</option><option>undetermined</option><option value="unjudged">未判断</option></select>处理结果<select id="status"><option value="">全部</option><option>succeeded</option><option>failed-http</option><option>failed-client</option><option>failed-format</option><option>truncated</option><option>failed-empty-text</option></select>物理页<select id="page"></select><span id="count"></span></nav><main><section><a id="full" target="_blank" rel="noopener"><img id="image"></a><pre id="source"></pre></section><section><h2 id="title"></h2><pre id="text"></pre><h2>质量自评</h2><pre id="assessment"></pre><div id="history"></div></section></main><script>const rows=__DATA__;const el=id=>document.getElementById(id);function draw(){const r=rows.find(x=>String(x.physical_page)===el('page').value);el('history').replaceChildren();if(!r){el('title').textContent='无匹配页面';el('source').textContent='';el('full').removeAttribute('href');el('text').textContent='无匹配页面';el('assessment').textContent='';el('image').removeAttribute('src');return}el('image').src=r.source.image;el('full').href=r.source.image;el('source').textContent=JSON.stringify(r.source,null,2);el('title').textContent='物理第'+r.physical_page+'页：'+r.status;el('text').textContent=r.text||'无可解析正文，查看原始响应';el('assessment').textContent=r.quality?JSON.stringify(r.quality,null,2):('未判断，不能归因于原图质量。原始质量段（不修补、不纳入等级统计）：\\n'+(r.quality_raw||'无'));for(const h of r.attempts){const a=document.createElement('a');a.textContent='尝试'+h.receipt.attempt+'原始响应（'+h.receipt.status+'）';a.href=h.path+'/response.raw.json';a.target='_blank';el('history').append(a,document.createElement('br'));}}function filter(){const q=el('quality').value,s=el('status').value;const matches=rows.filter(r=>(!q||(r.quality?.overall_quality||'unjudged')===q)&&(!s||r.status===s));el('page').replaceChildren();for(const r of matches){const o=document.createElement('option');o.value=r.physical_page;o.textContent=r.physical_page;el('page').append(o)}el('count').textContent=matches.length+'页';draw()}el('status').replaceChildren();for(const status of ['',...new Set(rows.map(r=>r.status))]){const o=document.createElement('option');o.value=status;o.textContent=status||'全部';el('status').append(o)}el('quality').onchange=filter;el('status').onchange=filter;el('page').onchange=draw;filter();</script></html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--history-manifest", type=Path, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--limit", type=int, required=True)
    p.add_argument("--phase", choices=["pilot", "remainder"], required=True)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--retry-page", action="append", type=int)
    p.add_argument("--retry-reason", default="")
    p = sub.add_parser("bundle")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--zip", type=Path)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "bundle": bundle}[args.command](args)
