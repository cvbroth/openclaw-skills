"""Engines consume one explicit image; no project paths or HTML decisions."""

import base64
import io
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

PROMPT = """按图片阅读顺序逐字转写为Markdown，保留题号、题干、选项、数字和否定词。不解题、不润色、不根据知识纠错、不补全或重编号。难辨处标记【无法辨认】，不得静默跳过。"""
QUALITY_PROMPT = """同时只根据图片可见情况评价原图，不以转写流畅证明清晰。输出严格两个标记段：<transcription_markdown>原样转写</transcription_markdown><quality_json>{"overall_quality":"good|usable_with_defects|poor|undetermined","suggested_action":"keep|check_original|request_clearer_source|undetermined","evidence":["最多3条可对照观察"],"uncertainty_note":"不确定处；这是未经校准的模型自评"}</quality_json>。good为正文直接可辨；usable_with_defects为部分有缺损需核对；poor为关键正文难辨；观察不足为undetermined。不要凭上下文猜字反推清晰。"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not send Authorization to a different URL/provider implicitly.
        return None


def safe(value, secret):
    """Provider echo must not leak key into diagnostics, even in a mock failure."""
    return value.replace(secret, "[REDACTED]") if secret else value


def separate(text, quality):
    if not quality:
        return text, None, None
    import re

    match = re.fullmatch(
        r"\s*<transcription_markdown>(.*?)</transcription_markdown>\s*<quality_json>(.*?)</quality_json>\s*",
        text,
        re.S,
    )
    if not match:
        return (
            "",
            None,
            {
                "stage": "response_parse",
                "category": "local",
                "code": "SECTION_FORMAT",
                "message": "Separate sections missing; raw response retained only in diagnostics, not mixed into body.",
            },
        )
    try:
        data = json.loads(match[2])
        if (
            data.get("overall_quality") not in {"good", "usable_with_defects", "poor", "undetermined"}
            or data.get("suggested_action")
            not in {"keep", "check_original", "request_clearer_source", "undetermined"}
            or not isinstance(data.get("evidence"), list)
            or len(data["evidence"]) > 3
            or not all(isinstance(x, str) for x in data["evidence"])
            or not isinstance(data.get("uncertainty_note"), str)
        ):
            raise ValueError("quality schema")
        data["assessment_kind"] = "uncalibrated-model-self-assessment"
        return match[1], data, None
    except (ValueError, TypeError, AttributeError):
        return (
            match[1],
            None,
            {
                "stage": "response_parse",
                "category": "local",
                "code": "QUALITY_FORMAT",
                "message": "Quality JSON invalid; transcription independently retained.",
            },
        )


def recognize(image, engine, params):
    from PIL import Image

    started = time.monotonic()
    image = Path(image)
    if engine["type"] in {"minimax-messages", "openai-vision"} and image.stat().st_size > 20 * 1024 * 1024:
        return {
            "status": "FAILED",
            "text": "",
            "blocks": [],
            "quality": None,
            "error": {
                "category": "local",
                "stage": "request_prepare",
                "code": "IMAGE_BYTE_LIMIT",
                "message": "Application image cap is 20 MiB; no silent resize or provider switch.",
            },
        }
    data = image.read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        input_info = {
            "width": im.width,
            "height": im.height,
            "mime": Image.MIME[im.format],
            "bytes": len(data),
        }
    import hashlib

    input_info["sha256"] = hashlib.sha256(data).hexdigest()
    result = {
        "status": "SUCCEEDED",
        "text": "",
        "blocks": [],
        "quality": None,
        "error": None,
        "input": input_info,
        "usage": None,
        "native": None,
        "raw_response": None,
    }
    kind = engine["type"]
    if kind == "fixture":
        if engine["model"] == "delay":
            time.sleep(30)
        if engine["model"] == "failure" or (engine["model"] == "page2-failure" and image.stem == "page-2"):
            raise ValueError("SYNTHETIC_FAILURE")
        result.update(
            text="合成测试\n1. 保留原文？\nA. 是\nB. 否\nC. 未知\nD. 待核对", native={"fixture": True}
        )
    elif kind == "rapidocr":
        from rapidocr_onnxruntime import RapidOCR

        ocr = RapidOCR(intra_op_num_threads=engine["cpu_threads"], inter_op_num_threads=1)
        rows, timing = ocr(str(image))
        result["text"] = "\n".join(row[1] for row in rows or [])
        result["blocks"] = [
            {
                "id": f"b{i + 1:04d}",
                "type": "text",
                "text": row[1],
                "reading_order": i,
                "coordinates": row[0],
                "coordinate_system": "input-image-pixels",
                "ocr_score": float(row[2]),
            }
            for i, row in enumerate(rows or [])
        ]
        result["native"] = {
            "rows": rows,
            "timings": timing,
            "engine": "rapidocr-onnxruntime",
            "version": "1.4.4",
            "cpu_threads": engine["cpu_threads"],
        }
    else:
        secret = os.environ.get(engine["credential_env"])
        if not secret:
            return {
                **result,
                "status": "FAILED",
                "error": {
                    "category": "local",
                    "stage": "request_prepare",
                    "code": "CREDENTIAL_UNAVAILABLE",
                    "message": "Configured server credential unavailable.",
                },
            }
        prompt = (
            PROMPT
            + (" 语言：" + params["language"])
            + (QUALITY_PROMPT if params["quality"] else "只输出转写正文，不输出评价或总结。")
        )
        image64 = base64.b64encode(data).decode("ascii")
        if kind == "minimax-messages":
            payload = {
                "model": engine["model"],
                "max_tokens": 12000,
                "thinking": {"type": "disabled"},
                "temperature": 1,
                "stream": False,
                "service_tier": "standard",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": input_info["mime"],
                                    "data": image64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            }
        else:
            payload = {
                "model": engine["model"],
                "max_tokens": 12000,
                "temperature": 1,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:" + input_info["mime"] + ";base64," + image64},
                            },
                        ],
                    }
                ],
            }
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + secret}
        if kind == "minimax-messages":
            headers["anthropic-version"] = "2023-06-01"
        encoded_body = json.dumps(payload, ensure_ascii=False).encode()
        submitted = base64.b64decode(image64, validate=True)
        if submitted != data:
            raise ValueError("SUBMITTED_IMAGE_CHANGED")
        result["submitted_input"] = {
            **input_info,
            "client_bytes_unchanged": True,
            "provider_internal_transform": "unknown",
        }
        result["request_body_sha256"] = hashlib.sha256(encoded_body).hexdigest()
        request = urllib.request.Request(engine["endpoint"], encoded_body, headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=engine["timeout"]) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError("REMOTE_RESPONSE_LIMIT")
        except urllib.error.HTTPError as exc:
            raw = exc.read(1024 * 1024)
            result.update(
                status="FAILED",
                raw_response=safe(raw.decode("utf-8", errors="replace"), secret),
                error={
                    "category": "remote",
                    "stage": "request",
                    "code": exc.code,
                    "message": safe(raw.decode("utf-8", errors="replace"), secret)[:2000],
                },
            )
            return result
        raw = safe(raw.decode("utf-8"), secret)
        result["raw_response"] = raw
        try:
            response = json.loads(raw)
            result["usage"] = response.get("usage")
            result["returned_model"] = response.get("model")
            if kind == "minimax-messages":
                text = "".join(b["text"] for b in response["content"] if b.get("type") == "text")
                finish = response.get("stop_reason")
                complete = finish == "end_turn"
            else:
                text = response["choices"][0]["message"]["content"]
                finish = response["choices"][0].get("finish_reason")
                complete = finish == "stop"
            if not isinstance(text, str):
                raise ValueError("text missing")
            result["text"], result["quality"], result["error"] = separate(text, params["quality"])
            if not complete:
                result.update(
                    status="PARTIAL",
                    error={
                        "category": "remote",
                        "stage": "response",
                        "code": "STOP_REASON",
                        "message": str(finish),
                    },
                )
            elif result["error"]:
                result["status"] = "PARTIAL"
        except (ValueError, KeyError, IndexError, TypeError):
            result.update(
                status="FAILED",
                error={
                    "category": "local",
                    "stage": "response_parse",
                    "code": "RESPONSE_SCHEMA",
                    "message": "Provider response does not match configured protocol.",
                },
            )
    if not result["text"].strip() and result["status"] == "SUCCEEDED":
        result.update(
            status="FAILED",
            error={
                "category": "local",
                "stage": "response_parse",
                "code": "EMPTY_TEXT",
                "message": "No transcription text.",
            },
        )
    result["elapsed_seconds"] = time.monotonic() - started
    return result
