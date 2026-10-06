"""Conservative OCR question sample structuring and fixed DOCX/PDF layout.

Standalone on purpose: the existing restricted Python tool can submit this source
as code and consume its sole registered input via FILETOOLS_INPUT.
"""
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import fitz
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

FONT_FAMILY = "Droid Sans Fallback"
PAGE_MARK = re.compile(r"^##\s*(?:第\s*(\d+)\s*页|Page\s+(\d+))\s*$", re.I)
QUESTION = re.compile(r"^(\d{1,3})[.．、]\s*(.+)$")
OPTION = re.compile(r"^([A-DＡ-Ｄ])[.．、:：)）]\s*(.*)$")
CHAPTER = re.compile(r"^(?:#{1,3}\s+(?!第\s*\d+\s*页)(.+)|第[一二三四五六七八九十百\d]+[章节篇]\s*.*)$")


def join_scan_lines(parts):
    """Join within one semantic block only; retain Latin word boundaries."""
    result = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if result and result[-1].isascii() and result[-1].isalnum() and part[0].isascii() and part[0].isalnum():
            result += " "
        result += part
    return result


def structure_ocr(raw, pages=(6, 10), evidence=None, reviewed_edits=None):
    """Return independent blocks plus untouched line references and audit records.

    Repeated boundary headers require three distinct source pages. Position
    evidence may additionally name exact (page,line,text) margin fragments.
    Ambiguous numbering/inline options remain verbatim and receive an issue.
    """
    records, page = [], None
    for number, line in enumerate(raw.splitlines(), 1):
        mark = PAGE_MARK.match(line.strip())
        if mark:
            page = int(mark.group(1) or mark.group(2))
            continue
        if page is None and line.strip() and not line.strip().startswith("<!--"):
            raise ValueError("OCR_PAGE_MARKERS_REQUIRED")
        if page is not None and pages[0] <= page <= pages[1] and line.strip() and not line.strip().startswith("<!--"):
            records.append({"page": page, "line": number, "raw": line, "text": line.strip()})
    if {r["page"] for r in records} != set(range(pages[0], pages[1] + 1)):
        raise ValueError("OCR_SAMPLE_PAGES_MISSING")
    edit_map = {}
    for edit in reviewed_edits or []:
        key = (edit["page"], edit["line"])
        if key in edit_map or edit.get("verified") is not True or not edit.get("reference") or not edit.get("reason"):
            raise ValueError("INVALID_REVIEW_EVIDENCE")
        edit_map[key] = edit
    expanded = []
    applied = []
    for record in records:
        edit = edit_map.pop((record["page"], record["line"]), None)
        if not edit:
            expanded.append(record)
            continue
        if edit["original"] != record["raw"] or not isinstance(edit["replacement"], list) or not edit["replacement"]:
            raise ValueError("REVIEW_SOURCE_MISMATCH")
        for index, text in enumerate(edit["replacement"]):
            if not isinstance(text, str) or not text.strip() or "\n" in text:
                raise ValueError("INVALID_REVIEW_REPLACEMENT")
            expanded.append({**record, "text": text, "part": index, "review": edit})
        applied.append(edit)
    if edit_map:
        raise ValueError("REVIEW_SOURCE_NOT_FOUND")
    records = expanded
    boundaries = {}
    for source_page in range(pages[0], pages[1] + 1):
        lines = [r for r in records if r["page"] == source_page]
        for index in {0, len(lines) - 1}:
            boundaries.setdefault(lines[index]["text"], set()).add(source_page)
    margin_evidence = {}
    source_keys = {(r["page"], r["line"], r["text"]) for r in records}
    for item in evidence or []:
        key = (item["page"], item["line"], item["text"])
        if (item.get("region") not in ("header", "footer") or item.get("verified") is not True
                or not item.get("reference") or key in margin_evidence):
            raise ValueError("INVALID_MARGIN_EVIDENCE")
        if key not in source_keys:
            raise ValueError("MARGIN_SOURCE_MISMATCH")
        margin_evidence[key] = item
    blocks, issues, removed = [], [], []
    current, active, chapter = None, None, None

    def issue(code, fragments, detail):
        issues.append({"code": code, "detail": detail, "fragments": fragments})

    def finish():
        if current is None:
            return
        labels = [b["label"] for b in current["parts"] if b["kind"] == "option"]
        if labels != list("ABCD"):
            issue("OPTIONS_INCOMPLETE_OR_ORDER", current["fragments"], f"Observed options: {labels}; no options supplied.")
        stem = current["parts"][0]
        if stem["text"] and (stem["text"].count("“") > stem["text"].count("”") or stem["text"].endswith("著")):
            issue("POSSIBLE_TRUNCATION", stem["fragments"], "Unclosed quotation or suspicious final fragment; compare original page, do not complete it.")

    for record in records:
        text = record["text"]
        peers = [r for r in records if r["page"] == record["page"]]
        at_boundary = record is peers[0] or record is peers[-1]
        repeat = at_boundary and len(boundaries.get(text, set())) >= 3
        # Never classify a chapter/question/option as a repeated running header.
        repeat = repeat and not (CHAPTER.match(text) or QUESTION.match(text) or OPTION.match(text))
        positional = margin_evidence.get((record["page"], record["line"], text))
        if repeat or positional:
            removed.append({"fragment": record, "reason": "verified-margin-position" if positional else "same-exact-text-at-page-boundary",
                            "evidence": positional or {"pages": sorted(boundaries[text])}})
            continue
        heading = CHAPTER.match(text)
        if heading:
            finish()
            chapter = re.sub(r"^#{1,3}\s*", "", text)
            blocks.append({"kind": "chapter", "text": chapter, "fragments": [record]})
            current, active = None, None
            continue
        match = QUESTION.match(text)
        if match and re.match(r"^\d+[.]\d{1,2}(?:\D|$)", text):
            match = None  # Unspaced decimal body numbers are not question anchors.
        if match:
            number = int(match.group(1))
            expected = current is None or number == current["number"] + 1
            observed = [b["label"] for b in current["parts"] if b["kind"] == "option"] if current else []
            completed = bool(observed) and observed[-1] == "D"
            if expected and (current is None or completed):
                finish()
                active = {"kind": "stem", "text": match.group(2), "fragments": [record]}
                current = {"kind": "question", "number": number, "chapter": chapter, "parts": [active], "fragments": [record]}
                blocks.append(current)
                continue
            issue("AMBIGUOUS_NUMBERING", [record], "Numbered line is not a proven new question; preserved inside the current block.")
        match = OPTION.match(text)
        if match and current:
            label = unicodedata.normalize("NFKC", match.group(1))
            previous = [b["label"] for b in current["parts"] if b["kind"] == "option"]
            if label in previous or (previous and ord(label) != ord(previous[-1]) + 1) or (not previous and label != "A"):
                issue("OPTION_ORDER", [record], f"Unexpected option {label}; kept in source order.")
            active = {"kind": "option", "label": label, "text": match.group(2), "fragments": [record]}
            current["parts"].append(active)
            current["fragments"].append(record)
            continue
        if current and text[0] in "①②③④":
            active = {"kind": "point", "text": text, "fragments": [record]}
            current["parts"].append(active)
            current["fragments"].append(record)
            continue
        if re.search(r"\s+[B-D][.．、]", text):
            issue("INLINE_OPTIONS_UNRESOLVED", [record], "Multiple inline option markers require original-page review; not split by guesswork.")
        if active is not None:
            active["text"] = join_scan_lines([active["text"], text])
            active["fragments"].append(record)
            current["fragments"].append(record)
        else:
            blocks.append({"kind": "unresolved", "text": text, "fragments": [record]})
            issue("UNRESOLVED_STRUCTURE", [record], "No established question/option context; text retained.")
    finish()
    preserved = [r for b in blocks for r in b["fragments"]] + [item["fragment"] for item in removed]
    if Counter((r["page"], r["line"], r["raw"]) for r in preserved) != Counter((r["page"], r["line"], r["raw"]) for r in records):
        raise ValueError("SOURCE_FRAGMENT_ACCOUNTING_FAILED")
    return {"schema_version": 1, "source_sha256": hashlib.sha256(raw.encode()).hexdigest(), "pages": list(pages),
            "blocks": blocks, "issues": issues, "removed_headers_footers": removed,
            "review_status": "original-page-comparison-required", "reviewed_edits": applied}


def source_label(fragments):
    pages = sorted({r["page"] for r in fragments})
    lines = [r["line"] for r in fragments]
    return f"来源：原PDF第{'、'.join(map(str, pages))}页；OCR行{min(lines)}–{max(lines)}"


def paragraphs(model, title):
    result = [("Title", title)]
    for block in model["blocks"]:
        if block["kind"] == "chapter":
            result.append(("Heading 1", block["text"]))
        elif block["kind"] == "question":
            for part in block["parts"]:
                if part["kind"] == "stem":
                    text = f"{block['number']}.\u00a0{part['text']}"
                    style = "Question"
                elif part["kind"] == "option":
                    text = f"{part['label']}. {part['text']}"
                    style = "Option"
                else:
                    text, style = part["text"], "Point"
                result.append((style, text))
            result.append(("Source", source_label(block["fragments"])))
        else:
            result.append(("Unresolved", "[结构待核实] " + block["text"]))
            result.append(("Source", source_label(block["fragments"])))
    return result


def _font_style(style, size):
    style.font.name = FONT_FAMILY
    style.font.size = Pt(size)
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn("w:" + key), FONT_FAMILY)
        fonts.attrib.pop(qn("w:" + key + "Theme"), None)
    style.paragraph_format.line_spacing = 1.35
    style.paragraph_format.space_after = Pt(6)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.widow_control = True


def write_docx(path, items):
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Cm(2)
    for name, size in [("Normal", 11.5), ("Title", 16), ("Heading 1", 14), ("Question", 11.5),
                       ("Option", 11.5), ("Point", 11.5), ("Source", 9), ("Unresolved", 11.5)]:
        style = document.styles[name] if name in document.styles else document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        _font_style(style, size)
        if name in ("Title", "Heading 1"):
            style.paragraph_format.keep_with_next = True
            style.paragraph_format.space_before = Pt(10)
        if name in ("Option", "Point"):
            style.paragraph_format.left_indent = Cm(0.65)
            style.paragraph_format.first_line_indent = Cm(-0.35)
    # Keep a long stem splittable while retaining the number and first characters.
    for style, text in items:
        paragraph = document.add_paragraph(text, style)
        paragraph.paragraph_format.keep_together = False
        paragraph.paragraph_format.keep_with_next = style in ("Title", "Heading 1")
    document.core_properties.title = items[0][1]
    document.save(path)


def write_pdf(path, items, font_path):
    font_path = Path(font_path)
    if not font_path.is_file():
        raise ValueError("FONT_FILE_UNAVAILABLE")
    font = fitz.Font(fontfile=str(font_path))
    missing = sorted({c for _, text in items for c in text if not c.isspace() and not font.has_glyph(ord(c))})
    if missing:
        raise ValueError("FONT_MISSING_GLYPHS: " + "".join(missing))
    css = f'''@font-face {{font-family: sample; src: url({font_path.name});}}
    body {{font-family: sample; font-size: 11.5pt; line-height: 1.35; margin: 0;}}
    p {{margin: 0 0 6pt 0;}} h1 {{font-size: 14pt; margin: 10pt 0 6pt 0;}}
    .title {{font-size:16pt;}} .option,.point {{margin-left:18.4pt; text-indent:-9.9pt;}}
    .source {{font-size:9pt; color:#666;}}'''
    body = []
    for style, text in items:
        tag = "h1" if style == "Heading 1" else "p"
        body.append(f'<{tag} class="{style.lower().replace(" ", "-")}">{html.escape(text)}</{tag}>')
    story = fitz.Story("<html><body>" + "".join(body) + "</body></html>", user_css=css, archive=fitz.Archive(str(font_path.parent)))
    media = fitz.paper_rect("a4")
    inset = 2 * 72 / 2.54
    where = media + (inset, inset, -inset, -inset)
    writer = fitz.DocumentWriter(str(path))
    more, count = True, 0
    try:
        while more:
            count += 1
            if count > 50:
                raise ValueError("SAMPLE_LAYOUT_PAGE_LIMIT")
            device = writer.begin_page(media)
            more, _ = story.place(where)
            story.draw(device)
            writer.end_page()
    finally:
        writer.close()


def validate_pair(docx_path, pdf_path, items):
    """Check actual extracted content and geometry, not merely file existence."""
    expected = [text for _, text in items]
    document = Document(docx_path)
    if [p.text for p in document.paragraphs] != expected:
        raise ValueError("DOCX_CONTENT_MISMATCH")
    def canonical(text):
        return re.sub(r"\s+", "", text)
    with fitz.open(pdf_path) as pdf:
        actual = "".join(page.get_text(sort=True) for page in pdf)
        if canonical(actual) != canonical("".join(expected)):
            raise ValueError("PDF_CONTENT_OR_ORDER_MISMATCH")
        geometry = []
        for number, page in enumerate(pdf, 1):
            if not page.get_text().strip():
                raise ValueError("EMPTY_PDF_PAGE")
            if any("\ufffd" in word[4] for word in page.get_text("words")):
                raise ValueError("PDF_REPLACEMENT_GLYPH")
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        rect = fitz.Rect(span["bbox"])
                        if not page.rect.contains(rect):
                            raise ValueError("PDF_TEXT_CROPPED")
            geometry.append({"page": number, "words": len(page.get_text("words"))})
    return {"content_equal": True, "pdf_pages": geometry, "docx_paragraphs": len(document.paragraphs),
            "visual_review": "required", "word_render": "not-checked-by-this-function"}


def generate_sample(input_path, output_dir, font_path, title="合成验证样本（非用户原册）", pages=(6, 10)):
    """Generate a small sample only; no automatic full-book processing or saving."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    input_bytes = Path(input_path).read_bytes()
    if Path(input_path).suffix.lower() == ".json":
        review = json.loads(input_bytes)
        raw = review["raw_ocr"]
        raw_bytes = raw.encode("utf-8")
        model = structure_ocr(raw, pages, review.get("margin_evidence"), review.get("reviewed_edits"))
        model["review_notes"] = review.get("review_notes", [])
    else:
        raw_bytes = input_bytes
        raw = raw_bytes.decode("utf-8")
        model = structure_ocr(raw, pages)
    items = paragraphs(model, title)
    write_docx(output / "sample.docx", items)
    write_pdf(output / "sample.pdf", items, font_path)
    checks = validate_pair(output / "sample.docx", output / "sample.pdf", items)
    (output / "structured.json").write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "original-ocr.md").write_bytes(raw_bytes)
    lines = ["# 疑点及处理记录", "", "原始OCR不改写。下列修订仅依据提供的原页核对记录；生成器不自行验证记录，未确定处不得凭常识补字。", ""]
    for issue in model["issues"]:
        lines += [f"## {issue['code']}", issue["detail"]]
        for fragment in issue["fragments"]:
            lines.append(f"- 原PDF第{fragment['page']}页 / OCR行{fragment['line']}：{fragment['raw']}")
        lines.append("")
    lines += ["## 对照原页的独立修订（不写回OCR）", ""]
    for edit in model["reviewed_edits"]:
        lines += [f"- 第{edit['page']}页 / OCR行{edit['line']}；原文：{edit['original']}",
                  f"  修订：{' / '.join(edit['replacement'])}；原因：{edit['reason']}；依据：{edit['reference']}"]
    for note in model.get("review_notes", []):
        lines.append("- " + note)
    lines += ["## 移出正文的页眉页脚", ""]
    for removed in model["removed_headers_footers"]:
        r = removed["fragment"]
        lines.append(f"- 第{r['page']}页 / OCR行{r['line']}：{r['raw']}；证据：{json.dumps(removed['evidence'], ensure_ascii=False)}")
    (output / "issues.md").write_text("\n".join(lines), encoding="utf-8")
    checks.update(source_sha256=model["source_sha256"], issues=len(model["issues"]), font=FONT_FAMILY,
                  font_sha256=hashlib.sha256(Path(font_path).read_bytes()).hexdigest(), original_pdf_review="supplied-manual-evidence" if model["reviewed_edits"] else "not-performed",
                  generator_verified_review_evidence=False)
    (output / "validation.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    return checks
