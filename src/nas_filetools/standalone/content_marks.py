"""Conservative, version-bound edge candidates and explicit human decisions."""

from copy import deepcopy
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from .text_revisions import mapped_text
from .table_structure import tables, correct, serialize
from ..artifact_project import relative


def normalized(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text)
        if not c.isspace() and not unicodedata.category(c).startswith("P")
    ).casefold()


def mark_path(root, aid):
    path = root / "review/content-marks" / f"{aid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_marks(root, artifact):
    path = mark_path(root, artifact["artifact_id"])
    if not path.exists():
        return {
            "schema": "content-marks-v1",
            "artifact_id": artifact["artifact_id"],
            "sha256": artifact["sha256"],
            "revision": 0,
            "candidates": [],
        }
    data = json.loads(path.read_text())
    if data["sha256"] != artifact["sha256"]:
        raise ValueError("清理标记与所选文字版本哈希不一致")
    return data


def detect(rows):
    from markdown_it import MarkdownIt

    edges = []
    page_rows = defaultdict(list)
    for row in rows:
        n = row["view"].get("source_page")
        if type(n) is int and row["text"].strip() and set(row["view"].get("source_pages", [n])) == {n}:
            page_rows[n].append(row)
    edge_locations = {
        (n, side): json.dumps(group[index]["view"]["locator"], sort_keys=True)
        for n, group in page_rows.items()
        for side, index in [("header", 0), ("footer", -1)]
    }
    for row in rows:
        text, view = row["text"], row["view"]
        n = view.get("source_page")
        if type(n) is not int or set(view.get("source_pages", [n])) != {n}:
            continue
        tokens = MarkdownIt("commonmark", {"html": True}).enable("table").parse(text)
        excluded = []
        for t in tokens:
            if t.map and t.type in {
                "table_open",
                "html_block",
                "fence",
                "code_block",
                "heading_open",
                "list_item_open",
            }:
                excluded.append(t.map)
        lines = text.splitlines(keepends=True)
        offsets = []
        off = 0
        for line in lines:
            offsets.append(off)
            off += len(line)
        indices = [i for i, line in enumerate(lines) if line.strip()]
        for side, indices_side in [("header", indices[:2]), ("footer", indices[-2:])]:
            if edge_locations.get((n, side)) != json.dumps(view["locator"], sort_keys=True):
                continue
            for i in indices_side:
                raw = lines[i].rstrip("\r\n")
                body = raw.strip()
                if (
                    not body
                    or len(body) > 100
                    or any(a <= i < b for a, b in excluded)
                    or re.match(r"^(?:[#>*+-]|[A-H][.、．]|\d+[.、．)）])", body)
                ):
                    continue
                edges.append(
                    {
                        "source_page": n,
                        "locator": view["locator"],
                        "start": offsets[i],
                        "end": offsets[i] + len(raw),
                        "text": raw,
                        "side": side,
                        "normal": normalized(body),
                        "edge_rank": indices.index(i)
                        if side == "header"
                        else len(indices) - 1 - indices.index(i),
                    }
                )
    families = defaultdict(list)
    numbers = defaultdict(list)
    for edge in edges:
        if re.fullmatch(r"(?:第\s*)?[-—–]?\s*\d{1,5}\s*[-—–]?(?:\s*页)?", edge["text"].strip()):
            value = int(re.search(r"\d+", edge["text"]).group())
            numbers[edge["side"], value - edge["source_page"]].append(edge)
        elif len(edge["normal"]) >= 3:
            key = next(
                (
                    k
                    for k in families
                    if k[0] == edge["side"]
                    and SequenceMatcher(None, k[1], edge["normal"], autojunk=False).ratio() >= 0.88
                ),
                (edge["side"], edge["normal"]),
            )
            families[key].append(edge)
    selected = []
    count = len({r["view"].get("source_page") for r in rows if type(r["view"].get("source_page")) is int})
    for (side, _), members in families.items():
        distinct = len({e["source_page"] for e in members})
        if distinct >= 3 and distinct / max(count, 1) >= 0.35:
            for e in members:
                selected.append(
                    (
                        e,
                        side,
                        0.8,
                        f"来源页首尾少量内容块重复/高度相似（归一化相似度≥0.88）：{distinct}/{count}页；忽略空格和标点比较，未经人工确认不清理",
                    )
                )
    for (side, offset), members in numbers.items():
        distinct = len({e["source_page"] for e in members})
        if distinct >= 3:
            for e in members:
                selected.append(
                    (
                        e,
                        "page_number",
                        0.65,
                        f"页边缘文字顺序；至少{distinct}页印刷数字与物理页固定偏移{offset:+d}；无图像坐标时仅为疑似页码",
                    )
                )
    result = {}
    for edge, kind, confidence, reason in selected:
        key = json.dumps(
            [edge["locator"], edge["start"], edge["end"], edge["text"]], sort_keys=True, ensure_ascii=False
        )
        mid = hashlib.sha256(key.encode()).hexdigest()[:24]
        result[mid] = {k: v for k, v in edge.items() if k not in {"normal", "side"}} | {
            "id": mid,
            "kind": kind,
            "confidence": confidence,
            "basis": reason,
            "decision": "pending",
            "coordinates": None,
            "coordinate_note": "没有可靠文字框坐标；首尾顺序证据不是像素位置",
        }
    return list(result.values())


def attach_coordinates(root, rows, candidates):
    """Reuse exact block evidence; input-image boxes are not mislabeled original coordinates."""
    from .direct_source import read_payload

    for mark in candidates:
        row = next(r for r in rows if r["view"]["locator"] == mark["locator"])
        try:
            payload = read_payload(root, row["view"]["data"])
            if not payload.get("raw_path"):
                continue
            result = json.loads(relative(root, payload["raw_path"]).read_text())
            for block in result.get("blocks", []):
                if (
                    (block.get("text") or "").strip() != mark["text"].strip()
                    or not block.get("coordinates")
                    or not block.get("coordinate_system")
                ):
                    continue
                mark["input_coordinate_evidence"] = {
                    "coordinates": block["coordinates"],
                    "coordinate_system": block["coordinate_system"],
                    "input": result.get("input"),
                    "block_id": block.get("id"),
                    "raw_path": payload["raw_path"],
                }
                if block["coordinate_system"] in {
                    "source-pdf-points",
                    "original-image-pixels",
                    "PDF points; source physical page",
                }:
                    mark["coordinates"] = deepcopy(block["coordinates"])
                    mark["coordinate_system"] = block["coordinate_system"]
                    mark["coordinate_note"] = "复用精确匹配的原始块坐标"
                else:
                    mark["coordinate_note"] = "保留输入图坐标证据；未获可靠原图变换，不冒充原图坐标"
                break
        except (ValueError, OSError, KeyError):
            continue


def inherit_marks(root, project, parent, child, changes):
    from .tasks import atomic

    old = read_marks(root, parent)
    if not old["candidates"]:
        return
    data = deepcopy(old)
    data.update(
        artifact_id=child["artifact_id"],
        sha256=child["sha256"],
        revision=1,
        parent_artifact_id=parent["artifact_id"],
    )
    changed = {json.dumps(c["locator"], sort_keys=True) for c in changes}
    for mark in data["candidates"]:
        if json.dumps(mark["locator"], sort_keys=True) in changed:
            mark["previous_decision"] = mark["decision"]
            mark["decision"] = "needs_review"
            mark["basis"] += "；该片段人工修订，旧范围未重新核实，禁止清理"
            mark["coordinates"] = None
    atomic(mark_path(root, child["artifact_id"]), data)


def clean_rows(rows, marks, settings):
    result = []
    summary = []
    for row in rows:
        text = row["text"]
        ranges = []
        for mark in marks["candidates"]:
            if (
                mark["decision"] != "confirmed"
                or mark.get("actor_type") != "human-self-declared"
                or mark["locator"] != row["view"]["locator"]
            ):
                continue
            if not (
                (mark["kind"] == "header" and settings.get("remove_headers"))
                or (mark["kind"] in {"footer", "page_number"} and settings.get("remove_footers"))
            ):
                continue
            a, b = mark["start"], mark["end"]
            if text[a:b] != mark["text"]:
                raise ValueError("确认标记文字范围已变化，需要重新复核")
            if any(t["start"] < b and a < t["end"] for t in tables(text)):
                raise ValueError("清理标记触及表格，拒绝删除表格内容")
            ranges.append((a, b))
            summary.append(deepcopy(mark))
        ordered = sorted(ranges)
        if any(b > c for (a, b), (c, d) in zip(ordered, ordered[1:])):
            raise ValueError("确认清理范围重叠，需要复核")
        for a, b in reversed(ordered):
            text = text[:a] + text[b:]
        result.append({**row, "text": text})
    return result, summary


class ContentMarks:
    def content_marks(self, pid, aid):
        with self.lock:
            p = self.get(pid)
            a = next(a for a in p["artifacts"] if a["artifact_id"] == aid)
            relative(self.path(pid), a["path"])
            return read_marks(self.path(pid), a)

    def identify_marks(self, pid, aid):
        from .tasks import atomic

        with self.lock:
            p = self.get(pid)
            a = next(a for a in p["artifacts"] if a["artifact_id"] == aid)
            root = self.path(pid)
            old = read_marks(root, a)
            existing = {m["id"]: m for m in old["candidates"]}
            rows = mapped_text(root, a)
            found = detect(rows)
            attach_coordinates(root, rows, found)
            for mark in found:
                if mark["id"] not in existing:
                    existing[mark["id"]] = mark
            data = {**old, "revision": old["revision"] + 1, "candidates": list(existing.values())}
            atomic(mark_path(root, aid), data)
            return data

    def decide_marks(self, pid, aid, request):
        from .tasks import atomic, now

        with self.lock:
            data = self.content_marks(pid, aid)
            if request["revision"] != data["revision"]:
                raise ValueError("标记决定已更新，请刷新后重试")
            if request.get("reviewer_type", "human") not in {"human", "developer-agent"}:
                raise ValueError("未知决定人类型")
            if request["decision"] not in {"confirmed", "rejected", "pending"}:
                raise ValueError("未知人工决定")
            ids = set(request["ids"])
            known = {m["id"] for m in data["candidates"]}
            if not ids or not ids <= known:
                raise ValueError("未知候选标记")
            for mark in data["candidates"]:
                if mark["id"] not in ids:
                    continue
                if mark["decision"] == "needs_review" and request["decision"] == "confirmed":
                    raise ValueError("修订后的失效标记不能直接确认；请重新选择文字范围")
                if request.get("kind"):
                    if request["kind"] not in {"header", "footer", "page_number", "body"}:
                        raise ValueError("未知清理类型")
                    mark["kind"] = request["kind"]
                mark.update(
                    decision=request["decision"],
                    decided_at=now(),
                    actor_type="developer-agent"
                    if request.get("reviewer_type") == "developer-agent"
                    else "human-self-declared",
                )
            data["revision"] += 1
            path = mark_path(self.path(pid), aid)
            atomic(path.with_name(f"{aid}-decision-{data['revision']}.json"), data)
            atomic(path, data)
            return data

    def manual_mark(self, pid, aid, request):
        from .tasks import atomic

        with self.lock:
            data = self.content_marks(pid, aid)
            if request["revision"] != data["revision"]:
                raise ValueError("标记版本已变化，请刷新")
            a = next(a for a in self.get(pid)["artifacts"] if a["artifact_id"] == aid)
            row = next(
                r for r in mapped_text(self.path(pid), a) if r["view"]["locator"] == request["locator"]
            )
            start, end = request["start"], request["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(row["text"]):
                raise ValueError("请选择非空的文字范围")
            if request["kind"] not in {"header", "footer", "page_number"}:
                raise ValueError("未知标记类型")
            if any(t["start"] < end and start < t["end"] for t in tables(row["text"])):
                raise ValueError("不能将表格内容登记为页眉页脚清理")
            text = row["text"][start:end]
            mid = hashlib.sha256(
                json.dumps(
                    [request["locator"], start, end, text], sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()[:24]
            mark = {
                "id": mid,
                "source_page": row["view"].get("source_page"),
                "locator": request["locator"],
                "start": start,
                "end": end,
                "text": text,
                "kind": request["kind"],
                "confidence": 1.0,
                "basis": "用户对照原文手工选择具体范围，待明确确认",
                "decision": "pending",
                "coordinates": None,
            }
            data["candidates"] = [m for m in data["candidates"] if m["id"] != mid] + [mark]
            data["revision"] += 1
            path = mark_path(self.path(pid), aid)
            atomic(path.with_name(f"{aid}-manual-{data['revision']}.json"), data)
            atomic(path, data)
            return data

    def table_info(self, pid, aid, locator):
        row = next(
            r
            for r in mapped_text(
                self.path(pid), next(a for a in self.get(pid)["artifacts"] if a["artifact_id"] == aid)
            )
            if r["view"]["locator"] == locator
        )
        return tables(row["text"])

    def revise_table(self, pid, request):
        info = self.text_artifact(pid, request["parent_artifact_id"])
        page = next(x for x in info["pages"] if x["locator"] == request["locator"])
        table = next(t for t in tables(page["text"]) if t["id"] == request["table_id"])
        if table.get("error"):
            raise ValueError(table["error"] + "；请在原文编辑中修正，不能猜测丢失单元格")
        model = correct(table["model"], request)
        text = page["text"][: table["start"]] + serialize(model) + "\n\n" + page["text"][table["end"] :]
        return self.save_text_revision(
            pid,
            {
                k: request[k]
                for k in [
                    "request_id",
                    "parent_artifact_id",
                    "parent_sha256",
                    "head_id",
                    "head_sha256",
                    "locator",
                ]
            }
            | {"text": text, "reviewer_type": request.get("reviewer_type", "human")},
        )
