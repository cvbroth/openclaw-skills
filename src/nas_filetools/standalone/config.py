"""Versioned trusted-server configuration. Never accepts credentials from HTTP."""

import json
import re
from urllib.parse import urlsplit

TYPES = {"rapidocr", "minimax-messages", "openai-vision", "fixture"}


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("configuration integer out of range")
    return value


def validate(data, *, testing=False):
    if set(data) != {"version", "service", "conversion", "template", "engines"} or data["version"] != 1:
        raise ValueError("configuration schema/version")
    service = data["service"]
    if (
        set(service) != {"upload_bytes", "max_pages", "max_pixels", "bind", "port"}
        or service["bind"] != "127.0.0.1"
    ):
        raise ValueError("loopback service configuration required")
    integer(service["upload_bytes"], 1024, 512 * 1024 * 1024)
    integer(service["max_pages"], 1, 1000)
    integer(service["max_pixels"], 100000, 40000000)
    integer(service["port"], 1024, 65535)
    conversion = data["conversion"]
    if set(conversion) != {"dpi", "language", "quality", "max_selected_pages", "generate_documents"}:
        raise ValueError("conversion keys")
    integer(conversion["dpi"], 100, 300)
    integer(conversion["max_selected_pages"], 1, 20)
    if conversion["language"] not in {"zh", "en"} or any(
        type(conversion[k]) is not bool for k in ["quality", "generate_documents"]
    ):
        raise ValueError("conversion values")
    if set(data["template"]) != {"id", "version"}:
        raise ValueError("template keys")
    from ..document_templates import load_template

    load_template(data["template"]["id"], data["template"]["version"])
    if not isinstance(data["engines"], dict) or not data["engines"]:
        raise ValueError("engines required")
    for name, engine in data["engines"].items():
        if not re.fullmatch(r"[a-z0-9-]{1,40}", name) or set(engine) != {
            "type",
            "model",
            "endpoint",
            "credential_env",
            "timeout",
            "concurrency",
            "retries",
            "cpu_threads",
        }:
            raise ValueError("engine keys/id")
        if engine["type"] not in TYPES or (engine["type"] == "fixture" and not testing):
            raise ValueError("engine type")
        integer(engine["timeout"], 1, 1800)
        integer(engine["cpu_threads"], 1, 2)
        if (
            type(engine["concurrency"]) is not int
            or type(engine["retries"]) is not int
            or engine["concurrency"] != 1
            or engine["retries"] != 0
        ):
            raise ValueError("single queue; explicit retries only")
        if engine["type"] in {"minimax-messages", "openai-vision"}:
            url = urlsplit(engine["endpoint"])
            if url.username or url.password or url.query or url.fragment or not url.hostname:
                raise ValueError("endpoint must not contain credentials/query")
            if url.scheme != "https" and not (testing and url.hostname in {"127.0.0.1", "localhost"}):
                raise ValueError("HTTPS endpoint required")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", engine["credential_env"]):
                raise ValueError("credential environment reference required")
        elif engine["endpoint"] or engine["credential_env"]:
            raise ValueError("local engine does not take remote credentials")
    return data


def load(path, testing=False):
    with open(path, encoding="utf-8") as stream:
        return validate(json.load(stream), testing=testing)


def snapshot(engine):
    return {k: v for k, v in engine.items() if k != "credential_env"}


def capabilities(engine):
    native = engine["type"] == "rapidocr"
    return {
        "images": True,
        "transcription": True,
        "quality": not native,
        "native_structure": native,
        "coordinates": native,
        "input": "one PNG/JPEG per call; bounded pixels; PDF rendered by task layer",
        "protocol": engine["type"],
        "verified_provider_scope": "MiniMax messages only"
        if engine["type"] == "minimax-messages"
        else "configured endpoint only; not all providers",
    }
