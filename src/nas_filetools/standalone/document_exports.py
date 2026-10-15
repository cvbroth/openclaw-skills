"""One Pandoc export transaction; continuous pagination only."""

from .page_ranges import parse_pages


def export_options(data, project, artifact):
    if not isinstance(data, dict) or set(data) - {
        "source_artifact_id",
        "formats",
        "pages",
        "remove_headers",
        "remove_footers",
        "new_header",
        "new_page_numbers",
        "template",
        "mode",
    }:
        raise ValueError("导出设置已迁移：使用连续自然分页；不再支持来源强制分页、紧凑适配或空白占位")
    if data.get("mode", "pandoc") not in {"pandoc", "template"}:
        raise ValueError("旧导出引擎已移除，请刷新页面使用Pandoc导出")
    if artifact.get("recycled") or artifact["format"] != "markdown" or not artifact.get("path"):
        raise ValueError("请选择有效Markdown文字版本")
    formats = data.get("formats", ["docx", "pdf"])
    if (
        not isinstance(formats, list)
        or not formats
        or any(not isinstance(f, str) for f in formats)
        or len(formats) != len(set(formats))
        or any(f not in {"docx", "pdf"} for f in formats)
    ):
        raise ValueError("请选择Word、PDF或两者")
    result = {
        "mode": "pandoc",
        "purpose": "export",
        "formats": formats,
        "source_pages": None,
        "pagination": {"mode": "continuous"},
    }
    for key, default in [
        ("remove_headers", False),
        ("remove_footers", False),
        ("new_header", False),
        ("new_page_numbers", True),
    ]:
        value = data.get(key, default)
        if type(value) is not bool:
            raise ValueError("清理和页眉页脚设置必须明确选择")
        result[key] = value
    value = data.get("pages", "全部")
    if isinstance(value, str):
        value = value.strip()
    if value != "全部":
        total = project.get("source_info", {}).get("units")
        if type(total) is not int:
            raise ValueError("来源物理页数未知，只能导出全部已有内容")
        result["source_pages"] = parse_pages(value, total, 1000)
        if not artifact.get("pages") or any(type(v.get("source_page")) is not int for v in artifact["pages"]):
            raise ValueError("文字稿缺少来源映射，不能按来源页选择")
    if data.get("template"):
        result["template"] = data["template"]
    return result
