"""Reader-faithful Markdown export. No question parser, option packing or OCR."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import fitz
from docx import Document
from docx.shared import Mm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from ..reading_style import snapshot
from ..document_fonts import font_audit, font_runs, apply_run_font, embed_fonts
from .content_structure import parse_markdown, items
from .preview_worker import export_docx


def direct_template():
    style = snapshot()
    raw = json.dumps(style, ensure_ascii=False, sort_keys=True).encode()
    return {
        "record": {
            "id": "markdown-direct",
            "version": style["version"],
            "name": "Markdown原文直出",
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "reading_style": style,
        "font": {"path": style["font_path"], "sha256": style["font_sha256"]},
        "font_fallbacks": style["fallbacks"],
    }


def compact_options(value):
    value = value or {}
    if not isinstance(value, dict) or set(value) - {
        "enabled",
        "minimum_font_pt",
        "minimum_line_multiple",
        "minimum_paragraph_em",
    }:
        raise ValueError("紧凑适配设置无效")
    result = {
        "enabled": False,
        "minimum_font_pt": 10,
        "minimum_line_multiple": 1.3,
        "minimum_paragraph_em": 0.3,
        **value,
    }
    if type(result["enabled"]) is not bool:
        raise ValueError("紧凑适配须明确选择")
    for key, low, high in [
        ("minimum_font_pt", 8, 10.5),
        ("minimum_line_multiple", 1.2, 1.85),
        ("minimum_paragraph_em", 0, 1),
    ]:
        if type(result[key]) not in {int, float} or not low <= result[key] <= high:
            raise ValueError(f"紧凑适配 {key} 超出范围 {low}–{high}")
    return result


def check_views(artifact, total):
    views = artifact.get("pages", [])
    if not views:
        raise ValueError("原文直出缺少来源页映射；请使用自定义模板连续排版，不能推断来源页。")
    previous = 0
    for v in views:
        n = v.get("source_page")
        if type(n) is not int or n < 1 or type(total) is not int or n > total:
            raise ValueError("原文直出缺少可靠的来源物理页映射；片段位置不是原件页码。")
        if not v.get("data"):
            raise ValueError(f"来源第{n}页缺少文字记录资源，不能当作成功空白页导出。")
        if "source_pages" in v and (
            not isinstance(v["source_pages"], list)
            or any(type(x) is not int for x in v["source_pages"])
            or set(v["source_pages"]) != {n}
        ):
            raise ValueError(f"来源第{n}页片段涉及多个页或映射不明确，不能精确拆分直出。")
        if n < previous:
            raise ValueError(f"来源第{n}页映射逆序，不能改变正文顺序。")
        previous = n


def write_reader_docx(path, models, style, body_pt, line, paragraph_em):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = [Mm(v) for v in style["paper_mm"]]
    section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Mm(
        style["margin_mm"]
    )
    for model in models:
        for block in model["blocks"]:
            level = int(block["style"][-1]) if block["type"] == "heading" else None
            size = body_pt * style["heading_scale"][level - 1] if level else body_pt
            p = doc.add_paragraph(style=f"Heading {level}" if level else "Normal")
            fmt = p.paragraph_format
            # CSS line-height is an absolute multiple of the declared font size.
            # Word's MULTIPLE uses font metrics and makes CJK lines much taller.
            fmt.line_spacing = Pt(size * line)
            gap = size * style["heading_margin_em"][level - 1] if level else size * paragraph_em
            fmt.space_before = fmt.space_after = Pt(gap)
            fmt.left_indent = fmt.right_indent = fmt.first_line_indent = Pt(0)
            fmt.keep_with_next = False  # Reader headings do not bind across physical source pages.
            fmt.keep_together = False
            fmt.widow_control = False
            for part in block["runs"]:
                for name, text in font_runs(part["text"], style["font_path"]):
                    run = p.add_run(text)
                    apply_run_font(run, name or style["font_family"])
                    run.font.size = Pt(size)
                    run.font.bold = bool(level or part.get("bold"))
                    run.font.italic = bool(part.get("italic"))
                    run.font.color.rgb = RGBColor.from_string("243145")
    doc.save(path)
    embed_fonts(path)


def page_text(page):
    return re.sub(r"\s", "", page.get_text())


def generate(request):
    out = Path(request["output"])
    style = request["template_data"]["reading_style"]
    if snapshot() != style:
        raise ValueError("阅读样式或字体与快照不一致，请建立新导出任务；历史文件保留。")
    policy = compact_options(request.get("direct_compact"))
    groups = []
    for page in request["pages"]:
        n = page.get("source_pdf_physical_page")
        if type(n) is not int:
            raise ValueError("原文直出缺少来源页映射")
        if not page.get("text", "").strip():
            raise ValueError(f"来源第{n}页没有正文，不能作为成功提取的空白页导出。")
        model = parse_markdown(page["text"], page.get("source_locator"))
        if model["diagnostics"]:
            labels = {
                "POSSIBLE_TABLE_PRESERVED_AS_TEXT": "疑似表格或含竖线的内容",
                "UNSUPPORTED_BLOCK_PRESERVED_AS_TEXT": "引用块或分隔线",
                "IMAGE_REFERENCE_NOT_RENDERED": "图片引用",
                "LINK_DISPLAY_TEXT_ONLY": "超链接",
                "INLINE_UNSUPPORTED": "特殊行内格式",
                "HEADING_LEVEL_4_TO_6_RENDERED_AS_3": "四至六级标题",
                "LITERAL_BLOCK_PRESERVED": "代码块或HTML块",
            }
            codes = ", ".join(
                sorted({labels.get(d["code"], d["code"]) for d in model["diagnostics"]})
            )
            raise ValueError(
                f"来源第{n}页包含目前原文直出不支持的格式：{codes}；原文保留，请调整格式或使用其他输出方式。"
            )
        if not groups or groups[-1]["source_page"] != n:
            groups.append({"source_page": n, "models": []})
        groups[-1]["models"].append(model)
    if not groups:
        raise ValueError("没有可直出的来源正文")
    fonts = font_audit(
        [
            {
                "source_pdf_physical_page": g["source_page"],
                "items": [i for m in g["models"] for i in items(m)],
            }
            for g in groups
        ],
        style["font_path"],
    )
    (out / "font-resolution.json").write_text(json.dumps(fonts, ensure_ascii=False, indent=2))
    report = {"schema": "markdown-direct-pagination-v1", "policy": policy, "groups": [], "verified": False}
    chosen, expected = [], []
    for index, group in enumerate(groups):
        n = group["source_page"]
        entry = {"source_page": n, "output_pages": [index + 1], "attempts": []}
        report["groups"].append(entry)
        attempts = [(style["body_pt"], style["line_multiple"], style["paragraph_em"])]
        if policy["enabled"]:
            attempts.append(
                (style["body_pt"], policy["minimum_line_multiple"], policy["minimum_paragraph_em"])
            )
            size = style["body_pt"] - 0.5
            while size > policy["minimum_font_pt"]:
                attempts.append((size, policy["minimum_line_multiple"], policy["minimum_paragraph_em"]))
                size -= 0.5
            if policy["minimum_font_pt"] < style["body_pt"]:
                attempts.append(
                    (
                        policy["minimum_font_pt"],
                        policy["minimum_line_multiple"],
                        policy["minimum_paragraph_em"],
                    )
                )
        content = "".join(b["text"] for m in group["models"] for b in m["blocks"])
        for attempt, (size, line, gap) in enumerate(attempts):
            folder = out / "pagination-work" / f"group-{index + 1}-attempt-{attempt + 1}"
            folder.mkdir(parents=True)
            path = folder / "group.docx"
            write_reader_docx(path, group["models"], style, size, line, gap)
            actual_doc = Document(path)
            if "".join(p.text for p in actual_doc.paragraphs) != content:
                raise ValueError(f"来源第{n}页Word正文或顺序不一致，未发布。")
            pdf = export_docx(path, folder, timeout=40)
            with fitz.open(pdf) as rendered:
                texts = [page_text(p) for p in rendered]
            entry["attempts"].append(
                {
                    "body_pt": size,
                    "line_multiple": line,
                    "paragraph_em": gap,
                    "actual_output_pages": len(texts),
                }
            )
            (out / "pagination-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            if len(texts) == 1:
                break
        if len(texts) != 1:
            entry["error"] = "SOURCE_PAGE_OVERFLOW"
            (out / "pagination-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            raise ValueError(
                f"SOURCE_PAGE_OVERFLOW: 来源第{n}页按当前阅读样式需要{len(texts)}页；"
                + (
                    "紧凑适配已到可见下限，仍无法单页容纳。"
                    if policy["enabled"]
                    else "未启用紧凑适配；可明确选择字号与间距下限后重试。"
                )
            )
        if texts[0] != re.sub(r"\s", "", content):
            raise ValueError(f"来源第{n}页PDF正文或顺序不一致，未发布。")
        entry["content_equal"] = True
        chosen.append(path)
        expected.extend(texts)
    merged = Document(chosen[0])
    for path in chosen[1:]:
        body = [deepcopy(c) for c in Document(path).element.body if c.tag != qn("w:sectPr")]
        props = body[0].find(qn("w:pPr"))
        if props is None:
            props = OxmlElement("w:pPr")
            body[0].insert(0, props)
        props.append(OxmlElement("w:pageBreakBefore"))
        for child in body:
            merged.element.body.insert(len(merged.element.body) - 1, child)
    merged.save(out / "document.docx")
    embed_fonts(out / "document.docx")
    pdf = export_docx(out / "document.docx", out, timeout=40)
    with fitz.open(pdf) as rendered:
        if [page_text(p) for p in rendered] != expected:
            raise ValueError("合并后来源分页或正文发生变化，未发布。")
        for i, page in enumerate(rendered):
            if any(
                code == 0xFFFD or (glyph == 0 and not chr(code).isspace())
                for span in page.get_texttrace()
                for code, glyph, _, _ in span["chars"]
            ):
                raise ValueError(f"来源第{groups[i]['source_page']}页PDF有缺字，未发布。")
            if any(
                b[0] < -1 or b[1] < -1 or b[2] > page.rect.width + 1 or b[3] > page.rect.height + 1
                for b in page.get_text("blocks")
            ):
                raise ValueError(f"来源第{groups[i]['source_page']}页有内容越界，未发布。")
    report["verified"] = True
    (out / "pagination-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (out / "content-structure.json").write_text(
        json.dumps(
            {
                "schema": "derived-content-v1",
                "mode": "markdown-direct",
                "source_artifact_id": request["source_artifact_id"],
                "source_sha256": request["source_sha256"],
                "pages": groups,
                "reading_style": style,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    (out / "layout-validation.json").write_text(
        json.dumps(
            {
                "mode": "markdown-direct",
                "content_equal": True,
                "source_output_mapping": report["groups"],
                "reading_style": style,
                "font_resolution": fonts,
                "visual_acceptance": "requires visual evidence",
                "pdf_renderer": "LibreOffice from the same DOCX",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
