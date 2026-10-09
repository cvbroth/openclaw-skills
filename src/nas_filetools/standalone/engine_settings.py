"""Private engine overlay; credentials never leave this service-side boundary."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from .config import capabilities, snapshot, validate


class EngineSettings:
    def __init__(self, root, config):
        self.config = config
        self.directory = Path(root) / "private"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.directory.chmod(0o700)
        self.path = self.directory / "engines.json"
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if saved.get("version") != 1 or set(saved) != {"version", "engines"}:
                raise ValueError("private settings schema/version")
            self.entries = saved["engines"]
        else:
            self.entries = {}

    def engine(self, eid):
        if eid == "pdf-text":
            return {
                "type": "pdf-text",
                "model": "PyMuPDF text extraction",
                "endpoint": "",
                "credential_env": "",
                "timeout": 60,
                "cpu_threads": 2,
                "concurrency": 1,
                "retries": 0,
            }
        if eid not in self.config["engines"]:
            raise ValueError("unknown engine")
        return copy.deepcopy(self.entries.get(eid, {}).get("config", self.config["engines"][eid]))

    def credential(self, eid):
        entry = self.entries.get(eid, {})
        if "secret" in entry:
            return entry["secret"]
        return os.environ.get(self.engine(eid)["credential_env"], "")

    def public(self):
        result = {}
        for eid in ["pdf-text", *self.config["engines"]]:
            engine = self.engine(eid)
            entry = self.entries.get(eid, {})
            remote = engine["type"] in {"minimax-messages", "openai-vision"}
            label = {
                "pdf-text": "直接提取PDF文字",
                "rapidocr": "RapidOCR 本地文字识别",
                "minimax-messages": "MiniMax 图像识别",
                "openai-vision": "OpenAI兼容图像接口",
                "fixture": "合成测试引擎",
            }[engine["type"]]
            enabled = entry.get("enabled", True)
            available = enabled and (not remote or bool(self.credential(eid)))
            result[eid] = {
                **snapshot(engine),
                "name": entry.get("name", label),
                "provider": entry.get(
                    "provider",
                    "MiniMax"
                    if engine["type"] == "minimax-messages"
                    else "本地"
                    if not remote
                    else "配置的兼容服务",
                ),
                "location": "remote" if remote else "local",
                "enabled": enabled,
                "available": available,
                "credential_configured": bool(self.credential(eid)) if remote else False,
                "capabilities": {
                    "images": False,
                    "transcription": True,
                    "quality": False,
                    "coordinates": True,
                    "input": "selected PDF text layer",
                }
                if eid == "pdf-text"
                else capabilities(engine),
                "connection_status": "not-tested",
                "description": "无需模型；文字层不保证完整版面"
                if eid == "pdf-text"
                else "本机CPU识别，不提供视觉质量评价"
                if not remote
                else "显式启动才发送图片；可能消耗接口额度",
            }
        return result

    def update(self, eid, data):
        if eid not in self.config["engines"] or not isinstance(data, dict):
            raise ValueError("editable engine required")
        if set(data) - {
            "name",
            "provider",
            "endpoint",
            "model",
            "timeout",
            "enabled",
            "key_action",
            "api_key",
        }:
            raise ValueError("unknown settings field")
        entry = copy.deepcopy(self.entries.get(eid, {}))
        engine = self.engine(eid)
        for field in ["name", "provider", "model", "endpoint"]:
            if field in data:
                value = data[field]
                if (
                    not isinstance(value, str)
                    or len(value) > (2048 if field == "endpoint" else 160)
                    or any(ord(c) < 32 for c in value)
                ):
                    raise ValueError(field + ": invalid text")
                if field in ["name", "provider"]:
                    entry[field] = value
                else:
                    engine[field] = value
        if "timeout" in data:
            engine["timeout"] = data["timeout"]
        if "enabled" in data:
            if type(data["enabled"]) is not bool:
                raise ValueError("enabled: boolean required")
            entry["enabled"] = data["enabled"]
        if (
            engine["type"] not in {"minimax-messages", "openai-vision", "fixture"}
            and engine["model"] != self.engine(eid)["model"]
        ):
            raise ValueError("model: 本地固定模型不能通过显示配置更换权重。")
        action = data.get("key_action", "keep")
        if action not in ["keep", "replace", "clear"]:
            raise ValueError("key_action: invalid")
        if engine["type"] not in {"minimax-messages", "openai-vision"} and action != "keep":
            raise ValueError("local engine has no API key")
        if action == "replace":
            key = data.get("api_key")
            if not isinstance(key, str) or not 1 <= len(key) <= 8192 or any(ord(c) < 32 for c in key):
                raise ValueError("api_key: invalid")
            entry["secret"] = key
        elif action == "clear":
            entry["secret"] = ""
        elif data.get("api_key"):
            raise ValueError("select replace to supply a key")
        candidate = copy.deepcopy(self.config)
        candidate["engines"][eid] = engine
        validate(candidate, testing=any(e["type"] == "fixture" for e in candidate["engines"].values()))
        entry["config"] = engine
        entries = {**self.entries, eid: entry}
        fd, name = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"version": 1, "engines": entries}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        self.entries = entries
        return self.public()[eid]

    def test(self, eid):
        engine = self.engine(eid)
        if engine["type"] in {"minimax-messages", "openai-vision"}:
            return {
                "status": "unverified",
                "requests": 0,
                "message": "尚未验证：本次仅校验配置，不请求远端、不发图片、不生成内容。供应商无已验证免费测试接口。",
            }
        ready = eid == "pdf-text" or importlib.util.find_spec("rapidocr_onnxruntime") is not None
        return {
            "status": "local-dependency-present" if ready else "unavailable",
            "requests": 0,
            "message": "只检查本地依赖，未运行识别模型。",
        }
