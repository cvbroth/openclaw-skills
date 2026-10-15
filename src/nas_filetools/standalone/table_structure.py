"""Source-ranged tables. Explicit rectangular spans, never guessed merged cells."""

import hashlib
import html
import re
from html.parser import HTMLParser


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.cell = None
        self.row = None
        self.header = False
        self.depth = 0
        self.inline = []

    def handle_starttag(self, tag, attrs):
        allowed = {
            "table",
            "thead",
            "tbody",
            "tfoot",
            "tr",
            "td",
            "th",
            "br",
            "p",
            "strong",
            "b",
            "em",
            "i",
            "code",
            "caption",
            "a",
        }
        if tag not in allowed:
            raise ValueError("表格包含不支持的标签：" + tag)
        attrs = dict(attrs)
        if "style" in attrs:
            match = re.fullmatch(r"text-align:\s*(left|center|right);?", attrs.pop("style").strip())
            if not match:
                raise ValueError("表格CSS仅支持明确的文字对齐")
            attrs["align"] = match.group(1)
        if attrs.get("align") not in {None, "left", "center", "right"}:
            raise ValueError("不支持的单元格对齐")
        if tag == "a" and attrs.get("href"):
            url = attrs["href"]
            if re.match(r"^[a-zA-Z][\w+.-]*:", url) and not re.match(r"^(https?|mailto):", url, re.I):
                raise ValueError("不支持的表格链接协议")
        if set(attrs) - ({"href"} if tag == "a" else {"rowspan", "colspan", "scope", "align"}):
            raise ValueError("表格仅允许 rowspan/colspan/scope 属性")
        if tag == "table":
            self.depth += 1
            if self.depth != 1:
                raise ValueError("暂不支持嵌套表格")
        elif tag == "thead":
            self.header = True
        elif tag == "tr":
            if self.row is not None:
                raise ValueError("表格行标签未闭合")
            self.row = []
            self.rows.append(self.row)
        elif tag in {"td", "th"}:
            if self.row is None or self.cell is not None:
                raise ValueError("表格单元格标签不完整")
            try:
                rs, cs = int(attrs.get("rowspan", 1)), int(attrs.get("colspan", 1))
            except ValueError as exc:
                raise ValueError("表格合并跨度必须为整数") from exc
            if not 1 <= rs <= 1000 or not 1 <= cs <= 100:
                raise ValueError("表格合并跨度超出限制")
            self.cell = {"text": "", "rowspan": rs, "colspan": cs, "header": tag == "th" or self.header}
            if attrs.get("align"):
                self.cell["alignment"] = attrs["align"]
            self.cell["runs"] = []
            self.inline = []
            self.row.append(self.cell)
        elif tag in {"br", "p"} and self.cell is not None and self.cell["text"]:
            self.handle_data("\n")
        elif tag in {"strong", "b", "em", "i", "code", "a"}:
            self.inline.append((tag, attrs.get("href")))
        elif tag == "caption":
            raise ValueError("表格标题请作为表格前独立正文保留；暂不支持caption")

    def handle_endtag(self, tag):
        if tag in {"strong", "b", "em", "i", "code", "a"}:
            if self.inline and self.inline[-1][0] == tag:
                self.inline.pop()
        elif tag in {"td", "th"}:
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag == "thead":
            self.header = False
        elif tag == "table":
            self.depth -= 1

    def handle_data(self, text):
        if self.cell is not None:
            self.cell["text"] += text
            run = {"text": text}
            for tag, href in self.inline:
                if tag in {"strong", "b"}:
                    run["bold"] = True
                if tag in {"em", "i"}:
                    run["italic"] = True
                if tag == "code":
                    run["code"] = True
                if tag == "a" and href:
                    run["href"] = href
            self.cell["runs"].append(run)
        elif text.strip():
            raise ValueError("表格单元格外存在文字，不能静默丢弃")


def validate(model):
    height, width = model["rows"], model["columns"]
    if not 1 <= height <= 1000 or not 1 <= width <= 100:
        raise ValueError("表格大小超出限制")
    occupied = {}
    for cell in model["cells"]:
        r, c, rs, cs = (cell[k] for k in ("row", "column", "rowspan", "colspan"))
        if (
            any(type(n) is not int for n in (r, c, rs, cs))
            or r < 0
            or c < 0
            or rs < 1
            or cs < 1
            or r + rs > height
            or c + cs > width
        ):
            raise ValueError("单元格位置或跨度越界")
        if not isinstance(cell["text"], str) or len(cell["text"]) > 100000:
            raise ValueError("单元格文字无效")
        for y in range(r, r + rs):
            for x in range(c, c + cs):
                if (y, x) in occupied:
                    raise ValueError("单元格合并关系重叠")
                occupied[y, x] = cell
        if "runs" in cell and "".join(r["text"] for r in cell["runs"]) != cell["text"]:
            raise ValueError("单元格文字与格式版本不一致")
    if len(occupied) != height * width:
        raise ValueError("表格存在未登记空单元格或丢列，需人工复核，不能自动补齐")
    return model


def parse_html(raw):
    p = TableParser()
    p.feed(raw)
    p.close()
    if p.depth or p.cell is not None or p.row is not None:
        raise ValueError("表格HTML未完整闭合")
    occupied, cells, width = set(), [], 0
    for r, row in enumerate(p.rows):
        c = 0
        for item in row:
            while (r, c) in occupied:
                c += 1
            cell = {**item, "row": r, "column": c}
            cells.append(cell)
            for y in range(r, r + cell["rowspan"]):
                for x in range(c, c + cell["colspan"]):
                    if (y, x) in occupied:
                        raise ValueError("表格合并关系重叠")
                    occupied.add((y, x))
            c += cell["colspan"]
            width = max(width, c)
    return validate(
        {
            "schema": "source-table-v1",
            "rows": len(p.rows),
            "columns": width,
            "cells": cells,
            "coordinates": None,
        }
    )


def cell_html(cell):
    result = []
    for run in cell.get("runs", [{"text": cell["text"]}]):
        text = html.escape(run["text"]).replace("\n", "<br>")
        if run.get("code"):
            text = "<code>" + text + "</code>"
        if run.get("italic"):
            text = "<em>" + text + "</em>"
        if run.get("bold"):
            text = "<strong>" + text + "</strong>"
        if run.get("href"):
            text = '<a href="' + html.escape(run["href"], quote=True) + '">' + text + "</a>"
        result.append(text)
    return "".join(result)


def to_html(model):
    validate(model)
    rows = []
    for r in range(model["rows"]):
        cells = []
        for c in sorted((c for c in model["cells"] if c["row"] == r), key=lambda c: c["column"]):
            tag = "th" if c.get("header") else "td"
            attrs = "".join(f' {k}="{c[k]}"' for k in ["rowspan", "colspan"] if c[k] > 1)
            if c.get("alignment"):
                attrs += ' align="' + c["alignment"] + '"'
            cells.append("<" + tag + attrs + ">" + cell_html(c) + "</" + tag + ">")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def pipe_cells(line):
    """Count explicit cells before a Markdown renderer can fill or discard columns."""
    text = line.strip()
    parts = []
    current = ""
    escaped = False
    for char in text:
        if escaped:
            current += "\\" + char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            parts.append(current)
            current = ""
        else:
            current += char
    if escaped:
        current += "\\"
    parts.append(current)
    if text.startswith("|"):
        parts = parts[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        parts = parts[:-1]
    return parts


def tables(text):
    from markdown_it import MarkdownIt

    parser = MarkdownIt("commonmark", {"html": True}).enable("table")
    tokens = parser.parse(text)
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    found = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        raw = None
        if t.type == "table_open":
            end = i + 1
            while end < len(tokens) and tokens[end].type != "table_close":
                end += 1
            raw = parser.renderer.render(tokens[i : end + 1], parser.options, {})
            i = end
        elif t.type == "html_block" and re.match(r"\s*<table(?:\s|>)", t.content, re.I):
            raw = t.content
        if raw is not None:
            start, end = offsets[t.map[0]], offsets[t.map[1]]
            original = text[start:end]
            try:
                if not original.lstrip().lower().startswith("<table"):
                    widths = [len(pipe_cells(line)) for line in original.splitlines() if line.strip()]
                    if widths and any(width != widths[0] for width in widths):
                        raise ValueError(
                            "Markdown表格行列数不一致，拒绝丢列或猜测空单元格；请对照原图修正并保存新版本"
                        )
                model = parse_html(raw)
                record = {
                    "id": hashlib.sha256((str(start) + ":" + original).encode()).hexdigest()[:20],
                    "start": start,
                    "end": end,
                    "source_lines": t.map,
                    "original": original,
                    "model": model,
                    "html": to_html(model),
                }
                if not original.lstrip().lower().startswith("<table") and model["rows"] >= 2:
                    top = [c for c in model["cells"] if c["row"] == 0]
                    sub = [c["text"] for c in model["cells"] if c["row"] == 1 and c["text"]]
                    if (
                        any(not c["text"].strip() for c in top)
                        and len(sub) >= 4
                        and len(set(sub)) < len(sub) / 1.5
                    ):
                        record["review_required"] = (
                            "多级表头的合并关系未登记；普通Markdown竖线不能表达合并，请对照原图修正或明确保留独立单元格"
                        )
                found.append(record)
            except ValueError as exc:
                found.append(
                    {
                        "id": hashlib.sha256((str(start) + ":" + original).encode()).hexdigest()[:20],
                        "start": start,
                        "end": end,
                        "source_lines": t.map,
                        "original": original,
                        "error": str(exc),
                    }
                )
        i += 1
    return found


def correct(model, request):
    from copy import deepcopy

    model = deepcopy(model)
    for edit in request.get("edits", []):
        cell = next(
            (c for c in model["cells"] if c["row"] == edit["row"] and c["column"] == edit["column"]), None
        )
        if cell is None:
            raise ValueError("未知单元格位置")
        if cell["text"] != edit["text"]:
            cell.pop("runs", None)
        cell["text"] = edit["text"]
        if "header" in edit:
            cell["header"] = bool(edit["header"])
    if request.get("merge"):
        rect = request["merge"]
        r, c, rs, cs = (rect[k] for k in ("row", "column", "rowspan", "colspan"))
        chosen = [x for x in model["cells"] if r <= x["row"] < r + rs and c <= x["column"] < c + cs]
        if (
            not chosen
            or any(x["row"] + x["rowspan"] > r + rs or x["column"] + x["colspan"] > c + cs for x in chosen)
            or sum(x["rowspan"] * x["colspan"] for x in chosen) != rs * cs
        ):
            raise ValueError("合并矩形必须完整包含原单元格，不能切断已有合并关系")
        chosen.sort(key=lambda x: (x["row"], x["column"]))
        merged = {
            **chosen[0],
            "row": r,
            "column": c,
            "rowspan": rs,
            "colspan": cs,
            "text": "\n".join(x["text"] for x in chosen if x["text"]),
        }
        combined = []
        for x in chosen:
            if not x["text"]:
                continue
            if combined:
                combined.append({"text": "\n"})
            combined.extend(x.get("runs", [{"text": x["text"]}]))
        merged["runs"] = combined
        model["cells"] = [x for x in model["cells"] if x not in chosen] + [merged]
    if request.get("unmerge"):
        pos = request["unmerge"]
        cell = next(x for x in model["cells"] if x["row"] == pos["row"] and x["column"] == pos["column"])
        model["cells"].remove(cell)
        for r in range(cell["row"], cell["row"] + cell["rowspan"]):
            for c in range(cell["column"], cell["column"] + cell["colspan"]):
                model["cells"].append(
                    {
                        **cell,
                        "row": r,
                        "column": c,
                        "rowspan": 1,
                        "colspan": 1,
                        "runs": cell.get("runs", [{"text": cell["text"]}])
                        if (r, c) == (cell["row"], cell["column"])
                        else [],
                        "text": cell["text"] if (r, c) == (cell["row"], cell["column"]) else "",
                    }
                )
    return validate(model)


def serialize(model):
    """Ordinary tables stay Markdown; explicit spans and multi-row heads use HTML."""
    validate(model)
    if any(
        c["rowspan"] != 1 or c["colspan"] != 1 or bool(c.get("header")) != (c["row"] == 0)
        for c in model["cells"]
    ):
        return to_html(model)

    def escape(text):
        return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", text).replace("\n", "<br>")

    def content(cell):
        result = []
        for run in cell.get("runs", [{"text": cell["text"]}]):
            text = escape(run["text"])
            if run.get("code"):
                if "\n" in run["text"]:
                    raise ValueError("MULTILINE_CODE")
                delimiter = "`" * (max((len(x) for x in re.findall(r"`+", run["text"])), default=0) + 1)
                text = delimiter + " " + run["text"] + " " + delimiter
            if run.get("italic"):
                text = "*" + text + "*"
            if run.get("bold"):
                text = "**" + text + "**"
            if run.get("href"):
                from urllib.parse import quote

                text = "[" + text + "](<" + quote(run["href"], safe=":/?#[]@!$&()*+,;=%") + ">)"
            result.append(text)
        return "".join(result)

    rows = []
    alignment = {}
    try:
        for r in range(model["rows"]):
            cells = sorted((c for c in model["cells"] if c["row"] == r), key=lambda c: c["column"])
            for c in cells:
                align = c.get("alignment")
                if c["column"] in alignment and align != alignment[c["column"]]:
                    return to_html(model)
                alignment[c["column"]] = align
            rows.append("| " + " | ".join(content(c) for c in cells) + " |")
            if r == 0:
                rows.append(
                    "| "
                    + " | ".join(
                        {"left": ":---", "center": ":---:", "right": "---:"}.get(alignment[i], "---")
                        for i in range(model["columns"])
                    )
                    + " |"
                )
    except ValueError:
        return to_html(model)
    return "\n".join(rows)
