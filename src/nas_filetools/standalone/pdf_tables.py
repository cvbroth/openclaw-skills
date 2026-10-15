"""Reuse PyMuPDF's vector-table finder on existing PDF text layers, without OCR."""

from collections import Counter
import re
import fitz
from .table_structure import validate, to_html


def canonical(text):
    return re.sub(r"\s", "", text)


def markdown_table(model):
    def escape(text):
        return "<br>".join(re.sub(r"([\\`*_\[\]<>|])", r"\\\1", line) for line in text.split("\n"))

    rows = []
    for r in range(model["rows"]):
        cells = sorted((c for c in model["cells"] if c["row"] == r), key=lambda c: c["column"])
        rows.append("| " + " | ".join(escape(c["text"]) for c in cells) + " |")
        if r == 0:
            rows.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(rows)


def table_model(page, table, physical_page):
    # A missing rectangle is a covered position only when an evidenced larger rectangle covers it.
    rects = sorted(set(tuple(round(v, 3) for v in cell) for cell in table.cells if cell))
    xs = sorted({v for rect in rects for v in [rect[0], rect[2]]})
    ys = sorted({v for rect in rects for v in [rect[1], rect[3]]})

    def snap(values):
        result = []
        for v in values:
            if not result or v - result[-1] > 0.5:
                result.append(v)
        return result

    xs, ys = snap(xs), snap(ys)
    if len(xs) != table.col_count + 1 or len(ys) != table.row_count + 1:
        raise ValueError("表格网格边界不足，不能猜测缺列或合并")
    def locate(values,v):
        return min(range(len(values)),key=lambda i:abs(values[i]-v))
    cells = []
    for rect in rects:
        r, c = locate(ys, rect[1]), locate(xs, rect[0])
        rs, cs = locate(ys, rect[3]) - r, locate(xs, rect[2]) - c
        if any(
            abs(values[index] - v) > 0.5
            for values, index, v in [
                (ys, r, rect[1]),
                (xs, c, rect[0]),
                (ys, r + rs, rect[3]),
                (xs, c + cs, rect[2]),
            ]
        ):
            raise ValueError("表格坐标无法精确对齐网格")
        text = page.get_textbox(fitz.Rect(rect)).rstrip("\r\n")
        cells.append(
            {
                "row": r,
                "column": c,
                "rowspan": rs,
                "colspan": cs,
                "text": text,
                "header": False,
                "coordinates": list(rect),
                "coordinate_system": "source-pdf-points",
            }
        )
    head_rows = (
        0
        if table.header.external
        else max((cell["rowspan"] for cell in cells if cell["row"] == 0), default=1)
    )
    for cell in cells:
        cell["header"] = cell["row"] < head_rows
    return validate(
        {
            "schema": "source-table-v1",
            "rows": table.row_count,
            "columns": table.col_count,
            "cells": cells,
            "coordinates": list(table.bbox),
            "coordinate_system": "source-pdf-points",
            "source_physical_page": physical_page,
            "rotation": page.rotation,
            "cropbox": list(page.cropbox),
            "header_evidence": "PyMuPDF internal header and explicit span geometry; editable, not human-confirmed",
        }
    )


def extract(page, physical_page):
    original = page.get_text("text", sort=False)
    original_blocks = page.get_text("blocks", sort=False)
    found = [
        t for t in page.find_tables(strategy="lines_strict").tables if t.row_count >= 2 and t.col_count >= 2
    ]
    if not found:
        return {
            "text": original,
            "tables": [],
            "issues": [],
            "native_blocks": original_blocks,
            "order": "PDF native order; not guaranteed logical reading order",
        }
    models = []
    issues = []
    for index, table in enumerate(found):
        try:
            model = table_model(page, table, physical_page)
            if not any(c["text"].strip() for c in model["cells"]):
                raise ValueError("表格文字层为空，需对照确认空单元格或补齐缺失文字")
            models.append(model)
        except ValueError as exc:
            issues.append(
                {
                    "table": index + 1,
                    "reason": str(exc),
                    "source_page": physical_page,
                    "coordinates": list(table.bbox),
                }
            )
    if issues:
        return {
            "text": original,
            "tables": models,
            "issues": issues,
            "native_blocks": original_blocks,
            "order": "native text retained; table structure needs correction",
        }
    entries = []
    semantic = []
    inserted = set()
    outside = []
    word_groups = {}
    for word in page.get_text("words", sort=False):
        word_groups.setdefault(word[5], {}).setdefault(word[6], []).append(word)
    lines = []
    for block in original_blocks:
        if block[6] != 0:
            continue
        rect = fitz.Rect(block[:4])
        boxes = [fitz.Rect(m["coordinates"]) + (-0.5, -0.5, 0.5, 0.5) for m in models]
        if any(box.contains(rect) for box in boxes) or not any(box.intersects(rect) for box in boxes):
            lines.append((block[4], rect))
            continue
        groups = word_groups.get(block[5], {})
        raw_lines = block[4].splitlines(keepends=True)
        if len(raw_lines) != len(groups):
            issues.append(
                {"reason": "跨表格边界文字行不能完整对应原始块，保留原文待复核", "source_page": physical_page}
            )
            continue
        for text, words in zip(raw_lines, groups.values()):
            box = fitz.Rect(words[0][:4])
            for word in words[1:]:
                box |= fitz.Rect(word[:4])
            lines.append((text, box))
    for text, rect in lines:
        contained = []
        for i, model in enumerate(models):
            box = fitz.Rect(model["coordinates"]) + (-0.5, -0.5, 0.5, 0.5)
            if box.contains(rect):
                contained.append(i)
            elif box.intersects(rect) and rect.width and rect.height:
                issues.append(
                    {
                        "table": i + 1,
                        "reason": "文字行跨越表格边界，不能可靠拆分；原始文字保留",
                        "source_page": physical_page,
                    }
                )
        if len(contained) > 1:
            issues.append({"reason": "表格区域重叠，需复核", "source_page": physical_page})
        if contained:
            index = contained[0]
            if index not in inserted:
                model = models[index]
                simple = (
                    all(c["rowspan"] == c["colspan"] == 1 for c in model["cells"])
                    and not found[index].header.external
                )
                rendered = markdown_table(model) if simple else to_html(model)
                entries.append(rendered)
                semantic.append(
                    {
                        "type": "table",
                        "text": rendered,
                        "table": model,
                        "coordinates": model["coordinates"],
                        "coordinate_system": "source-pdf-points",
                    }
                )
                inserted.add(index)
        else:
            entries.append(text)
            semantic.append(
                {
                    "type": "text",
                    "text": text,
                    "coordinates": list(rect),
                    "coordinate_system": "source-pdf-points",
                }
            )
            outside.append(text)
    expected = "".join(outside) + "".join(c["text"] for m in models for c in m["cells"])
    if len(inserted) != len(models) or Counter(canonical(expected)) != Counter(canonical(original)):
        issues.append(
            {
                "reason": "表格转换前后全文字符不一致，拒绝丢失或重复原文；保留原始文字待复核",
                "source_page": physical_page,
            }
        )
    if issues:
        return {
            "text": original,
            "tables": models,
            "issues": issues,
            "native_blocks": original_blocks,
            "order": "native text retained; table structure needs correction",
        }
    return {
        "text": "\n\n".join(entries),
        "semantic_blocks": [{**b, "reading_order": i} for i, b in enumerate(semantic)],
        "tables": models,
        "issues": [],
        "native_blocks": original_blocks,
        "order": "outside text follows PDF native line order; table cells follow explicit row-column grid",
    }
