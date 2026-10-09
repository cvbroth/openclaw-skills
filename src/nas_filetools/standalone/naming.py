"""Presentation metadata only: IDs, physical paths and bytes remain immutable."""

import re
from pathlib import Path


def project_title(name):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:70] or "文件项目"
    if Path(title).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx"}:
        title = Path(title).stem
    return title


def decorate(project):
    tasks = {t["task_id"]: t for t in project.get("tasks", [])}
    for a in project["artifacts"]:
        source = a["artifact_id"] == project.get("source_artifact_id")
        engine = (
            tasks.get(a.get("task_id"), {}).get("engine_name")
            or a.get("recognition_engine")
            or tasks.get(a.get("task_id"), {}).get("engine_id", "历史结果")
        )
        engine = {"m3": "MiniMax M3", "local": "本地OCR", "format": "复用已有文字"}.get(engine, engine)
        purpose = (
            "原件"
            if source
            else {"markdown": "提取文字", "docx": "Word排版稿", "pdf": "PDF排版稿"}.get(
                a["format"],
                "原图评价"
                if a.get("role") == "quality"
                else "技术诊断"
                if a.get("role") == "diagnostic"
                else "来源结构",
            )
        )
        a["display_name"] = a.get("display_name_override") or purpose
        task = tasks.get(a.get("task_id"), {})
        physical_pages = sorted(
            {v["source_page"] for v in a.get("pages", []) if type(v.get("source_page")) is int}
        )
        if not physical_pages:
            physical_pages = sorted(int(n) for n in task.get("pages", {}))
        a["display_metadata"] = {
            "method": "复用已有文字排版" if task.get("operation") == "format-artifact" else engine,
            "version": str(a.get("version", "1")),
            "template": a.get("template_label"),
            "created_at": a.get("created_at") or task.get("created_at"),
            "source_pages": physical_pages,
        }
        a["structure_notice"] = (
            (
                "已按支持的试题结构排版，仍须核对原文"
                if a.get("content_nature") == "exam-structured"
                else "基础Markdown排版；题目结构未核对"
                if a.get("content_nature") == "markdown-basic"
                else "保真片段；未确认题目结构"
            )
            if a["format"] in {"docx", "pdf"}
            else ""
        )
        title = project_title(project["name"])
        suffix = Path(a.get("path") or "").suffix or {
            "image": ".png",
            "reference": ".pdf",
            "markdown": ".md",
            "json": ".json",
            "docx": ".docx",
            "pdf": ".pdf",
        }.get(a["format"], "")
        parts = [title, a["display_name"]]
        parts = [
            re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", x).encode()[:limit].decode("utf-8", errors="ignore")
            for x, limit in zip(parts, [96, 90])
        ]
        a["download_name"] = "_".join(parts) + f"_v{a['version']}{suffix}"
    return project
