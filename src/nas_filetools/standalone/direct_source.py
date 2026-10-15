"""Resolve selected immutable text, not the latest OCR status or a boolean badge."""

import json
from ..artifact_project import relative, digest
from .text_revisions import mapped_text
from .adapters import separate


def read_payload(root, path):
    raw = relative(root, path).read_text()
    return json.loads(raw.split("=", 1)[1].rstrip(";\n"))


def content_state(root, project, artifact, row, cache=None):
    cache = {} if cache is None else cache
    view, text = row["view"], row["text"]
    if not text.strip():
        return False, "没有正文（空白或提取失败），不能生成成功空白页"
    revision = artifact.get("text_revision")
    if revision:
        records = cache.setdefault("records", {})
        if revision["record"] not in records:
            record_path = relative(root, revision["record"])
            registered = next((a for a in project["artifacts"] if a.get("path") == revision["record"]), None)
            if not registered or digest(record_path) != registered["sha256"]:
                return False, "人工修订回执哈希不可核实"
            records[revision["record"]] = json.loads(record_path.read_text())
        record = records[revision["record"]]
        parent = next(a for a in project["artifacts"] if a["artifact_id"] == revision["parent_artifact_id"])
        if (
            record["parent_sha256"] != parent["sha256"]
            or record["parent_artifact_id"] != parent["artifact_id"]
        ):
            return False, "人工修订父版本证据不一致"
        change = next((c for c in record["changes"] if c["locator"] == view["locator"]), None)
        if change:
            if change["after"] != text:
                return False, "人工修订正文与回执不一致"
            return True, "使用选定版本的人工修订正文；历史提取诊断保留"
        versions = cache.setdefault("rows", {})
        if parent["artifact_id"] not in versions:
            versions[parent["artifact_id"]] = mapped_text(root, parent)
        parent_rows = versions[parent["artifact_id"]]
        parent_row = next(r for r in parent_rows if r["view"]["locator"] == view["locator"])
        if parent_row["text"] != text:
            return False, "未修订片段与父版本不一致"
        return content_state(root, project, parent, parent_row, cache)
    payload = read_payload(root, view["data"])
    if payload.get("raw_path"):
        result_path = relative(root, payload["raw_path"])
        result = json.loads(result_path.read_text())
        if result.get("text") != text:
            return False, "登记正文与对应提取结果不一致"
        if (
            result.get("incomplete")
            or result.get("truncated")
            or result.get("content_complete") is False
            or result.get("content_status") in {"partial", "missing", "failed"}
        ):
            return False, "提取结果明确记录正文不完整"
        raw_path = result_path.with_name("response.raw.json")
        raw = json.loads(raw_path.read_text()) if raw_path.is_file() else None
        if raw and raw.get("stop_reason") not in {None, "end_turn", "stop"}:
            return False, "模型响应非正常结束，正文可能截断"
        if raw and any(c.get("finish_reason") not in {None, "stop"} for c in raw.get("choices", [])):
            return False, "模型响应非正常结束，正文可能截断"
        status = result.get("status")
        if status == "SUCCEEDED" and not result.get("error"):
            return True, "选定版本与成功提取记录一致"
        if (
            status == "PARTIAL"
            and result.get("error", {}).get("code") == "QUALITY_FORMAT"
            and raw
            and raw.get("stop_reason") in {"end_turn", "stop"}
        ):
            response = "".join(c.get("text", "") for c in raw.get("content", []) if c.get("type") == "text")
            body, _, error = separate(response, True)
            if body == text and error and error["code"] == "QUALITY_FORMAT":
                return True, "仅原图质量评价JSON错误；完整分隔的正文与原始响应一致，诊断保留"
        return False, "正文提取状态为" + str(status) + "，缺少独立完整正文证据"
    if view.get("error") or view.get("content_status") in {"partial", "missing", "failed"}:
        return False, "存在错误或部分正文标记，但缺少可核实的独立提取证据"
    return True, "使用哈希及完整组装校验通过的登记正文"
