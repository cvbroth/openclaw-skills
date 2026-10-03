"""Strict shared contracts; callers never supply a source/output path to the service."""

import hashlib
import re
from dataclasses import asdict, dataclass


class Fault(Exception):
    def __init__(self, code, message=""):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 64 * 1024 * 1024
    max_pages: int = 500
    max_audio_seconds: int = 7200
    max_image_pixels: int = 24_000_000
    max_docx_expanded_bytes: int = 128 * 1024 * 1024
    max_output_chars: int = 2_000_000
    max_asset_bytes: int = 32 * 1024 * 1024
    max_read_chars: int = 12_000
    max_segments: int = 20_000
    preview_pages: int = 3
    large_pages: int = 20
    large_audio_seconds: int = 600
    ttl_seconds: int = 72 * 3600
    timeout_seconds: int = 3600
    concurrency: int = 1
    engine_threads: int = 2
    worker_memory_mb: int = 4096
    inspection_timeout_seconds: int = 15
    max_jobs_per_scope: int = 32
    max_original_bytes_per_scope: int = 1024 * 1024 * 1024
    whisper_model: str = "small"
    model_cache: str = "/var/cache/nas-filetools"
    offline: bool = True

    def __post_init__(self):
        numeric = [name for name, value in asdict(self).items() if name not in
                   ("whisper_model", "model_cache", "offline")]
        if any(type(getattr(self, name)) is not int or getattr(self, name) < 1 for name in numeric):
            raise Fault("INVALID_CONFIG")
        if (self.concurrency > 2 or self.engine_threads > 8 or self.worker_memory_mb < 256 or
                self.inspection_timeout_seconds > 60 or self.max_read_chars > 12000 or self.max_pages > 500 or
                self.max_audio_seconds > 7200 or self.max_bytes > 64 * 1024 * 1024 or
                type(self.offline) is not bool or not isinstance(self.whisper_model, str) or
                not isinstance(self.model_cache, str)):
            raise Fault("INVALID_CONFIG")

    def dict(self):
        return asdict(self)


AGENT_USERS = {"main": "chen", "chen": "chen", "liang": "liang", "ziling": "azl"}
ID = re.compile(r"^[0-9a-f]{32}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
FORMATS = {
    ".pdf": "pdf", ".docx": "docx", ".md": "text", ".txt": "text",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".bmp": "image", ".tif": "image", ".tiff": "image",
    ".wav": "audio", ".mp3": "audio", ".m4a": "audio", ".flac": "audio", ".ogg": "audio",
}


def strict(raw, allowed, required=()):
    if not isinstance(raw, dict) or set(raw) - set(allowed) or set(required) - set(raw):
        raise Fault("INVALID_PARAMETERS")
    return raw


def valid_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Fault("INVALID_ID")
    return value


def owner(raw):
    strict(raw, ("user_id", "agent_id", "session_hash"), ("user_id", "agent_id", "session_hash"))
    if (not isinstance(raw["agent_id"], str) or AGENT_USERS.get(raw["agent_id"]) != raw["user_id"] or
            not isinstance(raw["session_hash"], str) or not HASH.fullmatch(raw["session_hash"])):
        raise Fault("FORBIDDEN")
    return hashlib.sha256((raw["user_id"] + "\0" + raw["agent_id"] + "\0" +
                           raw["session_hash"]).encode()).hexdigest()


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise Fault("INVALID_RANGE")
    return value


def options(raw, info):
    strict(raw, ("mode", "pages", "time_range", "paragraphs", "ocr", "language"), ("mode",))
    if raw["mode"] not in ("preview", "range", "full"):
        raise Fault("INVALID_PARAMETERS")
    if raw.get("ocr", "auto") not in ("auto", "always"):
        raise Fault("INVALID_PARAMETERS")
    if raw.get("language") not in (None, "zh", "en"):
        raise Fault("INVALID_PARAMETERS")
    fields = {"pdf": "pages", "image": "pages", "audio": "time_range",
              "docx": "paragraphs", "text": "paragraphs"}
    field = fields[info["kind"]]
    specified = set(raw) & {"pages", "time_range", "paragraphs"}
    if specified and (specified != {field} or raw["mode"] != "range"):
        raise Fault("INVALID_RANGE")
    if raw["mode"] == "range" and not specified:
        raise Fault("INVALID_RANGE")
    if specified:
        interval = raw[field]
        if not isinstance(interval, list) or len(interval) != 2:
            raise Fault("INVALID_RANGE")
        if field == "time_range":
            if any(type(v) not in (int, float) or not 0 <= v <= info["duration"] for v in interval):
                raise Fault("INVALID_RANGE")
        else:
            for v in interval:
                integer(v, 1, info["units"])
        if interval[0] > interval[1] or (field == "time_range" and interval[0] == interval[1]):
            raise Fault("INVALID_RANGE")
    return {"mode": raw["mode"], "ocr": raw.get("ocr", "auto"),
            "language": raw.get("language"), **{f: raw[f] for f in specified}}
