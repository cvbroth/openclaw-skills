"""Strict printer-style physical page selections, shared at the HTTP boundary."""

import re


def parse_pages(value, total, maximum=1000):
    if type(total) is not int or total < 1:
        raise ValueError("原件页数未知，请先完成文件检查。")
    if isinstance(value, str):
        text = value.strip().replace("，", ",")
        if text == "全部":
            pages = list(range(1, total + 1))
        else:
            # Spaces may separate selections or surround a range/comma.
            text = re.sub(r"\s*([-,])\s*", r"\1", text)
            text = re.sub(r"\s+", ",", text)
            parts = text.split(",")
            pages = []
            for part in parts:
                if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?", part):
                    raise ValueError("页码须为整数、正序范围或‘全部’，不能为空。")
                endpoints = [int(n) for n in part.split("-")]
                start, end = endpoints[0], endpoints[-1]
                if start > end:
                    raise ValueError("页码范围不能倒序。")
                if start < 1 or end > total:
                    raise ValueError(f"页码越界，原件共{total}页。")
                pages.extend(range(start, end + 1))
    elif isinstance(value, list) and all(type(n) is int for n in value):
        pages = value
    else:
        raise ValueError("页码必须为范围文本或整数列表。")
    pages = sorted(set(pages))
    if not pages or any(n < 1 or n > total for n in pages):
        raise ValueError("页码为空或越界。")
    if len(pages) > maximum:
        raise ValueError(f"实际选择{len(pages)}页，单任务最多{maximum}页。")
    return pages
