"""Immutable mapped-text revisions, independent of recognition and formatting."""

from copy import deepcopy
from datetime import datetime, timezone
import difflib
import json
import hashlib
import os
import shutil
import uuid

from ..artifact_project import digest, page_data, register_artifact, relative
from .content_structure import parse_markdown, reading_html


class RevisionConflict(ValueError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat()


def mapped_text(root, artifact):
    if artifact.get("recycled") or artifact["format"] != "markdown" or not artifact.get("path"):
        raise ValueError("仅可编辑已登记且未回收的 Markdown")
    if digest(relative(root, artifact["path"])) != artifact["sha256"]:
        raise RevisionConflict("文字稿哈希已变化，请重新打开")
    rows, seen = [], set()
    for view in artifact.get("pages", []):
        loc = view.get("locator")
        key = json.dumps(loc, sort_keys=True)
        if not loc or loc.get("kind") not in {"block", "physical_page", "page"} or key in seen:
            raise ValueError("缺少唯一稳定分段映射，不能逐页修补")
        seen.add(key)
        if not view.get("data") or not view.get("data_sha256"):
            raise ValueError("缺少已核实的逐页文字映射，不能猜页")
        path = relative(root, view["data"])
        if digest(path) != view["data_sha256"]:
            raise RevisionConflict("页面文字资源哈希变化")
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("window.PROJECT_PAGE="):
            raise ValueError("未知文字资源格式")
        data = json.loads(raw.split("=", 1)[1].rstrip(";\n"))
        if not isinstance(data.get("text"), str):
            raise ValueError("页面文字缺失")
        rows.append({"view": deepcopy(view), "text": data["text"]})
    if not rows:
        raise ValueError("此历史稿没有逐页或稳定分段映射，不能逐页修补")
    # Only accept complete, evidenced assembly. Never infer page boundaries from prose.
    body = relative(root, artifact["path"]).read_text(encoding="utf-8")
    plain = "\n\n".join(r["text"] for r in rows)
    tid = artifact.get("task_id")
    marked = "\n\n".join(
        f"<!-- source physical page {r['view'].get('source_page')}; task {tid} -->\n" + r["text"]
        for r in rows
    )
    if body not in {plain, marked}:
        raise ValueError("整稿与逐页映射不一致；保留原件，禁用编辑")
    return rows


class TextRevisions:
    def text_artifact(self, pid, aid):
        with self.lock:
            p = self.get(pid)
            a = next((a for a in p["artifacts"] if a["artifact_id"] == aid), None)
            if not a:
                raise ValueError("未知文字产物")
            root_id = a.get("text_revision", {}).get("root_artifact_id", aid)
            head_id = p.get("text_revision_heads", {}).get(root_id, root_id)
            head = next(a for a in p["artifacts"] if a["artifact_id"] == head_id)
            rows = mapped_text(self.path(pid), a)
            return {
                "artifact_id": aid,
                "sha256": a["sha256"],
                "head_id": head_id,
                "head_sha256": head["sha256"],
                "root_artifact_id": root_id,
                "pages": [
                    {
                        "locator": r["view"]["locator"],
                        "source_page": r["view"].get("source_page"),
                        "text": r["text"],
                    }
                    for r in rows
                ],
                "history": [
                    {"artifact_id": x["artifact_id"], "version": x["version"], "sha256": x["sha256"]}
                    for x in p["artifacts"]
                    if x["artifact_id"] == root_id
                    or x.get("text_revision", {}).get("root_artifact_id") == root_id
                ],
                "template": p.get("selected_template"),
            }

    def save_text_revision(self, pid, request):
        from .tasks import atomic

        allowed = {
            "request_id",
            "parent_artifact_id",
            "parent_sha256",
            "head_id",
            "head_sha256",
            "locator",
            "text",
            "restore_artifact_id",
            "reviewer_type",
        }
        if set(request) - allowed:
            raise ValueError("未知修订字段")
        reviewer = request.get("reviewer_type", "unspecified")
        if reviewer not in {"human", "developer-agent", "unspecified"}:
            raise ValueError("未知审阅者类型")
        rid = str(uuid.UUID(request["request_id"]))
        fingerprint = hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        with self.lock:
            p = self.get(pid)
            receipts = p.setdefault("text_revision_requests", {})
            if rid in receipts:
                old = receipts[rid]
                if old["request"] != fingerprint:
                    raise RevisionConflict("相同请求 ID 对应不同内容")
                return {**old["receipt"], "replayed": True}
            info = self.text_artifact(pid, request["parent_artifact_id"])
            if (
                request["parent_sha256"] != info["sha256"]
                or request["head_id"] != info["head_id"]
                or request["head_sha256"] != info["head_sha256"]
            ):
                raise RevisionConflict("基础版本冲突；请保留草稿并重新打开最新版本")
            # Editing a historical version requires explicit restore, not an accidental branch.
            if info["artifact_id"] != info["head_id"] and not request.get("restore_artifact_id"):
                raise RevisionConflict("历史版本只读；请恢复为新版本后编辑")
            parent = next(a for a in p["artifacts"] if a["artifact_id"] == info["artifact_id"])
            root = self.path(pid)
            rows = mapped_text(root, parent)
            changes = []
            if request.get("restore_artifact_id"):
                restored = self.text_artifact(pid, request["restore_artifact_id"])
                if restored["root_artifact_id"] != info["root_artifact_id"]:
                    raise ValueError("不能恢复其他修订链")
                replacement = {json.dumps(x["locator"], sort_keys=True): x["text"] for x in restored["pages"]}
                if set(replacement) != {json.dumps(x["view"]["locator"], sort_keys=True) for x in rows}:
                    raise ValueError("历史位置映射不一致")
            else:
                text = request.get("text")
                if not isinstance(text, str) or len(text.encode()) > 500_000 or "\x00" in text:
                    raise ValueError("文字必须为不含 NUL 的字符串，单段最多500000字节")
                key = json.dumps(request.get("locator"), sort_keys=True)
                if key not in {json.dumps(x["view"]["locator"], sort_keys=True) for x in rows}:
                    raise ValueError("未知稳定位置")
                replacement = {key: text}
            for row in rows:
                key = json.dumps(row["view"]["locator"], sort_keys=True)
                new = replacement.get(key, row["text"])
                if new != row["text"]:
                    changes.append(
                        {
                            "locator": row["view"]["locator"],
                            "source_page": row["view"].get("source_page"),
                            "before": row["text"],
                            "after": new,
                        }
                    )
                    row["text"] = new
            receipt = {
                "artifact_id": parent["artifact_id"],
                "sha256": parent["sha256"],
                "no_change": not changes,
                "engine_calls": 0,
            }
            if not changes:
                return receipt
            revision_id = str(uuid.uuid4())
            final = root / "content" / "revisions" / revision_id
            staging = final.with_name("." + revision_id)
            staging.mkdir(parents=True)
            committed = False
            try:
                (staging / "content.md").write_text("\n\n".join(x["text"] for x in rows), encoding="utf-8")
                views, structures = [], []
                for i, row in enumerate(rows):
                    view = row["view"]
                    model = parse_markdown(
                        row["text"],
                        {"locator": view["locator"], "source_sha256": p["artifacts"][0]["sha256"]},
                    )
                    page_data(
                        staging, f"page-{i}.js", {"text": row["text"], "reading_html": reading_html(model)}
                    )
                    view["data"] = f"content/revisions/{revision_id}/page-{i}.js"
                    view["data_sha256"] = digest(staging / f"page-{i}.js")
                    views.append(view)
                    structures.append(
                        {
                            "physical_page": view.get("source_page"),
                            "locator": view["locator"],
                            "text": row["text"],
                            "structure": model,
                            "coordinates": None,
                            "coordinate_note": "source evidence only; edited text has no precise coordinates",
                        }
                    )
                atomic(
                    staging / "structure.json",
                    {
                        "schema": "manual-text-structure-v1",
                        "project_id": pid,
                        "source_sha256": p["artifacts"][0]["sha256"],
                        "pages": structures,
                    },
                )
                record = {
                    "schema": "manual-text-revision-v1",
                    "project_id": pid,
                    "revision_id": revision_id,
                    "parent_artifact_id": parent["artifact_id"],
                    "parent_sha256": parent["sha256"],
                    "root_artifact_id": info["root_artifact_id"],
                    "created_at": stamp(),
                    "actor_type": "developer-agent"
                    if reviewer == "developer-agent"
                    else "human-self-declared"
                    if reviewer == "human"
                    else "unspecified-interface",
                    "identity_verified": False,
                    "changes": changes,
                    "restore_artifact_id": request.get("restore_artifact_id"),
                    "source_sha256": p["artifacts"][0]["sha256"],
                }
                atomic(staging / "revision.json", record)
                os.replace(staging, final)
                base = str(final.relative_to(root))
                a = register_artifact(
                    root,
                    p,
                    name="修订文字",
                    format="markdown",
                    path=base + "/content.md",
                    version=str(len(info["history"]) + 1),
                    parents=[parent["artifact_id"]],
                    pages=views,
                )
                a.update(
                    role="result",
                    content_nature="manual-revision",
                    text_revision={
                        "root_artifact_id": info["root_artifact_id"],
                        "parent_artifact_id": parent["artifact_id"],
                        "revision_id": revision_id,
                        "record": base + "/revision.json",
                        "created_at": record["created_at"],
                    },
                )
                for file in ("structure.json", "revision.json"):
                    diagnostic = register_artifact(
                        root, p, name=file, format="json", path=base + "/" + file, parents=[a["artifact_id"]]
                    )
                    diagnostic["role"] = "diagnostic"
                p.setdefault("text_revision_heads", {})[info["root_artifact_id"]] = a["artifact_id"]
                receipt = {
                    "artifact_id": a["artifact_id"],
                    "sha256": a["sha256"],
                    "no_change": False,
                    "engine_calls": 0,
                }
                receipts[rid] = {"request": fingerprint, "receipt": receipt}
                # One atomic registry commit after all referenced resources are complete.
                from .naming import decorate

                decorate(p)
                atomic(root / "project.json", p)
                committed = True
                return receipt
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
                if not committed and final.exists():
                    shutil.rmtree(final)

    def text_diff(self, pid, aid, against):
        left, right = self.text_artifact(pid, against), self.text_artifact(pid, aid)
        if left["root_artifact_id"] != right["root_artifact_id"]:
            raise ValueError("不同修订链不能比较")
        before = "\n\n".join(x["text"] for x in left["pages"])
        after = "\n\n".join(x["text"] for x in right["pages"])
        return {
            "before_artifact_id": against,
            "after_artifact_id": aid,
            "diff": "".join(
                difflib.unified_diff(
                    before.splitlines(True), after.splitlines(True), fromfile="历史文字", tofile="当前文字"
                )
            ),
        }
