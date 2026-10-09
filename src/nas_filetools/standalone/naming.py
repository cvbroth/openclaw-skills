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
        if source:
            purpose = "原图" if a["format"] == "image" else "原件"
        elif a["format"] == "markdown":
            purpose = "文字提取稿"
        elif a["format"] in {"docx", "pdf"}:
            purpose = (
                "试题排版稿"
                if a.get("content_nature") == "exam-structured"
                else (
                    "Markdown排版稿（题目结构未核对）"
                    if a.get("content_nature") == "markdown-basic"
                    else "保真片段排版稿（未确认题目结构）"
                )
            )
        elif a.get("role") == "quality":
            purpose = "原图评价记录"
        elif a.get("role") == "diagnostic":
            purpose = "技术诊断"
        else:
            purpose = "来源结构记录"
        a["display_name"] = a.get("display_name_override") or (
            " · ".join(
                [purpose, project["name"]]
                if source
                else [
                    purpose,
                    engine,
                    *([a["format"].upper()] if a["format"] in {"docx", "pdf"} else []),
                    "第" + str(a["version"]) + "版",
                    *([a["template_label"]] if a.get("template_label") else []),
                ]
            )
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
        parts = [title, purpose, engine]
        parts = [
            re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", x).encode()[:limit].decode("utf-8", errors="ignore")
            for x, limit in zip(parts, [96, 90, 32])
        ]
        a["download_name"] = "_".join(parts) + f"_v{a['version']}{suffix}"
    return project
