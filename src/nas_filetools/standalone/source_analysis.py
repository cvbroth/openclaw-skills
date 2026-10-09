"""Metadata/text-layer inspection only, no rasterization, OCR or network."""

import json
from pathlib import Path
import signal
import sys
import time
import unicodedata
from ..artifact_project import digest
from ..contracts import Fault


def atomic(path, data):
    path = Path(path)
    temp = path.with_suffix(".next")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def inspect_page(page):
    text = page.get_text("text", sort=False)
    visible = "".join(c for c in text if not c.isspace())
    bad = sum(c == "\ufffd" or unicodedata.category(c).startswith("C") for c in visible)
    rect = page.rect
    area = max(rect.width * rect.height, 1)
    images = page.get_image_info()
    coverage = min(
        1.0,
        sum(
            max(0, min(b["bbox"][2], rect.x1) - max(b["bbox"][0], rect.x0))
            * max(0, min(b["bbox"][3], rect.y1) - max(b["bbox"][1], rect.y0))
            / area
            for b in images
        ),
    )
    has_text = bool(visible)
    category = (
        "mixed"
        if has_text and coverage >= 0.5
        else "text"
        if has_text
        else "scan"
        if coverage >= 0.5
        else "blank_or_undetermined"
    )
    usable = (
        "candidate"
        if len(visible) >= 30 and bad / max(len(visible), 1) < 0.02
        else "uncertain"
        if has_text
        else "no_text"
    )
    notes = (
        ["文字层不等于可靠文字；未对原图逐字核对。"] if has_text else ["未检测到可提取文字，不证明页面空白。"]
    )
    if category == "mixed":
        notes.append("文字层与大面积图片共存：可能是带OCR层扫描件，也可能是混合版面。")
    elif images:
        notes.append("图片可能为插图；存在图片不等于需要OCR。")
    return {
        "category": category,
        "text_layer_detected": has_text,
        "text_usability": usable,
        "non_whitespace_characters": len(visible),
        "replacement_or_control_characters": bad,
        "image_count": len(images),
        "image_area_fraction_upper_estimate": coverage,
        "page_size_pt": [rect.width, rect.height],
        "text_sample": text[:300],
        "notes": notes,
        "status": "SUCCEEDED",
    }


def main(request, output):
    started = time.monotonic()
    data = {
        "schema": "source-analysis-v1",
        "source_sha256": request["source_sha256"],
        "status": "RUNNING",
        "completed_pages": 0,
        "total_pages": None,
        "pages": [],
        "summary": {},
        "limits": {"total_seconds": 120, "per_page_seconds": 5, "cpu_threads": 2},
        "classification": "experimental heuristics; not accuracy or visual quality",
        "visual_quality_performed": False,
    }

    def publish():
        counts = {}
        for row in data["pages"]:
            counts[row["category"]] = counts.get(row["category"], 0) + 1
        data["summary"] = counts
        data["elapsed_seconds"] = time.monotonic() - started
        atomic(output, data)

    try:
        if digest(request["source"]) != request["source_sha256"]:
            raise Fault("SOURCE_HASH_CHANGED", "原件哈希变化，停止分析；未修改原件。")
        if request["kind"] == "image":
            from PIL import Image

            from .tasks import inspect_file

            inspect_file(
                request["source"],
                {"service": {"max_pages": request["max_pages"], "max_pixels": request["max_pixels"]}},
            )
            with Image.open(request["source"]) as image:
                image.verify()
                data.update(
                    total_pages=1,
                    completed_pages=1,
                    dimensions=[image.width, image.height],
                    actual_type=image.format,
                    status="SUCCEEDED",
                )
            publish()
            return
        import fitz

        with fitz.open(request["source"]) as doc:
            if doc.needs_pass:
                raise Fault("PDF_PASSWORD_REQUIRED", "PDF需要密码；未解密或修改原件，暂不支持密码输入。")
            if not doc.is_pdf or not len(doc):
                raise Fault("INVALID_PDF", "PDF基本有效性检查失败或没有页面。")
            if len(doc) > request["max_pages"]:
                raise Fault("PAGE_LIMIT", "PDF总页数超过配置上限。")
            data.update(total_pages=len(doc), actual_type="PDF")
            publish()

            def timeout(*args):
                raise TimeoutError("page analysis deadline")

            signal.signal(signal.SIGALRM, timeout)
            for n in range(len(doc)):
                if time.monotonic() - started >= 115:
                    data.update(
                        status="PARTIAL",
                        error={
                            "code": "ANALYSIS_DEADLINE",
                            "message": "已保存完成页，未检查页面保持未知；可重试分析。",
                        },
                    )
                    break
                try:
                    signal.setitimer(signal.ITIMER_REAL, 5)
                    row = inspect_page(doc[n])
                except Exception as exc:
                    row = {
                        "category": "blank_or_undetermined",
                        "status": "FAILED",
                        "text_layer_detected": None,
                        "text_usability": "unknown",
                        "text_sample": "",
                        "notes": ["页面检测失败，不按空白或可用处理。"],
                        "error": {"code": type(exc).__name__},
                    }
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                row["physical_page"] = n + 1
                data["pages"].append(row)
                data["completed_pages"] = len(data["pages"])
                publish()
            else:
                data["status"] = (
                    "PARTIAL" if any(p["status"] != "SUCCEEDED" for p in data["pages"]) else "SUCCEEDED"
                )
    except Exception as exc:
        data.update(
            status="FAILED",
            error={
                "code": exc.code if isinstance(exc, Fault) else type(exc).__name__,
                "message": exc.message
                if isinstance(exc, Fault)
                else "原件检测失败；原文件与项目保留，可重试分析。",
            },
        )
    publish()


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
