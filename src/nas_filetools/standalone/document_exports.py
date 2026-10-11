"""Explicit document export choices, independent of recognition and feedback."""

from .page_ranges import parse_pages


def export_options(data, project, artifact):
    if not isinstance(data, dict):
        raise ValueError("导出设置必须是对象")
    if set(data) - {"source_artifact_id", "template", "formats", "pages", "pagination"}:
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
        if not views or any(
            type(v.get("source_page")) is not int or not 1 <= v["source_page"] <= total for v in views
        ):
            raise ValueError("文字稿缺少来源页映射，不能按原件页选择")
        available = {v["source_page"] for v in views}
        missing = sorted(set(selected) - available)
        if missing:
            raise ValueError("所选原件页没有文字记录：" + ",".join(map(str, missing[:20])))
    return {"formats": formats, "source_pages": selected}
