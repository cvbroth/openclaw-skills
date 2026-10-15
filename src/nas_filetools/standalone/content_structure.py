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
            + (
                '<img src="'
                + html.escape(r["image"], quote=True)
                + '" alt="'
                + html.escape(r["text"], quote=True)
                + '">'
                if r.get("image")
                else (('<a href="' + html.escape(r["href"], quote=True) + '">') if r.get("href") else "")
                + html.escape(r["text"]).replace("\n", "<br>")
                + ("</a>" if r.get("href") else "")
            )
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

    from .markdown_rules import preserve_question_numbers

    parser = MarkdownIt("commonmark", {"html": True, "breaks": True}).enable("table")
    tokens = parser.parse(preserve_question_numbers(text))
    blocks, diagnostics, stack = [], [], []
    style = "Normal"
    quote_depth = 0
    table_records = __import__(__package__ + ".table_structure", fromlist=["tables"]).tables(text)
    table_by_line = {t["source_lines"][0]: t for t in table_records}
    skip_until = -1
    # Recognize real table grammar, including matching columns and escaped pipes.
    # Ordinary pipes (including Setext headings) are reader text, not table evidence.
    bold = italic = 0
    href = None
    marker = ""
    depth = 0
    lines = text.splitlines()
    for t in tokens:
        if t.map and t.map[0] < skip_until:
            continue
        if t.map and t.map[0] in table_by_line:
            record = table_by_line[t.map[0]]
            skip_until = record["source_lines"][1]
            if record.get("error"):
                diagnostics.append({"code": "TABLE_NEEDS_REVIEW", "reason": record["error"]})
                blocks.append(
                    {
                        "id": record["id"],
                        "type": "literal",
                        "style": "Code",
                        "text": record["original"],
                        "runs": [{"text": record["original"]}],
                        "source_lines": record["source_lines"],
                        "raw": record["original"],
                        "source": source,
                    }
                )
            else:
                blocks.append(
                    {
                        "id": record["id"],
                        "type": "table",
                        "style": "Table",
                        "text": "\n".join(c["text"] for c in record["model"]["cells"]),
                        "runs": [{"text": "\n".join(c["text"] for c in record["model"]["cells"])}],
                        "table": record["model"],
                        "safe_html": record["html"],
                        "source_lines": record["source_lines"],
                        "source": source,
                    }
                )
            continue
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
            style = "Heading " + str(int(t.tag[1:]))
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
                elif child.type in ("softbreak", "hardbreak") or (
                    child.type == "html_inline" and re.fullmatch(r"<br\s*/?>", child.content, re.I)
                ):
                    runs.append({"text": "\n", "bold": bool(bold), "italic": bool(italic)})
                elif child.type in ("text", "code_inline", "html_inline", "image"):
                    runs.append(
                        {
                            "text": child.content,
                            "bold": bool(bold),
                            "italic": bool(italic),
                            "code": child.type == "code_inline",
                            **({"href": href} if href else {}),
                            **({"image": child.attrs.get("src")} if child.type == "image" else {}),
                        }
                    )
                    if child.type == "image":
                        diagnostics.append(
                            {
                                "code": "IMAGE_REFERENCE_LOCAL",
                                "supported": True,
                                "source_lines": t.map,
                                "content": child.content,
                                "reference": child.attrs.get("src"),
                            }
                        )
                elif child.type in ("link_open", "link_close"):
                    if child.type == "link_close":
                        href = None
                    if child.type == "link_open":
                        href = child.attrs.get("href")
                        diagnostics.append(
                            {
                                "code": "LINK_PRESERVED",
                                "supported": True,
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
                "quote_depth": quote_depth,
                "source": source,
                "source_lines": t.map,
                "raw": raw,
            }
            blocks.append(block)
        elif t.type in ("fence", "code_block", "html_block"):
            blocks.append(
                {
                    "id": "literal-" + str(len(blocks)),
                    "type": "literal",
                    "style": "Code",
                    "quote_depth": quote_depth,
                    "text": t.content,
                    "runs": [{"text": t.content}],
                    "source": source,
                    "source_lines": t.map,
                    "raw": t.content,
                }
            )
            diagnostics.append(
                {"code": "LITERAL_BLOCK_PRESERVED", "supported": True, "type": t.type, "source_lines": t.map}
            )
            # Literal contents are escaped, never executed as HTML.

        elif t.type == "blockquote_open":
            quote_depth += 1
        elif t.type == "blockquote_close":
            quote_depth -= 1
        elif t.type == "hr":
            rule = "\n".join(lines[slice(*t.map)]) if t.map else t.markup
            if quote_depth:
                rule = re.sub(r"^(?:\s*> ?)+", "", rule)
            blocks.append(
                {
                    "id": "literal-" + str(len(blocks)),
                    "type": "separator",
                    "style": "Separator",
                    "text": rule,
                    "runs": [{"text": rule}],
                    "source": source,
                    "source_lines": t.map,
                    "raw": rule,
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
    # Allowlisted generated tags only. Literal code/HTML is escaped as document text.
    output = []
    for b in model["blocks"]:
        if b["type"] == "table":
            output.append(b["safe_html"])
            continue
        tag = "h" + b["style"][-1] if b["type"] == "heading" else "p"
        classes = []
        if b.get("quote_depth"):
            classes.append("md-quote")
        if b["style"] in {"Code", "Separator"}:
            classes.append("md-" + b["style"].lower())
        attrs = ' class="' + " ".join(classes) + '"' if classes else ""
        if b.get("quote_depth"):
            attrs += ' style="--quote-depth:' + str(b["quote_depth"]) + '"'
        output.append("<" + tag + attrs + ">" + RichText(b["runs"]).safe_html + "</" + tag + ">")
    return "".join(output)
