"""Private development extension of the existing catalog/published/drafts registry."""

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from ..document_templates import TEMPLATE_ROOT, validate_parameters
from ..artifact_project import digest
from .word_import import WordImports
from .word_styles import validate_styles


def installed_fonts():
    result = subprocess.check_output(
        ["fc-list", "--format", "%{family}\t%{file}\n"], text=True, timeout=10, stderr=subprocess.DEVNULL
    )
    fonts = {}
    for row in result.splitlines():
        family, _, path = row.partition("\t")
        if not Path(path).is_file():
            continue
        for name in family.split(","):
            fonts.setdefault(name, {"name": name, "path": path, "sha256": digest(path)})
    return fonts


class TemplateLibrary(WordImports):
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.exists():
            shutil.copytree(TEMPLATE_ROOT, self.root)
        self.fonts = installed_fonts()

    def catalog(self):
        return json.loads((self.root / "catalog.json").read_text())

    def write_catalog(self, data):
        from .tasks import atomic

        atomic(self.root / "catalog.json", data)

    def validate(self, doc):
        if not isinstance(doc, dict):
            raise ValueError("template: object required")
        expected = {"schema_version", "id", "version", "name", "description", "content_types", "parameters"}
        if doc.get("schema_version") == 3:
            expected.add("word_styles")
            if "import_source" in doc:
                expected.add("import_source")
        if set(doc) != expected:
            raise ValueError("template fields: " + str(sorted(set(doc) ^ expected)))
        if doc["schema_version"] not in {2, 3}:
            raise ValueError("schema_version: expected 2 or 3")
        for k, pattern in [("id", r"[a-z0-9][a-z0-9-]{0,63}"), ("version", r"\d+\.\d+\.\d+")]:
            if not isinstance(doc[k], str) or len(doc[k]) > 64 or not re.fullmatch(pattern, doc[k]):
                raise ValueError(k + ": invalid")
        for k in ["name", "description"]:
            if not isinstance(doc[k], str) or not 1 <= len(doc[k]) <= 300:
                raise ValueError(k + ": 1..300 characters required")
        if (
            not isinstance(doc["content_types"], list)
            or not doc["content_types"]
            or not all(isinstance(t, str) for t in doc["content_types"])
            or not set(doc["content_types"]) <= {"markdown-basic", "reviewed-single-choice"}
        ):
            raise ValueError("content_types: unsupported")
        params = doc["parameters"]
        if not isinstance(params, dict):
            raise ValueError("parameters: object required")
        rules = json.loads((TEMPLATE_ROOT / "schema.json").read_text())["parameters"]
        unknown = set(params) - set(rules)
        missing = [k for k, v in rules.items() if k not in params and "default" not in v]
        if unknown or missing:
            raise ValueError("parameters: unknown " + str(sorted(unknown)) + "; missing " + str(missing))
        family = params.get("font_family")
        if family not in self.fonts:
            raise ValueError("parameters.font_family: not installed")
        # Same parameter schema as the package, with a server-proven font choice.
        if (
            all(type(params.get(k)) in {int, float} for k in ["footer_distance_cm", "margin_cm"])
            and params["footer_distance_cm"] >= params["margin_cm"]
        ):
            raise ValueError("parameters.footer_distance_cm: 页脚距离须小于统一边距（cm）")
        if (
            all(type(params.get(k)) in {int, float} for k in ["option_hanging_cm", "option_indent_cm"])
            and params["option_hanging_cm"] > params["option_indent_cm"]
        ):
            raise ValueError("parameters.option_hanging_cm: 悬挂须不大于选项缩进（cm）")
        try:
            validate_parameters({**params, "font_family": "Droid Sans Fallback"})
        except ValueError as exc:
            key = str(exc).partition(": ")[2]
            if key in rules:
                rule = rules[key]
                limits = (
                    f"{rule.get('minimum')}–{rule.get('maximum')}"
                    if "minimum" in rule
                    else str(rule.get("enum", rule["type"]))
                )
                raise ValueError(f"parameters.{key}: 无效值；允许范围/类型 {limits}（单位见字段）") from exc
            raise
        if doc["schema_version"] == 3:
            validate_styles(doc["word_styles"])
            if "import_source" in doc:
                import uuid

                source = doc["import_source"]
                if not isinstance(source, dict) or set(source) != {
                    "import_id",
                    "sha256",
                    "section_index",
                    "font_selection_confirmed",
                }:
                    raise ValueError("import_source: 导入来源字段不完整或未知")
                iid = str(uuid.UUID(source["import_id"]))
                record = json.loads((self.root / "imports" / iid / "report.json").read_text())
                original = (
                    self.root / "imports" / iid / ("original" + Path(record["filename"]).suffix.lower())
                )
                if not original.is_file() or digest(original) != record["file_sha256"]:
                    raise ValueError("import_source.sha256: 原始导入文件变化")
                if (
                    source.get("sha256") != record["file_sha256"]
                    or source.get("font_selection_confirmed") is not True
                ):
                    raise ValueError("import_source.font_selection_confirmed: 请明确选择统一服务器字体")
                if type(source.get("section_index")) is not int or not 0 <= source["section_index"] < len(
                    record["sections"]
                ):
                    raise ValueError("import_source.section_index: 请选择适用节")
        return copy.deepcopy(doc)

    def path(self, entry):
        return self.root / entry["status"] / entry["id"] / (entry["version"] + ".json")

    def load(self, tid, version, allow_draft=False):
        matches = [e for e in self.catalog()["templates"] if e["id"] == tid and e["version"] == version]
        if len(matches) != 1:
            raise ValueError("template: unknown ID/version")
        e = matches[0]
        if e["status"] != "published" and not allow_draft:
            raise ValueError("template: draft is preview-only")
        raw = self.path(e).read_bytes()
        if hashlib.sha256(raw).hexdigest() != e["sha256"]:
            raise ValueError("template.sha256: changed immutable version")
        d = json.loads(raw)
        if d["schema_version"] == 1:
            params = validate_parameters(d["parameters"])
            doc = {
                "schema_version": 2,
                "id": e["id"],
                "version": e["version"],
                "name": e["name"],
                "description": e["purpose"],
                "content_types": ["reviewed-single-choice", "markdown-basic"],
                "parameters": params,
            }
        else:
            doc = self.validate(d)
            params = validate_parameters({**doc["parameters"], "font_family": "Droid Sans Fallback"})
            params["font_family"] = doc["parameters"]["font_family"]
        if params["font_family"] not in self.fonts:
            raise ValueError("parameters.font_family: not installed")
        return {
            "record": dict(e),
            "document": doc,
            "parameters": params,
            "font": self.fonts[params["font_family"]],
            "word_styles": doc.get("word_styles"),
        }

    def save(self, doc):
        doc = self.validate(doc)
        catalog = self.catalog()
        if any(e["id"] == doc["id"] and e["version"] == doc["version"] for e in catalog["templates"]):
            raise ValueError("version: already exists; save a new version")
        path = self.root / "drafts" / doc["id"] / (doc["version"] + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        entry = {
            "id": doc["id"],
            "version": doc["version"],
            "name": doc["name"],
            "purpose": doc["description"],
            "supported_structure": ", ".join(doc["content_types"]),
            "status": "drafts",
            "sha256": digest(path),
            "required_capabilities": ["markdown-basic-v1", "python-docx==1.1.2", "libreoffice-pdf-export"],
            "preview_evidence": "not performed",
        }
        catalog["templates"].append(entry)
        self.write_catalog(catalog)
        return entry

    def publish(self, tid, version, project):
        loaded = self.load(tid, version, True)
        entry = loaded["record"]
        if entry["status"] == "published":
            return entry
        if project.get("project_kind") != "template-preview":
            raise ValueError("preview: fixed synthetic project required")
        tasks = project.get("tasks", [])
        if not any(
            t.get("template", {}).get("id") == tid
            and t.get("template", {}).get("version") == version
            and t.get("template_sha256") == entry["sha256"]
            and t["status"] == "SUCCEEDED"
            for t in tasks
        ):
            raise ValueError("preview: successful fixed-content generation required")
        required = [a for a in project["artifacts"] if a["format"] in {"docx", "pdf"}]
        if {a["format"] for a in required} != {"docx", "pdf"} or any(
            a.get("preview_render", {}).get("status") != "SUCCEEDED" for a in required
        ):
            raise ValueError("preview: actual Word and PDF images required")
        destination = self.root / "published" / tid / (version + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.path(entry).open("rb") as a, destination.open("xb") as b:
            shutil.copyfileobj(a, b)
        catalog = self.catalog()
        for e in catalog["templates"]:
            if e["id"] == tid and e["version"] == version:
                e.update(
                    status="published",
                    preview_evidence="fixed synthetic preview project " + project["project_id"],
                )
                entry = e
        # Draft file remains as history; catalog now points to the published immutable file.
        self.write_catalog(catalog)
        return entry
