"""Explicit document export choices, independent of recognition and feedback."""

from .page_ranges import parse_pages


def export_options(data, project, artifact):
    if not isinstance(data, dict):
        raise ValueError("导出设置必须是对象")
    if set(data) - {
        "source_artifact_id",
        "template",
        "formats",
        "pages",
        "pagination",
        "mode",
        "compact",
        "purpose",
    }:
        raise ValueError("不支持的导出设置")
    formats = data.get("formats", ["docx", "pdf"])
    if (
        not isinstance(formats, list)
        or not formats
        or any(not isinstance(fmt, str) or fmt not in {"docx", "pdf"} for fmt in formats)
        or len(formats) != len(set(formats))
    ):
        raise ValueError("请选择 Word、PDF 或两者")
    if artifact.get("recycled") or artifact["format"] != "markdown" or not artifact.get("path"):
        raise ValueError("请选择可用的文字版本")
    mode = data.get("mode", "template")
    if mode not in {"template", "markdown-direct"}:
        raise ValueError("请选择原文直出或自定义模板")
    if mode == "markdown-direct":
        from .markdown_direct import check_views, compact_options

        purpose = data.get("purpose", "export")
        if purpose not in {"export", "check", "preview"}:
            raise ValueError("无效的原文直出操作")
        if purpose == "export":
            check_views(artifact, project.get("source_info", {}).get("units"))
        compact = compact_options(data.get("compact"))
    selected = None
    value = data.get("pages", "全部")
    if isinstance(value, str):
        value = value.strip()
    if value != "全部":
        total = project.get("source_info", {}).get("units")
        if type(total) is not int:
            raise ValueError("原件页数未知，请导出全部已有文字")
        selected = parse_pages(value, total, 1000)
        views = artifact.get("pages", [])
        if mode != "markdown-direct" and (
            not views
            or any(type(v.get("source_page")) is not int or not 1 <= v["source_page"] <= total for v in views)
        ):
            raise ValueError("文字稿缺少来源页映射，不能按原件页选择")
        available = {v["source_page"] for v in views}
        missing = sorted(set(selected) - available)
        if missing and mode != "markdown-direct":
            raise ValueError("所选原件页没有文字记录：" + ",".join(map(str, missing[:20])))
    return {
        "formats": formats,
        "source_pages": selected,
        "mode": mode,
        **({"compact": compact, "purpose": purpose} if mode == "markdown-direct" else {}),
    }
