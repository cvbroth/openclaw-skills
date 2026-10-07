"""Isolated, resumable direct-image experiment. Private inputs/outputs never belong in Git.

Credentials are accepted on stdin only, retained in memory, and never included in
request audit files. This is not a FileTools production entry point.
"""
import argparse
import base64
import hashlib
import json
import random
import shutil
import signal
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROMPT = """请仅依据这张图片，按原图阅读顺序逐字转写所有现存文字，保留题号、题干、选项、数字及页边文字。不要解题，不润色，不纠错改写，不根据常识补全。不提供答案。无法辨认的字符或文字段请在原位置明确标注【无法辨认】，不得静默跳过。只输出转写文本，不输出质量评分、总结或审核意见。"""
ENDPOINT = "https://api.minimaxi.com/anthropic/v1/messages"
MODEL = "MiniMax-M3"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sample_pages(seed, count=50):
    if not 1 <= count <= 164:
        raise ValueError("count outside 1..164")
    return sorted([23] + random.Random(seed).sample([p for p in range(6, 170) if p != 23], count - 1))


def prepare(args):
    import fitz
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS: preserve the locked sample")
    pdf_sha = sha(args.pdf.read_bytes())
    if pdf_sha != args.pdf_sha:
        raise ValueError("SOURCE_PDF_HASH_MISMATCH")
    pages = sample_pages(args.seed, args.count)
    args.output.mkdir(parents=True)
    (args.output / "images").mkdir()
    document = fitz.open(args.pdf)
    if document.page_count < max(pages):
        raise ValueError("PDF_PAGE_RANGE")
    records = []
    for page in pages:
        started = time.monotonic()
        image = document[page - 1].get_pixmap(matrix=fitz.Matrix(220 / 72, 220 / 72), alpha=False, annots=False)
        target = args.output / "images" / f"page-{page}.png"
        image.save(target)
        records.append({"physical_page": page, "image": str(target.relative_to(args.output)), "width": image.width,
                        "height": image.height, "mime": "image/png", "bytes": target.stat().st_size,
                        "sha256": sha(target.read_bytes()), "render_seconds": time.monotonic() - started})
    manifest = {"schema": "m3-direct-images-v1", "seed": args.seed,
                "sampling": "Python random.Random(seed).sample(sorted physical 6..169 excluding 23, count-1); include 23; sort",
                "python_version": sys.version.split()[0], "count": len(pages), "physical_pages": pages,
                "source_pdf_sha256": pdf_sha, "source_pdf_pages": document.page_count,
                "dpi": 220, "renderer": f"PyMuPDF {fitz.VersionBind}", "prompt": PROMPT,
                "prompt_sha256": sha(PROMPT.encode()), "images": records}
    write_json(args.output / "manifest.json", manifest)
    print(json.dumps({"pages": pages, "count": len(pages), "pdf_sha256": pdf_sha}))


def make_request(image, record):
    from PIL import Image
    import io
    if sha(image) != record["sha256"] or len(image) != record["bytes"]:
        raise ValueError("SOURCE_IMAGE_CHANGED")
    payload = {"model": MODEL, "max_tokens": 12000, "thinking": {"type": "disabled"},
               "temperature": 1, "stream": False, "service_tier": "standard",
               "messages": [{"role": "user", "content": [
                   {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(image).decode("ascii")}},
                   {"type": "text", "text": PROMPT}]}]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    decoded = base64.b64decode(json.loads(body)["messages"][0]["content"][0]["source"]["data"], validate=True)
    with Image.open(io.BytesIO(decoded)) as im:
        submitted = {"width": im.width, "height": im.height, "format": im.format, "mime": Image.MIME[im.format],
                     "bytes": len(decoded), "sha256": sha(decoded)}
    if decoded != image or [submitted["width"], submitted["height"]] != [record["width"], record["height"]]:
        raise ValueError("SUBMISSION_IMAGE_MISMATCH")
    return body, submitted


def extract_response(response):
    if not isinstance(response.get("content"), list):
        raise ValueError("NO_CONTENT_BLOCKS")
    blocks = [b["text"] for b in response["content"] if b.get("type") == "text" and isinstance(b.get("text"), str)]
    text = "".join(blocks)  # preserve text verbatim, without strip/normalization
    if not text:
        return text, "failed-empty-text"
    if response.get("stop_reason") == "max_tokens":
        return text, "truncated"
    if response.get("stop_reason") != "end_turn":
        return text, "needs-review-stop-reason"
    return text, "succeeded"


def run(args):
    key = sys.stdin.readline().rstrip("\r\n")
    if not key:
        raise ValueError("NO_CREDENTIAL_ON_STDIN")
    manifest = json.loads((args.directory / "manifest.json").read_text())
    attempts = args.directory / "attempts"
    attempts.mkdir(exist_ok=True)
    completed = 0
    retry_pages = set(getattr(args, "retry_page", []) or [])
    if retry_pages - {r["physical_page"] for r in manifest["images"]}:
        raise ValueError("RETRY_PAGE_OUTSIDE_LOCKED_SAMPLE")
    if retry_pages and not getattr(args, "retry_reason", ""):
        raise ValueError("RETRY_REASON_REQUIRED")
    for record in manifest["images"]:
        page = record["physical_page"]
        page_root = attempts / f"page-{page}"
        existing = sorted(page_root.glob("attempt-*"))
        if retry_pages and page not in retry_pages:
            continue
        if retry_pages:
            if len(existing) != 1:
                raise ValueError("RETRY_REQUIRES_EXACTLY_ONE_PREVIOUS_ATTEMPT")
            previous = json.loads((existing[-1] / "receipt.json").read_text())
            if not (previous["status"].startswith("failed") or previous["status"] == "truncated"):
                raise ValueError("RETRY_REQUIRES_FAILED_OR_TRUNCATED_ATTEMPT")
        elif existing:  # never overwrite/retry silently, including interrupted attempts
            continue
        if args.limit and completed >= args.limit:
            break
        number = len(existing) + 1
        target = page_root / f"attempt-{number}"
        target.mkdir(parents=True)
        image = (args.directory / record["image"]).read_bytes()
        body, submitted = make_request(image, record)
        (target / "request.json").write_bytes(body)  # private request body, no headers/credentials
        receipt = {"physical_page": page, "attempt": number, "started_at": datetime.now(timezone.utc).isoformat(),
                   "status": "started", "endpoint": ENDPOINT, "requested_model": MODEL,
                   "request_body_sha256": sha(body), "request_body_bytes": len(body),
                   "source": record, "submitted": submitted, "prompt_sha256": sha(PROMPT.encode()),
                   "context": "one user message; one original image; no tools, history, OCR or reference"}
        if retry_pages:
            receipt["retry_reason"] = args.retry_reason
        write_json(target / "receipt.json", receipt)
        started = time.monotonic()
        try:
            def deadline(_signum, _frame):
                raise TimeoutError("PAGE_DEADLINE")

            signal.signal(signal.SIGALRM, deadline)
            signal.alarm(args.timeout)
            request = urllib.request.Request(ENDPOINT, body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01"})
            try:
                with urllib.request.urlopen(request, timeout=args.timeout) as response:
                    raw, code = response.read(), response.status
            except urllib.error.HTTPError as error:
                raw, code = error.read(), error.code
            (target / "response.raw.json").write_bytes(raw)
            receipt.update({"http_status": code, "response_bytes": len(raw), "response_sha256": sha(raw)})
            if code == 200:
                response = json.loads(raw)
                text, status = extract_response(response)
                (target / "transcription.txt").write_text(text, encoding="utf-8")
                receipt.update({"status": status, "returned_model": response.get("model"), "stop_reason": response.get("stop_reason"),
                                "usage": response.get("usage"), "transcription_sha256": sha(text.encode()), "text_characters": len(text)})
            else:
                receipt["status"] = "failed-http"
        except Exception as error:
            # A fixed category only: exception strings can include secrets or URLs supplied by servers.
            receipt.update({"status": "failed-client", "error_type": type(error).__name__})
        finally:
            signal.alarm(0)
        receipt.update({"elapsed_seconds": time.monotonic() - started, "finished_at": datetime.now(timezone.utc).isoformat()})
        write_json(target / "receipt.json", receipt)
        print(json.dumps({k: receipt.get(k) for k in ("physical_page", "status", "http_status", "elapsed_seconds", "usage")}), flush=True)
        completed += 1
        if receipt.get("http_status") in (401, 403, 429):
            break


HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>M3原图转写人工对照</title>
<style>body{font-family:system-ui,sans-serif;margin:1.5rem;max-width:1500px}header{position:sticky;top:0;background:white;padding:1rem;border-bottom:1px solid #ccc}img{max-width:100%;height:auto}textarea{width:98%;min-height:12rem;font:inherit}#notes{min-height:5rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}select,button{font:inherit;margin:.4rem}.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1rem}.columns>div{min-width:0;overflow-wrap:anywhere}@media(max-width:800px){.columns{display:block}}</style>
<header><b>M3原图转写 · 人工审核全部未填写</b><br><label>物理页<select id="page"></select></label><button id="previous">上一页</button><button id="next">下一页</button><button id="export">导出人工审核JSON</button><p>原始转写未纠错。点击图片可打开原尺寸图；文本框可选择复制。未审核不等于准确。刷新前请导出，浏览器不会自动保存。</p></header>
<main id="main"></main><script id="data" type="application/json">__DATA__</script><script>
'use strict';const data=JSON.parse(document.getElementById('data').textContent),page=document.getElementById('page'),main=document.getElementById('main'),draft={};
function el(t,s,p){const n=document.createElement(t);if(s!==undefined)n.textContent=s;if(p)p.append(n);return n}
for(const r of data.pages){const o=el('option',String(r.physical_page),page);o.value=r.physical_page;draft[r.physical_page]={rating:'',notes:''}}
function draw(){main.replaceChildren();const r=data.pages.find(x=>String(x.physical_page)===page.value),v=draft[r.physical_page];location.hash='page-'+r.physical_page;el('h1','PDF物理第'+r.physical_page+'页',main);el('p','调用状态：'+r.status,main);for(const h of r.attempts){const line=el('p','尝试'+h.attempt+'：'+h.status,main);if(h.raw){const link=el('a',' 查看该次原始响应',line);link.href=h.raw;link.target='_blank';link.rel='noopener'}}const cols=el('div',undefined,main);cols.className='columns';const left=el('div',undefined,cols);el('h2','220dpi原图',left);const a=el('a',undefined,left);a.href=r.image;a.target='_blank';a.rel='noopener';const im=el('img',undefined,a);im.src=r.image;im.alt='PDF物理第'+r.physical_page+'页原图';el('p','源图：'+JSON.stringify(r.source),left);el('p',r.submitted?'实际提交图像：'+JSON.stringify(r.submitted)+'；与原图字节一致，无客户端缩放或重编码。服务内部处理未知。':'尚无实际提交图像证据',left);const right=el('div',undefined,cols);el('h2','M3原始转写（不改字）',right);const text=el('textarea',undefined,right);text.readOnly=true;text.value=r.text;const raw=el('a','完整原始响应',right);if(r.raw){raw.href=r.raw;raw.target='_blank';raw.rel='noopener'}else raw.removeAttribute('href');const d=el('details',undefined,right);el('summary','调用及用量记录',d);el('pre',JSON.stringify(r.receipt,null,2),d);el('h2','人工审核（初始空白）',right);const s=el('select',undefined,right);for(const [key,label]of [['','尚未填写'],['基本准确','基本准确'],['有少量错误','有少量错误'],['错漏严重','错漏严重'],['暂无法判断','暂无法判断']]){const o=el('option',label,s);o.value=key}s.value=v.rating;s.onchange=()=>v.rating=s.value;el('p','备注',right);const n=el('textarea',undefined,right);n.id='notes';n.value=v.notes;n.oninput=()=>v.notes=n.value;}
page.onchange=draw;document.getElementById('previous').onclick=()=>{page.selectedIndex=Math.max(0,page.selectedIndex-1);draw()};document.getElementById('next').onclick=()=>{page.selectedIndex=Math.min(data.pages.length-1,page.selectedIndex+1);draw()};document.getElementById('export').onclick=()=>{const result={schema:'m3-human-review-v1',manifest_sha256:data.manifest_sha256,source_pdf_sha256:data.source_pdf_sha256,exported_at:new Date().toISOString(),reviewer_type:'user-self-declared',pages:data.pages.map(r=>({physical_page:r.physical_page,image_sha256:r.source.sha256,transcription_sha256:r.receipt?.transcription_sha256,...draft[r.physical_page]}))};const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='m3-human-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};const initial=location.hash.match(/^#page-(\\d+)$/);if(initial&&data.pages.some(r=>String(r.physical_page)===initial[1]))page.value=initial[1];draw();
</script></html>'''


def bundle(args):
    if args.output.exists() or args.zip.exists():
        raise ValueError("OUTPUT_EXISTS")
    args.output.mkdir(parents=True)
    manifest_path = args.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    shutil.copyfile(manifest_path, args.output / "manifest.json")
    shutil.copytree(args.directory / "images", args.output / "images")
    (args.output / "responses").mkdir()
    (args.output / "transcriptions").mkdir()
    pages, usage, all_attempts = [], {}, []
    for source in manifest["images"]:
        page = source["physical_page"]
        histories = []
        receipt, raw, text, text_path = {}, None, "", None
        for attempt in sorted((args.directory / "attempts" / f"page-{page}").glob("attempt-*")):
            receipt = json.loads((attempt / "receipt.json").read_text())
            raw_path, text_path = attempt / "response.raw.json", attempt / "transcription.txt"
            raw = None
            name = f"page-{page}-{attempt.name}"
            if raw_path.exists():
                raw = f"responses/{name}.raw.json"
                shutil.copyfile(raw_path, args.output / raw)
            text = text_path.read_bytes().decode("utf-8") if text_path.exists() else ""
            if text_path.exists():
                shutil.copyfile(text_path, args.output / "transcriptions" / f"{name}.txt")
            write_json(args.output / "responses" / f"{name}.receipt.json", receipt)
            histories.append({"attempt": receipt.get("attempt", 1), "status": receipt["status"], "raw": raw, "receipt": receipt})
            all_attempts.append(receipt)
            for key, value in (receipt.get("usage") or {}).items():
                if isinstance(value, (int, float)):
                    usage[key] = usage.get(key, 0) + value
        if text_path and text_path.exists():
            shutil.copyfile(text_path, args.output / "transcriptions" / f"page-{page}.txt")
        pages.append({"physical_page": page, "image": source["image"], "source": source,
                      "status": receipt.get("status", "not-called"), "submitted": receipt.get("submitted"),
                      "raw": raw, "text": text, "receipt": receipt, "attempts": histories})
    totals = {"sample_pages": len(pages), "attempted": sum(bool(p["receipt"]) for p in pages),
              "succeeded": sum(p["status"] == "succeeded" for p in pages),
              "truncated": sum(p["status"] == "truncated" for p in pages),
              "failed": sum(p["status"].startswith("failed") for p in pages),
              "not_called": sum(p["status"] == "not-called" for p in pages),
              "unfinished_or_other": sum(p["status"] not in ("succeeded", "truncated", "not-called") and not p["status"].startswith("failed") for p in pages),
              "requests": len(all_attempts), "retry_requests": sum(r.get("attempt", 1) > 1 for r in all_attempts),
              "failed_attempts": sum(r["status"].startswith("failed") for r in all_attempts),
              "attempts_without_usage": sum(not r.get("usage") for r in all_attempts),
              "elapsed_seconds": sum(r.get("elapsed_seconds", 0) for r in all_attempts), "usage": usage,
              "human_reviews": 0, "accuracy": "not-measured", "provider_internal_image_processing": "unknown"}
    write_json(args.output / "summary.json", totals)
    data = {"pages": pages, "manifest_sha256": sha(manifest_path.read_bytes()), "source_pdf_sha256": manifest["source_pdf_sha256"]}
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (args.output / "index.html").write_text(HTML.replace("__DATA__", encoded), encoding="utf-8")
    lines = ["# M3原图直接转写人工审核包", "", "打开 index.html；第23页入口 index.html#page-23。全部人工审核字段空白。", "",
             "源PDF SHA-256：" + manifest["source_pdf_sha256"], "随机种子：" + str(manifest["seed"]),
             "页码：" + ", ".join(map(str, manifest["physical_pages"])), "", json.dumps(totals, ensure_ascii=False, indent=2), "",
             "通过同一MiniMax中国区Anthropic Messages端点直传PNG；逐页独立请求。实际提交图像与源PNG字节一致，服务内部是否缩放未知。",
             "原始响应及转写未人工清理。质量和转写准确性等待用户审核；未计算准确率。旧测评未混入本轮。", "",
             "|物理页|状态|秒|输入token|输出token|", "|---|---|---:|---:|---:|"]
    for p in pages:
        r, u = p["receipt"], p["receipt"].get("usage") or {}
        lines.append(f"|{p['physical_page']}|{p['status']}|{r.get('elapsed_seconds', '不可得')}|{u.get('input_tokens', '不可得')}|{u.get('output_tokens', '不可得')}|")
    (args.output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(args.output.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(args.output))
    print(json.dumps({**totals, "zip_bytes": args.zip.stat().st_size, "zip_sha256": sha(args.zip.read_bytes())}))


def audit(args):
    """Whitelist-only evidence: no image bytes, transcription or response body."""
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS")
    manifest_path = args.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if manifest["physical_pages"] != sample_pages(manifest["seed"], manifest["count"]):
        raise ValueError("SAMPLE_CHANGED")
    rows = []
    for source in manifest["images"]:
        page = source["physical_page"]
        image = (args.directory / source["image"]).read_bytes()
        expected_body, submitted = make_request(image, source)
        attempts = sorted((args.directory / "attempts" / f"page-{page}").glob("attempt-*"))
        if not attempts:
            raise ValueError("MISSING_PAGE_ATTEMPT")
        for attempt in attempts:
            receipt = json.loads((attempt / "receipt.json").read_bytes())
            body = (attempt / "request.json").read_bytes()
            raw = (attempt / "response.raw.json").read_bytes()
            if body != expected_body or receipt["request_body_sha256"] != sha(body):
                raise ValueError("REQUEST_CHANGED")
            if receipt["submitted"] != submitted or receipt["source"] != source or receipt["endpoint"] != ENDPOINT:
                raise ValueError("RECEIPT_IMAGE_OR_ENDPOINT_CHANGED")
            if receipt["response_sha256"] != sha(raw):
                raise ValueError("RESPONSE_CHANGED")
            if receipt["http_status"] == 200:
                response = json.loads(raw)
                text, status = extract_response(response)
                if (attempt / "transcription.txt").read_bytes() != text.encode() or status != receipt["status"]:
                    raise ValueError("TRANSCRIPTION_CHANGED")
            rows.append({k: receipt.get(k) for k in ("physical_page", "attempt", "started_at", "finished_at", "status", "http_status", "elapsed_seconds", "requested_model", "returned_model", "stop_reason", "usage", "submitted", "request_body_sha256", "response_sha256", "response_bytes", "transcription_sha256", "text_characters", "retry_reason")})
    result = {"schema": "m3-original50-audit-v1", "source_pdf_sha256": manifest["source_pdf_sha256"],
              "manifest_sha256": sha(manifest_path.read_bytes()), "seed": manifest["seed"],
              "physical_pages": manifest["physical_pages"], "dpi": manifest["dpi"], "renderer": manifest["renderer"],
              "prompt_sha256": manifest["prompt_sha256"], "source_bytes_sum": sum(r["bytes"] for r in manifest["images"]),
              "source_image_dimensions": sorted({(r["width"], r["height"]) for r in manifest["images"]}),
              "source_image_bytes_range": [min(r["bytes"] for r in manifest["images"]), max(r["bytes"] for r in manifest["images"])],
              "requests": len(rows), "all_submission_bytes_equal_source": True,
              "all_request_config_and_prompt_equal": True, "all_success_text_files_equal_raw_response_text": True,
              "provider_internal_image_processing": "unknown", "human_reviews": 0, "attempts": rows}
    write_json(args.output, result)
    print(json.dumps({"pages": len(manifest["physical_pages"]), "requests": len(rows), "audit_sha256": sha(args.output.read_bytes())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--pdf-sha", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--retry-page", type=int, action="append", default=[])
    p.add_argument("--retry-reason", default="")
    p = sub.add_parser("bundle")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--zip", type=Path, required=True)
    p = sub.add_parser("audit")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "bundle": bundle, "audit": audit}[args.command](args)
