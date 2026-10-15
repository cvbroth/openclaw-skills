"""Shared conservative Markdown preparation for reader and Pandoc."""

import re


def preserve_question_numbers(text):
    # Only explicit question + option evidence. Ordinary ordered lists stay lists.
    lines = text.splitlines(keepends=True)
    fenced = False
    for i, line in enumerate(lines):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        if fenced:
            continue
        match = re.match(r"^(\s{0,3})(\d+)([.)])\s+", line)
        if not match:
            continue
        following = ""
        for later in lines[i + 1 : i + 40]:
            if re.match(r"^\s*\d+[.)]\s+", later):
                break
            following += later
        if re.search(r"(?m)^\s*A[.．、)）]\s*\S", following) and re.search(
            r"(?m)^\s*B[.．、)）]\s*\S", following
        ):
            start = match.start(3)
            lines[i] = line[:start] + "\\" + line[start:]
    return "".join(lines)


def preserve_list_starts(ast, text):
    """Keep explicitly written numeric starts while retaining native Word lists."""
    from copy import deepcopy
    from markdown_it import MarkdownIt

    records = []
    stack = []
    lines = text.splitlines()
    for token in MarkdownIt("commonmark", {"html": True}).enable("table").parse(text):
        if token.type in {"ordered_list_open", "bullet_list_open"}:
            record = [] if token.type == "ordered_list_open" else None
            if record is not None:
                records.append(record)
            stack.append(record)
        elif token.type in {"ordered_list_close", "bullet_list_close"}:
            stack.pop()
        elif token.type == "list_item_open" and stack and stack[-1] is not None:
            match = re.match(r"^\s*(?:>\s*)*(\d+)[.)](?:\s+|$)", lines[token.map[0]])
            if not match:
                raise ValueError("无法核实Markdown列表原始编号")
            stack[-1].append(int(match.group(1)))
    cursor = 0

    class Expansion(list):
        pass

    def visit(value):
        nonlocal cursor
        if isinstance(value, list):
            result = []
            for item in value:
                converted = visit(item)
                if isinstance(converted, Expansion):
                    result.extend(converted)
                else:
                    result.append(converted)
            return result
        if not isinstance(value, dict):
            return value
        if value.get("t") == "OrderedList":
            if cursor >= len(records):
                raise ValueError("导出列表与阅读结构不一致")
            numbers = records[cursor]
            cursor += 1
            node = deepcopy(value)
            items = visit(node["c"][1])
            if len(numbers) != len(items):
                raise ValueError("导出列表项与原始编号数量不一致")
            groups = Expansion()
            current = []
            start = None
            last = None
            for number, item in zip(numbers, items):
                if last is not None and number != last + 1:
                    groups.append({"t": "OrderedList", "c": [[start, *node["c"][0][1:]], current]})
                    current = []
                    start = None
                if start is None:
                    start = number
                current.append(item)
                last = number
            if current:
                groups.append({"t": "OrderedList", "c": [[start, *node["c"][0][1:]], current]})
            return groups
        return {k: visit(v) for k, v in value.items()}

    result = visit(ast)
    if cursor != len(records):
        raise ValueError("原始列表不能完整对应导出结构")
    return result
