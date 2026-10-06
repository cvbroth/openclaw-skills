"""Read published package templates by ID/version; attachments are never templates."""
import hashlib
import json
import math
import re
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).with_name("templates")
SUPPORTED_CAPABILITIES = frozenset(("reviewed-single-choice-v1", "python-docx==1.1.2", "PyMuPDF==1.25.5",
                                    "fixed-droid-font", "native-font-subset"))


def validate_parameters(parameters):
    rules = json.loads((TEMPLATE_ROOT / "schema.json").read_bytes())["parameters"]
    if not isinstance(parameters, dict) or set(parameters) != set(rules):
        raise ValueError("TEMPLATE_PARAMETER_KEYS_INVALID")
    for key, rule in rules.items():
        value = parameters[key]
        kind = rule["type"]
        if kind == "string":
            valid = isinstance(value, str) and value in rule["enum"]
        else:
            valid = (type(value) is int if kind == "integer" else type(value) in (int, float))
            valid = valid and math.isfinite(value) and rule["minimum"] <= value <= rule["maximum"]
        if not valid:
            raise ValueError("TEMPLATE_PARAMETER_INVALID: " + key)
    if (parameters["margin_cm"] < 1 or parameters["footer_distance_cm"] <= 0
            or parameters["footer_distance_cm"] >= parameters["margin_cm"]
            or parameters["option_hanging_cm"] > parameters["option_indent_cm"]
            or min(parameters[k] for k in ("body_pt", "source_pt", "footer_pt")) < 6):
        raise ValueError("TEMPLATE_GEOMETRY_INVALID")
    return dict(parameters)


def load_template(template_id=None, version=None):
    catalog = json.loads((TEMPLATE_ROOT / "catalog.json").read_bytes())
    if catalog.get("schema_version") != 1:
        raise ValueError("TEMPLATE_CATALOG_SCHEMA_INVALID")
    template_id = catalog["default"]["id"] if template_id is None else template_id
    version = catalog["default"]["version"] if version is None else version
    if (not isinstance(template_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", template_id)
            or not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version)):
        raise ValueError("TEMPLATE_ID_OR_VERSION_INVALID")
    matches = [t for t in catalog["templates"] if t["id"] == template_id and t["version"] == version]
    if len(matches) != 1 or matches[0]["status"] != "published":
        raise ValueError("TEMPLATE_NOT_PUBLISHED")
    entry = matches[0]
    if any(not isinstance(entry.get(k), str) or not entry[k] for k in
           ("name", "purpose", "supported_structure", "preview_evidence")):
        raise ValueError("TEMPLATE_CATALOG_METADATA_INVALID")
    if not isinstance(entry.get("required_capabilities"), list) or not entry["required_capabilities"]:
        raise ValueError("TEMPLATE_CAPABILITIES_REQUIRED")
    if not set(entry["required_capabilities"]).issubset(SUPPORTED_CAPABILITIES):
        raise ValueError("TEMPLATE_CAPABILITY_UNAVAILABLE")
    data = (TEMPLATE_ROOT / "published" / template_id / (version + ".json")).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("TEMPLATE_VERSION_HASH_MISMATCH")
    document = json.loads(data)
    if set(document) != {"schema_version", "parameters"} or document["schema_version"] != 1:
        raise ValueError("TEMPLATE_SCHEMA_INVALID")
    return {"record": dict(entry), "parameters": validate_parameters(document["parameters"])}
