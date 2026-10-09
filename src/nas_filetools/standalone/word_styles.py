"""Explicit standalone v3 style extension; every accepted setting is executed."""

import math
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_LINE_SPACING
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

STYLE_NAMES = {"Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Option", "Footer"}
SECTION_FIELDS = {
    "width_cm",
    "height_cm",
    "top_cm",
    "bottom_cm",
    "left_cm",
    "right_cm",
    "header_distance_cm",
    "footer_distance_cm",
}
PARA_FIELDS = {
    "size_pt",
    "space_before_pt",
    "space_after_pt",
    "line_mode",
    "line_value",
    "left_cm",
    "right_cm",
    "first_line_cm",
    "bold",
    "italic",
}


def validate_styles(data):
    if not isinstance(data, dict) or set(data) != {"section", "paragraphs"}:
        raise ValueError("word_styles: section 和 paragraphs 必须提供")
    section = data["section"]
    if not isinstance(section, dict) or set(section) - SECTION_FIELDS:
        raise ValueError("word_styles.section: 存在不支持字段")
    for k, v in section.items():
        lo, hi = (10, 60) if k in {"width_cm", "height_cm"} else (0.2, 8)
        if type(v) not in {int, float} or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f"word_styles.section.{k}: 范围 {lo}–{hi} cm")
    if not isinstance(data["paragraphs"], dict) or set(data["paragraphs"]) - STYLE_NAMES:
        raise ValueError("word_styles.paragraphs: 不支持的样式名称")
    if section.get("left_cm", 2) + section.get("right_cm", 2) >= section.get("width_cm", 21) or section.get(
        "top_cm", 2
    ) + section.get("bottom_cm", 2) >= section.get("height_cm", 29.7):
        raise ValueError("word_styles.section: 页边距总和必须小于纸张尺寸")
    for name, props in data["paragraphs"].items():
        if not isinstance(props, dict) or set(props) - PARA_FIELDS:
            raise ValueError("word_styles.paragraphs." + name + ": 不支持的字段")
        for k, v in props.items():
            field = f"word_styles.paragraphs.{name}.{k}"
            if k in {"bold", "italic"}:
                valid = type(v) is bool
            elif k == "line_mode":
                valid = isinstance(v, str) and v in {"multiple", "exact", "at_least"}
            else:
                lo, hi = (-4, 8) if k == "first_line_cm" else (0, 8) if k.endswith("_cm") else (0, 96)
                if k == "size_pt":
                    lo, hi = 6, 48
                if k == "line_value":
                    lo, hi = (0.8, 3) if props.get("line_mode") == "multiple" else (6, 96)
                valid = type(v) in {int, float} and math.isfinite(v) and lo <= v <= hi
            if not valid:
                raise ValueError(field + ": 无效值或超出范围")
        if props.get("line_mode") == "exact" and props.get("line_value", 0) < props.get("size_pt", 6):
            raise ValueError(
                f"word_styles.paragraphs.{name}.line_value: 固定行距不能低于该样式字号，避免文字重叠"
            )
        if ("line_mode" in props) != ("line_value" in props):
            raise ValueError(f"word_styles.paragraphs.{name}: 行距类型和值必须同时提供")
    return data


def apply_styles(path, extension, *, compact=False, font_scale=1, min_pt=6, materialize=False):
    doc = Document(path)
    extension = extension or {"section": {}, "paragraphs": {}}
    for section in doc.sections:
        mapping = {
            "width_cm": "page_width",
            "height_cm": "page_height",
            "top_cm": "top_margin",
            "bottom_cm": "bottom_margin",
            "left_cm": "left_margin",
            "right_cm": "right_margin",
            "header_distance_cm": "header_distance",
            "footer_distance_cm": "footer_distance",
        }
        for key, attr in mapping.items():
            if key in extension["section"]:
                setattr(section, attr, Cm(extension["section"][key]))
        section.orientation = (
            WD_ORIENT.LANDSCAPE if section.page_width > section.page_height else WD_ORIENT.PORTRAIT
        )
    from copy import deepcopy

    paragraphs_styles = deepcopy(extension["paragraphs"])
    if "Normal" in paragraphs_styles:
        for body_style in ["Question", "Option", "Point", "Unresolved", "Material"]:
            paragraphs_styles[body_style] = {
                **paragraphs_styles["Normal"],
                **paragraphs_styles.get(body_style, {}),
            }
    for name, props in paragraphs_styles.items():
        style = doc.styles[name] if name in doc.styles else doc.styles["Normal"]
        fmt = style.paragraph_format
        if "size_pt" in props:
            style.font.size = Pt(props["size_pt"])
        for key in ["bold", "italic"]:
            if key in props:
                setattr(style.font, key, props[key])
        for key in ["space_before_pt", "space_after_pt"]:
            if key in props:
                setattr(fmt, key[:-3], Pt(props[key]))
        for key, attr in [
            ("left_cm", "left_indent"),
            ("right_cm", "right_indent"),
            ("first_line_cm", "first_line_indent"),
        ]:
            if key in props:
                setattr(fmt, attr, Cm(props[key]))
        if "line_mode" in props:
            fmt.line_spacing = (
                props["line_value"] if props["line_mode"] == "multiple" else Pt(props["line_value"])
            )
            if props["line_mode"] != "multiple":
                fmt.line_spacing_rule = (
                    WD_LINE_SPACING.EXACTLY if props["line_mode"] == "exact" else WD_LINE_SPACING.AT_LEAST
                )
    for style in doc.styles:
        if style.type != 1:
            continue
        if compact:
            style.paragraph_format.space_before = Pt(0)
            style.paragraph_format.space_after = Pt(0)
        if style.name != "Footer" and style.font.size is not None and font_scale != 1:
            style.font.size = Pt(max(min_pt, style.font.size.pt * font_scale))
        if font_scale != 1 and style.paragraph_format.line_spacing_rule in {
            WD_LINE_SPACING.EXACTLY,
            WD_LINE_SPACING.AT_LEAST,
        }:
            style.paragraph_format.line_spacing = Pt(
                max(min_pt, style.paragraph_format.line_spacing.pt * font_scale)
            )
    if extension["section"]:
        section = doc.sections[0]
        width = section.page_width - section.left_margin - section.right_margin
        for table in doc.tables:
            for col in table.columns:
                col.width = int(width / len(table.columns))
            for row in table.rows:
                for cell in row.cells:
                    cell.width = int(width / len(row.cells))
    if materialize:

        def paragraphs(container):
            yield from container.paragraphs
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells:
                        yield from paragraphs(cell)

        for p in paragraphs(doc):
            fmt = p.paragraph_format
            style = p.style
            for attr in [
                "space_before",
                "space_after",
                "line_spacing",
                "line_spacing_rule",
                "left_indent",
                "right_indent",
                "first_line_indent",
            ]:
                value = getattr(style.paragraph_format, attr)
                if value is not None:
                    setattr(fmt, attr, value)
            for run in p.runs:
                if style.font.size is not None:
                    run.font.size = style.font.size
                for attr in ["bold", "italic"]:
                    if getattr(run.font, attr) is None:
                        setattr(run.font, attr, getattr(style.font, attr))
                if style.font.name:
                    run.font.name = style.font.name
                    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), style.font.name)
    doc.save(path)
