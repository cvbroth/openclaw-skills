"""Strict shared contracts; callers never supply a source/output path to the service."""

import hashlib
import re
from dataclasses import asdict, dataclass, field


class Fault(Exception):
    def __init__(self, code, message=""):
        self.code = code
        self.message = message or code
        super().__init__(code + (": " + message if message else ""))


@dataclass(frozen=True)
class Limits:
    max_receive_bytes: int = 4 * 1024**3
    max_process_bytes: int = 4 * 1024**3
    max_control_bytes: int = 512 * 1024
    max_response_bytes: int = 2 * 1024**2
    max_pages: int = 10000
    max_audio_seconds: int = 21600
    audio_chunk_seconds: int = 600
    audio_overlap_seconds: int = 2
    max_image_pixels: int = 24_000_000
    max_docx_expanded_bytes: int = 128 * 1024**2
    max_text_bytes: int = 16 * 1024**2
    max_output_chars: int = 2_000_000
    max_asset_bytes: int = 32 * 1024**2
    max_read_chars: int = 12000
    max_segments: int = 20000
    max_manifest_bytes: int = 64 * 1024**2
    max_engine_log_bytes: int = 2 * 1024**2
    preview_pages: int = 3
    large_pages: int = 20
    large_audio_seconds: int = 600
    ttl_seconds: int = 72 * 3600
    cleanup_interval_seconds: int = 3600
    timeout_seconds: int = 3600
    audio_wall_factor: int = 8
    max_job_seconds: int = 72 * 3600
    stall_seconds: int = 1800
    upload_timeout_seconds: int = 3600
    script_timeout_seconds: int = 60
    script_output_bytes: int = 256 * 1024**2
    concurrency: int = 1
    engine_threads: int = 2
    worker_memory_mb: int = 4096
    inspection_timeout_seconds: int = 15
    max_jobs_per_scope: int = 32
    max_references_per_session: int = 32
    snapshot_quota_bytes: int = 100 * 1024**3
    saved_quota_bytes: int = 50 * 1024**3
    cache_quota_bytes: int = 20 * 1024**3
    disk_reserve_bytes: int = 1024**3
    quota_warning_percent: int = 80
    enabled_agents: tuple = ("main", "chen", "liang", "ziling")
    whisper_model: str = "small"
    model_cache: str = "/var/cache/nas-filetools"
    script_python: str = ""
    script_isolation: str = "landlock"
    offline: bool = True
    workspace_mode: bool = False
    gateway_workspace: str = ""
    source_roots: dict = field(default_factory=dict)

    def __post_init__(self):
        excluded = ("enabled_agents", "whisper_model", "model_cache", "script_python", "script_isolation", "offline",
                    "workspace_mode", "gateway_workspace", "source_roots")
        if any(type(value) is not int or value < 1 for name, value in asdict(self).items() if name not in excluded):
            raise Fault("INVALID_CONFIG")
        if (self.concurrency != 1 or self.engine_threads > 8 or self.worker_memory_mb < 256 or
                self.inspection_timeout_seconds > 60 or self.max_read_chars > 12000 or
                self.max_receive_bytes > 2**63-1 or self.max_control_bytes < 6*self.max_read_chars+8192 or
                self.snapshot_quota_bytes < self.max_receive_bytes or self.saved_quota_bytes < self.max_receive_bytes or
                self.max_process_bytes > self.max_receive_bytes or self.audio_overlap_seconds >= self.audio_chunk_seconds or
                self.quota_warning_percent > 100 or type(self.offline) is not bool):
            raise Fault("INVALID_CONFIG")
        if (not isinstance(self.enabled_agents, (tuple, list)) or not self.enabled_agents or
                any(not isinstance(a, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", a) for a in self.enabled_agents)):
            raise Fault("INVALID_CONFIG")
        object.__setattr__(self, "enabled_agents", tuple(self.enabled_agents))
        if any(not isinstance(getattr(self, k), str) for k in ("whisper_model", "model_cache", "script_python")):
            raise Fault("INVALID_CONFIG")
        if self.script_isolation not in ("landlock", "development"):
            raise Fault("INVALID_CONFIG")
        if (type(self.workspace_mode) is not bool or not isinstance(self.gateway_workspace, str) or
                not isinstance(self.source_roots, dict) or self.workspace_mode and len(self.enabled_agents) != 1):
            raise Fault("INVALID_WORKSPACE_CONFIG")

    @property
    def max_bytes(self):  # Read compatibility for V1 adapters, not a second configurable limit.
        return self.max_receive_bytes

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
    if (not isinstance(raw["agent_id"], str) or AGENT_USERS.get(raw["agent_id"], raw["agent_id"]) != raw["user_id"] or
            not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", raw["agent_id"]) or
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
    if info["kind"] not in fields:
        raise Fault("UNSUPPORTED_TYPE")
    if info.get("parse_error"):
        raise Fault(info["parse_error"])
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
