"""Rendered pagination evidence; no question-number exceptions or private fixtures."""
import hashlib

import fitz

from .document_sample import StoryLayout, canonical, item_groups, page_body


def paragraph_locations(pdf, items, template=None, expect_document_footer=True):
    text, positions = "", []
    for number, page in enumerate(pdf, 1):
        if expect_document_footer:
            page_body(page, number, template)  # Check exactly the expected footer band.
        bottom = page.rect.height - (template or {}).get("margin_cm", 2) * 72 / 2.54 if expect_document_footer else page.rect.height
        for word in page.get_text("words", sort=True):
            if word[1] > bottom:
                continue
            fragment = canonical(word[4])
            text += fragment
            positions.extend([(number, word[:4])] * len(fragment))
    if text != canonical("".join(value for style, value in items)):
        raise ValueError("PARAGRAPH_MAP_CONTENT_MISMATCH")
    cursor, rows = 0, []
    for index, (style, value) in enumerate(items):
        length = len(canonical(value))
        selected = positions[cursor:cursor + length]
        cursor += length
        lines = []
        for page, bbox in selected:
            if not lines or page != lines[-1]["page"] or abs(bbox[3] - lines[-1]["y1"]) > 6:
                lines.append({"page": page, "y0": bbox[1], "y1": bbox[3]})
            else:
                lines[-1]["y0"] = min(lines[-1]["y0"], bbox[1])
                lines[-1]["y1"] = max(lines[-1]["y1"], bbox[3])
        rows.append({"index": index, "style": style, "text_sha256": hashlib.sha256(value.encode()).hexdigest(),
                     "pages": sorted({page for page, bbox in selected}), "lines": lines})
    return rows


def check_layout(pdf_path, items, font_path, template=None):
    layout = StoryLayout(font_path, template)
    t = layout.template
    with fitz.open(pdf_path) as pdf:
        rows = paragraph_locations(pdf, items, template)
        questions, failures = [], []
        for index, row in enumerate(rows[:-1]):
            if row["style"] in ("Title", "Subject", "Heading 1", "Heading 2", "Heading 3"):
                if row["pages"][-1] != rows[index + 1]["pages"][0]:
                    failures.append({"item": index, "code": "HEADING_ORPHANED"})
        for start, end, group in item_groups(items):
            if group[0][0] != "Question":
                continue
            selected = rows[start:end]
            pages = sorted({page for row in selected for page in row["pages"]})
            stem = selected[0]
            opening_lines = sum(line["page"] == stem["pages"][0] for line in stem["lines"])
            short = layout.question_short(group)
            source_follows = selected[-2]["pages"][-1] == selected[-1]["pages"][0] and len(selected[-1]["pages"]) == 1
            if short and len(pages) != 1:
                failures.append({"start_item": start, "code": "SHORT_QUESTION_SPLIT"})
            if opening_lines < min(t["minimum_start_lines"], len(stem["lines"])):
                failures.append({"start_item": start, "code": "ONE_LINE_QUESTION_START"})
            if not source_follows:
                failures.append({"start_item": start, "code": "SOURCE_ORPHANED"})
            options = []
            for offset, (style, value) in enumerate(group):
                if style not in ("Option", "Point"):
                    continue
                row = selected[offset]
                option_short = layout.short_paragraph((style, value), t["short_option_max_lines"])
                if option_short and len(row["pages"]) != 1:
                    failures.append({"start_item": start, "code": "SHORT_OPTION_SPLIT", "item": start + offset})
                options.append({"item": start + offset, "pages": row["pages"], "short": option_short,
                                "lines_per_page": {page: sum(line["page"] == page for line in row["lines"]) for page in row["pages"]}})
            questions.append({"start_item": start, "number": group[0][1].split(".", 1)[0], "pages": pages,
                              "short": short, "stem_opening_lines": opening_lines, "source_follows_last_option": source_follows,
                              "source_page": selected[-1]["pages"][0], "options": options})
        page_metrics = []
        for number, page in enumerate(pdf, 1):
            traces = page.get_texttrace()
            if not traces:
                failures.append({"page": number, "code": "NO_DRAWING_TRACES"})
            for span in traces:
                if any(component > 0.001 for component in span["color"]):
                    failures.append({"page": number, "code": "NONBLACK_TEXT"})
                for codepoint, glyph, origin, bbox in span["chars"]:
                    if codepoint == 0xfffd or (glyph == 0 and not chr(codepoint).isspace()):
                        failures.append({"page": number, "code": "MISSING_GLYPH"})
                    if not page.rect.contains(fitz.Rect(bbox)):
                        failures.append({"page": number, "code": "CROPPED_GLYPH"})
            body_lines = [line for row in rows for line in row["lines"] if line["page"] == number]
            used_bottom = max(line["y1"] for line in body_lines)
            page_metrics.append({"page": number, "bottom_blank_pt": round(layout.where.y1 - used_bottom, 2),
                                 "body_lines": len(body_lines)})
        return {"passed": not failures, "failures": failures, "questions": questions,
                "paragraphs": rows, "pages": page_metrics, "document_page_numbers": "checked",
                "text_black": not any(f["code"] == "NONBLACK_TEXT" for f in failures)}


def compare_docx_content(previous, current):
    """Exclude exactly presentation headings/sources; compare all other text exactly.

    Headings retain their text/order; sources retain their original-PDF page list.
    Document page numbers are footer fields, outside these body paragraphs.
    """
    import re
    from docx import Document

    def parts(path):
        body, headings, sources = [], [], []
        for paragraph in Document(path).paragraphs:
            style, text = paragraph.style.name, paragraph.text
            if style in ("Title", "Subject") or style.startswith("Heading "):
                headings.append(text)
            elif style == "Source":
                match = re.search(r"原PDF[：:]?第([0-9、]+)页", text)
                if not match:
                    raise ValueError("UNKNOWN_SOURCE_DISPLAY")
                sources.append(match.group(1))
            else:
                body.append((style, text))
        return body, headings, sources

    before, after = parts(previous), parts(current)
    if before != after:
        raise ValueError("PREVIOUS_DOCUMENT_CONTENT_CHANGED")
    return {"exact_question_option_text_and_order": True, "heading_text_and_order_equal": True,
            "source_page_lists_equal": True, "body_paragraphs": len(after[0]),
            "questions": sum(style == "Question" for style, text in after[0]),
            "body_sha256": hashlib.sha256(repr(after[0]).encode()).hexdigest(),
            "exclusions": "heading style hierarchy; Source display including old OCR line metadata; footer page-number field"}
