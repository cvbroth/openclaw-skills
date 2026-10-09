"""CommonMark -> source-mapped declarative blocks, not inferred question ownership."""

import hashlib
import html
import re


class RichText(str):
    def __new__(cls, runs):
        obj = super().__new__(cls, "".join(r["text"] for r in runs))
        obj.runs = runs
        obj.safe_html = "".join(
            ("<b>" if r.get("bold") else "")
            + ("<i>" if r.get("italic") else "")
            + html.escape(r["text"]).replace("\n", "<br>")
            + ("</i>" if r.get("italic") else "")
            + ("</b>" if r.get("bold") else "")
            for r in runs
        )
        return obj

    def __getitem__(self, key):
        if not isinstance(key, slice):
            return str.__getitem__(self, key)
        start, stop, step = key.indices(len(self))
        if step != 1:
            return str.__getitem__(self, key)
        runs, cursor = [], 0
        for run in self.runs:
            end = cursor + len(run["text"])
            left, right = max(start, cursor), min(stop, end)
            if left < right:
                runs.append({**run, "text": run["text"][left - cursor : right - cursor]})
            cursor = end
        return RichText(runs)


def parse_markdown(text, source=None):
    from markdown_it import MarkdownIt

    parser = MarkdownIt("commonmark", {"html": False, "breaks": True})
    tokens = parser.parse(text)
    blocks, diagnostics, stack = [], [], []
    style = "Normal"
    if any(re.match(r"^\s*\|?.*\|.*$", line) for line in text.splitlines()):
        diagnostics.append({"code": "POSSIBLE_TABLE_PRESERVED_AS_TEXT"})
    bold = italic = 0
    marker = ""
    depth = 0
    lines = text.splitlines()
    for t in tokens:
        if t.type in ("bullet_list_open", "ordered_list_open"):
            stack.append(t.type)
            depth += 1
        elif t.type in ("bullet_list_close", "ordered_list_close"):
            stack.pop()
            depth -= 1
        elif t.type == "list_item_open":
            line = lines[t.map[0]] if t.map else ""
            match = re.match(r"^\s*([0-9]+[.)]|[-+*])\s+", line)
            marker = (match.group(1) if match else "•") + " "
        elif t.type == "list_item_close":
            marker = ""
        elif t.type == "heading_open":
            style = "Heading " + str(min(int(t.tag[1:]), 3))
        elif t.type == "heading_close":
            style = "Normal"
        elif t.type == "inline":
            runs = []
            if marker:
                runs.append({"text": marker, "bold": False, "italic": False})
            for child in t.children or []:
                if child.type == "strong_open":
                    bold += 1
                elif child.type == "strong_close":
                    bold -= 1
                elif child.type == "em_open":
                    italic += 1
                elif child.type == "em_close":
                    italic -= 1
                elif child.type in ("softbreak", "hardbreak"):
                    runs.append({"text": "\n", "bold": bool(bold), "italic": bool(italic)})
                elif child.type in ("text", "code_inline", "html_inline", "image"):
                    runs.append({"text": child.content, "bold": bool(bold), "italic": bool(italic)})
                    if child.type == "image":
                        diagnostics.append(
                            {
                                "code": "IMAGE_REFERENCE_NOT_RENDERED",
                                "source_lines": t.map,
                                "content": child.content,
                                "reference": child.attrs.get("src"),
                            }
                        )
                elif child.type in ("link_open", "link_close"):
                    if child.type == "link_open":
                        diagnostics.append(
                            {
                                "code": "LINK_DISPLAY_TEXT_ONLY",
                                "source_lines": t.map,
                                "reference": child.attrs.get("href"),
                            }
                        )
                else:
                    diagnostics.append(
                        {"code": "INLINE_UNSUPPORTED", "type": child.type, "source_lines": t.map}
                    )
            raw = "\n".join(lines[slice(*t.map)]) if t.map else t.content
            block = {
                "id": "md-" + hashlib.sha256((str(source) + str(t.map) + raw).encode()).hexdigest()[:16],
                "type": "list_item" if depth else ("heading" if style.startswith("Heading") else "paragraph"),
                "style": "Point" if depth else style,
                "runs": runs,
                "text": str(RichText(runs)),
                "list_depth": depth,
                "source": source,
                "source_lines": t.map,
                "raw": raw,
            }
            blocks.append(block)
            if style == "Heading 3" and any(
                x.type == "heading_open" and x.map == t.map and x.tag in ("h4", "h5", "h6") for x in tokens
            ):
                diagnostics.append({"code": "HEADING_LEVEL_4_TO_6_RENDERED_AS_3", "source_lines": t.map})
        elif t.type in ("fence", "code_block", "html_block"):
            blocks.append(
                {
                    "id": "literal-" + str(len(blocks)),
                    "type": "literal",
                    "style": "Normal",
                    "text": t.content,
                    "runs": [{"text": t.content}],
                    "source": source,
                    "source_lines": t.map,
                    "raw": t.content,
                }
            )
            diagnostics.append({"code": "LITERAL_BLOCK_PRESERVED", "type": t.type, "source_lines": t.map})
        elif t.type in ("blockquote_open", "hr"):
            diagnostics.append(
                {"code": "UNSUPPORTED_BLOCK_PRESERVED_AS_TEXT", "type": t.type, "source_lines": t.map}
            )
            if t.type == "hr":
                blocks.append(
                    {
                        "id": "literal-" + str(len(blocks)),
                        "type": "literal",
                        "style": "Normal",
                        "text": t.markup,
                        "runs": [{"text": t.markup}],
                        "source": source,
                        "source_lines": t.map,
                        "raw": t.markup,
                    }
                )
    return {
        "schema": "markdown-content-v1",
        "parser": "markdown-it-py==3.0.0; CommonMark; html disabled",
        "blocks": blocks,
        "diagnostics": diagnostics,
    }


def items(model):
    return [(b["style"], RichText(b["runs"])) for b in model["blocks"]]


def reading_html(model):
    # Only generated allowlisted tags. No raw model HTML, external resources or URLs.
    return "".join(
        "<"
        + ("h" + b["style"][-1] if b["type"] == "heading" else "p")
        + ">"
        + RichText(b["runs"]).safe_html
        + "</"
        + ("h" + b["style"][-1] if b["type"] == "heading" else "p")
        + ">"
        for b in model["blocks"]
    )
